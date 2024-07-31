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
# - "ko": 언어 코드 (ko: 한국어, en: 영어, ja: 일본어, zh: 중국어) / "mid": 식별자
# - 각 언어 코드에 대한 튜플의 구조:
#   ("토픽이름", "토픽ID")
TOPIC_MAP = {
    # 헤드라인 뉴스
    "headlines": {
        "mid": "/m/05jhg",
        "ko": ("헤드라인", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB"),
        "en": ("Headlines", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("ヘッドライン", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtcGhHZ0pLVUNnQVAB"),
        "zh": ("头条", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRFZxYUdjU0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "korea": {
        "mid": "/m/06qd3",
        "ko": ("대한민국", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp4WkRNU0FtdHZLQUFQAQ"),
        "en": ("South Korea", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp4WkRNU0FtVnVLQUFQAQ"),
        "ja": ("大韓民国", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp4WkRNU0FtcGhLQUFQAQ"),
        "zh": ("韩国", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFp4WkRNU0JYcG9MVU5PS0FBUAE")
    },
    "us": {
        "mid": "/m/09c7w0",
        "ko": ("미국", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSnJieWdBUAE"),
        "en": ("U.S.", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSmxiaWdBUAE"),
        "ja": ("米国", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSnFZU2dBUAE"),
        "zh": ("美国", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRGxqTjNjd0VnVjZhQzFEVGlnQVAB")
    },
    "japan": {
        "mid": "/m/03_3d",
        "ko": ("일본", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE5mTTJRU0FtdHZLQUFQAQ"),
        "en": ("Japan", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE5mTTJRU0FtVnVLQUFQAQ"),
        "ja": ("日本", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE5mTTJRU0FtcGhLQUFQAQ"),
        "zh": ("日本", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE5mTTJRU0JYcG9MVU5PS0FBUAE")
    },
    "china": {
        "mid": "/m/0d05w3",
        "ko": ("중국", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR1F3TlhjekVnSnJieWdBUAE"),
        "en": ("China", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR1F3TlhjekVnSmxiaWdBUAE"),
        "ja": ("中華人民共和国", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR1F3TlhjekVnSnFZU2dBUAE"),
        "zh": ("中国", "CAAqJggKIiBDQkFTRWdvSkwyMHZNR1F3TlhjekVnVjZhQzFEVGlnQVAB")
    },
    "world": {
        "mid": "/m/09nm_",
        "ko": ("세계", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB"),
        "en": ("World", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("世界", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtcGhHZ0pLVUNnQVAB"),
        "zh": ("全球", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "politics": {
        "mid": "/m/05qt0",
        "ko": ("정치", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtdHZLQUFQAQ"),
        "en": ("Politics", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtVnVLQUFQAQ"),
        "ja": ("政治", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtcGhLQUFQAQ"),
        "zh": ("政治", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZ4ZERBU0JYcG9MVU5PS0FBUAE")
    },

    # 연예 뉴스
    "entertainment": {
        "mid": "/m/02jjt",
        "ko": ("엔터테인먼트", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtdHZHZ0pMVWlnQVAB"),
        "en": ("Entertainment", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("エンタメ", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtcGhHZ0pLVUNnQVAB"),
        "zh": ("娱乐", "CAAqKggKIiRDQkFTRlFvSUwyMHZNREpxYW5RU0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "celebrity": {
        "mid": "/m/01rfz",
        "ko": ("연예", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtdHZLQUFQAQ"),
        "en": ("Celebrities", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtVnVLQUFQAQ"),
        "ja": ("有名人", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtcGhLQUFQAQ"),
        "zh": ("明星", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZ5Wm5vU0JYcG9MVU5PS0FBUAE")
    },
    "tv": {
        "mid": "/m/07c52",
        "ko": ("TV", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtdHZLQUFQAQ"),
        "en": ("TV", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtVnVLQUFQAQ"),
        "ja": ("テレビ", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtcGhLQUFQAQ"),
        "zh": ("电视", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGRqTlRJU0JYcG9MVU5PS0FBUAE")
    },
    "music": {
        "mid": "/m/04rlf",
        "ko": ("음악", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtdHZLQUFQAQ"),
        "en": ("Music", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtVnVLQUFQAQ"),
        "ja": ("音楽", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtcGhLQUFQAQ"),
        "zh": ("音乐", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFJ5YkdZU0JYcG9MVU5PS0FBUAE")
    },
    "movies": {
        "mid": "/m/02vxn",
        "ko": ("영화", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtdHZLQUFQAQ"),
        "en": ("Movies", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtVnVLQUFQAQ"),
        "ja": ("映画", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtcGhLQUFQAQ"),
        "zh": ("影视", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREoyZUc0U0JYcG9MVU5PS0FBUAE")
    },
    "theater": {
        "mid": "/m/03qsdpk",
        "ko": ("연극", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNhMjhvQUFQAQ"),
        "en": ("Theater", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNaVzRvQUFQAQ"),
        "ja": ("劇場", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNhbUVvQUFQAQ"),
        "zh": ("戏剧", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNRE54YzJSd2F4SUZlbWd0UTA0b0FBUAE")
    },

    # 스포츠 뉴스
    "sports": {
        "mid": "/m/06ntj",
        "ko": ("스포츠", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB"),
        "en": ("Sports", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("スポーツ", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtcGhHZ0pLVUNnQVAB"),
        "zh": ("体育", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "soccer": {
        "mid": "/m/02vx4",
        "ko": ("축구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtdHZLQUFQAQ"),
        "en": ("Soccer", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtVnVLQUFQAQ"),
        "ja": ("サッカー", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtcGhLQUFQAQ"),
        "zh": ("足球", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREoyZURRU0JYcG9MVU5PS0FBUAE")
    },
    "cycling": {
        "mid": "/m/01sgl",
        "ko": ("자전거", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ6WjJ3U0FtdHZLQUFQAQ"),
        "en": ("Cycling", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ6WjJ3U0FtVnVLQUFQAQ"),
        "ja": ("自転車", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ6WjJ3U0FtcGhLQUFQAQ"),
        "zh": ("骑行", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZ6WjJ3U0JYcG9MVU5PS0FBUAE")
    },
    "motorsports": {
        "mid": "/m/0410tth",
        "ko": ("모터스포츠", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TUhSMGFCSUNhMjhvQUFQAQ"),
        "en": ("Motor sports", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TUhSMGFCSUNaVzRvQUFQAQ"),
        "ja": ("モーター スポーツ", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TUhSMGFCSUNhbUVvQUFQAQ"),
        "zh": ("汽车运动", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNRFF4TUhSMGFCSUZlbWd0UTA0b0FBUAE")
    },
    "tennis": {
        "mid": "/m/07bs0",
        "ko": ("테니스", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtdHZLQUFQAQ"),
        "en": ("Tennis", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtVnVLQUFQAQ"),
        "ja": ("テニス", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtcGhLQUFQAQ"),
        "zh": ("网球", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGRpY3pBU0JYcG9MVU5PS0FBUAE")
    },
    "martial_arts": {
        "mid": "/m/05kc29",
        "ko": ("격투기", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSnJieWdBUAE"),
        "en": ("Combat sports", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSmxiaWdBUAE"),
        "ja": ("格闘技", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSnFZU2dBUAE"),
        "zh": ("格斗运动", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRFZyWXpJNUVnVjZhQzFEVGlnQVAB")
    },
    "basketball": {
        "mid": "/m/018w8",
        "ko": ("농구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtdHZLQUFQAQ"),
        "en": ("Basketball", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtVnVLQUFQAQ"),
        "ja": ("バスケットボール", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtcGhLQUFQAQ"),
        "zh": ("NBA", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREU0ZHpnU0JYcG9MVU5PS0FBUAE")
    },
    "baseball": {
        "mid": "/m/018jz",
        "ko": ("야구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtdHZLQUFQAQ"),
        "en": ("Baseball", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtVnVLQUFQAQ"),
        "ja": ("野球", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtcGhLQUFQAQ"),
        "zh": ("棒球", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREU0YW5vU0JYcG9MVU5PS0FBUAE")
    },
    "american_football": {
        "mid": "/m/0jm_",
        "ko": ("미식축구", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3B0WHhJQ2EyOG9BQVAB"),
        "en": ("Football", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3B0WHhJQ1pXNG9BQVAB"),
        "ja": ("アメフト", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3B0WHhJQ2FtRW9BQVAB"),
        "zh": ("美式足球", "CAAqJAgKIh5DQkFTRUFvSEwyMHZNR3B0WHhJRmVtZ3RRMDRvQUFQAQ")
    },
    "sports_betting": {
        "mid": "/m/04t39d",
        "ko": ("스포츠 베팅", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFIwTXpsa0VnSnJieWdBUAE"),
        "en": ("Sports betting", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFIwTXpsa0VnSmxiaWdBUAE"),
        "ja": ("スポーツ賭博", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFIwTXpsa0VnSnFZU2dBUAE"),
        "zh": ("体育博彩", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRFIwTXpsa0VnVjZhQzFEVGlnQVAB")
    },
    "water_sports": {
        "mid": "/m/02fhdf",
        "ko": ("수상 스포츠", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSnJieWdBUAE"),
        "en": ("Water sports", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSmxiaWdBUAE"),
        "ja": ("ウォーター スポーツ", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSnFZU2dBUAE"),
        "zh": ("水上运动", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREptYUdSbUVnVjZhQzFEVGlnQVAB")
    },
    "hockey": {
        "mid": "/m/03tmr",
        "ko": ("하키", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE4wYlhJU0FtdHZLQUFQAQ"),
        "en": ("Hockey", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE4wYlhJU0FtVnVLQUFQAQ"),
        "ja": ("ホッケー", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE4wYlhJU0FtcGhLQUFQAQ"),
        "zh": ("冰球", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE4wYlhJU0JYcG9MVU5PS0FBUAE")
    },
    "golf": {
        "mid": "/m/037hz",
        "ko": ("골프", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtdHZLQUFQAQ"),
        "en": ("Golf", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtVnVLQUFQAQ"),
        "ja": ("ゴルフ", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtcGhLQUFQAQ"),
        "zh": ("高尔夫", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE0zYUhvU0JYcG9MVU5PS0FBUAE")
    },
    "cricket": {
        "mid": "/m/09xp",
        "ko": ("크리켓", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGw0Y0Y4U0FtdHZLQUFQAQ"),
        "en": ("Cricket", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGw0Y0Y8U0FtVnVLQUFQAQ"),
        "ja": ("クリケット", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGw0Y0Y4U0FtcGhLQUFQAQ"),
        "zh": ("板球", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGw0Y0Y4U0JYcG9MVU5PS0FBUAE")
    },

    # 비즈니스 뉴스
    "business": {
        "mid": "/m/09s1f",
        "ko": ("비즈니스", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB"),
        "en": ("Business", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("ビジネス", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtcGhHZ0pLVUNnQVAB"),
        "zh": ("商业", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "economy": {
        "mid": "/m/0gfps3",
        "ko": ("경제", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpmTjNRU0FtdHZLQUFQAQ"),
        "en": ("Economy", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpmTjNRU0FtVnVLQUFQAQ"),
        "ja": ("経済", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpmTjNRU0FtcGhLQUFQAQ"),
        "zh": ("金融观察", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREpmTjNRU0FtdHZHZ0pMVWlnQVAB")
    },
    "personal_finance": {
        "mid": "/m/01y6cq",
        "ko": ("개인 금융", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSnJieWdBUAE"),
        "en": ("Personal Finance", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSmxiaWdBUAE"),
        "ja": ("個人経済", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSnFZU2dBUAE"),
        "zh": ("投资理财", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREY1Tm1OeEVnVjZhQzFEVGlnQVAB")
    },
    "finance": {
        "mid": "/m/02_7t",
        "ko": ("금융", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtdHZLQUFQAQ"),
        "en": ("Finance", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtVnVLQUFQAQ"),
        "ja": ("ファイナンス", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtcGhLQUFQAQ"),
        "zh": ("财经", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREpmTjNRU0JYcG9MVU5PS0FBUAE")
    },
    "digital_currency": {
        "mid": "/m/0r8lyw7",
        "ko": ("디지털 통화", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNhMjhvQUFQAQ"),
        "en": ("Digital currencies", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNaVzRvQUFQAQ"),
        "ja": ("デジタル通貨", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNhbUVvQUFQAQ"),
        "zh": ("数字货币", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNSEk0YkhsM054SUZlbWd0UTA0b0FBUAE")
    },

    # 기술 뉴스
    "technology": {
        "mid": "/m/07c1v",
        "ko": ("기술", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB"),
        "en": ("Technology", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("テクノロジー", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtcGhHZ0pLVUNnQVAB"),
        "zh": ("科技", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRGRqTVhZU0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "science_technology": {
        "mid": "/m/0ffw5f",
        "ko": ("과학/기술", "CAAqKAgKIiJDQkFTRXdvSkwyMHZNR1ptZHpWbUVnSnJieG9DUzFJb0FBUAE"),
        "en": ("Science & technology", "CAAqKAgKIiJDQkFTRXdvSkwyMHZNR1ptZHpWbUVnSmxiaG9DVlZNb0FBUAE"),
        "ja": ("科学＆テクノロジー", "CAAqKAgKIiJDQkFTRXdvSkwyMHZNR1ptZHpWbUVnSnFZUm9DU2xBb0FBUAE"),
        "zh": ("科学技术", "CAAqLAgKIiZDQkFTRmdvSkwyMHZNR1ptZHpWbUVnVjZhQzFEVGhvQ1EwNG9BQVAB")
    },	
    "mobile": {
        "mid": "/m/050k8",
        "ko": ("모바일", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtdHZLQUFQAQ"),
        "en": ("Mobile", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtVnVLQUFQAQ"),
        "ja": ("モバイル", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtcGhLQUFQAQ"),
        "zh": ("移动设备", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFV3YXpnU0JYcG9MVU5PS0FBUAE")
    },
    "energy": {
        "mid": "/m/02mm",
        "ko": ("에너지", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY8U0FtdHZLQUFQAQ"),
        "en": ("Energy", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY8U0FtVnVLQUFQAQ"),
        "ja": ("エネルギー", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY8U0FtcGhLQUFQAQ"),
        "zh": ("能源", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREp0YlY8U0JYcG9MVU5PS0FBUAE")
    },
    "games": {
        "mid": "/m/01mw1",
        "ko": ("게임", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtdHZLQUFQAQ"),
        "en": ("Games", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtVnVLQUFQAQ"),
        "ja": ("ゲーム", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtcGhLQUFQAQ"),
        "zh": ("游戏", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZ0ZHpFU0JYcG9MVU5PS0FBUAE")
    },
    "internet_security": {
        "mid": "/m/03jfnx",
        "ko": ("인터넷 보안", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSnJieWdBUAE"),
        "en": ("Internet security", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSmxiaWdBUAE"),
        "ja": ("インターネット セキュリティ", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSnFZU2dBUAE"),
        "zh": ("互联网安全", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRE5xWm01NEVnVjZhQzFEVGlnQVAB")
    },
    "gadgets": {
        "mid": "/m/02mf1n",
        "ko": ("전자기기", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp0WmpGdUVnSnJieWdBUAE"),
        "en": ("Gadgets", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp0WmpGdUVnSmxiaWdBUAE"),
        "ja": ("ガジェット", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp0WmpGdUVnSnFZU2dBUAE"),
        "zh": ("小工具", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREp0WmpGdUVnVjZhQzFEVGlnQVAB")
    },
    "virtual_reality": {
        "mid": "/m/07_ny",
        "ko": ("가상 현실", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtdHZLQUFQAQ"),
        "en": ("Virtual Reality", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtVnVLQUFQAQ"),
        "ja": ("バーチャル リアリティ", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtcGhLQUFQAQ"),
        "zh": ("虚拟现实", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGRmYm5rU0JYcG9MVU5PS0FBUAE")
    },
    "robotics": {
        "mid": "/m/02p0t5f",
        "ko": ("로봇", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNhMjhvQUFQAQ"),
        "en": ("Robotics", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNaVzRvQUFQAQ"),
        "ja": ("ロボット工学", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNhbUVvQUFQAQ"),
        "zh": ("机器人", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNREp3TUhRMVpoSUZlbWd0UTA0b0FBUAE")
    },
    "ai": {
        "mid": "/m/0mkz",
        "ko": ("인공지능", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNRzFyZWhJQ2EyOG9BQVAB"),
        "en": ("Artificial Intelligence", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNRzFyZWhJQ1pXNG9BQVAB"),
        "ja": ("人工知能", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNRzFyZWhJQ2FtRW9BQVAB"),
        "zh": ("人工智能", "CAAqJAgKIh5DQkFTRUFvSEwyMHZNRzFyZWhJRmVtZ3RRMDRvQUFQAQ")
    },
    "automation": {
        "mid": "/m/017cmr",
        "ko": ("자동화", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUzWTIxeUVnSnJieWdBUAE"),
        "en": ("Automation", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUzWTIxeUVnSmxiaWdBUAE"),
        "ja": ("自動", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUzWTIxeUVnSnFZU2dBUAE"),
        "zh": ("自动化", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREUzWTIxeUVnVjZhQzFEVGlnQVAB")
    },    

    # 건강 뉴스
    "health": {
        "mid": "/m/0kt51",
        "ko": ("건강", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtdHZLQUFQAQ"),
        "en": ("Health", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ"),
        "ja": ("健康", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtcGhLQUFQAQ"),
        "zh": ("健康", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNR3QwTlRFU0JYcG9MVU5PS0FBUAE")
    },
    "nutrition": {
        "mid": "/m/05djc",
        "ko": ("영양", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtdHZLQUFQAQ"),
        "en": ("Nutrition", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtVnVLQUFQAQ"),
        "ja": ("栄養", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtcGhLQUFQAQ"),
        "zh": ("营养", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZrYW1NU0JYcG9MVU5PS0FBUAE")
    },
    "public_health": {
        "mid": "/m/02cm61",
        "ko": ("공공보건학", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSnJieWdBUAE"),
        "en": ("Public health", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSmxiaWdBUAE"),
        "ja": ("公衆衛生", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSnFZU2dBUAE"),
        "zh": ("公共卫生", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREpqYlRZeEVnVjZhQzFEVGlnQVAB")
    },
    "mental_health": {
        "mid": "/m/03x69g",
        "ko": ("정신 건강", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSnJieWdBUAE"),
        "en": ("Mental health", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSmxiaWdBUAE"),
        "ja": ("メンタルヘルス", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSnFZU2dBUAE"),
        "zh": ("心理健康", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRE40TmpsbkVnVjZhQzFEVGlnQVAB")
    },
    "medicine": {
        "mid": "/m/04sh3",
        "ko": ("의약품", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtdHZLQUFQAQ"),
        "en": ("Medicine", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtVnVLQUFQAQ"),
        "ja": ("医薬品", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtcGhLQUFQAQ"),
        "zh": ("药物", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFJ6YURNU0JYcG9MVU5PS0FBUAE")
    },

    # 과학 뉴스
    "science": {
        "mid": "/m/06mq7",
        "ko": ("과학", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtdHZHZ0pMVWlnQVAB"),
        "en": ("Science", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB"),
        "ja": ("科学", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtcGhLQUFQAQ"),
        "zh": ("科学", "CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp0Y1RjU0JYcG9MVU5PR2dKRFRpZ0FQAQ")
    },
    "space": {
        "mid": "/m/01833w",
        "ko": ("우주", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSnJieWdBUAE"),
        "en": ("Space", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSmxiaWdBUAE"),
        "ja": ("宇宙", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSnFZU2dBUAE"),
        "zh": ("太空", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREU0TXpOM0VnVjZhQzFEVGlnQVAB")
    },
    "wildlife": {
        "mid": "/g/13bb_ts",
        "ko": ("야생동물", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNhMjhvQUFQAQ"),
        "en": ("Wildlife", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNaVzRvQUFQAQ"),
        "ja": ("野生動物", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNhbUVvQUFQAQ"),
        "zh": ("野生动植物", "CAAqKAgKIiJDQkFTRXdvS0wyY3ZNVE5pWWw5MGN4SUZlbWd0UTA0b0FBUAE")
    },
    "environment": {
        "mid": "/m/02py09",
        "ko": ("환경", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSnJieWdBUAE"),
        "en": ("Environment", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSmxiaWdBUAE"),
        "ja": ("環境", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSnFZU2dBUAE"),
        "zh": ("环境", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREp3ZVRBNUVnVjZhQzFEVGlnQVAB")
    },
    "neuroscience": {
        "mid": "/m/05b6c",
        "ko": ("신경과학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtdHZLQUFQAQ"),
        "en": ("Neuroscience", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtVnVLQUFQAQ"),
        "ja": ("神経科学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtcGhLQUFQAQ"),
        "zh": ("神经学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZpTm1NU0JYcG9MVU5PS0FBUAE")
    },
    "physics": {
        "mid": "/m/05qjt",
        "ko": ("물리학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4YW5RU0FtdHZLQUFQAQ"),
        "en": ("Physics", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4YW5RU0FtVnVLQUFQAQ"),
        "ja": ("物理学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4YW5RU0FtcGhLQUFQAQ"),
        "zh": ("物理学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZ4YW5RU0JYcG9MVU5PS0FBUAE")
    },
    "geography": {
        "mid": "/m/036hv",
        "ko": ("지리학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtdHZLQUFQAQ"),
        "en": ("Geology", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtVnVLQUFQAQ"),
        "ja": ("地質学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtcGhLQUFQAQ"),
        "zh": ("地质学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE0yYUhZU0JYcG9MVU5PS0FBUAE")
    },
    "paleontology": {
        "mid": "/m/05rjl",
        "ko": ("고생물학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ5YW13U0FtdHZLQUFQAQ",),
        "en": ("Paleontology", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ5YW13U0FtVnVLQUFQAQ"),
        "ja": ("古生物学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ5YW13U0FtcGhLQUFQAQ"),
        "zh": ("古生物学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRFZ5YW13U0JYcG9MVU5PS0FBUAE")
    },
    "social_science": {
        "mid": "/m/06n6p",
        "ko": ("사회 과학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtdHZLQUFQAQ"),
        "en": ("Social sciences", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtVnVLQUFQAQ"),
        "ja": ("社会科学", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtcGhLQUFQAQ"),
        "zh": ("社会科学", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE0zYUhvU0JYcG9MVU5PS0FBUAE")
    },

    # 교육 뉴스
    "education": {
        "mid": "/g/121p6d90",
        "ko": ("교육", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbXR2S0FBUAE"),
        "en": ("Education", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbVZ1S0FBUAE"),
        "ja": ("教育", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbXBoS0FBUAE"),
        "zh": ("教育", "CAAqKQgKIiNDQkFTRkFvTEwyY3ZNVEl4Y0Raa09UQVNCWHBvTFVOT0tBQVAB")
    },
    "job_market": {
        "mid": "/m/04115t2",
        "ko": ("채용정보", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNhMjhvQUFQAQ"),
        "en": ("Jobs", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNaVzRvQUFQAQ"),
        "ja": ("就職", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNhbUVvQUFQAQ"),
        "zh": ("求职", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNRFF4TVRWME1oSUZlbWd0UTA0b0FBUAE")
    },
    "online_education": {
        "mid": "/m/03r55",
        "ko": ("온라인 교육", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFYwYW5KaUVnSnJieWdBUAE"),
        "en": ("Higher education", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtVnVLQUFQAQ"),
        "zh": ("在线教育", "CAAqJggKIiBDQkFTRWdvSkwyMHZNRFYwYW5KaUVnVjZhQzFEVGlnQVAB")
    },
    "higher_education": {
        "mid": "/m/03r55",
        "ko": ("고등교육", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtdHZLQUFQAQ"),
        "en": ("Higher education", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtVnVLQUFQAQ"),
        "ja": ("高等教育", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtcGhLQUFQAQ"),
        "zh": ("高等教育", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE55TlRVU0JYcG9MVU5PS0FBUAE")
    },

    # 라이프스타일 뉴스
    "automotive": {
        "mid": "/m/0k4j",
        "ko": ("차량", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ2EyOG9BQVAB"),
        "en": ("Vehicles", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ1pXNG9BQVAB"),
        "ja": ("乗り物", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ2FtRW9BQVAB"),
        "zh": ("车辆", "CAAqJAgKIh5DQkFTRUFvSEwyMHZNR3MwYWhJRmVtZ3RRMDRvQUFQAQ")
    },
    "art_design": {
        "mid": "/m/0jjw",
        "ko": ("예술/디자인", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ2EyOG9BQVAB"),
        "en": ("Arts & design", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ1pXNG9BQVAB"),
        "ja": ("アート、デザイン", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ2FtRW9BQVAB"),
        "zh": ("艺术与设计", "CAAqJAgKIh5DQkFTRUFvSEwyMHZNR3BxZHhJRmVtZ3RRMDRvQUFQAQ")
    },
    "beauty": {
        "mid": "/m/01f43",
        "ko": ("미용", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtdHZLQUFQAQ"),
        "en": ("Beauty", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtVnVLQUFQAQ"),
        "ja": ("美容", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtcGhLQUFQAQ"),
        "zh": ("美容时尚", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREZtTkRNU0JYcG9MVU5PS0FBUAE")
    },
    "food": {
        "mid": "/m/02wbm",
        "ko": ("음식", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtdHZLQUFQAQ"),
        "en": ("Food", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtVnVLQUFQAQ"),
        "ja": ("フード", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtcGhLQUFQAQ"),
        "zh": ("食品", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNREozWW0wU0JYcG9MVU5PS0FBUAE")
    },
    "travel": {
        "mid": "/m/014dsx",
        "ko": ("여행", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSnJieWdBUAE"),
        "en": ("Travel", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSmxiaWdBUAE"),
        "ja": ("トラベル", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSnFZU2dBUAE"),
        "zh": ("旅行", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREUwWkhONEVnVjZhQzFEVGlnQVAB")
    },
    "shopping": {
        "mid": "/m/0hhdb",
        "ko": ("쇼핑", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtdHZLQUFQAQ"),
        "en": ("Shopping", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtVnVLQUFQAQ"),
        "ja": ("ショッピング", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtcGhLQUFQAQ"),
        "zh": ("购物", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNR2hvWkdJU0JYcG9MVU5PS0FBUAE")
    },
    "home": {
        "mid": "/m/01l0mw",
        "ko": ("홈", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSnJieWdBUAE"),
        "en": ("Home", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSmxiaWdBUAE"),
        "ja": ("住居", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSnFZU2dBUAE"),
        "zh": ("家居", "CAAqJggKIiBDQkFTRWdvSkwyMHZNREZzTUcxM0VnVjZhQzFEVGlnQVAB")
    },
    "outdoor": {
        "mid": "/m/05b0n7k",
        "ko": ("야외 활동", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNhMjhvQUFQAQ"),
        "en": ("Outdoors", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNaVzRvQUFQAQ"),
        "ja": ("アウトドア・アクティビティ", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNhbUVvQUFQAQ"),
        "zh": ("户外休闲", "CAAqKAgKIiJDQkFTRXdvS0wyMHZNRFZpTUc0M2F4SUZlbWd0UTA0b0FBUAE")
    },
    "fashion": {
        "mid": "/m/032tl",
        "ko": ("패션", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtdHZLQUFQAQ"),
        "en": ("Fashion", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtVnVLQUFQAQ"),
        "ja": ("ファッション", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtcGhLQUFQAQ"),
        "zh": ("时尚", "CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE15ZEd3U0JYcG9MVU5PS0FBUAE")
    }
}

TOPIC_CATEGORY = {
    'ko': "주제",
    'en': "Topics",
    'ja': "トピック",
    'zh': "主题"
}

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

import requests
import base64
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote

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

            # 유니코드 문자 처리
            decoded_str = decoded_str.replace("\\u0026", "&").replace("\\u003d", "=")
            
            # URL 추출 및 정리
            url_match = re.search(r'(https?://[^\s]+)', decoded_str)
            if url_match:
                extracted_url = url_match.group(1)
                return clean_url(extracted_url)

        except Exception as e:
            logging.error(f"새로운 디코딩 방식 실패: {e}")
        
        # 기존 방식 시도 (유튜브 링크 포함)
        try:
            decoded_str = decode_base64_url_part(base64_str)
            youtube_id = extract_youtube_id(decoded_str)
            if youtube_id:
                return f"https://www.youtube.com/watch?v={youtube_id}"

            url_match = re.search(r'(https?://[^\s]+)', decoded_str)
            if url_match:
                return clean_url(url_match.group(1))
        except Exception as e:
            logging.error(f"기존 디코딩 방식 실패: {e}")

    return clean_url(source_url)  # 디코딩 실패 시 원본 URL 정리 후 반환

def clean_url(url):
    """URL을 정리하는 함수"""
    parsed_url = urlparse(url)
    
    # MSN 링크 https로 변환
    if parsed_url.netloc.endswith('msn.com'):
        parsed_url = parsed_url._replace(scheme='https')
    
    # 쿼리 파라미터 정리
    query_params = parse_qs(parsed_url.query)
    cleaned_params = {k: v[0] for k, v in query_params.items() if k in ['id', 'article']}
    cleaned_query = urlencode(cleaned_params)
    
    # 최종 URL 생성
    final_url = urlunparse(parsed_url._replace(query=cleaned_query))
    return unquote(final_url)  # URL 디코딩

def get_original_url(google_link, session, max_retries=5):
    logging.info(f"ORIGIN_LINK_TOPIC 값 확인: {ORIGIN_LINK_TOPIC}")

    if ORIGIN_LINK_TOPIC:
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
        logging.info(f"ORIGIN_LINK_TOPIC가 False, 원 링크 사용: {google_link}")
        return clean_url(google_link)

def fetch_rss_feed(url):
    """RSS 피드를 가져옵니다."""
    response = requests.get(url)
    return response.content

def parse_rss_title(rss_data):
    root = ET.fromstring(rss_data)
    title = root.find('.//channel/title').text
    topic_name = title.split(' - ')[0]
    return topic_name

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
            "keywords": ["technology", "science_technology", "mobile", "energy", "games", "internet_security", 
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

    lang = get_language_from_params(TOPIC_PARAMS)

    if TOPIC_MODE:
        topic_name, topic_id = get_topic_info(TOPIC_KEYWORD, lang)
        rss_url = f"https://news.google.com/rss/topics/{topic_id}"
        if TOPIC_PARAMS:
            rss_url += TOPIC_PARAMS
        category = get_topic_category(TOPIC_KEYWORD, lang)
    else:
        rss_url = RSS_URL_TOPIC
        topic_name, topic_keyword = get_topic_by_id(rss_url)
        if topic_keyword is None:
            category = TOPIC_CATEGORY.get(lang, "Topics")
        else:
            category = get_topic_category(topic_keyword, lang)

    rss_data = fetch_rss_feed(rss_url)
    if rss_data is None:
        logging.error("RSS 데이터를 가져오는 데 실패했습니다.")
        return

    if not TOPIC_MODE and topic_name is None:
        topic_name = parse_rss_title(rss_data)

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

        save_news_item(pub_date, guid, title, link, TOPIC_KEYWORD if TOPIC_MODE else "general", related_news_json)

        if not INITIALIZE_TOPIC:
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