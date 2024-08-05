
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
DISCORD_WEBHOOK_TOP = os.environ.get('DISCORD_WEBHOOK_TOP')
DISCORD_AVATAR_TOP = os.environ.get('DISCORD_AVATAR_TOP', '').strip()
DISCORD_USERNAME_TOP = os.environ.get('DISCORD_USERNAME_TOP', '').strip()
INITIALIZE_TOP = os.environ.get('INITIALIZE_MODE_TOP', 'false').lower() == 'true'
ADVANCED_FILTER_TOP = os.environ.get('ADVANCED_FILTER_TOP', '')
DATE_FILTER_TOP = os.environ.get('DATE_FILTER_TOP', '')
ORIGIN_LINK_TOP = os.environ.get('ORIGIN_LINK_TOP', 'true').lower() == 'true'
TOP_MODE = os.environ.get('TOP_MODE', 'false').lower() == 'true'
TOP_COUNTRY = os.environ.get('TOP_COUNTRY')
RSS_URL_TOP = os.environ.get('RSS_URL_TOP')

# DB 설정
DB_PATH = 'google_news_top.db'

def check_env_variables():
    """환경 변수가 올바르게 설정되어 있는지 확인합니다."""
    global TOP_MODE, RSS_URL_TOP

    if not DISCORD_WEBHOOK_TOP:
        logging.error("DISCORD_WEBHOOK_TOP 환경 변수가 설정되지 않았습니다.")
        raise ValueError("DISCORD_WEBHOOK_TOP 환경 변수가 설정되지 않았습니다.")

    if TOP_MODE:
        if not TOP_COUNTRY:
            logging.error("TOP_MODE가 true로 설정되었지만 TOP_COUNTRY가 지정되지 않았습니다.")
            raise ValueError("TOP_MODE가 true일 때는 TOP_COUNTRY를 반드시 지정해야 합니다.")
        if RSS_URL_TOP:
            logging.error("TOP_MODE가 true로 설정되었지만 RSS_URL_TOP도 설정되어 있습니다.")
            raise ValueError("TOP_MODE가 true일 때는 RSS_URL_TOP를 설정하지 않아야 합니다.")
        logging.info(f"TOP_MODE가 활성화되었습니다. 선택된 국가: {TOP_COUNTRY}")
    else:
        if not RSS_URL_TOP:
            logging.error("TOP_MODE가 false이고 RSS_URL_TOP가 설정되지 않았습니다.")
            raise ValueError("TOP_MODE가 false일 때는 RSS_URL_TOP를 반드시 설정해야 합니다.")
        if TOP_COUNTRY:
            logging.warning("RSS_URL_TOP가 설정되어 있어 TOP_MODE가 false로 설정되었습니다. TOP_COUNTRY 설정은 무시됩니다.")
        TOP_MODE = False
        logging.info(f"RSS_URL_TOP가 설정되었습니다: {RSS_URL_TOP}")

    logging.info("환경 변수 확인 완료")
    
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
    logging.info(f"ORIGIN_LINK_TOP 값 확인: {ORIGIN_LINK_TOP}")

    # ORIGIN_LINK_TOP 설정과 상관없이 항상 원본 링크를 시도
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

def fetch_rss_feed(url, max_retries=3, retry_delay=5):
    """RSS 피드를 가져옵니다."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # 4xx, 5xx 상태 코드에 대해 예외를 발생시킵니다.
            return response.content
        except RequestException as e:
            logging.warning(f"RSS 피드 가져오기 실패 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt + 1 < max_retries:
                time.sleep(retry_delay)
            else:
                logging.error(f"RSS 피드를 가져오는데 실패했습니다: {url}")
                raise

def parse_rss_feed(rss_data):
    """RSS 피드를 파싱합니다."""
    try:
        root = ET.fromstring(rss_data)
        return root.findall('.//item')
    except ET.ParseError as e:
        logging.error(f"RSS 데이터 파싱 중 오류 발생: {e}")
        raise

def get_rss_url():
    if TOP_MODE:
        if not TOP_COUNTRY:
            raise ValueError("TOP_MODE가 true일 때 TOP_COUNTRY를 지정해야 합니다.")
        
        country_configs = {
            # 동아시아
            'KR': ('ko', 'KR:ko', 'Google 뉴스', '주요 뉴스', '한국', 'South Korea', '🇰🇷', 'Asia/Seoul', '%Y년 %m월 %d일 %H:%M:%S'),
            'JP': ('ja', 'JP:ja', 'Google ニュース', 'トップニュース', '日本', 'Japan', '🇯🇵', 'Asia/Tokyo', '%Y年%m月%d日 %H:%M:%S'),
            'CN': ('zh-CN', 'CN:zh-Hans', 'Google 新闻', '焦点新闻', '中国', 'China', '🇨🇳', 'Asia/Shanghai', '%Y年%m月%d日 %H:%M:%S'),
            'TW': ('zh-TW', 'TW:zh-Hant', 'Google 新聞', '焦點新聞', '台灣', 'Taiwan', '🇹🇼', 'Asia/Taipei', '%Y年%m月%d日 %H:%M:%S'),
            'HK': ('zh-HK', 'HK:zh-Hant', 'Google 新聞', '焦點新聞', '香港', 'Hong Kong', '🇭🇰', 'Asia/Hong_Kong', '%Y年%m月%d日 %H:%M:%S'),
            
            # 동남아시아
            'VN': ('vi', 'VN:vi', 'Google Tin tức', 'Tin nổi bật', 'Việt Nam', 'Vietnam', '🇻🇳', 'Asia/Ho_Chi_Minh', '%d/%m/%Y %H:%M:%S'),
            'TH': ('th', 'TH:th', 'Google News', 'เรื่องเด่น', 'ประเทศไทย', 'Thailand', '🇹🇭', 'Asia/Bangkok', '%d/%m/%Y %H:%M:%S'),
            'PH': ('en-PH', 'PH:en', 'Google News', 'Top stories', 'Philippines', 'Philippines', '🇵🇭', 'Asia/Manila', '%Y-%m-%d %I:%M:%S %p'),
            'MY': ('ms-MY', 'MY:ms', 'Berita Google', 'Berita hangat', 'Malaysia', 'Malaysia', '🇲🇾', 'Asia/Kuala_Lumpur', '%d/%m/%Y %H:%M:%S'),
            'SG': ('en-SG', 'SG:en', 'Google News', 'Top stories', 'Singapore', 'Singapore', '🇸🇬', 'Asia/Singapore', '%Y-%m-%d %I:%M:%S %p'),
            'ID': ('id', 'ID:id', 'Google Berita', 'Artikel populer', 'Indonesia', 'Indonesia', '🇮🇩', 'Asia/Jakarta', '%d/%m/%Y %H:%M:%S'),
            
            # 남아시아
            'IN': ('en-IN', 'IN:en', 'Google News', 'Top stories', 'India', 'India', '🇮🇳', 'Asia/Kolkata', '%d/%m/%Y %I:%M:%S %p'),
            'BD': ('bn', 'BD:bn', 'Google News', 'সেরা খবর', 'বাংলাদেশ', 'Bangladesh', '🇧🇩', 'Asia/Dhaka', '%d/%m/%Y %H:%M:%S'),
            'PK': ('en-PK', 'PK:en', 'Google News', 'Top stories', 'Pakistan', 'Pakistan', '🇵🇰', 'Asia/Karachi', '%d/%m/%Y %I:%M:%S %p'),
            
            # 서아시아
            'IL': ('he', 'IL:he', 'חדשות Google', 'הכתבות המובילות', 'ישראל', 'Israel', '🇮🇱', 'Asia/Jerusalem', '%d/%m/%Y %H:%M:%S'),
            'AE': ('ar', 'AE:ar', 'أخبار Google', 'أهم الأخبار', 'الإمارات العربية المتحدة', 'United Arab Emirates', '🇦🇪', 'Asia/Dubai', '%d/%m/%Y %I:%M:%S %p'),
            'TR': ('tr', 'TR:tr', 'Google Haberler', 'En çok okunan haberler', 'Türkiye', 'Turkey', '🇹🇷', 'Europe/Istanbul', '%d.%m.%Y %H:%M:%S'),
            'LB': ('ar', 'LB:ar', 'أخبار Google', 'أهم الأخبار', 'لبنان', 'Lebanon', '🇱🇧', 'Asia/Beirut', '%d/%m/%Y %I:%M:%S %p'),

            # 오세아니아
            'AU': ('en-AU', 'AU:en', 'Google News', 'Top stories', 'Australia', 'Australia', '🇦🇺', 'Australia/Sydney', '%d/%m/%Y %I:%M:%S %p'),
            'NZ': ('en-NZ', 'NZ:en', 'Google News', 'Top stories', 'New Zealand', 'New Zealand', '🇳🇿', 'Pacific/Auckland', '%d/%m/%Y %I:%M:%S %p'),

            # 러시아와 동유럽
            'RU': ('ru', 'RU:ru', 'Google Новости', 'Главные новости', 'Россия', 'Russia', '🇷🇺', 'Europe/Moscow', '%d.%m.%Y %H:%M:%S'),
            'UA': ('uk', 'UA:uk', 'Google Новини', 'Головні новини', 'Україна', 'Ukraine', '🇺🇦', 'Europe/Kiev', '%d.%m.%Y %H:%M:%S'),

            # 유럽
            'GR': ('el', 'GR:el', 'Ειδήσεις Google', 'Κυριότερες ειδήσεις', 'Ελλάδα', 'Greece', '🇬🇷', 'Europe/Athens', '%d/%m/%Y %H:%M:%S'),
            'DE': ('de', 'DE:de', 'Google News', 'Top-Meldungen', 'Deutschland', 'Germany', '🇩🇪', 'Europe/Berlin', '%d.%m.%Y %H:%M:%S'),
            'NL': ('nl', 'NL:nl', 'Google Nieuws', 'Voorpaginanieuws', 'Nederland', 'Netherlands', '🇳🇱', 'Europe/Amsterdam', '%d-%m-%Y %H:%M:%S'),
            'NO': ('no', 'NO:no', 'Google Nyheter', 'Hovedoppslag', 'Norge', 'Norway', '🇳🇴', 'Europe/Oslo', '%d.%m.%Y %H:%M:%S'),
            'LV': ('lv', 'LV:lv', 'Google ziņas', 'Populārākās ziņas', 'Latvija', 'Latvia', '🇱🇻', 'Europe/Riga', '%d.%m.%Y %H:%M:%S'),
            'LT': ('lt', 'LT:lt', 'Google naujienos', 'Populiariausios naujienos', 'Lietuva', 'Lithuania', '🇱🇹', 'Europe/Vilnius', '%Y-%m-%d %H:%M:%S'),
            'RO': ('ro', 'RO:ro', 'Știri Google', 'Cele mai populare subiecte', 'România', 'Romania', '🇷🇴', 'Europe/Bucharest', '%d.%m.%Y %H:%M:%S'),
            'BE': ('fr', 'BE:fr', 'Google Actualités', 'À la une', 'Belgique', 'Belgium', '🇧🇪', 'Europe/Brussels', '%d/%m/%Y %H:%M:%S'),
            'BG': ('bg', 'BG:bg', 'Google Новини', 'Водещи материали', 'България', 'Bulgaria', '🇧🇬', 'Europe/Sofia', '%d.%m.%Y %H:%M:%S'),
            'SK': ('sk', 'SK:sk', 'Správy Google', 'Hlavné správy', 'Slovensko', 'Slovakia', '🇸🇰', 'Europe/Bratislava', '%d.%m.%Y %H:%M:%S'),
            'SI': ('sl', 'SI:sl', 'Google News', 'Najpomembnejše novice', 'Slovenija', 'Slovenia', '🇸🇮', 'Europe/Ljubljana', '%d.%m.%Y %H:%M:%S'),
            'CH': ('de', 'CH:de', 'Google News', 'Top-Meldungen', 'Schweiz', 'Switzerland', '🇨🇭', 'Europe/Zurich', '%d.%m.%Y %H:%M:%S'),
            'ES': ('es', 'ES:es', 'Google News', 'Noticias destacadas', 'España', 'Spain', '🇪🇸', 'Europe/Madrid', '%d/%m/%Y %H:%M:%S'),
            'SE': ('sv', 'SE:sv', 'Google Nyheter', 'Huvudnyheter', 'Sverige', 'Sweden', '🇸🇪', 'Europe/Stockholm', '%Y-%m-%d %H:%M:%S'),
            'RS': ('sr', 'RS:sr', 'Google вести', 'Најважније вести', 'Србија', 'Serbia', '🇷🇸', 'Europe/Belgrade', '%d.%m.%Y %H:%M:%S'),
            'AT': ('de', 'AT:de', 'Google News', 'Top-Meldungen', 'Österreich', 'Austria', '🇦🇹', 'Europe/Vienna', '%d.%m.%Y %H:%M:%S'),
            'IE': ('en-IE', 'IE:en', 'Google News', 'Top stories', 'Ireland', 'Ireland', '🇮🇪', 'Europe/Dublin', '%d/%m/%Y %H:%M:%S'),
            'EE': ('et-EE', 'EE:et', 'Google News', 'Populaarseimad lood', 'Eesti', 'Estonia', '🇪🇪', 'Europe/Tallinn', '%d.%m.%Y %H:%M:%S'),
            'IT': ('it', 'IT:it', 'Google News', 'Notizie principali', 'Italia', 'Italy', '🇮🇹', 'Europe/Rome', '%d/%m/%Y %H:%M:%S'),
            'CZ': ('cs', 'CZ:cs', 'Zprávy Google', 'Hlavní události', 'Česko', 'Czech Republic', '🇨🇿', 'Europe/Prague', '%d.%m.%Y %H:%M:%S'),
            'GB': ('en-GB', 'GB:en', 'Google News', 'Top stories', 'United Kingdom', 'United Kingdom', '🇬🇧', 'Europe/London', '%d/%m/%Y %H:%M:%S'),
            'PL': ('pl', 'PL:pl', 'Google News', 'Najważniejsze artykuły', 'Polska', 'Poland', '🇵🇱', 'Europe/Warsaw', '%d.%m.%Y %H:%M:%S'),
            'PT': ('pt-PT', 'PT:pt-150', 'Google Notícias', 'Notícias principais', 'Portugal', 'Portugal', '🇵🇹', 'Europe/Lisbon', '%d/%m/%Y %H:%M:%S'),
            'FI': ('fi-FI', 'FI:fi', 'Google Uutiset', 'Pääuutiset', 'Suomi', 'Finland', '🇫🇮', 'Europe/Helsinki', '%d.%m.%Y %H:%M:%S'),
            'FR': ('fr', 'FR:fr', 'Google Actualités', 'À la une', 'France', 'France', '🇫🇷', 'Europe/Paris', '%d/%m/%Y %H:%M:%S'),
            'HU': ('hu', 'HU:hu', 'Google Hírek', 'Vezető hírek', 'Magyarország', 'Hungary', '🇭🇺', 'Europe/Budapest', '%Y.%m.%d %H:%M:%S'),

# 북미
            'CA': ('en-CA', 'CA:en', 'Google News', 'Top stories', 'Canada', 'Canada', '🇨🇦', 'America/Toronto', '%Y-%m-%d %I:%M:%S %p'),
            'MX': ('es-419', 'MX:es-419', 'Google Noticias', 'Noticias destacadas', 'México', 'Mexico', '🇲🇽', 'America/Mexico_City', '%d/%m/%Y %H:%M:%S'),
            'US': ('en-US', 'US:en', 'Google News', 'Top stories', 'United States', 'United States', '🇺🇸', 'America/New_York', '%Y-%m-%d %I:%M:%S %p'),
            'CU': ('es-419', 'CU:es-419', 'Google Noticias', 'Noticias destacadas', 'Cuba', 'Cuba', '🇨🇺', 'America/Havana', '%d/%m/%Y %H:%M:%S'),

            # 남미
            'AR': ('es-419', 'AR:es-419', 'Google Noticias', 'Noticias destacadas', 'Argentina', 'Argentina', '🇦🇷', 'America/Buenos_Aires', '%d/%m/%Y %H:%M:%S'),
            'BR': ('pt-BR', 'BR:pt-419', 'Google Notícias', 'Principais notícias', 'Brasil', 'Brazil', '🇧🇷', 'America/Sao_Paulo', '%d/%m/%Y %H:%M:%S'),
            'CL': ('es-419', 'CL:es-419', 'Google Noticias', 'Noticias destacadas', 'Chile', 'Chile', '🇨🇱', 'America/Santiago', '%d-%m-%Y %H:%M:%S'),
            'CO': ('es-419', 'CO:es-419', 'Google Noticias', 'Noticias destacadas', 'Colombia', 'Colombia', '🇨🇴', 'America/Bogota', '%d/%m/%Y %I:%M:%S %p'),
            'PE': ('es-419', 'PE:es-419', 'Google Noticias', 'Noticias destacadas', 'Perú', 'Peru', '🇵🇪', 'America/Lima', '%d/%m/%Y %I:%M:%S %p'),
            'VE': ('es-419', 'VE:es-419', 'Google Noticias', 'Noticias destacadas', 'Venezuela', 'Venezuela', '🇻🇪', 'America/Caracas', '%d/%m/%Y %I:%M:%S %p'),

            # 아프리카
            'ZA': ('en-ZA', 'ZA:en', 'Google News', 'Top stories', 'South Africa', 'South Africa', '🇿🇦', 'Africa/Johannesburg', '%Y-%m-%d %H:%M:%S'),
            'NG': ('en-NG', 'NG:en', 'Google News', 'Top stories', 'Nigeria', 'Nigeria', '🇳🇬', 'Africa/Lagos', '%d/%m/%Y %I:%M:%S %p'),
            'EG': ('ar', 'EG:ar', 'أخبار Google', 'أهم الأخبار', 'مصر', 'Egypt', '🇪🇬', 'Africa/Cairo', '%d/%m/%Y %I:%M:%S %p'),
            'KE': ('en-KE', 'KE:en', 'Google News', 'Top stories', 'Kenya', 'Kenya', '🇰🇪', 'Africa/Nairobi', '%d/%m/%Y %I:%M:%S %p'),
            'MA': ('fr', 'MA:fr', 'Google Actualités', 'À la une', 'Maroc', 'Morocco', '🇲🇦', 'Africa/Casablanca', '%d/%m/%Y %H:%M:%S'),
            'SN': ('fr', 'SN:fr', 'Google Actualités', 'À la une', 'Sénégal', 'Senegal', '🇸🇳', 'Africa/Dakar', '%d/%m/%Y %H:%M:%S'),
            'UG': ('en-UG', 'UG:en', 'Google News', 'Top stories', 'Uganda', 'Uganda', '🇺🇬', 'Africa/Kampala', '%d/%m/%Y %I:%M:%S %p'),
            'TZ': ('en-TZ', 'TZ:en', 'Google News', 'Top stories', 'Tanzania', 'Tanzania', '🇹🇿', 'Africa/Dar_es_Salaam', '%d/%m/%Y %I:%M:%S %p'),
            'ZW': ('en-ZW', 'ZW:en', 'Google News', 'Top stories', 'Zimbabwe', 'Zimbabwe', '🇿🇼', 'Africa/Harare', '%d/%m/%Y %I:%M:%S %p'),
            'ET': ('en-ET', 'ET:en', 'Google News', 'Top stories', 'Ethiopia', 'Ethiopia', '🇪🇹', 'Africa/Addis_Ababa', '%d/%m/%Y %I:%M:%S %p'),
            'GH': ('en-GH', 'GH:en', 'Google News', 'Top stories', 'Ghana', 'Ghana', '🇬🇭', 'Africa/Accra', '%d/%m/%Y %I:%M:%S %p'),
        }

        if TOP_COUNTRY not in country_configs:
            raise ValueError(f"지원되지 않는 국가 코드: {TOP_COUNTRY}")
        
        hl, ceid, google_news, news_type, country_name, country_name_en, flag, timezone, date_format = country_configs[TOP_COUNTRY]
        rss_url = f"https://news.google.com/rss?hl={hl}&gl={TOP_COUNTRY}&ceid={ceid}"
        
        # Discord 메시지 제목 형식 생성
        discord_source = f"`{google_news} - {news_type} - {country_name} {flag}`"
        
        return rss_url, discord_source, timezone, date_format
    elif RSS_URL_TOP:
        return RSS_URL_TOP, None, 'UTC', '%Y-%m-%d %H:%M:%S'
    else:
        raise ValueError("TOP_MODE가 false일 때 RSS_URL_TOP를 지정해야 합니다.")

def replace_brackets(text):
    """대괄호와 꺾쇠괄호를 유니코드 문자로 대체합니다."""
    text = text.replace('[', '［').replace(']', '］')
    text = text.replace('<', '〈').replace('>', '〉')
    text = re.sub(r'(?<!\s)(?<!^)［', ' ［', text)
    text = re.sub(r'］(?!\s)', '］ ', text)
    text = re.sub(r'(?<!\s)(?<!^)〈', ' 〈', text)
    text = re.sub(r'〉(?!\s)', '〉 ', text)
    return text

def parse_html_description(html_desc, session):
    """HTML 설명을 파싱하여 뉴스 항목을 추출합니다."""
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
            link = get_original_url(google_link, session)
            title_text = replace_brackets(title_match.text)
            press_name = press_match.text
            news_item = f"- [{title_text}](<{link}>) | {press_name}"
            news_items.append(news_item)

    news_string = '\n'.join(news_items)
    if full_content_link:
        news_string += f"\n\n▶️ [Google 뉴스에서 전체 콘텐츠 보기](<{full_content_link}>)"

    return news_string

def parse_rss_date(pub_date, timezone, date_format):
    """RSS 날짜를 파싱하여 형식화된 문자열로 반환합니다."""
    dt = parser.parse(pub_date)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=pytz.UTC)
    local_dt = dt.astimezone(pytz.timezone(timezone))
    return local_dt.strftime(date_format)

def format_discord_message(news_item, discord_source, timezone, date_format):
    """Discord 메시지를 포맷팅합니다."""
    formatted_date = parse_rss_date(news_item['pub_date'], timezone, date_format)

    if discord_source:
        message = f"{discord_source}\n**{news_item['title']}**\n{news_item['link']}"
    else:
        message = f"**{news_item['title']}**\n{news_item['link']}"
    
    if news_item['description']:
        message += f"\n>>> {news_item['description']}\n\n"
    else:
        message += "\n\n"
    
    message += f"📅 {formatted_date}"
    return message

def send_discord_message(webhook_url, message, avatar_url=None, username=None):
    """Discord 웹훅을 사용하여 메시지를 전송합니다."""
    payload = {"content": message}
    
    # 아바타 URL이 제공되고 비어있지 않으면 payload에 추가
    if avatar_url and avatar_url.strip():
        payload["avatar_url"] = avatar_url
    
    # 사용자 이름이 제공되고 비어있지 않으면 payload에 추가
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

def process_news_item(item, session):
    """개별 뉴스 항목을 처리합니다."""
    try:
        guid = item.find('guid').text
        title = replace_brackets(item.find('title').text)
        google_link = item.find('link').text
        link = get_original_url(google_link, session)
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        
        description = parse_html_description(description_html, session)
        related_news = extract_news_items(description_html, session)
        related_news_json = json.dumps(related_news, ensure_ascii=False)

        return {
            "guid": guid,
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "description": description,
            "related_news_json": related_news_json
        }
    except Exception as e:
        logging.error(f"뉴스 항목 처리 중 오류 발생: {e}", exc_info=True)
        return None

def main():
    """메인 함수: RSS 피드를 가져와 처리하고 Discord로 전송합니다."""
    try:
        check_env_variables()
        rss_url, discord_source, timezone, date_format = get_rss_url()
        
        retry_count = 3
        for attempt in range(retry_count):
            try:
                rss_data = fetch_rss_feed(rss_url)
                break
            except Exception as e:
                if attempt < retry_count - 1:
                    logging.warning(f"RSS 피드 가져오기 실패 (시도 {attempt + 1}/{retry_count}): {e}")
                    time.sleep(5)
                else:
                    logging.error(f"RSS 피드 가져오기 최종 실패: {e}")
                    raise

        root = ET.fromstring(rss_data)
        news_items = root.findall('.//item')

        init_db(reset=INITIALIZE_TOP)

        session = requests.Session()
        
        if INITIALIZE_TOP:
            # 초기 실행 시 날짜 기준으로 정렬
            news_items = sorted(news_items, key=lambda item: parse_pub_date(item.find('pubDate').text))
            logging.info("초기 실행: 뉴스 항목을 날짜 순으로 정렬했습니다.")
        else:
            # 후속 실행 시 처리 로직
            new_items = []
            for item in reversed(news_items):  # 최신 항목부터 확인
                guid = item.find('guid').text
                if is_guid_posted(guid):
                    logging.info(f"이미 게시된 뉴스 항목 발견, 처리 중단: {guid}")
                    break
                new_items.append(item)
            
            if new_items:
                news_items = list(reversed(new_items))  # 새 항목들을 다시 오래된 순서로 정렬
                logging.info(f"후속 실행: {len(news_items)}개의 새로운 뉴스 항목을 처리합니다.")
            else:
                logging.info("후속 실행: 새로운 뉴스 항목이 없습니다.")

        since_date, until_date, past_date = parse_date_filter(DATE_FILTER_TOP)

        for item in news_items:
            try:
                processed_item = process_news_item(item, session)
                if processed_item is None:
                    continue

                if not is_within_date_range(processed_item["pub_date"], since_date, until_date, past_date):
                    logging.info(f"날짜 필터에 의해 건너뛰어진 뉴스: {processed_item['title']}")
                    continue

                discord_message = format_discord_message(processed_item, discord_source, timezone, date_format)
                
                retry_count = 3
                for attempt in range(retry_count):
                    try:
                        send_discord_message(
                            DISCORD_WEBHOOK_TOP,
                            discord_message,
                            avatar_url=DISCORD_AVATAR_TOP,
                            username=DISCORD_USERNAME_TOP
                        )
                        break
                    except Exception as e:
                        if attempt < retry_count - 1:
                            logging.warning(f"Discord 메시지 전송 실패 (시도 {attempt + 1}/{retry_count}): {e}")
                            time.sleep(5)
                        else:
                            logging.error(f"Discord 메시지 전송 최종 실패: {e}")
                            raise

                save_news_item(
                    processed_item["pub_date"],
                    processed_item["guid"],
                    processed_item["title"],
                    processed_item["link"],
                    processed_item["related_news_json"]
                )

                # 모든 실행에서 3초 간격 적용
                time.sleep(3)
                logging.info(f"뉴스 항목 처리 완료: {processed_item['title']} (게시일: {processed_item['pub_date']})")

            except Exception as e:
                logging.error(f"뉴스 항목 '{item.find('title').text if item.find('title') is not None else 'Unknown'}' 처리 중 오류 발생: {e}", exc_info=True)
                continue

    except Exception as e:
        logging.error(f"프로그램 실행 중 오류 발생: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        check_env_variables()
        main()
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)  # 오류 발생 시 비정상 종료
    else:
        logging.info("프로그램 정상 종료")

