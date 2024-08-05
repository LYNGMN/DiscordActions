import xml.etree.ElementTree as ET
import requests
import re
import os
import time
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
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('google_news_top.log', encoding='utf-8')
        ]
    )

# 환경 변수 설정
class Config:
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

    @classmethod
    def check_env_variables(cls):
        if not cls.DISCORD_WEBHOOK_TOP:
            raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_TOP")

# 데이터베이스 관련 함수들
class Database:
    DB_PATH = 'google_news_top.db'

    @classmethod
    def init_db(cls, reset=False):
        with sqlite3.connect(cls.DB_PATH) as conn:
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
                
                c.execute("SELECT COUNT(*) FROM news_items")
                count = c.fetchone()[0]
                
                if reset or count == 0:
                    logging.info("새로운 데이터베이스가 초기화되었습니다.")
                else:
                    logging.info(f"기존 데이터베이스를 사용합니다. 현재 {count}개의 항목이 있습니다.")
                
            except sqlite3.Error as e:
                logging.error(f"데이터베이스 초기화 중 오류 발생: {e}")
                raise

    @classmethod
    def is_guid_posted(cls, guid):
        with sqlite3.connect(cls.DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM news_items WHERE guid = ?", (guid,))
            return c.fetchone() is not None

    @classmethod
    def save_news_item(cls, pub_date, guid, title, link, related_news):
        with sqlite3.connect(cls.DB_PATH) as conn:
            c = conn.cursor()
            
            c.execute("PRAGMA table_info(news_items)")
            columns = [column[1] for column in c.fetchall()]
            
            related_news_count = len(json.loads(related_news))
            
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

# URL 관련 함수들
class UrlUtils:
    @staticmethod
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
            raise Exception("Google에서 데이터를 가져오는데 실패했습니다.")

        text = response.text
        header = '[\\"garturlres\\",\\"'
        footer = '\\",'
        if header not in text:
            raise Exception(f"응답에서 헤더를 찾을 수 없습니다: {text}")
        start = text.split(header, 1)[1]
        if footer not in start:
            raise Exception("응답에서 푸터를 찾을 수 없습니다.")
        url = start.split(footer, 1)[0]
        return url

    @staticmethod
    def decode_base64_url_part(encoded_str):
        base64_str = encoded_str.replace("-", "+").replace("_", "/")
        base64_str += "=" * ((4 - len(base64_str) % 4) % 4)
        try:
            decoded_bytes = base64.urlsafe_b64decode(base64_str)
            decoded_str = decoded_bytes.decode('latin1')
            return decoded_str
        except Exception as e:
            return f"디코딩 중 오류 발생: {e}"

    @staticmethod
    def extract_youtube_id(decoded_str):
        pattern = r'\x08 "\x0b([\w-]{11})\x98\x01\x01'
        match = re.search(pattern, decoded_str)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def extract_regular_url(decoded_str):
        parts = re.split(r'[^\x20-\x7E]+', decoded_str)
        url_pattern = r'(https?://[^\s]+)'
        for part in parts:
            match = re.search(url_pattern, part)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def unescape_unicode(text):
        return re.sub(
            r'\\u([0-9a-fA-F]{4})',
            lambda m: chr(int(m.group(1), 16)),
            text
        )

    @staticmethod
    def clean_url(url):
        url = UrlUtils.unescape_unicode(url)
        url = url.replace('\\', '')
        url = unquote(url)

        parsed_url = urlparse(url)
        
        if parsed_url.netloc.endswith('msn.com'):
            parsed_url = parsed_url._replace(scheme='https')
            query_params = parse_qs(parsed_url.query)
            cleaned_params = {k: v[0] for k, v in query_params.items() if k in ['id', 'article']}
            cleaned_query = urlencode(cleaned_params)
            parsed_url = parsed_url._replace(query=cleaned_query)
        
        safe_chars = "/:@&=+$,?#"
        cleaned_path = quote(parsed_url.path, safe=safe_chars)
        cleaned_query = quote(parsed_url.query, safe=safe_chars)
        
        cleaned_url = urlunparse(parsed_url._replace(path=cleaned_path, query=cleaned_query))
        
        return cleaned_url

    @classmethod
    def decode_google_news_url(cls, source_url):
        url = urlparse(source_url)
        path = url.path.split("/")
        if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
            base64_str = path[-1]
            
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
                    return cls.clean_url(cls.fetch_decoded_batch_execute(base64_str))

                regular_url = cls.extract_regular_url(decoded_str)
                if regular_url:
                    return cls.clean_url(regular_url)
            except Exception:
                pass

            decoded_str = cls.decode_base64_url_part(base64_str)
            youtube_id = cls.extract_youtube_id(decoded_str)
            if youtube_id:
                return f"https://www.youtube.com/watch?v={youtube_id}"

            regular_url = cls.extract_regular_url(decoded_str)
            if regular_url:
                return cls.clean_url(regular_url)

        return cls.clean_url(source_url)

    @classmethod
    def get_original_url(cls, google_link, session, max_retries=5):
        logging.info(f"ORIGIN_LINK_TOP 값 확인: {Config.ORIGIN_LINK_TOP}")

        original_url = cls.decode_google_news_url(google_link)
        if original_url != google_link:
            return original_url

        retries = 0
        while retries < max_retries:
            try:
                response = session.get(google_link, allow_redirects=True, timeout=30)
                response.raise_for_status()
                return cls.clean_url(response.url)
            except requests.RequestException as e:
                logging.error(f"원본 URL을 가져오는데 실패 (시도 {retries + 1}/{max_retries}): {e}")
                retries += 1
                time.sleep(1)

        logging.warning(f"오리지널 링크 추출 실패, 원 링크 사용: {google_link}")
        return cls.clean_url(google_link)

# RSS 관련 함수들
class RssUtils:
    @staticmethod
    def fetch_rss_feed(url, max_retries=3, retry_delay=5):
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                return response.content
            except requests.RequestException as e:
                logging.warning(f"RSS 피드 가져오기 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt + 1 < max_retries:
                    time.sleep(retry_delay)
                else:
                    logging.error(f"RSS 피드를 가져오는데 실패했습니다: {url}")
                    raise

    @staticmethod
    def get_rss_url():
        if Config.TOP_MODE:
            if not Config.TOP_COUNTRY:
                raise ValueError("TOP_MODE가 true일 때 TOP_COUNTRY를 지정해야 합니다.")

            country_configs = {
                # 동아시아
                'KR': ('ko', 'KR:ko', 'Google 뉴스', '주요 뉴스', '한국', 'South Korea', '🇰🇷', 'Asia/Seoul'),
                'JP': ('ja', 'JP:ja', 'Google ニュース', 'トップニュース', '日本', 'Japan', '🇯🇵', 'Asia/Tokyo'),
                'CN': ('zh-CN', 'CN:zh-Hans', 'Google 新闻', '焦点新闻', '中国', 'China', '🇨🇳', 'Asia/Shanghai'),
                'TW': ('zh-TW', 'TW:zh-Hant', 'Google 新聞', '焦點新聞', '台灣', 'Taiwan', '🇹🇼', 'Asia/Taipei'),
                'HK': ('zh-HK', 'HK:zh-Hant', 'Google 新聞', '焦點新聞', '香港', 'Hong Kong', '🇭🇰', 'Asia/Hong_Kong'),

                # 동남아시아
                'VN': ('vi', 'VN:vi', 'Google Tin tức', 'Tin nổi bật', 'Việt Nam', 'Vietnam', '🇻🇳', 'Asia/Ho_Chi_Minh'),
                'TH': ('th', 'TH:th', 'Google News', 'เรื่องเด่น', 'ประเทศไทย', 'Thailand', '🇹🇭', 'Asia/Bangkok'),
                'PH': ('en-PH', 'PH:en', 'Google News', 'Top stories', 'Philippines', 'Philippines', '🇵🇭', 'Asia/Manila'),
                'MY': ('ms-MY', 'MY:ms', 'Berita Google', 'Berita hangat', 'Malaysia', 'Malaysia', '🇲🇾', 'Asia/Kuala_Lumpur'),
                'SG': ('en-SG', 'SG:en', 'Google News', 'Top stories', 'Singapore', 'Singapore', '🇸🇬', 'Asia/Singapore'),
                'ID': ('id', 'ID:id', 'Google Berita', 'Artikel populer', 'Indonesia', 'Indonesia', '🇮🇩', 'Asia/Jakarta'),

                # 남아시아
                'IN': ('en-IN', 'IN:en', 'Google News', 'Top stories', 'India', 'India', '🇮🇳', 'Asia/Kolkata'),
                'BD': ('bn', 'BD:bn', 'Google News', 'সেরা খবর', 'বাংলাদেশ', 'Bangladesh', '🇧🇩', 'Asia/Dhaka'),
                'PK': ('en-PK', 'PK:en', 'Google News', 'Top stories', 'Pakistan', 'Pakistan', '🇵🇰', 'Asia/Karachi'),

                # 서아시아
                'IL': ('he', 'IL:he', 'חדשות Google', 'הכתבות המובילות', 'ישראל', 'Israel', '🇮🇱', 'Asia/Jerusalem'),
                'AE': ('ar', 'AE:ar', 'أخبار Google', 'أهم الأخبار', 'الإمارات العربية المتحدة', 'United Arab Emirates', '🇦🇪', 'Asia/Dubai'),
                'TR': ('tr', 'TR:tr', 'Google Haberler', 'En çok okunan haberler', 'Türkiye', 'Turkey', '🇹🇷', 'Europe/Istanbul'),
                'LB': ('ar', 'LB:ar', 'أخبار Google', 'أهم الأخبار', 'لبنان', 'Lebanon', '🇱🇧', 'Asia/Beirut'),

                # 오세아니아
                'AU': ('en-AU', 'AU:en', 'Google News', 'Top stories', 'Australia', 'Australia', '🇦🇺', 'Australia/Sydney'),
                'NZ': ('en-NZ', 'NZ:en', 'Google News', 'Top stories', 'New Zealand', 'New Zealand', '🇳🇿', 'Pacific/Auckland'),

                # 러시아와 동유럽
                'RU': ('ru', 'RU:ru', 'Google Новости', 'Главные новости', 'Россия', 'Russia', '🇷🇺', 'Europe/Moscow'),
                'UA': ('uk', 'UA:uk', 'Google Новини', 'Головні новини', 'Україна', 'Ukraine', '🇺🇦', 'Europe/Kiev'),

                # 유럽
                'GR': ('el', 'GR:el', 'Ειδήσεις Google', 'Κυριότερες ειδήσεις', 'Ελλάδα', 'Greece', '🇬🇷', 'Europe/Athens'),
                'DE': ('de', 'DE:de', 'Google News', 'Top-Meldungen', 'Deutschland', 'Germany', '🇩🇪', 'Europe/Berlin'),
                'NL': ('nl', 'NL:nl', 'Google Nieuws', 'Voorpaginanieuws', 'Nederland', 'Netherlands', '🇳🇱', 'Europe/Amsterdam'),
                'NO': ('no', 'NO:no', 'Google Nyheter', 'Hovedoppslag', 'Norge', 'Norway', '🇳🇴', 'Europe/Oslo'),
                'LV': ('lv', 'LV:lv', 'Google ziņas', 'Populārākās ziņas', 'Latvija', 'Latvia', '🇱🇻', 'Europe/Riga'),
                'LT': ('lt', 'LT:lt', 'Google naujienos', 'Populiariausios naujienos', 'Lietuva', 'Lithuania', '🇱🇹', 'Europe/Vilnius'),
                'RO': ('ro', 'RO:ro', 'Știri Google', 'Cele mai populare subiecte', 'România', 'Romania', '🇷🇴', 'Europe/Bucharest'),
                'BE': ('fr', 'BE:fr', 'Google Actualités', 'À la une', 'Belgique', 'Belgium', '🇧🇪', 'Europe/Brussels'),
                'BG': ('bg', 'BG:bg', 'Google Новини', 'Водещи материали', 'България', 'Bulgaria', '🇧🇬', 'Europe/Sofia'),
                'SK': ('sk', 'SK:sk', 'Správy Google', 'Hlavné správy', 'Slovensko', 'Slovakia', '🇸🇰', 'Europe/Bratislava'),
                'SI': ('sl', 'SI:sl', 'Google News', 'Najpomembnejše novice', 'Slovenija', 'Slovenia', '🇸🇮', 'Europe/Ljubljana'),
                'CH': ('de', 'CH:de', 'Google News', 'Top-Meldungen', 'Schweiz', 'Switzerland', '🇨🇭', 'Europe/Zurich'),
                'ES': ('es', 'ES:es', 'Google News', 'Noticias destacadas', 'España', 'Spain', '🇪🇸', 'Europe/Madrid'),
                'SE': ('sv', 'SE:sv', 'Google Nyheter', 'Huvudnyheter', 'Sverige', 'Sweden', '🇸🇪', 'Europe/Stockholm'),
                'RS': ('sr', 'RS:sr', 'Google вести', 'Најважније вести', 'Србија', 'Serbia', '🇷🇸', 'Europe/Belgrade'),
                'AT': ('de', 'AT:de', 'Google News', 'Top-Meldungen', 'Österreich', 'Austria', '🇦🇹', 'Europe/Vienna'),
                'IE': ('en-IE', 'IE:en', 'Google News', 'Top stories', 'Ireland', 'Ireland', '🇮🇪', 'Europe/Dublin'),
                'EE': ('et-EE', 'EE:et', 'Google News', 'Populaarseimad lood', 'Eesti', 'Estonia', '🇪🇪', 'Europe/Tallinn'),
                'IT': ('it', 'IT:it', 'Google News', 'Notizie principali', 'Italia', 'Italy', '🇮🇹', 'Europe/Rome'),
                'CZ': ('cs', 'CZ:cs', 'Zprávy Google', 'Hlavní události', 'Česko', 'Czech Republic', '🇨🇿', 'Europe/Prague'),
                'GB': ('en-GB', 'GB:en', 'Google News', 'Top stories', 'United Kingdom', 'United Kingdom', '🇬🇧', 'Europe/London'),
                'PL': ('pl', 'PL:pl', 'Google News', 'Najważniejsze artykuły', 'Polska', 'Poland', '🇵🇱', 'Europe/Warsaw'),
                'PT': ('pt-PT', 'PT:pt-150', 'Google Notícias', 'Notícias principais', 'Portugal', 'Portugal', '🇵🇹', 'Europe/Lisbon'),
                'FI': ('fi-FI', 'FI:fi', 'Google Uutiset', 'Pääuutiset', 'Suomi', 'Finland', '🇫🇮', 'Europe/Helsinki'),
                'FR': ('fr', 'FR:fr', 'Google Actualités', 'À la une', 'France', 'France', '🇫🇷', 'Europe/Paris'),
                'HU': ('hu', 'HU:hu', 'Google Hírek', 'Vezető hírek', 'Magyarország', 'Hungary', '🇭🇺', 'Europe/Budapest'),

                # 북미
                'CA': ('en-CA', 'CA:en', 'Google News', 'Top stories', 'Canada', 'Canada', '🇨🇦', 'America/Toronto'),
                'MX': ('es-419', 'MX:es-419', 'Google Noticias', 'Noticias destacadas', 'México', 'Mexico', '🇲🇽', 'America/Mexico_City'),
                'US': ('en-US', 'US:en', 'Google News', 'Top stories', 'United States', 'United States', '🇺🇸', 'America/New_York'),
                'CU': ('es-419', 'CU:es-419', 'Google Noticias', 'Noticias destacadas', 'Cuba', 'Cuba', '🇨🇺', 'America/Havana'),

                # 남미
                'AR': ('es-419', 'AR:es-419', 'Google Noticias', 'Noticias destacadas', 'Argentina', 'Argentina', '🇦🇷', 'America/Buenos_Aires'),
                'BR': ('pt-BR', 'BR:pt-419', 'Google Notícias', 'Principais notícias', 'Brasil', 'Brazil', '🇧🇷', 'America/Sao_Paulo'),
                'CL': ('es-419', 'CL:es-419', 'Google Noticias', 'Noticias destacadas', 'Chile', 'Chile', '🇨🇱', 'America/Santiago'),
                'CO': ('es-419', 'CO:es-419', 'Google Noticias', 'Noticias destacadas', 'Colombia', 'Colombia', '🇨🇴', 'America/Bogota'),
                'PE': ('es-419', 'PE:es-419', 'Google Noticias', 'Noticias destacadas', 'Perú', 'Peru', '🇵🇪', 'America/Lima'),
                'VE': ('es-419', 'VE:es-419', 'Google Noticias', 'Noticias destacadas', 'Venezuela', 'Venezuela', '🇻🇪', 'America/Caracas'),

                # 아프리카
                'ZA': ('en-ZA', 'ZA:en', 'Google News', 'Top stories', 'South Africa', 'South Africa', '🇿🇦', 'Africa/Johannesburg'),
                'NG': ('en-NG', 'NG:en', 'Google News', 'Top stories', 'Nigeria', 'Nigeria', '🇳🇬', 'Africa/Lagos'),
                'EG': ('ar', 'EG:ar', 'أخبار Google', 'أهم الأخبار', 'مصر', 'Egypt', '🇪🇬', 'Africa/Cairo'),
                'KE': ('en-KE', 'KE:en', 'Google News', 'Top stories', 'Kenya', 'Kenya', '🇰🇪', 'Africa/Nairobi'),
                'MA': ('fr', 'MA:fr', 'Google Actualités', 'À la une', 'Maroc', 'Morocco', '🇲🇦', 'Africa/Casablanca'),
                'SN': ('fr', 'SN:fr', 'Google Actualités', 'À la une', 'Sénégal', 'Senegal', '🇸🇳', 'Africa/Dakar'),
                'UG': ('en-UG', 'UG:en', 'Google News', 'Top stories', 'Uganda', 'Uganda', '🇺🇬', 'Africa/Kampala'),
                'TZ': ('en-TZ', 'TZ:en', 'Google News', 'Top stories', 'Tanzania', 'Tanzania', '🇹🇿', 'Africa/Dar_es_Salaam'),
                'ZW': ('en-ZW', 'ZW:en', 'Google News', 'Top stories', 'Zimbabwe', 'Zimbabwe', '🇿🇼', 'Africa/Harare'),
                'ET': ('en-ET', 'ET:en', 'Google News', 'Top stories', 'Ethiopia', 'Ethiopia', '🇪🇹', 'Africa/Addis_Ababa'),
                'GH': ('en-GH', 'GH:en', 'Google News', 'Top stories', 'Ghana', 'Ghana', '🇬🇭', 'Africa/Accra'),
            }

            if Config.TOP_COUNTRY not in country_configs:
                raise ValueError(f"지원되지 않는 국가 코드: {Config.TOP_COUNTRY}")

            hl, ceid, google_news, news_type, country_name, country_name_en, flag, tz = country_configs[Config.TOP_COUNTRY]
            rss_url = f"https://news.google.com/rss?hl={hl}&gl={Config.TOP_COUNTRY}&ceid={ceid}"

            discord_title = f"`{google_news} - {news_type} - {country_name} {flag}`"

            return rss_url, discord_title
        elif Config.RSS_URL_TOP:
            return Config.RSS_URL_TOP, None
        else:
            raise ValueError("TOP_MODE가 false일 때 RSS_URL_TOP를 지정해야 합니다.")

# 텍스트 처리 관련 함수들
class TextUtils:
    @staticmethod
    def parse_rss_date(pub_date):
        dt = parser.parse(pub_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        
        timezone_str = None
        country_code = None
        
        if Config.TOP_MODE:
            if Config.TOP_COUNTRY in country_configs:
                timezone_str = country_configs[Config.TOP_COUNTRY][7]
                country_code = Config.TOP_COUNTRY
        elif Config.RSS_URL_TOP:
            parsed_url = urlparse(Config.RSS_URL_TOP)
            query_params = parse_qs(parsed_url.query)
            if 'gl' in query_params:
                country_code = query_params['gl'][0]
                if country_code in country_configs:
                    timezone_str = country_configs[country_code][7]
        
        if timezone_str:
            try:
                local_tz = pytz.timezone(timezone_str)
                dt_local = dt.astimezone(local_tz)
                
                if country_code == 'KR':
                    return f"{dt_local.strftime('%Y년 %m월 %d일 %H:%M:%S')} (KST)"
                elif country_code == 'JP':
                    return f"{dt_local.strftime('%Y年%m月%d日 %H時%M分%S秒')} (JST)"
                elif country_code == 'CN':
                    return f"{dt_local.strftime('%Y年%m月%d日 %H:%M:%S')} (CST)"
                elif country_code == 'TW':
                    return f"{dt_local.strftime('%Y年%m月%d日 %H:%M:%S')} (NST)"
                elif country_code == 'HK':
                    return f"{dt_local.strftime('%Y年%m月%d日 %H:%M:%S')} (HKT)"
                else:
                    tz_abbr = dt_local.strftime('%Z')
                    return f"{dt_local.strftime('%Y-%m-%d %H:%M:%S')} ({tz_abbr})"
            except pytz.exceptions.UnknownTimeZoneError:
                logging.warning(f"알 수 없는 시간대: {timezone_str}. UTC를 사용합니다.")
        
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} (UTC)"

# Discord 관련 함수
class DiscordUtils:
    @staticmethod
    def send_discord_message(webhook_url, message, avatar_url=None, username=None, max_retries=3):
        payload = {"content": message}
        
        if avatar_url and avatar_url.strip():
            payload["avatar_url"] = avatar_url
        
        if username and username.strip():
            payload["username"] = username
        
        headers = {"Content-Type": "application/json"}

        for attempt in range(max_retries):
            try:
                response = requests.post(webhook_url, json=payload, headers=headers, timeout=30)
                response.raise_for_status()
                logging.info("Discord에 메시지 게시 완료")
                return
            except requests.RequestException as e:
                logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt + 1 < max_retries:
                    time.sleep(5)
        
        logging.error("최대 재시도 횟수를 초과했습니다. Discord 메시지 전송 실패.")
        raise Exception("Discord 메시지 전송 실패")

# 뉴스 처리 관련 함수
class NewsProcessor:
    @staticmethod
    def extract_news_items(description, session):
        soup = BeautifulSoup(description, 'html.parser')
        news_items = []
        for li in soup.find_all('li'):
            a_tag = li.find('a')
            if a_tag:
                title = TextUtils.replace_brackets(a_tag.text)
                google_link = a_tag['href']
                link = UrlUtils.get_original_url(google_link, session)
                press = li.find('font', color="#6f6f6f").text if li.find('font', color="#6f6f6f") else ""
                news_items.append({"title": title, "link": link, "press": press})
        return news_items

    @staticmethod
    def apply_advanced_filter(title, description, advanced_filter):
        if not advanced_filter:
            return True

        text_to_check = (title + ' ' + description).lower()
        terms = re.findall(r'([+-]?)(?:"([^"]*)"|\S+)', advanced_filter)

        for prefix, term in terms:
            term = term.lower() if term else prefix.lower()
            if prefix == '+' or not prefix:
                if term not in text_to_check:
                    return False
            elif prefix == '-':
                exclude_terms = term.split()
                if len(exclude_terms) > 1:
                    if ' '.join(exclude_terms) in text_to_check:
                        return False
                else:
                    if term in text_to_check:
                        return False

        return True

    @staticmethod
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
                past_date = now - timedelta(days=value*30)
            elif unit == 'y':
                past_date = now - timedelta(days=value*365)
            logging.info(f"past_date 파싱 결과: {past_date}")
        else:
            logging.warning("past: 형식의 날짜 필터를 찾을 수 없습니다.")

        logging.info(f"최종 파싱 결과 - since_date: {since_date}, until_date: {until_date}, past_date: {past_date}")
        return since_date, until_date, past_date

    @staticmethod
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

# 메인 함수
def main():
    try:
        rss_url, discord_title = RssUtils.get_rss_url()
        rss_data = RssUtils.fetch_rss_feed(rss_url)
        root = ET.fromstring(rss_data)

        Database.init_db(reset=Config.INITIALIZE_TOP)

        session = requests.Session()
        
        news_items = root.findall('.//item')
        if Config.INITIALIZE_TOP:
            news_items = list(news_items)
        else:
            news_items = reversed(news_items)

        since_date, until_date, past_date = NewsProcessor.parse_date_filter(Config.DATE_FILTER_TOP)

        for item in news_items:
            try:
                guid = item.find('guid').text

                if not Config.INITIALIZE_TOP and Database.is_guid_posted(guid):
                    continue

                title = TextUtils.replace_brackets(item.find('title').text)
                google_link = item.find('link').text
                link = UrlUtils.get_original_url(google_link, session)
                pub_date = item.find('pubDate').text
                description_html = item.find('description').text
                
                formatted_date = TextUtils.parse_rss_date(pub_date)

                if not NewsProcessor.is_within_date_range(pub_date, since_date, until_date, past_date):
                    logging.info(f"날짜 필터에 의해 건너뛰어진 뉴스: {title}")
                    continue

                related_news = NewsProcessor.extract_news_items(description_html, session)
                related_news_json = json.dumps(related_news, ensure_ascii=False)

                description = TextUtils.parse_html_description(description_html, session)

                if not NewsProcessor.apply_advanced_filter(title, description, Config.ADVANCED_FILTER_TOP):
                    logging.info(f"고급 검색 필터에 의해 건너뛰어진 뉴스: {title}")
                    continue

                discord_message = f"{discord_title}\n**{title}**\n{link}\n>>> {description}\n\n📅 {formatted_date}"

                DiscordUtils.send_discord_message(
                    Config.DISCORD_WEBHOOK_TOP,
                    discord_message,
                    avatar_url=Config.DISCORD_AVATAR_TOP,
                    username=Config.DISCORD_USERNAME_TOP
                )

                Database.save_news_item(pub_date, guid, title, link, related_news_json)

                if not Config.INITIALIZE_TOP:
                    time.sleep(3)
            except Exception as e:
                logging.error(f"뉴스 항목 처리 중 오류 발생: {e}", exc_info=True)
                continue

    except Exception as e:
        logging.error(f"main 함수 실행 중 오류 발생: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        setup_logging()
        Config.check_env_variables()
        main()
    except Exception as e:
        logging.error(f"프로그램 실행 중 치명적인 오류 발생: {e}", exc_info=True)
        sys.exit(1)