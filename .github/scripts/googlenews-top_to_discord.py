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
INITIALIZE = os.environ.get('INITIALIZE_MODE', 'false').lower() == 'true'
ADVANCED_FILTER = os.environ.get('ADVANCED_FILTER', '')

# DB 설정
DB_PATH = 'google_news_top.db'

def check_env_variables():
    """환경 변수가 설정되어 있는지 확인합니다."""
    if not DISCORD_WEBHOOK:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK")

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

def decode_google_news_url(source_url):
    """Google 뉴스 URL을 디코딩하여 원본 URL을 추출합니다."""
    url = urlparse(source_url)
    path = url.path.split('/')
    if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
        base64_str = path[-1].replace('-', '+').replace('_', '/')
        # 패딩 동적 추가
        base64_str += "=" * ((4 - len(base64_str) % 4) % 4)
        try:
            decoded_bytes = base64.urlsafe_b64decode(base64_str)
            decoded_str = decoded_bytes.decode('latin1')
            # 정규 표현식을 사용하여 URL 패턴을 추출
            url_pattern = re.compile(r'http[s]?://[^\s]+')
            match = url_pattern.search(decoded_str)
            if match:
                final_url = match.group(0).strip('R')
                logging.info(f"Google 뉴스 URL 디코딩 성공: {source_url} -> {final_url}")
                return final_url
        except Exception as e:
            logging.error(f"Base64 디코딩 중 오류 발생: {e}")
    logging.warning(f"Google 뉴스 URL 디코딩 실패, 원본 URL 반환: {source_url}")
    return source_url

def extract_video_id_from_google_news(url):
    """Google News RSS URL에서 비디오 ID를 추출합니다."""
    parsed_url = urlparse(url)
    path_parts = parsed_url.path.split('/')
    if len(path_parts) > 2 and path_parts[-2] == 'articles':
        encoded_part = path_parts[-1]
        try:
            # Base64 디코딩 (패딩 추가)
            padding = '=' * ((4 - len(encoded_part) % 4) % 4)
            decoded = base64.urlsafe_b64decode(encoded_part + padding)
            
            # 디코딩된 바이트 문자열에서 YouTube 비디오 ID 패턴 찾기
            match = re.search(b'-([\w-]{11})', decoded)
            if match:
                return match.group(1).decode('utf-8')
        except Exception as e:
            logging.error(f"비디오 ID 추출 중 오류 발생: {str(e)}")
    return None

def get_original_link(google_link, session, max_retries=5):
    """원본 링크를 가져옵니다."""
    # Google News RSS 링크에서 직접 YouTube 비디오 ID 추출 시도
    video_id = extract_video_id_from_google_news(google_link)
    if video_id:
        youtube_link = f"https://www.youtube.com/watch?v={video_id}"
        # YouTube 링크 유효성 검사
        if is_valid_youtube_link(youtube_link, session):
            logging.info(f"Google News RSS에서 유효한 YouTube 링크 추출 성공: {youtube_link}")
            return youtube_link
        else:
            logging.warning(f"추출된 YouTube 링크가 유효하지 않습니다: {youtube_link}")

    decoded_url = decode_google_news_url(google_link)
    
    if not decoded_url.startswith('http'):
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

    return decoded_url

def is_valid_youtube_link(url, session):
    """YouTube 링크의 유효성을 확인합니다."""
    try:
        response = session.head(url, allow_redirects=True, timeout=10)
        return response.status_code == 200 and 'youtube.com' in response.url
    except requests.RequestException:
        return False

def extract_youtube_video_id(url):
    """유튜브 URL에서 비디오 ID를 추출합니다."""
    # 정규 표현식 패턴
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?(?:embed\/)?(?:v\/)?(?:shorts\/)?([^&\n?#]+)',
        r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?(?:embed\/)?(?:v\/)?(?:shorts\/)?([\w-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None

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

def extract_keyword_from_url(url):
    """RSS URL에서 키워드를 추출하고 디코딩합니다."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if 'q' in query_params:
        encoded_keyword = query_params['q'][0]
        return unquote(encoded_keyword)
    return "주요 뉴스"  # 기본값

def apply_advanced_filter(title, description, advanced_filter):
    """고급 검색 필터를 적용하여 게시물을 전송할지 결정합니다."""
    if not advanced_filter:
        return True

    text_to_check = (title + ' ' + description).lower()

    # 정규 표현식을 사용하여 고급 검색 쿼리 파싱
    terms = re.findall(r'([+-]?)(?:"([^"]*)"|\S+)', advanced_filter)

    for prefix, term in terms:
        term = term.lower() if term else prefix.lower()
        if prefix == '+' or not prefix:  # 포함해야 하는 단어
            if term not in text_to_check:
                return False
        elif prefix == '-':  # 제외해야 하는 단어 또는 구문
            # 여러 단어로 구성된 제외 구문 처리
            exclude_terms = term.split()
            if len(exclude_terms) > 1:
                if ' '.join(exclude_terms) in text_to_check:
                    return False
            else:
                if term in text_to_check:
                    return False

    return True

def main():
    """메인 함수: RSS 피드를 가져와 처리하고 Discord로 전송합니다."""
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    init_db(reset=INITIALIZE)

    # 환경 변수 가져오기
    discord_webhook_url = os.environ.get('DISCORD_WEBHOOK')
    discord_avatar_url = os.environ.get('DISCORD_AVATAR', '').strip()
    discord_username = os.environ.get('DISCORD_USERNAME', '').strip()

    session = requests.Session()
    
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

        description, related_news = parse_html_description(description_html, session, title, link)

        # 고급 검색 필터 적용
        if not apply_advanced_filter(title, description, ADVANCED_FILTER):
            logging.info(f"고급 검색 필터에 의해 건너뛰어진 뉴스: {title}")
            continue

        discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**{title}**\n{link}"
        if description:
            discord_message += f"\n>>> {description}"
        discord_message += f"\n\n📅 {formatted_date}"

        send_discord_message(
            discord_webhook_url,
            discord_message,
            avatar_url=discord_avatar_url,
            username=discord_username
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
