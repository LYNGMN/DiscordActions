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
from urllib.parse import urlparse
from datetime import datetime, timedelta
from dateutil import parser
from dateutil.tz import gettz
from bs4 import BeautifulSoup

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
DISCORD_WEBHOOK_TOPIC = os.environ.get('DISCORD_WEBHOOK_TOPIC')
DISCORD_AVATAR_TOPIC = os.environ.get('DISCORD_AVATAR_TOPIC', '').strip()
DISCORD_USERNAME_TOPIC = os.environ.get('DISCORD_USERNAME_TOPIC', '').strip()
INITIALIZE_TOPIC = os.environ.get('INITIALIZE_MODE_TOPIC', 'false').lower() == 'true'
ADVANCED_FILTER_TOPIC = os.environ.get('ADVANCED_FILTER_TOPIC', '')
DATE_FILTER_TOPIC = os.environ.get('DATE_FILTER_TOPIC', '')
ORIGIN_LINK_TOPIC = os.getenv('ORIGIN_LINK_TOPIC', '').lower()
ORIGIN_LINK_TOPIC = ORIGIN_LINK_TOPIC not in ['false', 'f', '0', 'no', 'n']
TOPIC_MODE = os.environ.get('TOPIC_MODE', 'false').lower() == 'true'
TOPIC_KEYWORD = os.environ.get('TOPIC_KEYWORD', '')
TOPIC_PARAMS = os.environ.get('TOPIC_PARAMS', '?hl=ko&gl=KR&ceid=KR%3Ako')
RSS_URL_TOPIC = os.environ.get('RSS_URL_TOPIC', '')

# DB 설정
DB_PATH = 'google_news_topic.db'

# 토픽 ID 매핑
# - "headlines": 토픽키워드
# - "ko": 언어 코드 (ko: 한국어, en: 영어, ja: 일본어, zh: 중국어)
# - 각 언어 코드에 대한 튜플의 구조:
#   ("토픽이름", "토픽ID", "MID")
TOPIC_MAP = {
    # 헤드라인 뉴스
    "headlines": {
        "ko": ("헤드라인", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB", "/m/05jhg"),
        "en": ("Headlines", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtVnVHZ0pWVXlnQVAB", "/m/05jhg"),
        "ja": ("ヘッドライン", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtcGhHZ0pLVUNnQVAB", "/m/05jhg"),
        "zh": ("头条", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRFZxYUdjU0JYcG9MVU5PR2dKRFRpZ0FQAQ", "/m/05jhg")
    },
    "korea": {
        "ko": ("대한민국", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp4WkRNU0FtdHZLQUFQAQ", "/m/06qd3")
    },
    "us": {
        "en": ("U.S.", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSmxiaWdBUAE", "/m/09c7w0")
    },
    "japan": {
        "ja": ("日本", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE5mTTJRU0FtcGhLQUFQAQ", "/m/03_3d")
    },
    "china": {
        "zh": ("中国", "CAAqJggKIiBDQkFTRWdvSkwyMHZNR1F3TlhjekVnVjZhQzFEVGlnQVAB", "/m/0d05w3")
    },
    "world": {
        "ko": ("세계", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB", "/m/09nm_"),
        "en": ("World", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB", "/m/09nm_"),
        "ja": ("世界", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtcGhHZ0pLVUNnQVAB", "/m/09nm_"),
        "zh": ("全球", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JYcG9MVU5PR2dKRFRpZ0FQAQ", "/m/09nm_")
    },
    "politics": {
        "ko": ("정치", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtdHZLQUFQAQ", "/m/05qt0"),
        "en": ("Politics", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtVnVLQUFQAQ", "/m/05qt0"),
        "ja": ("政治", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtcGhLQUFQAQ", "/m/05qt0"),
        "zh": ("政治", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZ4ZERBU0JYcG9MVU5PS0FBUAE", "/m/05qt0")
    },
	
	# 연예 뉴스
	"entertainment": {
        "ko": ("엔터테인먼트", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtdHZHZ0pMVWlnQVAB", "/m/02jjt"),
        "en": ("Entertainment", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB", "/m/02jjt"),
        "ja": ("エンタメ", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtcGhHZ0pLVUNnQVAB", "/m/02jjt"),
        "zh": ("娱乐", "CAAqKggKIiRDQkFTRlFvSUwyMHZNREpxYW5RU0JYcG9MVU5PR2dKRFRpZ0FQAQ", "/m/02jjt")
    },
    "celebrity": {
        "ko": ("연예", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtdHZLQUFQAQ", "/m/01rfz"),
        "en": ("Celebrities", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtVnVLQUFQAQ", "/m/01rfz"),
        "ja": ("有名人", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtcGhLQUFQAQ", "/m/01rfz"),
        "zh": ("明星", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZ5Wm5vU0JYcG9MVU5PS0FBUAE", "/m/01rfz")
    },
    "tv": {
        "ko": ("TV", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtdHZLQUFQAQ", "/m/07c52"),
        "en": ("TV", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtVnVLQUFQAQ", "/m/07c52"),
        "ja": ("テレビ", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtcGhLQUFQAQ", "/m/07c52"),
        "zh": ("电视", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGRqTlRJU0JYcG9MVU5PS0FBUAE", "/m/07c52")
    },
    "music": {
        "ko": ("음악", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtdHZLQUFQAQ", "/m/04rlf"),
        "en": ("Music", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtVnVLQUFQAQ", "/m/04rlf"),
        "ja": ("音楽", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtcGhLQUFQAQ", "/m/04rlf"),
        "zh": ("音乐", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFJ5YkdZU0JYcG9MVU5PS0FBUAE", "/m/04rlf")
    },
    "movies": {
        "ko": ("영화", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtdHZLQUFQAQ", "/m/02vxn"),
        "en": ("Movies", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtVnVLQUFQAQ", "/m/02vxn"),
        "ja": ("映画", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtcGhLQUFQAQ", "/m/02vxn"),
        "zh": ("影视", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREoyZUc0U0JYcG9MVU5PS0FBUAE", "/m/02vxn")
    },	
	"theater": {
        "ko": ("연극", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNhMjhvQUFQAQ", "/m/03qsdpk"),
        "en": ("Theater", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNaVzRvQUFQAQ", "/m/03qsdpk"),
        "ja": ("劇場", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNhbUVvQUFQAQ", "/m/03qsdpk"),
        "zh": ("戏剧", "PLACEHOLDER_ID_THEATER", None)
    },
	
	# 스포츠 뉴스
    "sports": {
        "ko": ("스포츠", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB", "/m/06ntj"),
        "en": ("Sports", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB", "/m/06ntj"),
        "ja": ("スポーツ", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtcGhHZ0pLVUNnQVAB", "/m/06ntj"),
        "zh": ("体育", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0JYcG9MVU5PR2dKRFRpZ0FQAQ", "/m/06ntj")
    },
    "soccer": {
        "ko": ("축구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtdHZLQUFQAQ", "/m/02vx4"),
        "en": ("Soccer", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtVnVLQUFQAQ", "/m/02vx4"),
        "ja": ("サッカー", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtcGhLQUFQAQ", "/m/02vx4"),
        "zh": ("足球", "PLACEHOLDER_ID_SOCCER", None)
    },
    "cycling": {
        "ko": ("자전거", "PLACEHOLDER_ID_CYCLING", None),
        "en": ("Cycling", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ6WjJ3U0FtVnVLQUFQAQ", "/m/01sgl"),
        "ja": ("自転車", "PLACEHOLDER_ID_CYCLING", None),
        "zh": ("骑行", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZ6WjJ3U0JYcG9MVU5PS0FBUAE", "/m/01sgl")
    },
    "motorsports": {
        "ko": ("모터스포츠", "PLACEHOLDER_ID_MOTORSPORTS", None),
        "en": ("Motor sports", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TUhSMGFCSUNaVzRvQUFQAQ", "/m/0410tth"),
        "ja": ("モーター スポーツ", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TUhSMGFCSUNhbUVvQUFQAQ", "/m/0410tth"),
        "zh": ("汽车运动", "PLACEHOLDER_ID_MOTORSPORTS", None)
    },
	"tennis": {
        "ko": ("테니스", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtdHZLQUFQAQ", "/m/07bs0"),
        "en": ("Tennis", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtVnVLQUFQAQ", "/m/07bs0"),
        "ja": ("テニス", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtcGhLQUFQAQ", "/m/07bs0"),
        "zh": ("网球", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGRpY3pBU0JYcG9MVU5PS0FBUAE", "/m/07bs0")
    },
    "martial_arts": {
        "ko": ("격투기", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSnJieWdBUAE", "/m/05kc29"),
        "en": ("Combat sports", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSmxiaWdBUAE", "/m/05kc29"),
        "ja": ("格闘技", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSnFZU2dBUAE", "/m/05kc29"),
        "zh": ("格斗运动", "PLACEHOLDER_ID_MARTIAL_ARTS", None)
    },
    "basketball": {
        "ko": ("농구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtdHZLQUFQAQ", "/m/018w8"),
        "en": ("Basketball", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtVnVLQUFQAQ", "/m/018w8"),
        "ja": ("バスケットボール", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtcGhLQUFQAQ", "/m/018w8"),
        "zh": ("NBA", "PLACEHOLDER_ID_BASKETBALL", None)
    },
    "baseball": {
        "ko": ("야구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtdHZLQUFQAQ", "/m/018jz"),
        "en": ("Baseball", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtVnVLQUFQAQ", "/m/018jz"),
        "ja": ("野球", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtcGhLQUFQAQ", "/m/018jz"),
        "zh": ("棒球", "PLACEHOLDER_ID_BASEBALL", None)
    },
    "american_football": {
        "ko": ("미식축구", "PLACEHOLDER_ID_AMERICAN_FOOTBALL", None),
        "en": ("Football", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3B0WHhJQ1pXNG9BQVAB", "/m/0jm_"),
        "ja": ("アメフト", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3B0WHhJQ2FtRW9BQVAB", "/m/0jm_"),
        "zh": ("美式足球", "PLACEHOLDER_ID_AMERICAN_FOOTBALL", None)
    },
    "sports_betting": {
        "ko": ("스포츠 베팅", "PLACEHOLDER_ID_SPORTS_BETTING", None),
        "en": ("Sports betting", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFIwTXpsa0VnSmxiaWdBUAE", "/m/04t39d"),
        "ja": ("スポーツ賭博", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFIwTXpsa0VnSnFZU2dBUAE", "/m/04t39d"),
        "zh": ("体育博彩", "PLACEHOLDER_ID_SPORTS_BETTING", None)
    },
    "water_sports": {
        "ko": ("수상 스포츠", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSnJieWdBUAE", "/m/02fhdf"),
        "en": ("Water sports", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSmxiaWdBUAE", "/m/02fhdf"),
        "ja": ("ウォーター スポーツ", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSnFZU2dBUAE", "/m/02fhdf"),
        "zh": ("水上运动", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREptYUdSbUVnVjZhQzFEVGlnQVAB", "/m/02fhdf")
    },
    "hockey": {
        "ko": ("하키", "PLACEHOLDER_ID_HOCKEY", None),
        "en": ("Hockey", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE4wYlhJU0FtVnVLQUFQAQ", "/m/03tmr"),
        "ja": ("ホッケー", "PLACEHOLDER_ID_HOCKEY", None),
        "zh": ("冰球", "PLACEHOLDER_ID_HOCKEY", None)
    },
    "golf": {
        "ko": ("골프", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtdHZLQUFQAQ", "/m/037hz"),
        "en": ("Golf", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtVnVLQUFQAQ", "/m/037hz"),
        "ja": ("ゴルフ", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtcGhLQUFQAQ", "/m/037hz"),
        "zh": ("高尔夫", "PLACEHOLDER_ID_GOLF", None)
    },
    "cricket": {
        "ko": ("크리켓", "PLACEHOLDER_ID_CRICKET", None),
        "en": ("Cricket", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGw0Y0Y8U0FtVnVLQUFQAQ", "/m/09xp"),
        "ja": ("クリケット", "PLACEHOLDER_ID_CRICKET", None),
        "zh": ("板球", "PLACEHOLDER_ID_CRICKET", None)
    },
	
    # 비즈니스 뉴스	
	"business": {
        "ko": ("비즈니스", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB", "/m/09s1f"),
        "en": ("Business", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB", "/m/09s1f"),
        "ja": ("ビジネス", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtcGhHZ0pLVUNnQVAB", "/m/09s1f"),
        "zh": ("商业", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JYcG9MVU5PR2dKRFRpZ0FQAQ", "/m/09s1f")
    },
    "economy": {
        "ko": ("경제", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSnJieWdBUAE", "/m/0gfps3"),
        "en": ("Economy", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSmxiaWdBUAE", "/m/0gfps3"),
        "ja": ("経済", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSnFZU2dBUAE", "/m/0gfps3"),
        "zh": ("金融观察", "CAAqJggKIiBDQkFTRWdvSkwyMHZNR2RtY0hNekVnVjZhQzFEVGlnQVAB", "/m/0gfps3")
    },
    "personal_finance": {
        "ko": ("개인 금융", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSnJieWdBUAE", "/m/01y6cq"),
        "en": ("Personal Finance", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSmxiaWdBUAE", "/m/01y6cq"),
        "ja": ("個人経済", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSnFZU2dBUAE", "/m/01y6cq"),
        "zh": ("投资理财", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREY1Tm1OeEVnVjZhQzFEVGlnQVAB", "/m/01y6cq")
    },
    "finance": {
        "ko": ("금융", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtdHZLQUFQAQ", "/m/02_7t"),
        "en": ("Finance", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtVnVLQUFQAQ", "/m/02_7t"),
        "ja": ("ファイナンス", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtcGhLQUFQAQ", "/m/02_7t"),
        "zh": ("财经", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREpmTjNRU0JYcG9MVU5PS0FBUAE", "/m/02_7t")
    },
    "digital_currency": {
        "ko": ("디지털 통화", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNhMjhvQUFQAQ", "/m/0r8lyw7"),
        "en": ("Digital currencies", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNaVzRvQUFQAQ", "/m/0r8lyw7"),
        "ja": ("デジタル通貨", "PLACEHOLDER_ID_DIGITAL_CURRENCY", None),
        "zh": ("数字货币", "PLACEHOLDER_ID_DIGITAL_CURRENCY", None)
    },
	
	# 기술 뉴스
    "technology": {
        "ko": ("과학/기술", "CAAqKAgKIiJDQkFTRXdvSkwyMHZNR1ptZHpWbUVnSnJieG9DUzFJb0FBUAE", "/m/0ffw5f"),
        "en": ("Technology", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB", "/m/07c1v"),
        "ja": ("科学＆テクノロジー", "CAAqKAgKIiJDQkFTRXdvSkwyMHZNR1ptZHpWbUVnSnFZUm9DU2xBb0FBUAE", "/m/0ffw5f"),
        "zh": ("科技", "PLACEHOLDER_ID_TECHNOLOGY", None)
    },
    "mobile": {
        "ko": ("모바일", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtdHZLQUFQAQ", "/m/050k8"),
        "en": ("Mobile", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtVnVLQUFQAQ", "/m/050k8"),
        "ja": ("モバイル", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtcGhLQUFQAQ", "/m/050k8"),
        "zh": ("移动设备", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFV3YXpnU0JYcG9MVU5PS0FBUAE", "/m/050k8")
    },
	"energy": {
        "ko": ("에너지", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY8U0FtdHZLQUFQAQ", "/m/02mm"),
        "en": ("Energy", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY8U0FtVnVLQUFQAQ", "/m/02mm"),
        "ja": ("エネルギー", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY8U0FtcGhLQUFQAQ", "/m/02mm"),
        "zh": ("能源", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREp0YlY8U0JYcG9MVU5PS0FBUAE", "/m/02mm")
    },
    "games": {
        "ko": ("게임", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtdHZLQUFQAQ", "/m/01mw1"),
        "en": ("Games", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtVnVLQUFQAQ", "/m/01mw1"),
        "ja": ("ゲーム", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtcGhLQUFQAQ", "/m/01mw1"),
        "zh": ("游戏", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZ0ZHpFU0JYcG9MVU5PS0FBUAE", "/m/01mw1")
    },
    "internet_security": {
        "ko": ("인터넷 보안", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSnJieWdBUAE", "/m/03jfnx"),
        "en": ("Internet security", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSmxiaWdBUAE", "/m/03jfnx"),
        "ja": ("インターネット セキュリティ", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSnFZU2dBUAE", "/m/03jfnx"),
        "zh": ("互联网安全", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRE5xWm01NEVnVjZhQzFEVGlnQVAB", "/m/03jfnx")
    },
    "electronics": {
        "ko": ("전자기기", "PLACEHOLDER_ID_ELECTRONICS", None),
        "en": ("Electronics", "PLACEHOLDER_ID_ELECTRONICS", None),
        "ja": ("ガジェット", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp0WmpGdUVnSnFZU2dBUAE", "/m/02mf1n"),
        "zh": ("小工具", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREp0WmpGdUVnVjZhQzFEVGlnQVAB", "/m/02mf1n")
    },
    "virtual_reality": {
        "ko": ("가상 현실", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtdHZLQUFQAQ", "/m/07_ny"),
        "en": ("Virtual Reality", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtVnVLQUFQAQ", "/m/07_ny"),
        "ja": ("バーチャル リアリティ", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtcGhLQUFQAQ", "/m/07_ny"),
        "zh": ("虚拟现实", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGRmYm5rU0JYcG9MVU5PS0FBUAE", "/m/07_ny")
    },
    "robotics": {
        "ko": ("로봇", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNhMjhvQUFQAQ", "/m/02p0t5f"),
        "en": ("Robotics", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNaVzRvQUFQAQ", "/m/02p0t5f"),
        "ja": ("ロボット工学", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNhbUVvQUFQAQ", "/m/02p0t5f"),
        "zh": ("机器人", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNREp3TUhRMVpoSUZlbWd0UTA0b0FBUAE", "/m/02p0t5f")
    },
	
	# 건강 뉴스
    "health": {
        "ko": ("건강", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtdHZLQUFQAQ", "/m/0kt51"),
        "en": ("Health", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ", "/m/0kt51"),
        "ja": ("健康", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtcGhLQUFQAQ", "/m/0kt51"),
        "zh": ("健康", "PLACEHOLDER_ID_HEALTH", None)
    },
    "nutrition": {
        "ko": ("영양", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtdHZLQUFQAQ", "/m/05djc"),
        "en": ("Nutrition", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtVnVLQUFQAQ", "/m/05djc"),
        "ja": ("栄養", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtcGhLQUFQAQ", "/m/05djc"),
        "zh": ("营养", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZrYW1NU0JYcG9MVU5PS0FBUAE", "/m/05djc")
    },
    "public_health": {
        "ko": ("공공보건학", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSnJieWdBUAE", "/m/02cm61"),
        "en": ("Public health", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSmxiaWdBUAE", "/m/02cm61"),
        "ja": ("公衆衛生", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSnFZU2dBUAE", "/m/02cm61"),
        "zh": ("公共卫生", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREpqYlRZeEVnVjZhQzFEVGlnQVAB", "/m/02cm61")
    },
    "mental_health": {
        "ko": ("정신 건강", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSnJieWdBUAE", "/m/03x69g"),
        "en": ("Mental health", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSmxiaWdBUAE", "/m/03x69g"),
        "ja": ("メンタルヘルス", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSnFZU2dBUAE", "/m/03x69g"),
        "zh": ("心理健康", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRE40TmpsbkVnVjZhQzFEVGlnQVAB", "/m/03x69g")
    },
    "medicine": {
        "ko": ("의약품", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtdHZLQUFQAQ", "/m/04sh3"),
        "en": ("Medicine", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtVnVLQUFQAQ", "/m/04sh3"),
        "ja": ("医薬品", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtcGhLQUFQAQ", "/m/04sh3"),
        "zh": ("药物", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFJ6YURNU0JYcG9MVU5PS0FBUAE", "/m/04sh3")
    },
	
	# 과학 뉴스
    "science": {
        "ko": ("과학", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtdHZHZ0pMVWlnQVAB", "/m/06mq7"),
        "en": ("Science", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB", "/m/06mq7"),
        "ja": ("科学", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtcGhLQUFQAQ", "/m/06mq7"),
        "zh": ("科学", "PLACEHOLDER_ID_SCIENCE", None)
    },
    "space": {
        "ko": ("우주", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSnJieWdBUAE", "/m/01833w"),
        "en": ("Space", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSmxiaWdBUAE", "/m/01833w"),
        "ja": ("宇宙", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSnFZU2dBUAE", "/m/01833w"),
        "zh": ("太空", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREU0TXpOM0VnVjZhQzFEVGlnQVAB", "/m/01833w")
    },
    "wildlife": {
        "ko": ("야생동물", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNhMjhvQUFQAQ", "/g/13bb_ts"),
        "en": ("Wildlife", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNaVzRvQUFQAQ", "/g/13bb_ts"),
        "ja": ("野生動物", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNhbUVvQUFQAQ", "/g/13bb_ts"),
        "zh": ("野生动植物", "CAAqKAgKIiJDQkFTRXdvS0wyY3ZNVE5pWWw5MGN4SUZlbWd0UTA0b0FBUAE", "/g/13bb_ts")
    },
    "environment": {
        "ko": ("환경", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSnJieWdBUAE", "/m/02py09"),
        "en": ("Environment", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSmxiaWdBUAE", "/m/02py09"),
        "ja": ("環境", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSnFZU2dBUAE", "/m/02py09"),
        "zh": ("环境", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREp3ZVRBNUVnVjZhQzFEVGlnQVAB", "/m/02py09")
    },
	"neuroscience": {
        "ko": ("신경과학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtdHZLQUFQAQ", "/m/05b6c"),
        "en": ("Neuroscience", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtVnVLQUFQAQ", "/m/05b6c"),
        "ja": ("神経科学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtcGhLQUFQAQ", "/m/05b6c"),
        "zh": ("神经科学", "PLACEHOLDER_ID_NEUROSCIENCE", None)
    },
    "physics": {
        "ko": ("물리학", "PLACEHOLDER_ID_PHYSICS", None),
        "en": ("Physics", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4YW5RU0FtVnVLQUFQAQ", "/m/05qjt"),
        "ja": ("物理学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4YW5RU0FtcGhLQUFQAQ", "/m/05qjt"),
        "zh": ("物理学", "PLACEHOLDER_ID_PHYSICS", None)
    },
    "geography": {
        "ko": ("지리학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtdHZLQUFQAQ", "/m/036hv"),
        "en": ("Geology", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtVnVLQUFQAQ", "/m/036hv"),
        "ja": ("地質学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtcGhLQUFQAQ", "/m/036hv"),
        "zh": ("地理学", "PLACEHOLDER_ID_GEOGRAPHY", None)
    },
    "paleontology": {
        "ko": ("고생물학", "PLACEHOLDER_ID_PALEONTOLOGY", None),
        "en": ("Paleontology", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ5YW13U0FtVnVLQUFQAQ", "/m/05rjl"),
        "ja": ("古生物学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ5YW13U0FtcGhLQUFQAQ", "/m/05rjl"),
        "zh": ("古生物学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZ5YW13U0JYcG9MVU5PS0FBUAE", "/m/05rjl")
    },
    "social_science": {
        "ko": ("사회 과학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp1Tm5BU0FtdHZLQUFQAQ", "/m/06n6p"),
        "en": ("Social sciences", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp1Tm5BU0FtVnVLQUFQAQ", "/m/06n6p"),
        "ja": ("社会科学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp1Tm5BU0FtcGhLQUFQAQ", "/m/06n6p"),
        "zh": ("社会科学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFp1Tm5BU0JYcG9MVU5PS0FBUAE", "/m/06n6p")
    },
	
	# 교육 뉴스
    "education": {
        "ko": ("교육", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbXR2S0FBUAE", "/g/121p6d90"),
        "en": ("Education", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbVZ1S0FBUAE", "/g/121p6d90"),
        "ja": ("教育", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbXBoS0FBUAE", "/g/121p6d90"),
        "zh": ("教育", "CAAqKQgKIiNDQkFTRkFvTEwyY3ZNVEl4Y0Raa09UQVNCWHBvTFVOT0tBQVAB", "/g/121p6d90")
    },
    "job_market": {
        "ko": ("채용정보", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNhMjhvQUFQAQ", "/m/04115t2"),
        "en": ("Jobs", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNaVzRvQUFQAQ", "/m/04115t2"),
        "ja": ("就職", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNhbUVvQUFQAQ", "/m/04115t2"),
        "zh": ("求职", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNRFF4TVRWME1oSUZlbWd0UTA0b0FBUAE", "/m/04115t2")
    },
    "online_education": {
        "ko": ("온라인 교육", "PLACEHOLDER_ID_ONLINE_EDUCATION", None),
        "en": ("Higher education", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtVnVLQUFQAQ", "/m/03r55"),
        "zh": ("在线教育", "PLACEHOLDER_ID_ONLINE_EDUCATION", None)
    },
    "higher_education": {
        "ko": ("고등교육", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtdHZLQUFQAQ", "/m/03r55"),
        "en": ("Higher education", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtVnVLQUFQAQ", "/m/03r55"),
        "ja": ("高等教育", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtcGhLQUFQAQ", "/m/03r55"),
        "zh": ("高等教育", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE55TlRVU0JYcG9MVU5PS0FBUAE", "/m/03r55")
    },
	
	# 라이프스타일 뉴스
    "lifestyle": {
        "ko": ("라이프스타일", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRE55YXpBU0FtdHZHZ0pMVWlnQVAB", "/m/03rk0"),
        "en": ("Lifestyle", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRE55YXpBU0FtVnVHZ0pMVWlnQVAB", "/m/03rk0"),
        "ja": ("ライフスタイル", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRE55YXpBU0FtcGhLQUFQAQ", "/m/03rk0"),
        "zh": ("生活方式", "PLACEHOLDER_ID_LIFESTYLE", None)
    },
    "automotive": {
        "ko": ("차량", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ2EyOG9BQVAB", "/m/0k4j"),
        "en": ("Vehicles", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ1pXNG9BQVAB", "/m/0k4j"),
        "ja": ("乗り物", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ2FtRW9BQVAB", "/m/0k4j"),
        "zh": ("车辆", "CAAqJAgKIh5DQkFTRUFvSEwyMHZNR3MwYWhJRmVtZ3RRMDRvQUFQAQ", "/m/0k4j")
    },
    "art_design": {
        "ko": ("예술/디자인", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ2EyOG9BQVAB", "/m/0jjw"),
        "en": ("Arts & design", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ1pXNG9BQVAB", "/m/0jjw"),
        "ja": ("アート、デザイン", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ2FtRW9BQVAB", "/m/0jjw"),
        "zh": ("艺术与设计", "CAAqJAgKIh5DQkFTRUFvSEwyMHZNR3BxZHhJRmVtZ3RRMDRvQUFQAQ", "/m/0jjw")
    },
    "beauty": {
        "ko": ("미용", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtdHZLQUFQAQ", "/m/01f43"),
        "en": ("Beauty", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtVnVLQUFQAQ", "/m/01f43"),
        "ja": ("美容", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtcGhLQUFQAQ", "/m/01f43"),
        "zh": ("美容时尚", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZtTkRNU0JYcG9MVU5PS0FBUAE", "/m/01f43")
    },
    "food": {
        "ko": ("음식", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtdHZLQUFQAQ", "/m/02wbm"),
        "en": ("Food", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtVnVLQUFQAQ", "/m/02wbm"),
        "ja": ("フード", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtcGhLQUFQAQ", "/m/02wbm"),
        "zh": ("食品", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREozWW0wU0JYcG9MVU5PS0FBUAE", "/m/02wbm")
    },
    "travel": {
        "ko": ("여행", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSnJieWdBUAE", "/m/014dsx"),
        "en": ("Travel", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSmxiaWdBUAE", "/m/014dsx"),
        "ja": ("トラベル", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSnFZU2dBUAE", "/m/014dsx"),
        "zh": ("旅行", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREUwWkhONEVnVjZhQzFEVGlnQVAB", "/m/014dsx")
    },
    "shopping": {
        "ko": ("쇼핑", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtdHZLQUFQAQ", "/m/0hhdb"),
        "en": ("Shopping", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtVnVLQUFQAQ", "/m/0hhdb"),
        "ja": ("ショッピング", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtcGhLQUFQAQ", "/m/0hhdb"),
        "zh": ("购物", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNR2hvWkdJU0JYcG9MVU5PS0FBUAE", "/m/0hhdb")
    },
	"home": {
        "ko": ("홈", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSnJieWdBUAE", "/m/01l0mw"),
        "en": ("Home", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSmxiaWdBUAE", "/m/01l0mw"),
        "ja": ("住居", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSnFZU2dBUAE", "/m/01l0mw"),
        "zh": ("家居", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREZzTUcxM0VnVjZhQzFEVGlnQVAB", "/m/01l0mw")
    },
    "outdoor": {
        "ko": ("야외 활동", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNhMjhvQUFQAQ", "/m/05b0n7k"),
        "en": ("Outdoors", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNaVzRvQUFQAQ", "/m/05b0n7k"),
        "ja": ("アウトドア・アクティビティ", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNhbUVvQUFQAQ", "/m/05b0n7k"),
        "zh": ("户外活动", "PLACEHOLDER_ID_OUTDOOR", None)
    },
    "fashion": {
        "ko": ("패션", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtdHZLQUFQAQ", "/m/032tl"),
        "en": ("Fashion", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtVnVLQUFQAQ", "/m/032tl"),
        "ja": ("ファッション", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtcGhLQUFQAQ", "/m/032tl"),
        "zh": ("时尚", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE15ZEd3U0JYcG9MVU5PS0FBUAE", "/m/032tl")
    }
}

def assign_mid_to_topics(topic_map):
    topic_mid_map = {}
    for topic_keyword, languages in topic_map.items():
        mids = [lang_data[2] for lang_data in languages.values() if lang_data[2] is not None]
        unique_mids = set(mids)
        if len(unique_mids) == 1 and len(mids) >= 2:
            topic_mid_map[topic_keyword] = list(unique_mids)[0]
        elif len(unique_mids) > 1:
            print(f"Warning: Multiple MIDs found for {topic_keyword}: {unique_mids}")
        else:
            print(f"No valid MID found for {topic_keyword}")
    return topic_mid_map

# TOPIC_MAP이 정의된 후에 이 함수를 호출하여 MID 맵을 생성합니다.
TOPIC_MID_MAP = assign_mid_to_topics(TOPIC_MAP)

# 결과 출력 (디버깅 용도)
for topic, mid in TOPIC_MID_MAP.items():
    print(f"{topic}: {mid}")

def force_decode_base64(data):
    try:
        if len(data) % 4 == 1:
            data = data[:-1]
        elif len(data) % 4 == 2:
            data += '=='
        elif len(data) % 4 == 3:
            data += '='
        logger.info(f"디코딩 문자열: {data}")
        decoded_data = base64.b64decode(data)
        return decoded_data, None
    except Exception as e:
        return None, str(e)

def extract_mid_from_topic_id(topic_id):
    logger.info(f"토픽 ID 처리 중: {topic_id}")

    first_decoded_data, first_error = force_decode_base64(topic_id)
    if first_error:
        logger.error(f"첫 번째 디코딩 실패: {first_error}")
        return None

    entity_match = re.search(b'CBA[A-Za-z0-9_-]+', first_decoded_data)
    if not entity_match:
        logger.error("entity_base64 추출 실패")
        return None
    
    entity_base64 = entity_match.group(0).decode('utf-8')
    logger.info(f"Entity base64: {entity_base64}")
    
    second_decoded_data, second_error = force_decode_base64(entity_base64)
    if second_error:
        logger.error(f"두 번째 디코딩 실패: {second_error}")
        return None

    mid_match = re.search(b'/(m|g)/[0-9a-zA-Z_-]+', second_decoded_data)
    if mid_match:
        mid = mid_match.group(0).decode('utf-8')
        logger.info(f"추출된 MID: {mid}")
        return mid
    else:
        logger.error("MID를 찾을 수 없음")
        return None

def find_topic_info(topic_id, topic_map, topic_mid_map, lang):
    # 직접 매칭 시도
    for topic_keyword, languages in topic_map.items():
        for lang_code, lang_data in languages.items():
            if lang_data[1] == topic_id:
                return topic_keyword, lang_data[0], get_topic_category(topic_keyword, lang)

    # MID 추출 및 매칭 시도
    mid = extract_mid_from_topic_id(topic_id)
    if mid:
        for topic_keyword, topic_mid in topic_mid_map.items():
            if topic_mid == mid:
                topic_name = topic_map[topic_keyword].get(lang, topic_map[topic_keyword]['en'])[0]
                category = get_topic_category(topic_keyword, lang)
                return topic_keyword, topic_name, category

    logger.warning(f"토픽 ID {topic_id}에 대한 정보를 찾을 수 없음")
    return None, "Unknown Topic", "General News"

def get_news_prefix(lang):
    """언어에 따라 뉴스 접두어를 반환합니다."""
    news_prefix_map = {
        'bn': "Google সংবাদ",
        'zh': "Google 新闻",
        'en': "Google News",
        'id': "Google Berita",
        'iw': "Google חדשות",
        'ja': "Google ニュース",
        'ar': "Google أخبار",
        'ms': "Google Berita",
        'ko': "Google 뉴스",
        'th': "Google ข่าว",
        'tr': "Google Haberler",
        'vi': "Google Tin tức",
        'ru': "Google Новости",
        'de': "Google Nachrichten",
        'fr': "Google Actualités",
        'es': "Google Noticias",
        'it': "Google Notizie",
        'nl': "Google Nieuws",
        'no': "Google Nyheter",
        'pl': "Google Wiadomości",
        'ro': "Google Știri",
        'hu': "Google Hírek",
        'cs': "Google Zprávy",
        'fi': "Google Uutiset",
        'da': "Google Nyheder",
        'el': "Google Ειδήσεις",
        'sv': "Google Nyheter",
        'pt': "Google Notícias",
        # 추가 언어...
    }
    return news_prefix_map.get(lang, "Google News")

def get_language_from_params(params):
    """URL 파라미터에서 언어 코드를 추출합니다."""
    hl_match = re.search(r'hl=(\w+)', params)
    if hl_match:
        lang = hl_match.group(1).lower()
        return "ko" if lang.startswith("ko") else "en"
    return "en"  # 기본값

def get_topic_info(keyword, lang):
    """토픽 키워드와 언어에 해당하는 정보를 반환합니다."""
    topic_info = TOPIC_MAP.get(keyword, {}).get(lang)
    if topic_info:
        return topic_info
    else:
        # 해당 언어가 없을 경우 en을 기본값으로 사용
        return TOPIC_MAP.get(keyword, {}).get("en", (keyword, ''))

def get_topic_by_id(rss_url_topic):
    """RSS URL에서 토픽 ID를 추출하여 해당하는 토픽 이름과 카테고리를 반환합니다."""
    parsed_url = urlparse(rss_url_topic)
    topic_id = parsed_url.path.split('/')[-1]
    for keyword, lang_data in TOPIC_MAP.items():
        for lang, (name, id) in lang_data.items():
            if id == topic_id:
                return name, keyword
    return None, None

def check_env_variables():
    """환경 변수가 설정되어 있는지 확인합니다."""
    if not DISCORD_WEBHOOK_TOPIC:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_TOPIC")
    if TOPIC_MODE:
        if TOPIC_KEYWORD not in TOPIC_MAP:
            raise ValueError(f"유효하지 않은 토픽 키워드입니다: {TOPIC_KEYWORD}")
        logging.info(f"토픽 모드 활성화: {TOPIC_KEYWORD}, 파라미터: {TOPIC_PARAMS}")
    else:
        if not RSS_URL_TOPIC:
            raise ValueError("토픽 모드가 비활성화되었을 때는 RSS_URL_TOPIC을 설정해야 합니다.")
        logging.info(f"일반 모드 활성화, RSS 피드 URL: {RSS_URL_TOPIC}")

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
                      topic TEXT,
                      related_news TEXT)''')
        logging.info("데이터베이스 초기화 완료")

def is_guid_posted(guid):
    """주어진 GUID가 이미 게시되었는지 확인합니다."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM news_items WHERE guid = ?", (guid,))
        return c.fetchone() is not None

def save_news_item(pub_date, guid, title, link, topic, related_news):
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
        columns = ["pub_date", "guid", "title", "link", "topic", "related_news"]
        values = [pub_date, guid, title, link, topic, related_news]
        
        related_news_items = json.loads(related_news)
        for i, item in enumerate(related_news_items):
            columns.extend([f"related_title_{i+1}", f"related_press_{i+1}", f"related_link_{i+1}"])
            values.extend([item['title'], item['press'], item['link']])
        
        placeholders = ", ".join(["?" for _ in values])
        columns_str = ", ".join(columns)
        
        c.execute(f"INSERT OR REPLACE INTO news_items ({columns_str}) VALUES ({placeholders})", values)
        
        logging.info(f"새 뉴스 항목 저장: {guid}")

def decode_base64_url_part(encoded_str):
    """base64로 인코딩된 문자열을 디코딩"""
    base64_str = encoded_str + "=" * ((4 - len(encoded_str) % 4) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(base64_str)
        decoded_str = decoded_bytes.decode('latin1')
        return decoded_str
    except Exception as e:
        return f"디코딩 중 오류 발생: {e}"

def extract_regular_url(decoded_str):
    """디코딩된 문자열에서 일반 URL 추출"""
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

def fetch_original_url_via_request(google_link, session, max_retries=5):
    """원본 링크를 가져오기 위해 requests를 사용"""
    wait_times = [5, 10, 30, 45, 60]
    for attempt in range(max_retries):
        try:
            response = session.get(google_link, allow_redirects=True, timeout=10)
            final_url = response.url
            logging.info(f"Requests 방식 성공 - Google 링크: {google_link}")
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

def decode_google_news_url(source_url):
    """Google 뉴스 URL을 디코딩하여 원본 URL을 추출합니다."""
    url = urlparse(source_url)
    path = url.path.split('/')
    if url.hostname == "news.google.com" and len(path) > 1 and path[-2] == "articles":
        base64_str = path[-1]
        decoded_str = decode_base64_url_part(base64_str)
        
        # 일반 URL 형태인지 먼저 확인
        regular_url = extract_regular_url(decoded_str)
        if regular_url:
            logging.info(f"일반 링크 추출 성공: {source_url} -> {regular_url}")
            return regular_url
        
        # 일반 URL이 아닌 경우 유튜브 ID 형태인지 확인
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
    ORIGIN_LINK_TOPIC 설정에 따라 동작이 달라집니다:
    - 설정하지 않았거나 True: 오리지널 링크를 가져옵니다.
    - False: 원 링크(구글 링크)를 그대로 사용합니다.
    """
    logging.info(f"ORIGIN_LINK_TOPIC 값 확인: {ORIGIN_LINK_TOPIC}")

    if ORIGIN_LINK_TOPIC:
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
                logging.error(f"원본 URL 가져오기 실패: {e}")
            retries += 1
        
        # 모든 시도가 실패한 경우 원 링크 반환
        logging.warning(f"오리지널 링크 추출 실패, 원 링크 사용: {google_link}")
        return google_link
    else:
        # ORIGIN_LINK_TOPIC가 False인 경우 원 링크를 그대로 반환
        logging.info(f"ORIGIN_LINK_TOPIC가 False, 원 링크 사용: {google_link}")
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

def parse_html_description(html_desc, session):
    """HTML 설명을 파싱하여 뉴스 항목을 추출합니다."""
    soup = BeautifulSoup(html_desc, 'html.parser')
    items = soup.find_all('li')

    news_items = []
    full_content_link = ""
    for item in items:
        if 'Google 뉴스에서 전체 콘텐츠 보기' in item.text or 'View Full Coverage on Google News' in item.text:
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
        news_string += f"▶️ [Google 뉴스에서 전체 콘텐츠 보기]({full_content_link})"

    return news_string

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
    """날짜 필터 문자열을 파싱하여 기준 날짜와 기간을 반환합니다."""
    since_date = None
    until_date = None
    past_date = None

    # since 또는 until 파싱
    since_match = re.search(r'since:(\d{4}-\d{2}-\d{2})', filter_string)
    until_match = re.search(r'until:(\d{4}-\d{2}-\d{2})', filter_string)
    
    if since_match:
        since_date = datetime.strptime(since_match.group(1), '%Y-%m-%d')
    elif until_match:
        until_date = datetime.strptime(until_match.group(1), '%Y-%m-%d')

    # past 파싱
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
    
    if since_date:
        return pub_datetime >= since_date
    if until_date:
        return pub_datetime <= until_date
    
    return True

def get_topic_category(keyword, lang='en'):
    """토픽 키워드에 해당하는 카테고리를 반환합니다."""
    categories = {
        "headlines": {
            "en": "Headlines news",
            "ko": "헤드라인 뉴스",
            "zh": "头条新闻",
            "ja": "ヘッドライン ニュース",
            "de": "Schlagzeilen",
            "fr": "Actualités à la une",
            "es": "Titulares",
            "pt": "Notícias principais",
            "it": "Notizie in primo piano",
            "nl": "Hoofdnieuws",
            "sv": "Nyheter i fokus",
            "ar": "عناوين الأخبار",
            "ru": "Главные новости",
            "keywords": ["headlines", "korea", "us", "japan", "china", "world", "politics"]
        },
        "entertainment": {
            "en": "Entertainment news",
            "ko": "연예 뉴스",
            "zh": "娱乐新闻",
            "ja": "芸能関連のニュース",
            "de": "Nachrichten aus dem Bereich Unterhaltung",
            "fr": "Actus divertissements",
            "es": "Noticias sobre espectáculos",
            "pt": "Notícias de entretenimento",
            "it": "Notizie di intrattenimento",
            "nl": "Entertainmentnieuws",
            "sv": "Underhållningsnyheter",
            "ar": "أخبار ترفيهية",
            "ru": "Развлекательные новости",
            "keywords": ["entertainment", "celebrity", "tv", "music", "movies", "theater"]
        },
        "sports": {
            "en": "Sports news",
            "ko": "스포츠 뉴스",
            "zh": "体育新闻",
            "ja": "スポーツ関連のニュース",
            "de": "Nachrichten aus dem Bereich Sport",
            "fr": "Actus sportives",
            "es": "Noticias sobre deportes",
            "pt": "Notícias de esportes",
            "it": "Notizie sportive",
            "nl": "Sportnieuws",
            "sv": "Sportnyheter",
            "ar": "الأخبار الرياضية",
            "ru": "Спортивные новости",
            "keywords": ["sports", "soccer", "cycling", "motorsports", "tennis", "martial_arts", 
                         "basketball", "baseball", "american_football", "sports_betting", 
                         "water_sports", "hockey", "golf", "cricket", "rugby"]
        },
        "business": {
            "en": "Business news",
            "ko": "비즈니스 뉴스",
            "zh": "财经新闻",
            "ja": "ビジネス関連のニュース",
            "de": "Wirtschaftsmeldungen",
            "fr": "Actus économiques",
            "es": "Noticias de negocios",
            "pt": "Notícias de negócios",
            "it": "Notizie economiche",
            "nl": "Zakennieuws",
            "sv": "Ekonominyheter",
            "ar": "أخبار الأعمال",
            "ru": "Бизнес новости",
            "keywords": ["business", "economy", "personal_finance", "finance", "digital_currency"]
        },
        "technology": {
            "en": "Technology news",
            "ko": "기술 뉴스",
            "zh": "科技新闻",
            "ja": "テクノロジー関連のニュース",
            "de": "Nachrichten aus dem Bereich Technologie",
            "fr": "Actus technologie",
            "es": "Noticias de tecnología",
            "pt": "Notícias de tecnologia",
            "it": "Notizie di tecnologia",
            "nl": "Technologienieuws",
            "sv": "Teknologinyheter",
            "ar": "أخبار التكنولوجيا",
            "ru": "Технологические новости",
            "keywords": ["technology", "mobile", "energy", "games", "internet_security", 
                         "electronics", "virtual_reality", "robotics"]
        },
        "health": {
            "en": "Health news",
            "ko": "건강 뉴스",
            "zh": "健康新闻",
            "ja": "健康関連のニュース",
            "de": "Nachrichten aus dem Bereich Gesundheit",
            "fr": "Actus santé",
            "es": "Noticias sobre salud",
            "pt": "Notícias de saúde",
            "it": "Notizie di salute",
            "nl": "Gezondheidsnieuws",
            "sv": "Hälsonews",
            "ar": "أخبار الصحة",
            "ru": "Новости здоровья",
            "keywords": ["health", "nutrition", "public_health", "mental_health", "medicine"]
        },
        "science": {
            "en": "Science news",
            "ko": "과학 뉴스",
            "zh": "科学新闻",
            "ja": "科学関連のニュース",
            "de": "Nachrichten aus dem Bereich Wissenschaft",
            "fr": "Actus sciences",
            "es": "Noticias de ciencia",
            "pt": "Notícias de ciência",
            "it": "Notizie di scienza",
            "nl": "Wetenschapsnieuws",
            "sv": "Vetenskapsnyheter",
            "ar": "أخبار علمية",
            "ru": "Научные новости",
            "keywords": ["science", "space", "wildlife", "environment", "neuroscience", 
                         "physics", "geography", "paleontology", "social_science"]
        },
        "education": {
            "en": "Education news",
            "ko": "교육 뉴스",
            "zh": "教育新闻",
            "ja": "教育関連のニュース",
            "de": "Nachrichten aus dem Bereich Bildung",
            "fr": "Actus enseignement",
            "es": "Noticias sobre educación",
            "pt": "Notícias de educação",
            "it": "Notizie di istruzione",
            "nl": "Onderwijsnieuws",
            "sv": "Utbildningsnyheter",
            "ar": "أخبار التعليم",
            "ru": "Образовательные новости",
            "keywords": ["education", "job_market", "online_education", "higher_education"]
        },
        "lifestyle": {
            "en": "Lifestyle news",
            "ko": "라이프스타일 뉴스",
            "zh": "生活时尚新闻",
            "ja": "ライフスタイル関連のニュース",
            "de": "Nachrichten aus dem Bereich Lifestyle",
            "fr": "Actus mode de vie",
            "es": "Noticias de estilo de vida",
            "pt": "Notícias de estilo de vida",
            "it": "Notizie di lifestyle",
            "nl": "Lifestyle nieuws",
            "sv": "Livsstilsnyheter",
            "ar": "أخبار أسلوب الحياة",
            "ru": "Новости образа жизни",
            "keywords": ["lifestyle", "automotive", "art_design", "beauty", "food", "travel", 
                         "shopping", "home", "outdoor", "fashion"]
        }
    }
    
    for category, data in categories.items():
        if keyword in data["keywords"]:
            return data[lang]
    
    return "기타 뉴스" if lang == 'ko' else "Other News"

def get_topic_display_name(keyword, lang):
    """토픽 키워드에 해당하는 표시 이름을 반환합니다."""
    topic_info = TOPIC_MAP.get(keyword, {}).get(lang)
    if topic_info:
        return topic_info[0]
    else:
        # 해당 언어가 없을 경우 en을 기본값으로 사용
        return TOPIC_MAP.get(keyword, {}).get("en", (keyword, ''))[0]

def get_country_emoji(country_code):
    """국가 코드를 유니코드 플래그 이모지로 변환합니다."""
    if len(country_code) != 2:
        return ''
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)

def is_korean_params(params):
    """파라미터가 한국어 설정인지 확인합니다."""
    return 'hl=ko' in params and 'gl=KR' in params and 'ceid=KR%3Ako' in params

def main():
    init_db(reset=INITIALIZE_TOPIC)

    session = requests.Session()

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_TOPIC)

    rss_url = RSS_URL_TOPIC
    topic_id = rss_url.split('topics/')[1].split('?')[0]
    
    lang = get_language_from_params(RSS_URL_TOPIC)
    country_code = re.search(r'gl=(\w+)', RSS_URL_TOPIC).group(1)
    country_emoji = get_country_emoji(country_code)
    
    topic_keyword, topic_name, category = find_topic_info(topic_id, TOPIC_MAP, TOPIC_MID_MAP, lang)
    
    news_prefix = get_news_prefix(lang)

    rss_data = fetch_rss_feed(rss_url)
    if rss_data is None:
        logging.error("RSS 데이터를 가져오는 데 실패했습니다.")
        return

    root = ET.fromstring(rss_data)

    news_items = root.findall('.//item')
    if INITIALIZE_TOPIC:
        news_items = sorted(news_items, key=lambda item: parser.parse(item.find('pubDate').text))
    else:
        news_items = list(reversed(news_items))

    for item in news_items:
        guid = item.find('guid').text

        if not INITIALIZE_TOPIC and is_guid_posted(guid):
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
        if not apply_advanced_filter(title, description, ADVANCED_FILTER_TOPIC):
            logging.info(f"고급 검색 필터에 의해 건너뛰어진 뉴스: {title}")
            continue
                
        # gl 파라미터에서 국가 코드 추출
        gl_param = re.search(r'gl=(\w+)', TOPIC_PARAMS)
        country_emoji = get_country_emoji(gl_param.group(1) if gl_param else 'KR')
        
        news_prefix = get_news_prefix(lang)

        # 로깅을 통해 각 값 확인
        logging.info(f"news_prefix: {news_prefix}")
        logging.info(f"category: {category}")
        logging.info(f"topic_name: {topic_name}")
        logging.info(f"country_emoji: {country_emoji}")

        discord_message = f"`{news_prefix} - {category} - {topic_name} {country_emoji}`\n**{title}**\n{link}"
        if description:
            discord_message += f"\n>>> {description}\n\n"
        else:
            discord_message += "\n\n"
        discord_message += f"📅 {formatted_date}"

        send_discord_message(
            DISCORD_WEBHOOK_TOPIC,
            discord_message,
            avatar_url=DISCORD_AVATAR_TOPIC,
            username=DISCORD_USERNAME_TOPIC
        )

        save_news_item(pub_date, guid, title, link, topic_keyword, related_news_json)

        if not INITIALIZE_TOPIC:
            time.sleep(3)

if __name__ == "__main__":
    try:
        check_env_variables()
        main()
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)
    else:
        logging.info("프로그램 정상 종료")