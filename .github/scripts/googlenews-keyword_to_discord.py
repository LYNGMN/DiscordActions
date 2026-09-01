import xml.etree.ElementTree as ET
import requests
import re
import os
import time
import random
import logging
import json
import sqlite3
import sys
import pytz
from datetime import datetime, timedelta
from dateutil import parser
from dateutil.tz import gettz
from bs4 import BeautifulSoup
from delivery_admin_alert import notify_admin
from google_news_manual_test import (
    prepare_manual_test_items,
    validate_manual_test_result,
)
from google_news_delivery_state import (
    count_ambiguous_retries,
    count_pending_deliveries,
    deliver_queued_item,
    is_item_handled,
    pending_delivery_guids,
    prepare_scheduled_items,
    record_filtered_item,
    reserve_delivery_with_messages,
)
from google_news_discord_delivery import send_webhook_message, split_discord_content
from google_news_feed_filter import compile_google_news_feed_filter
from feed_localization import (
    format_google_news_datetime,
    labels_for,
    localized_country_name,
    resolve_display_language,
)
from google_news_keyword_matcher import (
    extract_keyword_query,
)
from google_news_profile_result import write_profile_result
from google_news_related_links import resolve_related_url
from google_news_request_guard import BlockedRequestError, GoogleNewsRequestGuard
from google_news_url_resolver import GoogleNewsUrlResolver

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
DISCORD_WEBHOOK_KEYWORD = os.environ.get('DISCORD_WEBHOOK_KEYWORD')
DISCORD_AVATAR_KEYWORD = os.environ.get('DISCORD_AVATAR_KEYWORD')
DISCORD_USERNAME_KEYWORD = os.environ.get('DISCORD_USERNAME_KEYWORD')
DISCORD_WEBHOOK_ADMIN = os.environ.get('DISCORD_WEBHOOK_ADMIN', '')
INITIALIZE_KEYWORD = os.environ.get('INITIALIZE_MODE_KEYWORD', 'false').lower() == 'true'
ADVANCED_FILTER_KEYWORD = os.environ.get('ADVANCED_FILTER_KEYWORD', '')
DATE_FILTER_KEYWORD = os.environ.get('DATE_FILTER_KEYWORD', '')
AFTER_DATE = os.environ.get('AFTER_DATE', '')
BEFORE_DATE = os.environ.get('BEFORE_DATE', '')
WHEN = os.environ.get('WHEN', '')
HL = os.environ.get('HL', '')
GL = os.environ.get('GL', '')
CEID = os.environ.get('CEID', '')
ORIGIN_LINK_KEYWORD = os.getenv('ORIGIN_LINK_KEYWORD', '').lower()
ORIGIN_LINK_KEYWORD = ORIGIN_LINK_KEYWORD not in ['false', 'f', '0', 'no', 'n']
MANUAL_TEST_MODE = os.environ.get('MANUAL_TEST_MODE', 'false').lower() == 'true'
KEYWORD_MODE = os.environ.get('KEYWORD_MODE', 'false').lower() == 'true'
KEYWORD = os.environ.get('KEYWORD', '')
KEYWORD_DISPLAY_NAME = os.environ.get('KEYWORD_DISPLAY_NAME', '').strip()
RSS_URL_KEYWORD = os.environ.get('RSS_URL_KEYWORD', '')
PROFILE_ID = os.environ.get('GOOGLE_NEWS_PROFILE_ID', '')
RESULT_PATH = os.environ.get('GOOGLE_NEWS_RESULT_PATH', '')
VALIDATE_ONLY = os.environ.get('GOOGLE_NEWS_VALIDATE_ONLY', 'false').lower() == 'true'
MAX_NETWORK_RESOLUTIONS = int(os.environ.get('GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS', '1000'))
DELIVERY_ORDER = os.environ.get(
    'GOOGLE_NEWS_DELIVERY_ORDER', 'feed_oldest_first'
).lower()
KEYWORD_MATCH_MODE = os.environ.get('KEYWORD_MATCH_MODE', 'title').lower()
KEYWORD_MATCH_ALIASES = os.environ.get('KEYWORD_MATCH_ALIASES', '')
FEED_DATE_FILTER = os.environ.get('FEED_DATE_FILTER', '')
FEED_KEYWORD_FILTER = os.environ.get('FEED_KEYWORD_FILTER', '')
FEED_KEYWORD_SCOPE = os.environ.get('FEED_KEYWORD_SCOPE', 'title').lower()
FEED_TIMEZONE = os.environ.get('FEED_TIMEZONE', '')
FEED_COUNTRY = os.environ.get('FEED_COUNTRY', '')
DISPLAY_LANGUAGE = os.environ.get('DISPLAY_LANGUAGE', '')

# DB 설정
DB_PATH = os.environ.get('GOOGLE_NEWS_DB_PATH', 'google_news_keyword.db')
RESOLVER_DB_PATH = os.environ.get('GOOGLE_NEWS_RESOLVER_DB_PATH', DB_PATH)

country_configs = {
    # 동아시아
    'KR': ('ko', 'KR:ko', 'Google 뉴스', '한국', 'South Korea', '🇰🇷', 'Asia/Seoul', '%Y년 %m월 %d일 %H:%M:%S (KST)'),
    'JP': ('ja', 'JP:ja', 'Google ニュース', '日本', 'Japan', '🇯🇵', 'Asia/Tokyo', '%Y年%m月%d日 %H:%M:%S (JST)'),
    'CN': ('zh-CN', 'CN:zh-Hans', 'Google 新闻', '中国', 'China', '🇨🇳', 'Asia/Shanghai', '%Y年%m月%d日 %H:%M:%S (CST)'),
    'TW': ('zh-TW', 'TW:zh-Hant', 'Google 新聞', '台灣', 'Taiwan', '🇹🇼', 'Asia/Taipei', '%Y年%m月%d日 %H:%M:%S (NST)'),
    'HK': ('zh-HK', 'HK:zh-Hant', 'Google 新聞', '香港', 'Hong Kong', '🇭🇰', 'Asia/Hong_Kong', '%Y年%m月%d日 %H:%M:%S (HKT)'),
    
    # 동남아시아
    'VN': ('vi', 'VN:vi', 'Google Tin tức', 'Việt Nam', 'Vietnam', '🇻🇳', 'Asia/Ho_Chi_Minh', '%d/%m/%Y %H:%M:%S (ICT)'),
    'TH': ('th', 'TH:th', 'Google News', 'ประเทศไทย', 'Thailand', '🇹🇭', 'Asia/Bangkok', '%d/%m/%Y %H:%M:%S (ICT)'),
    'PH': ('en-PH', 'PH:en', 'Google News', 'Philippines', 'Philippines', '🇵🇭', 'Asia/Manila', '%Y-%m-%d %I:%M:%S %p (PHT)'),
    'MY': ('ms-MY', 'MY:ms', 'Berita Google', 'Malaysia', 'Malaysia', '🇲🇾', 'Asia/Kuala_Lumpur', '%d/%m/%Y %H:%M:%S (MYT)'),
    'SG': ('en-SG', 'SG:en', 'Google News', 'Singapore', 'Singapore', '🇸🇬', 'Asia/Singapore', '%Y-%m-%d %I:%M:%S %p (SGT)'),
    'ID': ('id', 'ID:id', 'Google Berita', 'Indonesia', 'Indonesia', '🇮🇩', 'Asia/Jakarta', '%d/%m/%Y %H:%M:%S (WIB)'),
    
    # 남아시아
    'IN': ('en-IN', 'IN:en', 'Google News', 'India', 'India', '🇮🇳', 'Asia/Kolkata', '%d/%m/%Y %I:%M:%S %p (IST)'),
    'BD': ('bn', 'BD:bn', 'Google News', 'বাংলাদেশ', 'Bangladesh', '🇧🇩', 'Asia/Dhaka', '%d/%m/%Y %H:%M:%S (BST)'),
    'PK': ('en-PK', 'PK:en', 'Google News', 'Pakistan', 'Pakistan', '🇵🇰', 'Asia/Karachi', '%d/%m/%Y %I:%M:%S %p (PKT)'),
    
    # 서아시아
    'IL': ('he', 'IL:he', 'חדשות Google', 'ישראל', 'Israel', '🇮🇱', 'Asia/Jerusalem', '%d/%m/%Y %H:%M:%S (IST)'),
    'AE': ('ar', 'AE:ar', 'أخبار Google', 'الإمارات العربية المتحدة', 'United Arab Emirates', '🇦🇪', 'Asia/Dubai', '%d/%m/%Y %I:%M:%S %p (GST)'),
    'TR': ('tr', 'TR:tr', 'Google Haberler', 'Türkiye', 'Turkey', '🇹🇷', 'Europe/Istanbul', '%d.%m.%Y %H:%M:%S (TRT)'),
    'LB': ('ar', 'LB:ar', 'أخبار Google', 'لبنان', 'Lebanon', '🇱🇧', 'Asia/Beirut', '%d/%m/%Y %I:%M:%S %p (EET)'),

    # 오세아니아
    'AU': ('en-AU', 'AU:en', 'Google News', 'Australia', 'Australia', '🇦🇺', 'Australia/Sydney', '%d/%m/%Y %I:%M:%S %p (AEST)'),
    'NZ': ('en-NZ', 'NZ:en', 'Google News', 'New Zealand', 'New Zealand', '🇳🇿', 'Pacific/Auckland', '%d/%m/%Y %I:%M:%S %p (NZST)'),

    # 러시아와 동유럽
    'RU': ('ru', 'RU:ru', 'Google Новости', 'Россия', 'Russia', '🇷🇺', 'Europe/Moscow', '%d.%m.%Y %H:%M:%S (MSK)'),
    'UA': ('uk', 'UA:uk', 'Google Новини', 'Україна', 'Ukraine', '🇺🇦', 'Europe/Kiev', '%d.%m.%Y %H:%M:%S (EET)'),

    # 유럽
    'GR': ('el', 'GR:el', 'Ειδήσεις Google', 'Ελλάδα', 'Greece', '🇬🇷', 'Europe/Athens', '%d/%m/%Y %H:%M:%S (EET)'),
    'DE': ('de', 'DE:de', 'Google News', 'Deutschland', 'Germany', '🇩🇪', 'Europe/Berlin', '%d.%m.%Y %H:%M:%S (CET)'),
    'NL': ('nl', 'NL:nl', 'Google Nieuws', 'Nederland', 'Netherlands', '🇳🇱', 'Europe/Amsterdam', '%d-%m-%Y %H:%M:%S (CET)'),
    'NO': ('no', 'NO:no', 'Google Nyheter', 'Norge', 'Norway', '🇳🇴', 'Europe/Oslo', '%d.%m.%Y %H:%M:%S (CET)'),
    'LV': ('lv', 'LV:lv', 'Google ziņas', 'Latvija', 'Latvia', '🇱🇻', 'Europe/Riga', '%d.%m.%Y %H:%M:%S (EET)'),
    'LT': ('lt', 'LT:lt', 'Google naujienos', 'Lietuva', 'Lithuania', '🇱🇹', 'Europe/Vilnius', '%Y-%m-%d %H:%M:%S (EET)'),
    'RO': ('ro', 'RO:ro', 'Știri Google', 'România', 'Romania', '🇷🇴', 'Europe/Bucharest', '%d.%m.%Y %H:%M:%S (EET)'),
    'BE': ('fr', 'BE:fr', 'Google Actualités', 'Belgique', 'Belgium', '🇧🇪', 'Europe/Brussels', '%d/%m/%Y %H:%M:%S (CET)'),
    'BG': ('bg', 'BG:bg', 'Google Новини', 'България', 'Bulgaria', '🇧🇬', 'Europe/Sofia', '%d.%m.%Y %H:%M:%S (EET)'),
    'SK': ('sk', 'SK:sk', 'Správy Google', 'Slovensko', 'Slovakia', '🇸🇰', 'Europe/Bratislava', '%d.%m.%Y %H:%M:%S (CET)'),
    'SI': ('sl', 'SI:sl', 'Google News', 'Slovenija', 'Slovenia', '🇸🇮', 'Europe/Ljubljana', '%d.%m.%Y %H:%M:%S (CET)'),
    'CH': ('de', 'CH:de', 'Google News', 'Schweiz', 'Switzerland', '🇨🇭', 'Europe/Zurich', '%d.%m.%Y %H:%M:%S (CET)'),
    'ES': ('es', 'ES:es', 'Google News', 'España', 'Spain', '🇪🇸', 'Europe/Madrid', '%d/%m/%Y %H:%M:%S (CET)'),
    'SE': ('sv', 'SE:sv', 'Google Nyheter', 'Sverige', 'Sweden', '🇸🇪', 'Europe/Stockholm', '%Y-%m-%d %H:%M:%S (CET)'),
    'RS': ('sr', 'RS:sr', 'Google вести', 'Србија', 'Serbia', '🇷🇸', 'Europe/Belgrade', '%d.%m.%Y %H:%M:%S (CET)'),
    'AT': ('de', 'AT:de', 'Google News', 'Österreich', 'Austria', '🇦🇹', 'Europe/Vienna', '%d.%m.%Y %H:%M:%S (CET)'),
    'IE': ('en-IE', 'IE:en', 'Google News', 'Ireland', 'Ireland', '🇮🇪', 'Europe/Dublin', '%d/%m/%Y %H:%M:%S (GMT)'),
    'EE': ('et-EE', 'EE:et', 'Google News', 'Eesti', 'Estonia', '🇪🇪', 'Europe/Tallinn', '%d.%m.%Y %H:%M:%S (EET)'),
    'IT': ('it', 'IT:it', 'Google News', 'Italia', 'Italy', '🇮🇹', 'Europe/Rome', '%d/%m/%Y %H:%M:%S (CET)'),
    'CZ': ('cs', 'CZ:cs', 'Zprávy Google', 'Česko', 'Czech Republic', '🇨🇿', 'Europe/Prague', '%d.%m.%Y %H:%M:%S (CET)'),
    'GB': ('en-GB', 'GB:en', 'Google News', 'United Kingdom', 'United Kingdom', '🇬🇧', 'Europe/London', '%d/%m/%Y %H:%M:%S (GMT)'),
    'PL': ('pl', 'PL:pl', 'Google News', 'Polska', 'Poland', '🇵🇱', 'Europe/Warsaw', '%d.%m.%Y %H:%M:%S (CET)'),
    'PT': ('pt-PT', 'PT:pt-150', 'Google Notícias', 'Portugal', 'Portugal', '🇵🇹', 'Europe/Lisbon', '%d/%m/%Y %H:%M:%S (WET)'),
    'FI': ('fi-FI', 'FI:fi', 'Google Uutiset', 'Suomi', 'Finland', '🇫🇮', 'Europe/Helsinki', '%d.%m.%Y %H:%M:%S (EET)'),
    'FR': ('fr', 'FR:fr', 'Google Actualités', 'France', 'France', '🇫🇷', 'Europe/Paris', '%d/%m/%Y %H:%M:%S (CET)'),
    'HU': ('hu', 'HU:hu', 'Google Hírek', 'Magyarország', 'Hungary', '🇭🇺', 'Europe/Budapest', '%Y.%m.%d %H:%M:%S (CET)'),

    # 북미
    'CA': ('en-CA', 'CA:en', 'Google News', 'Canada', 'Canada', '🇨🇦', 'America/Toronto', '%Y-%m-%d %I:%M:%S %p (EST)'),
    'MX': ('es-419', 'MX:es-419', 'Google Noticias', 'México', 'Mexico', '🇲🇽', 'America/Mexico_City', '%d/%m/%Y %H:%M:%S (CST)'),
    'US': ('en-US', 'US:en', 'Google News', 'United States', 'United States', '🇺🇸', 'America/New_York', '%Y-%m-%d %I:%M:%S %p (EST)'),
    'CU': ('es-419', 'CU:es-419', 'Google Noticias', 'Cuba', 'Cuba', '🇨🇺', 'America/Havana', '%d/%m/%Y %H:%M:%S (CST)'),

    # 남미
    'AR': ('es-419', 'AR:es-419', 'Google Noticias', 'Argentina', 'Argentina', '🇦🇷', 'America/Buenos_Aires', '%d/%m/%Y %H:%M:%S (ART)'),
    'BR': ('pt-BR', 'BR:pt-419', 'Google Notícias', 'Brasil', 'Brazil', '🇧🇷', 'America/Sao_Paulo', '%d/%m/%Y %H:%M:%S (BRT)'),
    'CL': ('es-419', 'CL:es-419', 'Google Noticias', 'Chile', 'Chile', '🇨🇱', 'America/Santiago', '%d-%m-%Y %H:%M:%S (CLT)'),
    'CO': ('es-419', 'CO:es-419', 'Google Noticias', 'Colombia', 'Colombia', '🇨🇴', 'America/Bogota', '%d/%m/%Y %I:%M:%S %p (COT)'),
    'PE': ('es-419', 'PE:es-419', 'Google Noticias', 'Perú', 'Peru', '🇵🇪', 'America/Lima', '%d/%m/%Y %I:%M:%S %p (PET)'),
    'VE': ('es-419', 'VE:es-419', 'Google Noticias', 'Venezuela', 'Venezuela', '🇻🇪', 'America/Caracas', '%d/%m/%Y %I:%M:%S %p (VET)'),

    # 아프리카
    'ZA': ('en-ZA', 'ZA:en', 'Google News', 'South Africa', 'South Africa', '🇿🇦', 'Africa/Johannesburg', '%Y-%m-%d %H:%M:%S (SAST)'),
    'NG': ('en-NG', 'NG:en', 'Google News', 'Nigeria', 'Nigeria', '🇳🇬', 'Africa/Lagos', '%d/%m/%Y %I:%M:%S %p (WAT)'),
    'EG': ('ar', 'EG:ar', 'أخبار Google', 'مصر', 'Egypt', '🇪🇬', 'Africa/Cairo', '%d/%m/%Y %I:%M:%S %p (EET)'),
    'KE': ('en-KE', 'KE:en', 'Google News', 'Kenya', 'Kenya', '🇰🇪', 'Africa/Nairobi', '%d/%m/%Y %I:%M:%S %p (EAT)'),
    'MA': ('fr', 'MA:fr', 'Google Actualités', 'Maroc', 'Morocco', '🇲🇦', 'Africa/Casablanca', '%d/%m/%Y %H:%M:%S (WET)'),
    'SN': ('fr', 'SN:fr', 'Google Actualités', 'Sénégal', 'Senegal', '🇸🇳', 'Africa/Dakar', '%d/%m/%Y %H:%M:%S (GMT)'),
    'UG': ('en-UG', 'UG:en', 'Google News', 'Uganda', 'Uganda', '🇺🇬', 'Africa/Kampala', '%d/%m/%Y %I:%M:%S %p (EAT)'),
    'TZ': ('en-TZ', 'TZ:en', 'Google News', 'Tanzania', 'Tanzania', '🇹🇿', 'Africa/Dar_es_Salaam', '%d/%m/%Y %I:%M:%S %p (EAT)'),
    'ZW': ('en-ZW', 'ZW:en', 'Google News', 'Zimbabwe', 'Zimbabwe', '🇿🇼', 'Africa/Harare', '%d/%m/%Y %I:%M:%S %p (CAT)'),
    'ET': ('en-ET', 'ET:en', 'Google News', 'Ethiopia', 'Ethiopia', '🇪🇹', 'Africa/Addis_Ababa', '%d/%m/%Y %I:%M:%S %p (EAT)'),
    'GH': ('en-GH', 'GH:en', 'Google News', 'Ghana', 'Ghana', '🇬🇭', 'Africa/Accra', '%d/%m/%Y %I:%M:%S %p (GMT)'),
}


def check_env_variables():
    """환경 변수가 올바르게 설정되어 있는지 확인합니다."""
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
    if GL and not country_configs.get(GL):
        raise ValueError("키워드 모드가 활성화되었지만 GL 환경 변수가 설정되지 않았습니다.")
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

def init_db(reset=False):
    """데이터베이스를 초기화하거나 기존 데이터베이스를 사용합니다."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        try:
            if reset:
                c.execute("DROP TABLE IF EXISTS google_news_delivery_messages")
                c.execute("DROP TABLE IF EXISTS google_news_article_identity")
                c.execute("DROP TABLE IF EXISTS news_items")
                logging.info("기존 기사 및 전송 상태가 초기화되었습니다.")
            
            c.execute('''CREATE TABLE IF NOT EXISTS news_items
                         (pub_date TEXT,
                          guid TEXT PRIMARY KEY,
                          title TEXT,
                          link TEXT,
                          related_news TEXT)''')
            
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_guid ON news_items(guid)")
            
            # 데이터베이스 무결성 검사
            c.execute("PRAGMA integrity_check")
            integrity_result = c.fetchone()[0]
            if integrity_result != "ok":
                logging.error(f"데이터베이스 무결성 검사 실패: {integrity_result}")
                raise sqlite3.IntegrityError("데이터베이스 무결성 검사 실패")
            
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

    logging.info("데이터베이스 초기화 완료")

def is_guid_posted(guid, conn):
    """주어진 GUID가 이미 게시되었는지 확인합니다."""
    try:
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
        conn.execute(
            "INSERT INTO news_items (pub_date, guid, title, link, related_news) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guid) DO UPDATE SET "
            "pub_date = excluded.pub_date, title = excluded.title, "
            "link = excluded.link, related_news = excluded.related_news",
            (pub_date, guid, title, link, related_news),
        )
        logging.info(f"뉴스 항목 저장/업데이트: {guid}")

def fetch_rss_feed(url, request_guard):
    """RSS 피드를 가져옵니다."""
    try:
        response = request_guard.request(
            "get",
            url,
            headers={"User-Agent": GoogleNewsUrlResolver.USER_AGENT},
        )
        return response.content
    except BlockedRequestError:
        raise
    except requests.RequestException as error:
        logging.warning("RSS 피드 가져오기 실패 (오류 유형: %s)", type(error).__name__)
        raise RuntimeError("rss_fetch_failed") from None

def parse_rss_feed(rss_data):
    """RSS 피드를 파싱합니다."""
    try:
        root = ET.fromstring(rss_data)
        return root.findall('.//item')
    except ET.ParseError as e:
        logging.error(f"RSS 데이터 파싱 중 오류 발생: {e}")
        raise

def extract_rss_feed_keyword(title):
    """RSS 피드 제목에서 키워드를 추출합니다."""
    match = re.search(r'"([^"]+)', title)
    if match:
        keyword = match.group(1)
        if 'when:' in keyword:
            keyword = keyword.split('when:')[0].strip()
        return keyword
    return None

def replace_brackets(text):
    """대괄호와 꺾쇠괄호를 유니코드 문자로 대체합니다."""
    text = text.replace('[', '［').replace(']', '］')
    text = text.replace('<', '〈').replace('>', '〉')
    text = re.sub(r'(?<!\s)(?<!^)［', ' ［', text)
    text = re.sub(r'］(?!\s)', '］ ', text)
    text = re.sub(r'(?<!\s)(?<!^)〈', ' 〈', text)
    text = re.sub(r'〉(?!\s)', '〉 ', text)
    return text

def send_discord_message(webhook_url, message, avatar_url=None, username=None):
    """Discord 웹훅 전송 결과의 메시지 ID를 반환합니다."""
    if VALIDATE_ONLY:
        logging.info("검증 모드: Discord 전송을 생략합니다.")
        return "0"
    payload = {"content": message}
    
    if avatar_url and avatar_url.strip():
        payload["avatar_url"] = avatar_url
    
    if username and username.strip():
        payload["username"] = username
    
    try:
        message_id = send_webhook_message(webhook_url, payload)
        logging.info("Discord에 메시지 게시 완료")
        return message_id
    except (requests.RequestException, TypeError, ValueError) as error:
        logging.error("Discord 메시지 전송 실패 (오류 유형: %s)", type(error).__name__)
        failure = RuntimeError("discord_delivery_failed")
        failure.error_code = getattr(error, "error_code", "final_failure")
        failure.attempt_count = getattr(error, "attempt_count", 1)
        raise failure from None


def record_profile_result(status, processed_count, error_code=None):
    if not RESULT_PATH:
        return
    write_profile_result(
        RESULT_PATH,
        PROFILE_ID,
        status,
        processed_count,
        count_pending_deliveries(DB_PATH),
        error_code,
        ambiguous_retry_count=count_ambiguous_retries(DB_PATH),
    )


def deliver_reserved_item(guid):
    outcome = deliver_queued_item(
        DB_PATH,
        guid,
        lambda content: send_discord_message(
            DISCORD_WEBHOOK_KEYWORD,
            content,
            avatar_url=DISCORD_AVATAR_KEYWORD,
            username=DISCORD_USERNAME_KEYWORD,
        ),
    )
    if outcome.ambiguous_retry_count:
        print("::warning title=Google News ambiguous retry::A response-unknown delivery was retried")
        notify_admin(
            DISCORD_WEBHOOK_ADMIN,
            "Google News",
            PROFILE_ID or "keyword",
            guid,
            "ambiguous_retry",
        )


def resume_pending_deliveries():
    pending_guids = pending_delivery_guids(DB_PATH)
    if MANUAL_TEST_MODE:
        pending_guids = pending_guids[:1]
    for guid in pending_guids:
        try:
            deliver_reserved_item(guid)
        except Exception as error:
            notify_admin(
                DISCORD_WEBHOOK_ADMIN,
                "Google News",
                PROFILE_ID or "keyword",
                guid,
                getattr(error, "error_code", "final_failure"),
            )
            raise
    return len(pending_guids)

def extract_news_items(description, resolver):
    """HTML 설명에서 뉴스 항목을 추출합니다."""
    soup = BeautifulSoup(description, 'html.parser')
    news_items = []
    for li in soup.find_all('li'):
        a_tag = li.find('a')
        if a_tag:
            title = replace_brackets(a_tag.text)
            google_link = a_tag['href']
            link = resolve_related_url(resolver, google_link)
            if link is None:
                continue
            press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
            news_items.append({"title": title, "link": link, "press": press})
    return news_items

def parse_html_description(html_desc, resolver, main_title, main_link):
    """HTML 설명을 파싱하여 관련 뉴스 문자열을 생성합니다."""
    news_items = extract_news_items(html_desc, resolver)
    
    news_items = [item for item in news_items if item['title'] != main_title or item['link'] != main_link]
    
    if not news_items:
        return "", []
    news_string = '\n'.join(
        f"> - [{item['title']}]({item['link']}) | {item['press']}"
        for item in news_items
    )
    return news_string, news_items


def format_discord_message(news_item, keyword, country_code):
    """Format one keyword notification using the selected locale."""
    config = country_configs.get(country_code, country_configs['US'])
    service_language, _, _, service_country_name, _, flag, service_timezone, _ = config
    service_display_language = resolve_display_language(
        "",
        service_language,
        country_code,
    )
    display_language = resolve_display_language(
        DISPLAY_LANGUAGE,
        service_language,
        country_code,
    )
    google_news = labels_for(display_language)["google_news"]
    country_name = (
        service_country_name
        if display_language == service_display_language
        else localized_country_name(country_code, display_language)
    )
    timezone_name = FEED_TIMEZONE or service_timezone
    formatted_date = format_google_news_datetime(
        news_item['pub_date'],
        FEED_COUNTRY or country_code,
        timezone_name,
        display_language,
    )
    message = (
        f"`{google_news} - {keyword} - {country_name} {flag}`\n"
        f"**{news_item['title']}**\n{news_item['link']}"
    )
    if news_item['description']:
        message += f"\n{news_item['description']}"
    return f"{message}\n\n📅 {formatted_date}"

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

def get_keyword_display_name(keyword):
    """Return the presentation label without changing the search expression."""
    return KEYWORD_DISPLAY_NAME or keyword


def get_rss_url():
    rss_base_url = "https://news.google.com/rss/search"
    
    if os.getenv('KEYWORD_MODE') == 'true':
        keyword = os.getenv('KEYWORD')
        encoded_keyword = requests.utils.quote(keyword)
        query_params = [f"q={encoded_keyword}"]
        
        if os.getenv('WHEN'):
            query_params[-1] += f"+when:{os.getenv('WHEN')}"
        elif os.getenv('AFTER_DATE') or os.getenv('BEFORE_DATE'):
            if os.getenv('AFTER_DATE'):
                query_params[-1] += f"+after:{os.getenv('AFTER_DATE')}"
            if os.getenv('BEFORE_DATE'):
                query_params[-1] += f"+before:{os.getenv('BEFORE_DATE')}"
        
        query_string = "+".join(query_params)
        
        country_code = os.getenv('GL', 'KR')
        hl, ceid = country_configs.get(country_code, country_configs['US'])[:2]
        
        rss_url = f"{rss_base_url}?{query_string}&hl={hl}&gl={country_code}&ceid={ceid}"
        return rss_url, keyword, country_code
    else:
        return os.getenv('RSS_URL_KEYWORD'), None, 'KR'

def main():
    processed_count = 0
    already_known_count = 0
    try:
        rss_url, keyword, country_code = get_rss_url()

        base_keyword_query = ""
        try:
            base_keyword_query = extract_keyword_query(KEYWORD, rss_url)
        except ValueError:
            if KEYWORD_MODE:
                raise
        service_timezone = country_configs.get(
            country_code, country_configs['US']
        )[6]
        service_language = country_configs.get(
            country_code, country_configs['US']
        )[0]
        display_language = resolve_display_language(
            DISPLAY_LANGUAGE,
            service_language,
            FEED_COUNTRY or country_code,
        )
        compiled_filter = compile_google_news_feed_filter(
            common_date=FEED_DATE_FILTER,
            common_keyword=FEED_KEYWORD_FILTER,
            common_scope=FEED_KEYWORD_SCOPE,
            legacy_date=DATE_FILTER_KEYWORD,
            legacy_keyword=ADVANCED_FILTER_KEYWORD,
            service_keyword=base_keyword_query,
            service_aliases=KEYWORD_MATCH_ALIASES,
            service_mode=KEYWORD_MATCH_MODE,
            explicit_timezone=FEED_TIMEZONE,
            service_timezone=service_timezone,
            country_code=FEED_COUNTRY or country_code,
            display_language=display_language,
        )
        filter_fingerprint = compiled_filter.fingerprint

        init_db(reset=INITIALIZE_KEYWORD)

        resumed_count = resume_pending_deliveries()
        processed_count += resumed_count
        if MANUAL_TEST_MODE and resumed_count:
            record_profile_result("success", processed_count)
            return 0

        session = requests.Session()
        request_guard = GoogleNewsRequestGuard(session, RESOLVER_DB_PATH)
        resolver = GoogleNewsUrlResolver(
            session=session,
            db_path=RESOLVER_DB_PATH,
            enabled=ORIGIN_LINK_KEYWORD,
            max_network_resolutions=MAX_NETWORK_RESOLUTIONS,
            request_guard=request_guard,
        )
        if request_guard.get_open_circuit() is not None:
            record_profile_result("skipped", 0, "circuit_open")
            return 75

        logging.info("Google News RSS 피드를 가져옵니다.")
        logging.debug(f"ORIGIN_LINK_KEYWORD 값: {ORIGIN_LINK_KEYWORD}")
        rss_data = fetch_rss_feed(rss_url, request_guard)
        news_items = parse_rss_feed(rss_data)

        total_items = len(news_items)
        logging.info(f"총 {total_items}개의 뉴스 항목을 가져왔습니다.")
        
        if not INITIALIZE_KEYWORD:
            news_items = [
                item
                for item in news_items
                if not is_item_handled(
                    DB_PATH,
                    item.find('guid').text,
                    filter_fingerprint,
                )
            ]
            logging.info(f"후속 실행: {len(news_items)}개의 새로운 뉴스 항목을 판정합니다.")

        matched_items = []
        filtered_count = 0
        for item in news_items:
            match_result = compiled_filter.matches(
                item.findtext('pubDate', ''),
                item.findtext('title', ''),
                item.findtext('description', ''),
            )
            if match_result.matched:
                matched_items.append(item)
            else:
                record_filtered_item(DB_PATH, item, filter_fingerprint)
                filtered_count += 1
        news_items = matched_items
        logging.info(
            "키워드 판정 완료: 일치 %s개, 제외 %s개",
            len(news_items),
            filtered_count,
        )

        if MANUAL_TEST_MODE:
            news_items = prepare_manual_test_items(news_items, DB_PATH, True)
        else:
            news_items = prepare_scheduled_items(
                news_items,
                DB_PATH,
                delivery_order=DELIVERY_ORDER,
            )
        manual_test_expected_count = len(news_items)
        if MANUAL_TEST_MODE:
            logging.info(
                f"수동 테스트 모드: {manual_test_expected_count}개의 최신 항목을 처리합니다."
            )

        if not news_items:
            logging.info("처리할 새로운 뉴스 항목이 없습니다.")
            logging.info(
                "Google News URL 변환 요약: %s", resolver.get_stats()
            )
            record_profile_result("success", 0)
            return 0

        profile_failed = False
        queued_items = []
        for item in news_items:
            current_guid = "unknown"
            try:
                guid = item.find('guid').text
                current_guid = guid
                pub_date = item.find('pubDate').text
                title = replace_brackets(item.find('title').text)
                google_link = item.find('link').text
                link = resolver.resolve(google_link).url
                description_html = item.find('description').text

                description, related_news = parse_html_description(
                    description_html, resolver, title, link
                )

                discord_message = format_discord_message(
                    {
                        "title": title,
                        "link": link,
                        "description": description,
                        "pub_date": pub_date,
                    },
                    get_keyword_display_name(keyword),
                    country_code,
                )

                if not reserve_delivery_with_messages(
                    DB_PATH,
                    guid,
                    title,
                    link,
                    split_discord_content(discord_message),
                ):
                    already_known_count += 1
                    continue
                save_news_item(pub_date, guid, title, link, json.dumps(related_news, ensure_ascii=False))
                queued_items.append((guid, title))
                logging.info(f"뉴스 항목 대기열 저장 완료: {title}")

            except Exception as error:
                profile_failed = True
                logging.error("뉴스 대기열 준비 실패 (오류 유형: %s)", type(error).__name__)
                print("::warning title=Google News queue preparation failed::No Discord delivery was started")
                notify_admin(
                    DISCORD_WEBHOOK_ADMIN,
                    "Google News",
                    PROFILE_ID or "keyword",
                    current_guid,
                    "final_failure",
                )
                break

        if not profile_failed:
            for guid, title in queued_items:
                try:
                    deliver_reserved_item(guid)
                    processed_count += 1
                    logging.info(f"뉴스 항목 처리 완료: {title}")
                except Exception as error:
                    profile_failed = True
                    logging.error("뉴스 항목 전송 실패 (오류 유형: %s)", type(error).__name__)
                    print("::warning title=Google News delivery failed::A queued delivery remains pending")
                    notify_admin(
                        DISCORD_WEBHOOK_ADMIN,
                        "Google News",
                        PROFILE_ID or "keyword",
                        guid,
                        getattr(error, "error_code", "final_failure"),
                    )
                    break

        validate_manual_test_result(
            MANUAL_TEST_MODE,
            manual_test_expected_count,
            processed_count,
            already_known_count,
        )
        if profile_failed:
            raise RuntimeError("profile_run_failed")
        logging.info(f"총 {processed_count}개의 뉴스 항목이 성공적으로 처리되었습니다.")
        logging.info("Google News URL 변환 요약: %s", resolver.get_stats())
        record_profile_result("success", processed_count)
        return 0

    except BlockedRequestError as error:
        logging.error("Google News 요청이 차단되었습니다 (코드: %s)", error.error_code)
        record_profile_result("failed", processed_count, error.error_code)
        return 1
    except Exception as error:
        logging.error("프로필 실행 실패 (오류 유형: %s)", type(error).__name__)
        record_profile_result("failed", processed_count, "profile_run_failed")
        return 1

if __name__ == "__main__":
    try:
        check_env_variables()
        exit_code = main()
    except Exception as error:
        logging.error("실행 준비 실패 (오류 유형: %s)", type(error).__name__)
        exit_code = 1
    else:
        if exit_code == 0:
            logging.info("프로그램 정상 종료")
    if exit_code:
        sys.exit(exit_code)
