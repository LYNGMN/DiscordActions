
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
RSS_URL_TOP = os.environ.get('RSS_URL_TOP')
TOP_MODE = os.environ.get('TOP_MODE', 'false').lower() == 'true'
TOP_COUNTRY = os.environ.get('TOP_COUNTRY')

# DB 설정
DB_PATH = 'google_news_top.db'

def check_env_variables():
    """환경 변수가 설정되어 있는지 확인합니다."""
    if not DISCORD_WEBHOOK_TOP:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_TOP")

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

def get_rss_url():
    if TOP_MODE:
        if not TOP_COUNTRY:
            raise ValueError("TOP_MODE가 true일 때 TOP_COUNTRY를 지정해야 합니다.")
        
        country_configs = {
            # 동아시아
            'KR': ('ko', 'KR:ko', 'Google 뉴스', '주요 뉴스', '한국', 'South Korea', '🇰🇷'),
            'JP': ('ja', 'JP:ja', 'Google ニュース', 'トップニュース', '日本', 'Japan', '🇯🇵'),
            'CN': ('zh-CN', 'CN:zh-Hans', 'Google 新闻', '焦点新闻', '中国', 'China', '🇨🇳'),
            'TW': ('zh-TW', 'TW:zh-Hant', 'Google 新聞', '焦點新聞', '台灣', 'Taiwan', '🇹🇼'),
            'HK': ('zh-HK', 'HK:zh-Hant', 'Google 新聞', '焦點新聞', '香港', 'Hong Kong', '🇭🇰'),
            
            # 동남아시아
            'VN': ('vi', 'VN:vi', 'Google Tin tức', 'Tin nổi bật', 'Việt Nam', 'Vietnam', '🇻🇳'),
            'TH': ('th', 'TH:th', 'Google News', 'เรื่องเด่น', 'ประเทศไทย', 'Thailand', '🇹🇭'),
            'PH': ('en-PH', 'PH:en', 'Google News', 'Top stories', 'Philippines', 'Philippines', '🇵🇭'),
            'MY': ('ms-MY', 'MY:ms', 'Berita Google', 'Berita hangat', 'Malaysia', 'Malaysia', '🇲🇾'),
            'SG': ('en-SG', 'SG:en', 'Google News', 'Top stories', 'Singapore', 'Singapore', '🇸🇬'),
            'ID': ('id', 'ID:id', 'Google Berita', 'Artikel populer', 'Indonesia', 'Indonesia', '🇮🇩'),
            
            # 남아시아
            'IN': ('en-IN', 'IN:en', 'Google News', 'Top stories', 'India', 'India', '🇮🇳'),
            'BD': ('bn', 'BD:bn', 'Google News', 'সেরা খবর', 'বাংলাদেশ', 'Bangladesh', '🇧🇩'),
            'PK': ('en-PK', 'PK:en', 'Google News', 'Top stories', 'Pakistan', 'Pakistan', '🇵🇰'),
            
            # 서아시아
            'IL': ('he', 'IL:he', 'חדשות Google', 'הכתבות המובילות', 'ישראל', 'Israel', '🇮🇱'),
            'AE': ('ar', 'AE:ar', 'أخبار Google', 'أهم الأخبار', 'الإمارات العربية المتحدة', 'United Arab Emirates', '🇦🇪'),
            'TR': ('tr', 'TR:tr', 'Google Haberler', 'En çok okunan haberler', 'Türkiye', 'Turkey', '🇹🇷'),
            'LB': ('ar', 'LB:ar', 'أخبار Google', 'أهم الأخبار', 'لبنان', 'Lebanon', '🇱🇧'),

            # 오세아니아
            'AU': ('en-AU', 'AU:en', 'Google News', 'Top stories', 'Australia', 'Australia', '🇦🇺'),
            'NZ': ('en-NZ', 'NZ:en', 'Google News', 'Top stories', 'New Zealand', 'New Zealand', '🇳🇿'),

            # 러시아와 동유럽
            'RU': ('ru', 'RU:ru', 'Google Новости', 'Главные новости', 'Россия', 'Russia', '🇷🇺'),
            'UA': ('uk', 'UA:uk', 'Google Новини', 'Головні новини', 'Україна', 'Ukraine', '🇺🇦'),

            # 유럽
            'GR': ('el', 'GR:el', 'Ειδήσεις Google', 'Κυριότερες ειδήσεις', 'Ελλάδα', 'Greece', '🇬🇷'),
            'DE': ('de', 'DE:de', 'Google News', 'Top-Meldungen', 'Deutschland', 'Germany', '🇩🇪'),
            'NL': ('nl', 'NL:nl', 'Google Nieuws', 'Voorpaginanieuws', 'Nederland', 'Netherlands', '🇳🇱'),
            'NO': ('no', 'NO:no', 'Google Nyheter', 'Hovedoppslag', 'Norge', 'Norway', '🇳🇴'),
            'LV': ('lv', 'LV:lv', 'Google ziņas', 'Populārākās ziņas', 'Latvija', 'Latvia', '🇱🇻'),
            'LT': ('lt', 'LT:lt', 'Google naujienos', 'Populiariausios naujienos', 'Lietuva', 'Lithuania', '🇱🇹'),
            'RO': ('ro', 'RO:ro', 'Știri Google', 'Cele mai populare subiecte', 'România', 'Romania', '🇷🇴'),
            'BE': ('fr', 'BE:fr', 'Google Actualités', 'À la une', 'Belgique', 'Belgium', '🇧🇪'),
            'BG': ('bg', 'BG:bg', 'Google Новини', 'Водещи материали', 'България', 'Bulgaria', '🇧🇬'),
            'SK': ('sk', 'SK:sk', 'Správy Google', 'Hlavné správy', 'Slovensko', 'Slovakia', '🇸🇰'),
            'SI': ('sl', 'SI:sl', 'Google News', 'Najpomembnejše novice', 'Slovenija', 'Slovenia', '🇸🇮'),
            'CH': ('de', 'CH:de', 'Google News', 'Top-Meldungen', 'Schweiz', 'Switzerland', '🇨🇭'),
            'ES': ('es', 'ES:es', 'Google News', 'Noticias destacadas', 'España', 'Spain', '🇪🇸'),
            'SE': ('sv', 'SE:sv', 'Google Nyheter', 'Huvudnyheter', 'Sverige', 'Sweden', '🇸🇪'),
            'RS': ('sr', 'RS:sr', 'Google вести', 'Најважније вести', 'Србија', 'Serbia', '🇷🇸'),
            'AT': ('de', 'AT:de', 'Google News', 'Top-Meldungen', 'Österreich', 'Austria', '🇦🇹'),
            'IE': ('en-IE', 'IE:en', 'Google News', 'Top stories', 'Ireland', 'Ireland', '🇮🇪'),
            'EE': ('et-EE', 'EE:et', 'Google News', 'Populaarseimad lood', 'Eesti', 'Estonia', '🇪🇪'),
            'IT': ('it', 'IT:it', 'Google News', 'Notizie principali', 'Italia', 'Italy', '🇮🇹'),
            'CZ': ('cs', 'CZ:cs', 'Zprávy Google', 'Hlavní události', 'Česko', 'Czech Republic', '🇨🇿'),
            'GB': ('en-GB', 'GB:en', 'Google News', 'Top stories', 'United Kingdom', 'United Kingdom', '🇬🇧'),
            'PL': ('pl', 'PL:pl', 'Google News', 'Najważniejsze artykuły', 'Polska', 'Poland', '🇵🇱'),
            'PT': ('pt-PT', 'PT:pt-150', 'Google Notícias', 'Notícias principais', 'Portugal', 'Portugal', '🇵🇹'),
            'FI': ('fi-FI', 'FI:fi', 'Google Uutiset', 'Pääuutiset', 'Suomi', 'Finland', '🇫🇮'),
            'FR': ('fr', 'FR:fr', 'Google Actualités', 'À la une', 'France', 'France', '🇫🇷'),
            'HU': ('hu', 'HU:hu', 'Google Hírek', 'Vezető hírek', 'Magyarország', 'Hungary', '🇭🇺'),

            # 북미
            'CA': ('en-CA', 'CA:en', 'Google News', 'Top stories', 'Canada', 'Canada', '🇨🇦'),
            'MX': ('es-419', 'MX:es-419', 'Google Noticias', 'Noticias destacadas', 'México', 'Mexico', '🇲🇽'),
            'US': ('en-US', 'US:en', 'Google News', 'Top stories', 'United States', 'United States', '🇺🇸'),
            'CU': ('es-419', 'CU:es-419', 'Google Noticias', 'Noticias destacadas', 'Cuba', 'Cuba', '🇨🇺'),

            # 남미
            'AR': ('es-419', 'AR:es-419', 'Google Noticias', 'Noticias destacadas', 'Argentina', 'Argentina', '🇦🇷'),
            'BR': ('pt-BR', 'BR:pt-419', 'Google Notícias', 'Principais notícias', 'Brasil', 'Brazil', '🇧🇷'),
            'CL': ('es-419', 'CL:es-419', 'Google Noticias', 'Noticias destacadas', 'Chile', 'Chile', '🇨🇱'),
            'CO': ('es-419', 'CO:es-419', 'Google Noticias', 'Noticias destacadas', 'Colombia', 'Colombia', '🇨🇴'),
            'PE': ('es-419', 'PE:es-419', 'Google Noticias', 'Noticias destacadas', 'Perú', 'Peru', '🇵🇪'),
            'VE': ('es-419', 'VE:es-419', 'Google Noticias', 'Noticias destacadas', 'Venezuela', 'Venezuela', '🇻🇪'),

            # 아프리카
            'ZA': ('en-ZA', 'ZA:en', 'Google News', 'Top stories', 'South Africa', 'South Africa', '🇿🇦'),
            'NG': ('en-NG', 'NG:en', 'Google News', 'Top stories', 'Nigeria', 'Nigeria', '🇳🇬'),
            'EG': ('ar', 'EG:ar', 'أخبار Google', 'أهم الأخبار', 'مصر', 'Egypt', '🇪🇬'),
            'KE': ('en-KE', 'KE:en', 'Google News', 'Top stories', 'Kenya', 'Kenya', '🇰🇪'),
            'MA': ('fr', 'MA:fr', 'Google Actualités', 'À la une', 'Maroc', 'Morocco', '🇲🇦'),
            'SN': ('fr', 'SN:fr', 'Google Actualités', 'À la une', 'Sénégal', 'Senegal', '🇸🇳'),
            'UG': ('en-UG', 'UG:en', 'Google News', 'Top stories', 'Uganda', 'Uganda', '🇺🇬'),
            'TZ': ('en-TZ', 'TZ:en', 'Google News', 'Top stories', 'Tanzania', 'Tanzania', '🇹🇿'),
            'ZW': ('en-ZW', 'ZW:en', 'Google News', 'Top stories', 'Zimbabwe', 'Zimbabwe', '🇿🇼'),
            'ET': ('en-ET', 'ET:en', 'Google News', 'Top stories', 'Ethiopia', 'Ethiopia', '🇪🇹'),
            'GH': ('en-GH', 'GH:en', 'Google News', 'Top stories', 'Ghana', 'Ghana', '🇬🇭'),
        }
        
        if TOP_COUNTRY not in country_configs:
            raise ValueError(f"지원되지 않는 국가 코드: {TOP_COUNTRY}")
        
        hl, ceid, google_news, news_type, country_name, country_name_en, flag = country_configs[TOP_COUNTRY]
        rss_url = f"https://news.google.com/rss?hl={hl}&gl={TOP_COUNTRY}&ceid={ceid}"
        
        # Discord 메시지 제목 형식 생성
        discord_source= f"`{google_news} - {news_type} - {country_name} {flag}`"
        
        return rss_url, discord_source
    elif RSS_URL_TOP:
        return RSS_URL_TOP, None
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

def parse_rss_date(pub_date):
    """RSS 날짜를 파싱하여 형식화된 문자열로 반환합니다."""
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

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

def main():
    """메인 함수: RSS 피드를 가져와 처리하고 Discord로 전송합니다."""
    rss_url, discord_source = get_rss_url()
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    init_db(reset=INITIALIZE_TOP)

    session = requests.Session()
    
    news_items = root.findall('.//item')
    if INITIALIZE_TOP:
        news_items = list(news_items)
    else:
        news_items = reversed(news_items)

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_TOP)

    for item in news_items:
        guid = item.find('guid').text

        if not INITIALIZE_TOP and is_guid_posted(guid):
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

        related_news = extract_news_items(description_html, session)
        related_news_json = json.dumps(related_news, ensure_ascii=False)

        description = parse_html_description(description_html, session)

        # 고급 검색 필터 적용
        if not apply_advanced_filter(title, description, ADVANCED_FILTER_TOP):
            logging.info(f"고급 검색 필터에 의해 건너뛰어진 뉴스: {title}")
            continue

        # Discord 메시지 구성
        if discord_source:
            discord_message = f"{discord_source}\n**{title}**\n{link}"
        else:
            discord_message = f"**{title}**\n{link}"
        if description:
            discord_message += f"\n>>> {description}\n\n"
        else:
            discord_message += "\n\n"
        discord_message += f"📅 {formatted_date}"

        send_discord_message(
            DISCORD_WEBHOOK_TOP,
            discord_message,
            avatar_url=DISCORD_AVATAR_TOP,
            username=DISCORD_USERNAME_TOP
        )

        save_news_item(pub_date, guid, title, link, related_news_json)

        if not INITIALIZE_TOP:
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
