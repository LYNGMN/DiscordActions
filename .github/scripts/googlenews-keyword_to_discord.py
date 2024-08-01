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
import pytz
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote, quote
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
    """데이터베이스를 초기화하거나 기존 데이터베이스를 사용합니다."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        try:
            if reset:
                c.execute("DROP TABLE IF EXISTS news_items")
                logging.info("기존 news_items 테이블 삭제됨")
            
            c.execute('''CREATE TABLE IF NOT EXISTS news_items
                         (pub_date TEXT,
                          guid TEXT PRIMARY KEY,
                          title TEXT,
                          link TEXT,
                          topic TEXT,
                          related_news TEXT)''')
            
            # 테이블이 비어있는지 확인
            c.execute("SELECT COUNT(*) FROM news_items")
            count = c.fetchone()[0]
            
            if reset or count == 0:
                logging.info("새로운 데이터베이스가 초기화되었습니다.")
            else:
                logging.info(f"기존 데이터베이스를 사용합니다. 현재 {count}개의 항목이 있습니다.")
            
        except sqlite3.Error as e:
            logging.error(f"데이터베이스 초기화 중 오류 발생: {e}")
            raise

def is_guid_posted(guid):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM news_items WHERE guid = ?", (guid,))
            result = c.fetchone() is not None
            logging.info(f"GUID {guid} 확인 결과: {'이미 게시됨' if result else '새로운 항목'}")
            return result
    except sqlite3.Error as e:
        logging.error(f"데이터베이스 오류 (GUID 확인 중): {e}")
        return False

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
		
def fetch_decoded_batch_execute(id):
    s = (
        '[[["Fbv4je","[\\"garturlreq\\",[[\\"en-US\\",\\"US\\",[\\"FINANCE_TOP_INDICES\\",\\"WEB_TEST_1_0_0\\"],'
        'null,null,1,1,\\"US:en\\",null,180,null,null,null,null,null,0,null,null,[1608992183,723341000]],'
        '\\"en-US\\",\\"US\\",1,[2,3,4,8],1,0,\\"655000234\\",0,0,null,0],\\"' +
        id +
        '\\"]",null,"generic"]]]'
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Referer": "https://news.google.com/"
    }

    response = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
        headers=headers,
        data={"f.req": s}
    )

    if response.status_code != 200:
        raise Exception("Failed to fetch data from Google.")

    text = response.text
    header = '[\\"garturlres\\",\\"'
    footer = '\\",'
    if header not in text:
        raise Exception(f"Header not found in response: {text}")
    start = text.split(header, 1)[1]
    if footer not in start:
        raise Exception("Footer not found in response.")
    url = start.split(footer, 1)[0]
    return url

def decode_base64_url_part(encoded_str):
    base64_str = encoded_str.replace("-", "+").replace("_", "/")
    base64_str += "=" * ((4 - len(base64_str) % 4) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(base64_str)
        decoded_str = decoded_bytes.decode('latin1')
        return decoded_str
    except Exception as e:
        return f"디코딩 중 오류 발생: {e}"

def extract_youtube_id(decoded_str):
    pattern = r'\x08 "\x0b([\w-]{11})\x98\x01\x01'
    match = re.search(pattern, decoded_str)
    if match:
        return match.group(1)
    return None

def extract_regular_url(decoded_str):
    """디코딩된 문자열에서 일반 URL 추출"""
    parts = re.split(r'[^\x20-\x7E]+', decoded_str)
    url_pattern = r'(https?://[^\s]+)'
    for part in parts:
        match = re.search(url_pattern, part)
        if match:
            return match.group(0)
    return None

def unescape_unicode(text):
    """유니코드 이스케이프 시퀀스를 실제 문자로 변환합니다."""
    return re.sub(
        r'\\u([0-9a-fA-F]{4})',
        lambda m: chr(int(m.group(1), 16)),
        text
    )

def clean_url(url):
    """URL을 정리하고 유니코드 문자를 처리하는 함수"""
    # 유니코드 이스케이프 시퀀스 처리
    url = unescape_unicode(url)
    
    # 백슬래시를 정리
    url = url.replace('\\', '')
    
    # URL 디코딩 (예: %2F -> /, %40 -> @ 등)
    url = unquote(url)

    parsed_url = urlparse(url)
    
    # MSN 링크 특별 처리: HTTPS로 변환 및 불필요한 쿼리 파라미터 제거
    if parsed_url.netloc.endswith('msn.com'):
        parsed_url = parsed_url._replace(scheme='https')
        query_params = parse_qs(parsed_url.query)
        cleaned_params = {k: v[0] for k, v in query_params.items() if k in ['id', 'article']}
        cleaned_query = urlencode(cleaned_params)
        parsed_url = parsed_url._replace(query=cleaned_query)
    
    # 공백 등 비정상적인 문자 처리
    # safe 파라미터에 특수 문자들을 포함하여 인코딩되지 않도록 설정
    safe_chars = "/:@&=+$,?#"
    cleaned_path = quote(parsed_url.path, safe=safe_chars)
    cleaned_query = quote(parsed_url.query, safe=safe_chars)
    
    # URL 재구성
    cleaned_url = urlunparse(parsed_url._replace(path=cleaned_path, query=cleaned_query))
    
    return cleaned_url

def decode_google_news_url(source_url):
    url = urlparse(source_url)
    path = url.path.split("/")
    if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
        base64_str = path[-1]
        
        # 먼저 새로운 방식 시도
        try:
            decoded_bytes = base64.urlsafe_b64decode(base64_str + '==')
            decoded_str = decoded_bytes.decode('latin1')

            prefix = b'\x08\x13\x22'.decode('latin1')
            if decoded_str.startswith(prefix):
                decoded_str = decoded_str[len(prefix):]

            suffix = b'\xd2\x01\x00'.decode('latin1')
            if decoded_str.endswith(suffix):
                decoded_str = decoded_str[:-len(suffix)]

            bytes_array = bytearray(decoded_str, 'latin1')
            length = bytes_array[0]
            if length >= 0x80:
                decoded_str = decoded_str[2:length+1]
            else:
                decoded_str = decoded_str[1:length+1]

            if decoded_str.startswith("AU_yqL"):
                return clean_url(fetch_decoded_batch_execute(base64_str))

            regular_url = extract_regular_url(decoded_str)
            if regular_url:
                return clean_url(regular_url)
        except Exception:
            pass  # 새로운 방식이 실패하면 기존 방식 시도

        # 기존 방식 시도 (유튜브 링크 포함)
        decoded_str = decode_base64_url_part(base64_str)
        youtube_id = extract_youtube_id(decoded_str)
        if youtube_id:
            return f"https://www.youtube.com/watch?v={youtube_id}"

        regular_url = extract_regular_url(decoded_str)
        if regular_url:
            return clean_url(regular_url)

    return clean_url(source_url)  # 디코딩 실패 시 원본 URL 정리 후 반환

def get_original_url(google_link, session, max_retries=5):
    if ORIGIN_LINK_KEYWORD:
        original_url = decode_google_news_url(google_link)
        if original_url != google_link:
            return original_url

        # 디코딩 실패 시 requests 방식 시도
        retries = 0
        while retries < max_retries:
            try:
                response = session.get(google_link, allow_redirects=True)
                if response.status_code == 200:
                    return clean_url(response.url)
            except requests.RequestException as e:
                logging.error(f"Failed to get original URL: {e}")
            retries += 1
        
        logging.warning(f"오리지널 링크 추출 실패, 원 링크 사용: {google_link}")
        return clean_url(google_link)
    else:
        logging.info(f"ORIGIN_LINK_KEYWORD가 False, 원 링크 사용: {google_link}")
        return clean_url(google_link)

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
    since_date = None
    until_date = None
    past_date = None

    logging.info(f"파싱 중인 날짜 필터 문자열: {filter_string}")

    if not filter_string:
        logging.warning("날짜 필터 문자열이 비어있습니다.")
        return since_date, until_date, past_date

    since_match = re.search(r'since:(\d{4}-\d{2}-\d{2})', filter_string)
    until_match = re.search(r'until:(\d{4}-\d{2}-\d{2})', filter_string)
    
    if since_match:
        since_date = datetime.strptime(since_match.group(1), '%Y-%m-%d').replace(tzinfo=pytz.UTC)
        logging.info(f"since_date 파싱 결과: {since_date}")
    if until_match:
        until_date = datetime.strptime(until_match.group(1), '%Y-%m-%d').replace(tzinfo=pytz.UTC)
        logging.info(f"until_date 파싱 결과: {until_date}")

    past_match = re.search(r'past:(\d+)([hdmy])', filter_string)
    if past_match:
        value = int(past_match.group(1))
        unit = past_match.group(2)
        now = datetime.now(pytz.UTC)
        if unit == 'h':
            past_date = now - timedelta(hours=value)
        elif unit == 'd':
            past_date = now - timedelta(days=value)
        elif unit == 'm':
            past_date = now - timedelta(days=value*30)  # 근사값 사용
        elif unit == 'y':
            past_date = now - timedelta(days=value*365)  # 근사값 사용
        logging.info(f"past_date 파싱 결과: {past_date}")
    else:
        logging.warning("past: 형식의 날짜 필터를 찾을 수 없습니다.")

    logging.info(f"최종 파싱 결과 - since_date: {since_date}, until_date: {until_date}, past_date: {past_date}")
    return since_date, until_date, past_date

def is_within_date_range(pub_date, since_date, until_date, past_date):
    pub_datetime = parser.parse(pub_date).replace(tzinfo=pytz.UTC)
    now = datetime.now(pytz.UTC)
    
    logging.info(f"검사 중인 기사 날짜: {pub_datetime}")
    logging.info(f"현재 날짜: {now}")
    logging.info(f"설정된 필터 - since_date: {since_date}, until_date: {until_date}, past_date: {past_date}")

    if past_date:
        result = pub_datetime >= past_date
        logging.info(f"past_date 필터 적용 결과: {result}")
        return result
    
    if since_date and pub_datetime < since_date:
        logging.info(f"since_date 필터에 의해 제외됨")
        return False
    if until_date and pub_datetime > until_date:
        logging.info(f"until_date 필터에 의해 제외됨")
        return False
    
    logging.info(f"모든 날짜 필터를 통과함")
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
    logging.info(f"적용될 날짜 필터 - since_date: {since_date}, until_date: {until_date}, past_date: {past_date}")

    with sqlite3.connect(DB_PATH) as conn:
        for item in news_items:
            guid = item.find('guid').text

            if not INITIALIZE_KEYWORD and is_guid_posted(guid, conn):
                logging.info(f"이미 게시된 항목 건너뜀: {guid}")
                continue

            title = replace_brackets(item.find('title').text)
            google_link = item.find('link').text
            link = get_original_url(google_link, session)
            pub_date = item.find('pubDate').text
            description_html = item.find('description').text
            
            formatted_date = parse_rss_date(pub_date)

            # 날짜 필터 적용 (중복 체크 후)
            if not is_within_date_range(pub_date, since_date, until_date, past_date):
                logging.info(f"날짜 필터에 의해 건너뛰어진 뉴스: {title}")
                continue

            logging.info(f"날짜 필터를 통과한 뉴스: {title}")

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

if __name__ == "__main__":
    try:
        check_env_variables()
        main()
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)  # 오류 발생 시 비정상 종료
    else:
        logging.info("프로그램 정상 종료")