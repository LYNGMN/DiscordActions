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
from datetime import datetime, timedelta
from dateutil import parser
from dateutil.tz import gettz
from bs4 import BeautifulSoup

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
DISCORD_WEBHOOK_KEYWORD = os.environ.get('DISCORD_WEBHOOK_KEYWORD')
DISCORD_AVATAR_KEYWORD = os.environ.get('DISCORD_AVATAR_KEYWORD')
DISCORD_USERNAME_KEYWORD = os.environ.get('DISCORD_USERNAME_KEYWORD')
INITIALIZE_KEYWORD = os.environ.get('INITIALIZE_MODE_KEYWORD', 'false').lower() == 'true'
KEYWORD_MODE = os.environ.get('KEYWORD_MODE', 'false').lower() == 'true'
KEYWORD = os.environ.get('KEYWORD', '')
RSS_URL_KEYWORD = os.environ.get('RSS_URL_KEYWORD', '')
AFTER_DATE = os.environ.get('AFTER_DATE', '')
BEFORE_DATE = os.environ.get('BEFORE_DATE', '')
WHEN = os.environ.get('WHEN', '')
HL = os.environ.get('HL', '')
GL = os.environ.get('GL', '')
CEID = os.environ.get('CEID', '')
ADVANCED_FILTER_KEYWORD = os.environ.get('ADVANCED_FILTER_KEYWORD', '')
DATE_FILTER_KEYWORD = os.environ.get('DATE_FILTER_KEYWORD', '')
ORIGIN_LINK_KEYWORD = os.getenv('ORIGIN_LINK_KEYWORD', '').lower()
ORIGIN_LINK_KEYWORD = ORIGIN_LINK_KEYWORD not in ['false', 'f', '0', 'no', 'n']

# ORIGIN_LINK_KEYWORD 값을 로그에 출력
logging.info(f"ORIGIN_LINK_KEYWORD 값: {ORIGIN_LINK_KEYWORD}")

# DB 설정
DB_PATH = 'google_news_keyword.db'

def check_env_variables():
    """환경 변수가 설정되어 있는지 확인합니다."""
    if not DISCORD_WEBHOOK_KEYWORD:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_KEYWORD")
    if KEYWORD_MODE and not KEYWORD:
        raise ValueError("키워드 모드가 활성화되었지만 KEYWORD 환경 변수가 설정되지 않았습니다.")
    if not KEYWORD_MODE and not RSS_URL_KEYWORD:
        raise ValueError("키워드 모드가 비활성화되었지만 RSS_URL_KEYWORD 환경 변수가 설정되지 않았습니다.")
    if AFTER_DATE and not is_valid_date(AFTER_DATE):
        raise ValueError("AFTER_DATE 환경 변수가 올바른 형식(YYYY-MM-DD)이 아닙니다.")
    if BEFORE_DATE and not is_valid_date(BEFORE_DATE):
        raise ValueError("BEFORE_DATE 환경 변수가 올바른 형식(YYYY-MM-DD)이 아닙니다.")
    if WHEN and (AFTER_DATE or BEFORE_DATE):
        logging.error("WHEN과 AFTER_DATE/BEFORE_DATE는 함께 사용할 수 없습니다. WHEN을 사용하거나 AFTER_DATE/BEFORE_DATE를 사용하세요.")
        raise ValueError("잘못된 날짜 쿼리 조합입니다.")
    if (HL or GL or CEID) and not (HL and GL and CEID):
        raise ValueError("HL, GL, CEID 환경 변수는 모두 설정되거나 모두 설정되지 않아야 합니다.")
    if ADVANCED_FILTER_KEYWORD:
        logging.info(f"고급 검색 필터가 설정되었습니다: {ADVANCED_FILTER_KEYWORD}")
    if DATE_FILTER_KEYWORD:
        logging.info(f"날짜 필터가 설정되었습니다: {DATE_FILTER_KEYWORD}")

def is_valid_date(date_string):
    """날짜 문자열이 올바른 형식(YYYY-MM-DD)인지 확인합니다."""
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

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
        result = c.fetchone()
        logging.info(f"GUID {guid} 중복 확인 결과: {'중복' if result else '새로운 항목'}")
        return result is not None

def save_news_item(pub_date, guid, title, link, related_news):
    """뉴스 항목을 데이터베이스에 저장합니다."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        
        # 기존 테이블 구조 확인
        c.execute("PRAGMA table_info(news_items)")
        columns = [column[1] for column in c.fetchall()]
        
        # 관련 뉴스 항목 수 확인
        related_news_items = json.loads(related_news)
        related_news_count = len(related_news_items)
        
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
        
        for i, item in enumerate(related_news_items):
            columns.extend([f"related_title_{i+1}", f"related_press_{i+1}", f"related_link_{i+1}"])
            values.extend([item.get('title', ''), item.get('press', ''), item.get('link', '')])
        
        placeholders = ", ".join(["?" for _ in values])
        columns_str = ", ".join(columns)
        
        c.execute(f"INSERT OR REPLACE INTO news_items ({columns_str}) VALUES ({placeholders})", values)
        
        logging.info(f"뉴스 항목 저장/업데이트: {guid}")
		
def decode_base64_url_part(encoded_str):
    """Base64로 인코딩된 문자열을 디코딩"""
    base64_str = encoded_str.replace("-", "+").replace("_", "/")
    base64_str += "=" * ((4 - len(base64_str) % 4) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(base64_str)
        decoded_str = decoded_bytes.decode('latin1')  # latin1을 사용하여 디코딩
        return decoded_str
    except Exception as e:
        return f"디코딩 중 오류 발생: {e}"

def extract_regular_url(decoded_str):
    """디코딩된 문자열에서 첫 번째 URL만 정확히 추출"""
    parts = re.split(r'[^\x20-\x7E]+', decoded_str)
    url_pattern = r'(https?://[^\s]+)'
    for part in parts:
        match = re.search(url_pattern, part)
        if match:
            return match.group(0)
    return None

def extract_youtube_id(decoded_str):
    """디코딩된 문자열에서 유튜브 영상 ID 추출"""
    pattern = r'\x08 "\x0b([\w-]{11})\x98\x01\x01'
    match = re.search(pattern, decoded_str)
    if match:
        return match.group(1)
    return None

def decode_google_news_url(source_url):
    """Google 뉴스 URL을 디코딩하여 원본 URL을 추출합니다."""
    url = urlparse(source_url)
    path = url.path.split('/')
    if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
        base64_str = path[-1]
        decoded_str = decode_base64_url_part(base64_str)
        
        regular_url = extract_regular_url(decoded_str)
        if regular_url:
            logging.info(f"일반 링크 추출 성공: {source_url} -> {regular_url}")
            return regular_url
        
        youtube_id = extract_youtube_id(decoded_str)
        if youtube_id:
            youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"
            logging.info(f"유튜브 링크 추출 성공: {source_url} -> {youtube_url}")
            return youtube_url
    
    logging.warning(f"Google 뉴스 URL 디코딩 실패, 원본 URL 반환: {source_url}")
    return source_url

def get_original_url(google_link, session, max_retries=5):
    """
    Google 뉴스 링크를 원본 URL로 변환합니다. 
    ORIGIN_LINK_KEYWORD 설정에 따라 동작이 달라집니다:
    - 설정하지 않았거나 True: 오리지널 링크를 가져옵니다.
    - False: 원 링크(구글 링크)를 그대로 사용합니다.
    """
    logging.info(f"ORIGIN_LINK_KEYWORD 값 확인: {ORIGIN_LINK_KEYWORD}")

    if ORIGIN_LINK_KEYWORD:
        # 오리지널 링크를 가져오려고 시도
        original_url = decode_google_news_url(google_link)
        if original_url != google_link:
            return original_url

        # 디코딩 실패 시 requests 방식 시도
        retries = 0
        while retries < max_retries:
            try:
                response = session.get(google_link, allow_redirects=True)
                if response.status_code == 200:
                    return response.url
            except requests.RequestException as e:
                logging.error(f"Failed to get original URL: {e}")
            retries += 1
        
        # 모든 시도가 실패한 경우 원 링크 반환
        logging.warning(f"오리지널 링크 추출 실패, 원 링크 사용: {google_link}")
        return google_link
    else:
        # ORIGIN_LINK_KEYWORD가 False인 경우 원 링크를 그대로 반환
        logging.info(f"ORIGIN_LINK_KEYWORD가 False, 원 링크 사용: {google_link}")
        return google_link

def fetch_rss_feed(url):
    """RSS 피드를 가져옵니다."""
    response = requests.get(url)
    return response.content

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
            link = get_original_url(google_link, session)
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            news_items.append({"title": title, "link": link, "press": press})
    return news_items

def parse_html_description(html_desc, session, main_title, main_link):
    """HTML 설명을 파싱하여 관련 뉴스 문자열을 생성합니다."""
    news_items = extract_news_items(html_desc, session)
    
    news_items = [item for item in news_items if item['title'] != main_title or item['link'] != main_link]
    
    if len(news_items) == 0:
        return "", []  # 관련 뉴스가 없거나 메인 뉴스와 동일한 경우
    elif len(news_items) == 1:
        return "", news_items  # 관련 뉴스가 1개인 경우 (표시하지 않음)
    else:
        news_string = '\n'.join([f"> - [{item['title']}]({item['link']}) | {item['press']}" for item in news_items])
        return news_string, news_items

def extract_rss_feed_category(title):
    """RSS 피드 제목에서 카테고리를 추출합니다."""
    match = re.search(r'"([^"]+)', title)
    if match:
        category = match.group(1)
        if 'when:' in category:
            category = category.split('when:')[0].strip()
        return category
    return "디스코드"

def apply_advanced_filter(title, description, advanced_filter):
    """고급 검색 필터를 적용하여 게시물을 전송할지 결정합니다."""
    if not advanced_filter:
        return True

    text_to_check = (title + ' ' + description).lower()

    terms = re.findall(r'([+-]?)(?:"([^"]*)"|\S+)', advanced_filter)

    for prefix, term in terms:
        term = term.lower() if term else prefix.lower()
        if prefix == '+' or not prefix:  # 포함해야 하는 단어
            if term not in text_to_check:
                return False
        elif prefix == '-':  # 제외해야 하는 단어 또는 구문
            exclude_terms = term.split()
            if len(exclude_terms) > 1:
                if ' '.join(exclude_terms) in text_to_check:
                    return False
            else:
                if term in text_to_check:
                    return False

    return True

def parse_date_filter(filter_string):
    """날짜 필터 문자열을 파싱하여 시작 날짜와 종료 날짜를 반환합니다."""
    since_date = None
    until_date = None
    past_date = None

    since_match = re.search(r'since:(\d{4}-\d{2}-\d{2})', filter_string)
    until_match = re.search(r'until:(\d{4}-\d{2}-\d{2})', filter_string)
    
    if since_match:
        since_date = datetime.strptime(since_match.group(1), '%Y-%m-%d')
    if until_match:
        until_date = datetime.strptime(until_match.group(1), '%Y-%m-%d')

    past_match = re.search(r'past:(\d+)([hdmy])', filter_string)
    if past_match:
        value = int(past_match.group(1))
        unit = past_match.group(2)
        now = datetime.now()
        if unit == 'h':
            past_date = now - timedelta(hours=value)
        elif unit == 'd':
            past_date = now - timedelta(days=value)
        elif unit == 'm':
            past_date = now - timedelta(days=value*30)  # 근사값 사용
        elif unit == 'y':
            past_date = now - timedelta(days=value*365)  # 근사값 사용

    return since_date, until_date, past_date

def is_within_date_range(pub_date, since_date, until_date, past_date):
    """주어진 날짜가 필터 범위 내에 있는지 확인합니다."""
    pub_datetime = parser.parse(pub_date)
    
    if past_date:
        return pub_datetime >= past_date
    
    if since_date and pub_datetime < since_date:
        return False
    if until_date and pub_datetime > until_date:
        return False
    
    return True
	
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
        
        if HL and GL and CEID:
            rss_url = f"{rss_base_url}?{query_string}&hl={HL}&gl={GL}&ceid={CEID}"
        else:
            rss_url = f"{rss_base_url}?{query_string}&hl=ko&gl=KR&ceid=KR:ko"
        
        category = KEYWORD
    else:
        rss_url = RSS_URL_KEYWORD
        rss_data = fetch_rss_feed(rss_url)
        root = ET.fromstring(rss_data)
        title_element = root.find('.//channel/title')
        if title_element is not None:
            category = extract_rss_feed_category(title_element.text)
        else:
            category = "디스코드"

    logging.info(f"사용된 RSS URL: {rss_url}")

    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    init_db(reset=INITIALIZE_KEYWORD)

    session = requests.Session()
    
    news_items = root.findall('.//item')
    news_items = sorted(news_items, key=lambda item: parser.parse(item.find('pubDate').text))

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_KEYWORD)

    for item in news_items:
        guid = item.find('guid').text

        if not INITIALIZE_KEYWORD and is_guid_posted(guid):
            continue

        title = replace_brackets(item.find('title').text)
        google_link = item.find('link').text
        link = get_original_url(google_link, session)
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        
        formatted_date = parse_rss_date(pub_date)

        # 날짜 필터 적용
        if not is_within_date_range(pub_date, since_date, until_date, past_date):
            logging.info(f"날짜 필터에 의해 건너뛰어진 뉴스: {title}")
            continue

        description, related_news = parse_html_description(description_html, session, title, link)

        # 고급 검색 필터 적용
        if not apply_advanced_filter(title, description, ADVANCED_FILTER_KEYWORD):
            logging.info(f"고급 검색 필터에 의해 건너뛰어진 뉴스: {title}")
            continue

        discord_message = f"`Google 뉴스 - {category} - 한국 🇰🇷`\n**{title}**\n{link}"
        if description:
            discord_message += f"\n{description}"
        discord_message += f"\n\n📅 {formatted_date}"

        send_discord_message(
            DISCORD_WEBHOOK_KEYWORD,
            discord_message,
            avatar_url=DISCORD_AVATAR_KEYWORD,
            username=DISCORD_USERNAME_KEYWORD
        )

        save_news_item(pub_date, guid, title, link, json.dumps(related_news, ensure_ascii=False))

        if not INITIALIZE_KEYWORD:
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