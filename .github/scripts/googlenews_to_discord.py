import xml.etree.ElementTree as ET
import requests
import re
import os
import time
import random
import logging
import json
import base64
import sqlite3
import sys
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime
from dateutil import parser
from dateutil.tz import gettz
from bs4 import BeautifulSoup

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK')
DISCORD_AVATAR = os.environ.get('DISCORD_AVATAR')
DISCORD_USERNAME = os.environ.get('DISCORD_USERNAME')
INITIALIZE = os.environ.get('INITIALIZE', 'false').lower() == 'true'
KEYWORD_MODE = os.environ.get('KEYWORD_MODE', 'false').lower() == 'true'
KEYWORD = os.environ.get('KEYWORD', '')
RSS_URL = os.environ.get('RSS_URL', '')
AFTER_DATE = os.environ.get('AFTER_DATE', '')
BEFORE_DATE = os.environ.get('BEFORE_DATE', '')
WHEN = os.environ.get('WHEN', '')
HL = os.environ.get('HL', 'ko')
GL = os.environ.get('GL', 'KR')
CEID = os.environ.get('CEID', 'KR:ko')

# DB 설정
DB_PATH = 'google_news.db'

def check_env_variables():
    """환경 변수가 설정되어 있는지 확인합니다."""
    if not DISCORD_WEBHOOK:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK")
    if KEYWORD_MODE and not KEYWORD:
        raise ValueError("키워드 모드가 활성화되었지만 KEYWORD 환경 변수가 설정되지 않았습니다.")
    if not KEYWORD_MODE and not RSS_URL:
        raise ValueError("키워드 모드가 비활성화되었지만 RSS_URL 환경 변수가 설정되지 않았습니다.")
    if AFTER_DATE and not is_valid_date(AFTER_DATE):
        raise ValueError("AFTER_DATE 환경 변수가 올바른 형식(YYYY-MM-DD)이 아닙니다.")
    if BEFORE_DATE and not is_valid_date(BEFORE_DATE):
        raise ValueError("BEFORE_DATE 환경 변수가 올바른 형식(YYYY-MM-DD)이 아닙니다.")
    if WHEN and not WHEN.endswith('d'):
        raise ValueError("WHEN 환경 변수는 'd'로 끝나야 합니다. (예: '14d')")
    if WHEN and (AFTER_DATE or BEFORE_DATE):
        logging.error("WHEN과 AFTER_DATE/BEFORE_DATE는 함께 사용할 수 없습니다. WHEN을 사용하거나 AFTER_DATE/BEFORE_DATE를 사용하세요.")
        raise ValueError("잘못된 날짜 쿼리 조합입니다.")
    if not HL or not GL or not CEID:
        raise ValueError("HL, GL, CEID 환경 변수가 모두 설정되어야 합니다.")

def is_valid_date(date_string):
    """날짜 문자열이 올바른 형식(YYYY-MM-DD)인지 확인합니다."""
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def init_db(reset=False):
    """데이터베이스를 초기화합니다."""
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
    """주어진 GUID가 이미 게시되었는지 확인합니다."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM news_items WHERE guid = ?", (guid,))
        return c.fetchone() is not None

def save_news_item(pub_date, guid, title, link, related_news):
    """뉴스 항목을 데이터베이스에 저장합니다."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO news_items (pub_date, guid, title, link, related_news) VALUES (?, ?, ?, ?, ?)",
                  (pub_date, guid, title, link, related_news))
        logging.info(f"새 뉴스 항목 저장: {guid}")

def decode_google_news_url(source_url):
    """Google 뉴스 URL을 디코딩하여 원본 URL을 추출합니다."""
    url = urlparse(source_url)
    path = url.path.split('/')
    if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
        base64_str = path[-1]
        # 패딩 동적 추가
        base64_str += "=" * ((4 - len(base64_str) % 4) % 4)
        try:
            decoded_bytes = base64.urlsafe_b64decode(base64_str)
            decoded_str = decoded_bytes.decode('latin1')

            # URL 패턴을 개선하여 정확한 URL을 추출합니다.
            url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
            match = url_pattern.search(decoded_str)
            if match:
                final_url = match.group(0)
                logging.info(f"Google 뉴스 URL 디코딩 성공: {source_url} -> {final_url}")
                return final_url

        except Exception as e:
            logging.error(f"Base64 디코딩 중 오류 발생: {e}")
    logging.warning(f"Google 뉴스 URL 디코딩 실패, 원본 URL 반환: {source_url}")
    return source_url

def get_original_link(google_link, session, max_retries=5):
    """원본 링크를 가져옵니다."""
    decoded_url = decode_google_news_url(google_link)
    
    if decoded_url.startswith('http'):
        return decoded_url

    # 디코딩 실패 또는 유효하지 않은 URL일 경우 request 방식으로 재시도
    logging.info(f"유효하지 않은 URL. request 방식으로 재시도: {google_link}")
    
    wait_times = [5, 10, 30, 45, 60]
    for attempt in range(max_retries):
        try:
            response = session.get(google_link, allow_redirects=True, timeout=10)
            final_url = response.url
            if 'news.google.com' not in final_url:
                logging.info(f"Request 방식 성공 - Google 링크: {google_link}")
                logging.info(f"최종 URL: {final_url}")
                return final_url
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logging.error(f"최대 시도 횟수 초과. 원본 링크를 가져오는 데 실패했습니다: {str(e)}")
                return google_link
            wait_time = wait_times[min(attempt, len(wait_times) - 1)] + random.uniform(0, 5)
            logging.warning(f"시도 {attempt + 1}/{max_retries}: 요청 실패. {wait_time:.2f}초 후 재시도합니다. 오류: {str(e)}")
            time.sleep(wait_time)

    logging.error(f"모든 방법 실패. 원래의 Google 링크를 사용합니다: {google_link}")
    return google_link

def fetch_rss_feed(url):
    """RSS 피드를 가져옵니다."""
    response = requests.get(url)
    return response.content

def replace_brackets(text):
    """대괄호와 꺾쇠괄호를 유니코드 문자로 대체합니다."""
    text = text.replace('[', '［').replace(']', '］')
    text = text.replace('<', '〈').replace('>', '〉')
    text = re.sub(r'(?<!\s)(?<!^)［', ' ［', text)
    text = re.sub(r'］(?!\s)', '］ ', text)
    text = re.sub(r'(?<!\s)(?<!^)〈', ' 〈', text)
    text = re.sub(r'〉(?!\s)', '〉 ', text)
    return text

def parse_rss_date(pub_date):
    """RSS 날짜를 파싱하여 형식화된 문자열로 반환합니다."""
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

def send_discord_message(webhook_url, message, avatar_url=None, username=None):
    """Discord 웹훅을 사용하여 메시지를 전송합니다."""
    payload = {"content": message}
    
    if avatar_url and avatar_url.strip():
        payload["avatar_url"] = avatar_url
    
    if username and username.strip():
        payload["username"] = username
    
    headers = {"Content-Type": "application/json"}
    response = requests.post(webhook_url, json=payload, headers=headers)
    if response.status_code != 204:
        logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        logging.error(response.text)
    else:
        logging.info("Discord에 메시지 게시 완료")
    time.sleep(3)

def extract_news_items(description, session):
    """HTML 설명에서 뉴스 항목을 추출합니다."""
    soup = BeautifulSoup(description, 'html.parser')
    news_items = []
    for li in soup.find_all('li'):
        a_tag = li.find('a')
        if a_tag:
            title = replace_brackets(a_tag.text)
            google_link = a_tag['href']
            link = get_original_link(google_link, session)
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            news_items.append({"title": title, "link": link, "press": press})
    return news_items

def parse_html_description(html_desc, session, main_title, main_link):
    """HTML 설명을 파싱하여 관련 뉴스 문자열을 생성합니다."""
    news_items = extract_news_items(html_desc, session)
    
    # 메인 뉴스와 동일한 제목과 링크를 가진 항목 제거
    news_items = [item for item in news_items if item['title'] != main_title or item['link'] != main_link]
    
    if len(news_items) == 0:
        return "", []  # 관련 뉴스가 없거나 메인 뉴스와 동일한 경우
    elif len(news_items) == 1:
        return "", news_items  # 관련 뉴스가 1개인 경우 (표시하지 않음)
    else:
        news_string = '\n'.join([f"> - [{item['title']}]({item['link']}) | {item['press']}" for item in news_items])
        return news_string, news_items

def extract_keyword_from_url(url):
    """RSS URL에서 키워드를 추출하고 디코딩합니다."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if 'q' in query_params:
        encoded_keyword = query_params['q'][0]
        return unquote(encoded_keyword)
    return "주요 뉴스"  # 기본값

def main():
    """메인 함수: RSS 피드를 가져와 처리하고 Discord로 전송합니다."""
    rss_base_url = "https://news.google.com/rss/search"
    
    if KEYWORD_MODE:
        encoded_keyword = requests.utils.quote(KEYWORD)
        query_params = [f"q={encoded_keyword}"]
        
        if WHEN:
            query_params[-1] += f"+when:{WHEN}"
        elif AFTER_DATE or BEFORE_DATE:
            if AFTER_DATE:
                query_params[-1] += f"+after:{AFTER_DATE}"
            if BEFORE_DATE:
                query_params[-1] += f"+before:{BEFORE_DATE}"
        
        query_string = "+".join(query_params)
        rss_url = f"{rss_base_url}?{query_string}&hl={HL}&gl={GL}&ceid={CEID}"
        category = KEYWORD
    else:
        rss_url = RSS_URL
        category = extract_keyword_from_url(rss_url)

    logging.info(f"사용된 RSS URL: {rss_url}")

    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    init_db(reset=INITIALIZE)

    session = requests.Session()
    
    news_items = root.findall('.//item')
    news_items = sorted(news_items, key=lambda item: parser.parse(item.find('pubDate').text))

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

        description, related_news = parse_html_description(description_html, session, title, link)

        discord_message = f"`Google 뉴스 - {category} - 한국 🇰🇷`\n**{title}**\n{link}"
        if description:
            discord_message += f"\n{description}"
        discord_message += f"\n\n📅 {formatted_date}"

        send_discord_message(
            DISCORD_WEBHOOK,
            discord_message,
            avatar_url=DISCORD_AVATAR,
            username=DISCORD_USERNAME
        )

        save_news_item(pub_date, guid, title, link, json.dumps(related_news, ensure_ascii=False))

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
