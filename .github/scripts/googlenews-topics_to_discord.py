import xml.etree.ElementTree as ET
import requests
from html import unescape
import re
import os
import time
import random
from datetime import datetime
from dateutil import parser
from dateutil.tz import gettz
import sqlite3
import logging
from bs4 import BeautifulSoup
import json
import urllib.parse

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
DISCORD_WEBHOOK_TOPICS = os.environ.get('DISCORD_WEBHOOK_TOPICS')
INITIALIZE = os.environ.get('INITIALIZE', 'false').lower() == 'true'

# DB 설정
DB_PATH = 'google_news_topic.db'

def check_env_variables():
    if not DISCORD_WEBHOOK_TOPICS:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_TOPICS")

def init_db(reset=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if reset:
        c.execute("DROP TABLE IF EXISTS news_items")
        logging.info("기존 news_items 테이블 삭제")
    c.execute('''CREATE TABLE IF NOT EXISTS news_items
                 (pub_date TEXT,
                  guid TEXT PRIMARY KEY,
                  title TEXT,
                  link TEXT,
                  related_news TEXT)''')
    conn.commit()
    conn.close()
    logging.info("데이터베이스 초기화 완료")

def is_guid_posted(guid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM news_items WHERE guid = ?", (guid,))
    result = c.fetchone()
    conn.close()
    return result is not None

def save_news_item(pub_date, guid, title, link, related_news):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 기존 테이블 구조 확인
    c.execute("PRAGMA table_info(news_items)")
    columns = [column[1] for column in c.fetchall()]
    
    # 관련 뉴스 항목 수 확인
    related_news_count = len(json.loads(related_news))
    
    # 필요한 열 추가
    for i in range(related_news_count):
        title_col = f"related_title_{i+1}"
        press_col = f"related_press_{i+1}"
        link_col = f"related_link_{i+1}"
        
        if title_col not in columns:
            c.execute(f"ALTER TABLE news_items ADD COLUMN {title_col} TEXT")
        if press_col not in columns:
            c.execute(f"ALTER TABLE news_items ADD COLUMN {press_col} TEXT")
        if link_col not in columns:
            c.execute(f"ALTER TABLE news_items ADD COLUMN {link_col} TEXT")
    
    # 데이터 삽입을 위한 SQL 쿼리 준비
    columns = ["pub_date", "guid", "title", "link", "related_news"]
    values = [pub_date, guid, title, link, related_news]
    
    related_news_items = json.loads(related_news)
    for i, item in enumerate(related_news_items):
        columns.extend([f"related_title_{i+1}", f"related_press_{i+1}", f"related_link_{i+1}"])
        values.extend([item['title'], item['press'], item['link']])
    
    placeholders = ", ".join(["?" for _ in values])
    columns_str = ", ".join(columns)
    
    c.execute(f"INSERT OR REPLACE INTO news_items ({columns_str}) VALUES ({placeholders})", values)
    
    conn.commit()
    conn.close()
    logging.info(f"새 뉴스 항목 저장: {guid}")

def fetch_rss_feed(url):
    response = requests.get(url)
    return response.content

def replace_brackets(text):
    return text.replace("[", "〔").replace("]", "〕")

def get_original_link(google_link, max_retries=5):
    session = requests.Session()
    wait_times = [5, 10, 30, 45, 60]  # 기본 대기 시간 (초)
    
    # MSN 링크 특별 처리
    if 'news.google.com/rss/articles/' in google_link and 'msn.com' in google_link:
        try:
            # Google News RSS 링크에서 실제 MSN 링크 추출
            parsed_url = urllib.parse.urlparse(google_link)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if 'url' in query_params:
                msn_link = query_params['url'][0]
                # URL 디코딩
                msn_link = urllib.parse.unquote(msn_link)
                # 추가 디코딩 처리
                msn_link = urllib.parse.unquote(msn_link)
                logging.info(f"추출된 MSN 링크: {msn_link}")
                return msn_link
        except Exception as e:
            logging.error(f"MSN 링크 추출 중 오류 발생: {str(e)}")
    
    for attempt in range(max_retries):
        try:
            response = session.get(google_link, allow_redirects=True, timeout=10)
            final_url = response.url
            # URL 디코딩
            final_url = urllib.parse.unquote(final_url)
            logging.info(f"Google 링크: {google_link}")
            logging.info(f"최종 URL: {final_url}")
            
            if 'news.google.com' not in final_url:
                return final_url
            else:
                base_wait_time = wait_times[min(attempt, len(wait_times) - 1)]
                wait_time = base_wait_time + random.uniform(0, 5)  # 0-5초의 랜덤 시간 추가
                logging.warning(f"시도 {attempt + 1}/{max_retries}: 원본 링크를 가져오지 못했습니다. {wait_time:.2f}초 후 재시도합니다.")
                time.sleep(wait_time)
        except requests.RequestException as e:
            base_wait_time = wait_times[min(attempt, len(wait_times) - 1)]
            wait_time = base_wait_time + random.uniform(0, 5)
            logging.warning(f"시도 {attempt + 1}/{max_retries}: 요청 중 오류 발생. {wait_time:.2f}초 후 재시도합니다. 오류: {str(e)}")
            time.sleep(wait_time)
    
    logging.error(f"최대 시도 횟수 초과. 원본 링크를 가져오는 데 실패했습니다. 원래의 Google 링크를 사용합니다: {google_link}")
    return google_link

def parse_html_description(html_desc):
    html_desc = unescape(html_desc)
    items = re.findall(r'<li>(.*?)</li>', html_desc, re.DOTALL)

    news_items = []
    full_content_link = ""
    for item in items:
        if 'Google 뉴스에서 전체 콘텐츠 보기' in item:
            full_content_link_match = re.search(r'<a href="(https://news\.google\.com/stories/.*?)"', item)
            if full_content_link_match:
                full_content_link = full_content_link_match.group(1)
            continue

        title_match = re.search(r'<a href="(.*?)".*?>(.*?)</a>', item)
        press_match = re.search(r'<font color="#6f6f6f">(.*?)</font>', item)
        if title_match and press_match:
            google_link, title_text = title_match.groups()
            link = get_original_link(google_link)
            title_text = replace_brackets(title_text)
            press_name = press_match.group(1)
            news_item = f"- [{title_text}](<{link}>) | {press_name}"
            news_items.append(news_item)

    news_string = '\n'.join(news_items)
    if full_content_link:
        news_string += f"\n\n▶️ [Google 뉴스에서 전체 콘텐츠 보기](<{full_content_link}>)"

    return news_string

def parse_rss_date(pub_date):
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

def send_discord_message(webhook_url, message):
    payload = {"content": message}
    headers = {"Content-Type": "application/json; charset=utf-8"}
    response = requests.post(webhook_url, json=payload, headers=headers)
    if response.status_code != 204:
        logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        logging.error(response.text)
    else:
        logging.info("Discord에 메시지 게시 완료")
    time.sleep(3)

def extract_news_items(description):
    news_items = []
    soup = BeautifulSoup(description, 'html.parser')
    for li in soup.find_all('li'):
        a_tag = li.find('a')
        if a_tag:
            title = a_tag.text
            google_link = a_tag['href']
            link = get_original_link(google_link)
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            news_items.append({"title": title, "link": link, "press": press})
    return news_items

def main():
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    if INITIALIZE:
        init_db(reset=True)  # DB 초기화
        logging.info("초기화 모드로 실행 중: 데이터베이스를 재설정하고 모든 뉴스 항목을 처리합니다.")
    else:
        init_db()

    news_items = root.findall('.//item')
    if INITIALIZE:
        news_items = list(news_items)  # 초기화 실행 시 모든 항목 처리 (오래된 순)
    else:
        news_items = reversed(news_items)  # 일반 실행 시 최신 항목부터 처리

    for item in news_items:
        guid = item.find('guid').text

        if not INITIALIZE and is_guid_posted(guid):
            continue

        title = item.find('title').text
        google_link = item.find('link').text
        link = get_original_link(google_link)
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        
        title = replace_brackets(title)
        formatted_date = parse_rss_date(pub_date)

        related_news = extract_news_items(description_html)
        related_news_json = json.dumps(related_news, ensure_ascii=False)

        description = parse_html_description(description_html)
        discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**[{title}](<{link}>)**\n>>> {description}\n\n📅 {formatted_date}"
        send_discord_message(DISCORD_WEBHOOK_TOPICS, discord_message)

        save_news_item(pub_date, guid, title, link, related_news_json)

        if not INITIALIZE:
            time.sleep(3)  # 일반 실행 시에만 딜레이 적용

if __name__ == "__main__":
    try:
        check_env_variables()
        main()
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
    finally:
        logging.info("프로그램 실행 종료")
