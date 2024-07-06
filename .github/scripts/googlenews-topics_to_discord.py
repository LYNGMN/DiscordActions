import xml.etree.ElementTree as ET
import aiohttp
import asyncio
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
INITIALIZE = os.environ.get('INITIALIZE', 'false').lower() == 'true'

# DB 설정
DB_PATH = 'google_news_topic.db'
CACHE_DB_PATH = 'link_cache.db'

# 사용자 에이전트 설정
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

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

def init_cache_db():
    conn = sqlite3.connect(CACHE_DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS link_cache
                 (google_link TEXT PRIMARY KEY, original_link TEXT)''')
    conn.commit()
    conn.close()

def get_cached_link(google_link):
    conn = sqlite3.connect(CACHE_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT original_link FROM link_cache WHERE google_link = ?", (google_link,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def cache_link(google_link, original_link):
    conn = sqlite3.connect(CACHE_DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO link_cache (google_link, original_link) VALUES (?, ?)",
              (google_link, original_link))
    conn.commit()
    conn.close()

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
    c.execute("INSERT OR REPLACE INTO news_items (pub_date, guid, title, link, related_news) VALUES (?, ?, ?, ?, ?)",
              (pub_date, guid, title, link, related_news))
    conn.commit()
    conn.close()
    logging.info(f"새 뉴스 항목 저장: {guid}")

async def fetch_rss_feed(url):
    async with aiohttp.ClientSession(headers={'User-Agent': USER_AGENT}) as session:
        async with session.get(url) as response:
            return await response.text()

def replace_brackets(text):
    return text.replace("[", "〔").replace("]", "〕")

async def get_original_link(session, google_link, max_retries=3):
    cached_link = get_cached_link(google_link)
    if cached_link:
        return cached_link
    
    for attempt in range(max_retries):
        try:
            async with session.get(google_link, allow_redirects=True, timeout=10) as response:
                original_link = str(response.url)
            cache_link(google_link, original_link)
            return original_link
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                logging.warning(f"원본 링크를 가져오는 데 실패했습니다: {google_link}. 오류: {e}")
                return google_link

async def process_news_items(session, description):
    news_items = []
    soup = BeautifulSoup(description, 'html.parser')
    tasks = []
    for li in soup.find_all('li'):
        a_tag = li.find('a')
        if a_tag:
            title = a_tag.text
            google_link = a_tag['href']
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            task = asyncio.ensure_future(get_original_link(session, google_link))
            tasks.append((title, task, press))
    
    for title, task, press in tasks:
        link = await task
        news_items.append({"title": title, "link": link, "press": press})
        await asyncio.sleep(0.1)
    
    return news_items

async def parse_html_description(session, html_desc):
    news_items = await process_news_items(session, html_desc)
    
    news_string = '\n'.join([f"- [{item['title']}](<{item['link']}>) | {item['press']}" for item in news_items])
    
    full_content_link_match = re.search(r'<a href="(https://news\.google\.com/stories/.*?)"', html_desc)
    if full_content_link_match:
        full_content_link = full_content_link_match.group(1)
        news_string += f"\n\n▶️ [Google 뉴스에서 전체 콘텐츠 보기](<{full_content_link}>)"

    return news_string, news_items

def parse_rss_date(pub_date):
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

async def send_discord_message(webhook_url, message, max_retries=3):
    payload = {"content": message}
    headers = {"Content-Type": "application/json; charset=utf-8"}
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload, headers=headers) as response:
                    if response.status == 204:
                        logging.info("Discord에 메시지 게시 완료")
                        return
                    else:
                        error_text = await response.text()
                        raise Exception(f"Discord 메시지 게시 실패. 상태 코드: {response.status}, 오류: {error_text}")
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Discord 메시지 게시 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(1)
            else:
                logging.error(f"Discord 메시지 게시 최종 실패: {e}")
                raise

async def main():
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = await fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    if INITIALIZE:
        init_db(reset=True)
        logging.info("초기화 모드로 실행 중: 데이터베이스를 재설정하고 모든 뉴스 항목을 처리합니다.")
    else:
        init_db()

    init_cache_db()

    news_items = root.findall('.//item')
    if INITIALIZE:
        news_items = list(news_items)
    else:
        news_items = reversed(news_items)

    async with aiohttp.ClientSession(headers={'User-Agent': USER_AGENT}) as session:
        for item in news_items:
            guid = item.find('guid').text

            if not INITIALIZE and is_guid_posted(guid):
                continue

            title = item.find('title').text
            google_link = item.find('link').text
            link = await get_original_link(session, google_link)
            pub_date = item.find('pubDate').text
            description_html = item.find('description').text
            
            title = replace_brackets(title)
            formatted_date = parse_rss_date(pub_date)

            description, related_news = await parse_html_description(session, description_html)
            
            discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**[{title}](<{link}>)**\n>>> {description}\n\n📅 {formatted_date}"
            await send_discord_message(DISCORD_WEBHOOK_TOPICS, discord_message)

            save_news_item(pub_date, guid, title, link, str(related_news))

            if not INITIALIZE:
                await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        check_env_variables()
        asyncio.run(main())
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
    finally:
        logging.info("프로그램 실행 종료")
