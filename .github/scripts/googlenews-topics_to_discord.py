import xml.etree.ElementTree as ET
import requests
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
import base64
import urllib.parse
import sys

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
    with sqlite3.connect(DB_PATH) as conn:
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
        logging.info("데이터베이스 초기화 완료")

def is_guid_posted(guid):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM news_items WHERE guid = ?", (guid,))
        return c.fetchone() is not None

def save_news_item(pub_date, guid, title, link, related_news):
    with sqlite3.connect(DB_PATH) as conn:
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
        
        logging.info(f"새 뉴스 항목 저장: {guid}")

def get_original_link(google_link, session, max_retries=5):
    def base64_decode_url(url):
        try:
            if 'news.google.com/articles/' in url:
                base64_url = url.replace("https://news.google.com/articles/", "").split("?")[0]
                decoded_url = base64.urlsafe_b64decode(base64_url + '=' * (4 - len(base64_url) % 4))
                actual_url = decoded_url[4:-3].decode('utf-8')
                return urllib.parse.unquote(actual_url)
            return None
        except Exception as e:
            logging.warning(f"Base64 디코딩 실패: {str(e)}")
            return None

    def requests_get_url(url, session, max_retries=5):
        wait_times = [5, 10, 30, 45, 60]
        for attempt in range(max_retries):
            try:
                response = session.get(url, allow_redirects=True, timeout=10)
                return response.url
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    logging.error(f"최대 시도 횟수 초과. 원본 링크를 가져오는 데 실패했습니다: {str(e)}")
                    return None
                wait_time = wait_times[min(attempt, len(wait_times) - 1)] + random.uniform(0, 5)
                logging.warning(f"시도 {attempt + 1}/{max_retries}: 요청 실패. {wait_time:.2f}초 후 재시도합니다. 오류: {str(e)}")
                time.sleep(wait_time)

    # 먼저 base64 디코딩 시도
    decoded_url = base64_decode_url(google_link)
    if decoded_url:
        logging.info(f"Base64 디코딩 성공 - Google 링크: {google_link}")
        logging.info(f"추출된 원본 URL: {decoded_url}")
        return decoded_url

    # base64 디코딩 실패 시 requests 사용
    logging.info(f"Base64 디코딩 실패. requests를 사용하여 재시도합니다.")

    final_url = requests_get_url(google_link, session, max_retries)
    if final_url:
        logging.info(f"Requests를 사용하여 성공 - Google 링크: {google_link}")
        logging.info(f"최종 URL: {final_url}")
        return final_url

    # 모든 방법 실패 시 원래 Google 링크 반환
    logging.error(f"모든 방법 실패. 원래의 Google 링크를 사용합니다: {google_link}")
    return google_link

def fetch_rss_feed(url):
    response = requests.get(url)
    return response.content

def replace_brackets(text):
    text = text.replace('[', '［').replace(']', '］')
    text = text.replace('<', '〈').replace('>', '〉')
    text = re.sub(r'(?<!\s)(?<!^)［', ' ［', text)
    text = re.sub(r'］(?!\s)', '］ ', text)
    text = re.sub(r'(?<!\s)(?<!^)〈', ' 〈', text)
    text = re.sub(r'〉(?!\s)', '〉 ', text)
    return text

def parse_html_description(html_desc, session):
    soup = BeautifulSoup(html_desc, 'html.parser')
    items = soup.find_all('li')

    news_items = []
    full_content_link = ""
    for item in items:
        if 'Google 뉴스에서 전체 콘텐츠 보기' in item.text:
            full_content_link_match = item.find('a')
            if full_content_link_match:
                full_content_link = full_content_link_match['href']
            continue

        title_match = item.find('a')
        press_match = item.find('font', color="#6f6f6f")
        if title_match and press_match:
            google_link = title_match['href']
            link = get_original_link(google_link, session)
            title_text = replace_brackets(title_match.text)
            press_name = press_match.text
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
    headers = {"Content-Type": "application/json"}
    response = requests.post(webhook_url, json=payload, headers=headers)
    if response.status_code != 204:
        logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        logging.error(response.text)
    else:
        logging.info("Discord에 메시지 게시 완료")
    time.sleep(3)

def extract_news_items(description, session):
    soup = BeautifulSoup(description, 'html.parser')
    news_items = []
    for li in soup.find_all('li'):
        a_tag = li.find('a')
        if a_tag:
            title = a_tag.text
            google_link = a_tag['href']
            link = get_original_link(google_link, session)
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            news_items.append({"title": title, "link": link, "press": press})
    return news_items

def main():
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    init_db(reset=INITIALIZE)

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })

    news_items = root.findall('.//item')
    if INITIALIZE:
        news_items = list(news_items)
    else:
        news_items = reversed(news_items)

    for item in news_items:
        guid = item.find('guid').text

        if not INITIALIZE and is_guid_posted(guid):
            continue

        title = replace_brackets(item.find('title').text)
        google_link = item.find('link').text
        link = get_original_link(google_link, session)
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        
        formatted_date = parse_rss_date(pub_date)

        related_news = extract_news_items(description_html, session)
        related_news_json = json.dumps(related_news, ensure_ascii=False)

        description = parse_html_description(description_html, session)

        discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**{title}**\n{link}"
        if description:
            discord_message += f"\n>>> {description}"
        else:
            discord_message += f"\n>>> "
        discord_message += f"\n\n📅 {formatted_date}"

        send_discord_message(DISCORD_WEBHOOK_TOPICS, discord_message)

        save_news_item(pub_date, guid, title, link, related_news_json)

        if not INITIALIZE:
            time.sleep(3)

if __name__ == "__main__":
    try:
        check_env_variables()
        main()
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)  # 오류 발생 시 비정상 종료
    else:
        logging.info("프로그램 정상 종료")
