import xml.etree.ElementTree as ET
import requests
from html import unescape
import re
import os
import time
from datetime import datetime
from dateutil import parser
from dateutil.tz import gettz
import sqlite3
import logging
from bs4 import BeautifulSoup

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
DISCORD_WEBHOOK_TOPICS = os.environ.get('DISCORD_WEBHOOK_TOPICS')

# DB 설정
DB_PATH = 'google_news_topic.db'

def check_env_variables():
    if not DISCORD_WEBHOOK_TOPICS:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_TOPICS")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news_items
                 (guid TEXT PRIMARY KEY,
                  pub_date TEXT,
                  title TEXT,
                  link TEXT,
                  related_news TEXT,
                  posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

def save_news_item(guid, pub_date, title, link, related_news):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO news_items 
                 (guid, pub_date, title, link, related_news) 
                 VALUES (?, ?, ?, ?, ?)""", 
              (guid, pub_date, title, link, related_news))
    conn.commit()
    conn.close()
    logging.info(f"새 뉴스 항목 저장: {guid}")

def fetch_rss_feed(url):
    response = requests.get(url)
    return response.content

def replace_brackets(text):
    return text.replace("[", "〔").replace("]", "〕")
    
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
            link, title_text = title_match.groups()
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
    headers = {"Content-Type": "application/json"}
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
            link = a_tag['href']
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            news_items.append({"title": title, "link": link, "press": press})
    return news_items

def main():
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    init_db()

    news_items = root.findall('.//item')
    for index, item in reversed(list(enumerate(news_items))):
        guid = item.find('guid').text

        if is_guid_posted(guid):
            continue

        title = item.find('title').text
        link = item.find('link').text
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        
        title = replace_brackets(title)
        formatted_date = parse_rss_date(pub_date)

        related_news = extract_news_items(description_html)
        related_news_json = json.dumps(related_news)

        description = parse_html_description(description_html)
        discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**[{title}](<{link}>)**\n>>> {description}\n\n📅 {formatted_date}"
        send_discord_message(DISCORD_WEBHOOK_TOPICS, discord_message)

        save_news_item(guid, pub_date, title, link, related_news_json)

if __name__ == "__main__":
    try:
        check_env_variables()
        main()
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
    finally:
        logging.info("프로그램 실행 종료")
