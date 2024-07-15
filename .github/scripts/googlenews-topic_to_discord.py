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
from urllib.parse import urlparse, parse_qs
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
TOPIC_MAP = {
    # 헤드라인 뉴스
    "headlines": {
        "ko-KR": ("헤드라인", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("Headlines", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB")
    },
    "korea": {
        "ko-KR": ("대한민국", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp4WkRNU0FtdHZLQUFQAQ")
    },
    "us": {
        "en-US": ("U.S.", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSmxiaWdBUAE")
    },
    "world": {
        "ko-KR": ("세계", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("World", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB")
    },
    "politics": {
        "ko-KR": ("정치", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtdHZLQUFQAQ"),
        "en-US": ("Politics", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtVnVLQUFQAQ")
    },
    
    # 연예 뉴스
    "entertainment": {
        "ko-KR": ("엔터테인먼트", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("Entertainment", "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB")
    },
    "celebrity": {
        "ko-KR": ("연예", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtdHZLQUFQAQ"),
        "en-US": ("Celebrities", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ5Wm5vU0FtVnVLQUFQAQ")
    },
    "tv": {
        "ko-KR": ("TV", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtdHZLQUFQAQ"),
        "en-US": ("TV", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRqTlRJU0FtVnVLQUFQAQ")
    },
    "music": {
        "ko-KR": ("음악", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtdHZLQUFQAQ"),
        "en-US": ("Music", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ5YkdZU0FtVnVLQUFQAQ")
    },
    "movies": {
        "ko-KR": ("영화", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtdHZLQUFQAQ"),
        "en-US": ("Movies", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZUc0U0FtVnVLQUFQAQ")
    },
    "theater": {
        "ko-KR": ("연극", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNhMjhvQUFQAQ"),
        "en-US": ("Theater", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRE54YzJSd2F4SUNaVzRvQUFQAQ")
    },
    
    # 스포츠 뉴스
    "sports": {
        "ko-KR": ("스포츠", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("Sports", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB")
    },
    "soccer": {
        "ko-KR": ("축구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtdHZLQUFQAQ"),
        "en-US": ("Soccer", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREoyZURRU0FtVnVLQUFQAQ")
    },
    "cycling": {
        "ko-KR": ("자전거", "PLACEHOLDER_ID_CYCLING"),
        "en-US": ("Cycling", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ6WjJ3U0FtVnVLQUFQAQ")
    },
    "motorsports": {
        "ko-KR": ("모터스포츠", "PLACEHOLDER_ID_MOTORSPORTS"),
        "en-US": ("Motor sports", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TUhSMGFCSUNaVzRvQUFQAQ")
    },
    "tennis": {
        "ko-KR": ("테니스", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtdHZLQUFQAQ"),
        "en-US": ("Tennis", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRpY3pBU0FtVnVLQUFQAQ")
    },
    "martial_arts": {
        "ko-KR": ("격투기", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSnJieWdBUAE"),
        "en-US": ("Combat sports", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFZyWXpJNUVnSmxiaWdBUAE")
    },
    "basketball": {
        "ko-KR": ("농구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtdHZLQUFQAQ"),
        "en-US": ("Basketball", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0ZHpnU0FtVnVLQUFQAQ")
    },
    "baseball": {
        "ko-KR": ("야구", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtdHZLQUFQAQ"),
        "en-US": ("Baseball", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREU0YW5vU0FtVnVLQUFQAQ")
    },
    "american_football": {
        "ko-KR": ("미식축구", "PLACEHOLDER_ID_AMERICAN_FOOTBALL"),
        "en-US": ("Football", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3B0WHhJQ1pXNG9BQVAB")
    },
    "sports_betting": {
        "ko-KR": ("스포츠 베팅", "PLACEHOLDER_ID_SPORTS_BETTING"),
        "en-US": ("Sports betting", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRFIwTXpsa0VnSmxiaWdBUAE")
    },
    "water_sports": {
        "ko-KR": ("수상 스포츠", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSnJieWdBUAE"),
        "en-US": ("Water sports", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREptYUdSbUVnSmxiaWdBUAE")
    },
    "hockey": {
        "ko-KR": ("하키", "PLACEHOLDER_ID_HOCKEY"),
        "en-US": ("Hockey", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE4wYlhJU0FtVnVLQUFQAQ")
    },
    "golf": {
        "ko-KR": ("골프", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtdHZLQUFQAQ"),
        "en-US": ("Golf", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0zYUhvU0FtVnVLQUFQAQ")
    },
    "cricket": {
        "ko-KR": ("크리켓", "PLACEHOLDER_ID_CRICKET"),
        "en-US": ("Cricket", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGw0Y0Y4U0FtVnVLQUFQAQ")
    },
    "rugby": {
        "ko-KR": ("럭비", "PLACEHOLDER_ID_RUGBY"),
        "en-US": ("Rugby", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFppY2pnU0FtVnVLQUFQAQ")
    },
    
    # 비즈니스 뉴스
    "business": {
        "ko-KR": ("비즈니스", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("Business", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB")
    },
    "economy": {
        "ko-KR": ("경제", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSnJieWdBUAE"),
        "en-US": ("Economy", "CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSmxiaWdBUAE")
    },
    "personal_finance": {
        "ko-KR": ("개인 금융", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSnJieWdBUAE"),
        "en-US": ("Personal Finance", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREY1Tm1OeEVnSmxiaWdBUAE")
    },
    "finance": {
        "ko-KR": ("금융", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtdHZLQUFQAQ"),
        "en-US": ("Finance", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpmTjNRU0FtVnVLQUFQAQ")
    },
    "digital_currency": {
        "ko-KR": ("디지털 통화", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNhMjhvQUFQAQ"),
        "en-US": ("Digital currencies", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNSEk0YkhsM054SUNaVzRvQUFQAQ")
    },
    
    # 기술 뉴스
    "technology": {
        "ko-KR": ("과학/기술", "CAAqKAgKIiJDQkFTRXdvSkwyMHZNR1ptZHpWbUVnSnJieG9DUzFJb0FBUAE"),
        "en-US": ("Technology", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB")
    },
    "mobile": {
        "ko-KR": ("모바일", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtdHZLQUFQAQ"),
        "en-US": ("Mobile", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFV3YXpnU0FtVnVLQUFQAQ")
    },
    "energy": {
        "ko-KR": ("에너지", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY4U0FtdHZLQUFQAQ"),
        "en-US": ("Energy", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREp0YlY4U0FtVnVLQUFQAQ")
    },
    "games": {
        "ko-KR": ("게임", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtdHZLQUFQAQ"),
        "en-US": ("Games", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZ0ZHpFU0FtVnVLQUFQAQ")
    },
    "internet_security": {
        "ko-KR": ("인터넷 보안", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSnJieWdBUAE"),
        "en-US": ("Internet security", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSmxiaWdBUAE")
    },
    "electronics": {
        "ko-KR": ("전자기기", "PLACEHOLDER_ID_ELECTRONICS"),
        "en-US": ("Electronics", "PLACEHOLDER_ID_ELECTRONICS")
    },
    "virtual_reality": {
        "ko-KR": ("가상 현실", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtdHZLQUFQAQ"),
        "en-US": ("Virtual Reality", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGRmYm5rU0FtVnVLQUFQAQ")
    },
    "robotics": {
        "ko-KR": ("로봇", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNhMjhvQUFQAQ"),
        "en-US": ("Robotics", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNREp3TUhRMVpoSUNaVzRvQUFQAQ")
    },
    
    # 건강 뉴스
    "health": {
        "ko-KR": ("건강", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtdHZLQUFQAQ"),
        "en-US": ("Health", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ")
    },
    "nutrition": {
        "ko-KR": ("영양", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtdHZLQUFQAQ"),
        "en-US": ("Nutrition", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZrYW1NU0FtVnVLQUFQAQ")
    },
    "public_health": {
        "ko-KR": ("공공보건학", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSnJieWdBUAE"),
        "en-US": ("Public health", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREpqYlRZeEVnSmxiaWdBUAE")
    },
    "mental_health": {
        "ko-KR": ("정신 건강", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSnJieWdBUAE"),
        "en-US": ("Mental health", "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE40TmpsbkVnSmxiaWdBUAE")
    },
    "medicine": {
        "ko-KR": ("의약품", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtdHZLQUFQAQ"),
        "en-US": ("Medicine", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFJ6YURNU0FtVnVLQUFQAQ")
    },
    
    # 과학 뉴스
    "science": {
        "ko-KR": ("과학", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("Science", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB")
    },
    "space": {
        "ko-KR": ("우주", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSnJieWdBUAE"),
        "en-US": ("Space", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREU0TXpOM0VnSmxiaWdBUAE")
    },
    "wildlife": {
        "ko-KR": ("야생동물", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNhMjhvQUFQAQ"),
        "en-US": ("Wildlife", "CAAqJAgKIh5DQkFTRUFvS0wyY3ZNVE5pWWw5MGN4SUNaVzRvQUFQAQ")
    },
    "environment": {
        "ko-KR": ("환경", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSnJieWdBUAE"),
        "en-US": ("Environment", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREp3ZVRBNUVnSmxiaWdBUAE")
    },
    "neuroscience": {
        "ko-KR": ("신경과학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtdHZLQUFQAQ"),
        "en-US": ("Neuroscience", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZpTm1NU0FtVnVLQUFQAQ")
    },
    "physics": {
        "ko-KR": ("물리학", "PLACEHOLDER_ID_PHYSICS"),
        "en-US": ("Physics", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4YW5RU0FtVnVLQUFQAQ")
    },
    "geography": {
        "ko-KR": ("지리학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtdHZLQUFQAQ"),
        "en-US": ("Geology", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE0yYUhZU0FtVnVLQUFQAQ")
    },
    "paleontology": {
        "ko-KR": ("고생물학", "PLACEHOLDER_ID_PALEONTOLOGY"),
        "en-US": ("Paleontology", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ5YW13U0FtVnVLQUFQAQ")
    },
    "social_science": {
        "ko-KR": ("사회 과학", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp1Tm5BU0FtdHZLQUFQAQ"),
        "en-US": ("Social sciences", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp1Tm5BU0FtVnVLQUFQAQ")
    },
    
    # 교육 뉴스
    "education": {
        "ko-KR": ("교육", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbXR2S0FBUAE"),
        "en-US": ("Education", "CAAqJQgKIh9DQkFTRVFvTEwyY3ZNVEl4Y0Raa09UQVNBbVZ1S0FBUAE")
    },
    "job_market": {
        "ko-KR": ("채용정보", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNhMjhvQUFQAQ"),
        "en-US": ("Jobs", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFF4TVRWME1oSUNaVzRvQUFQAQ")
    },
    "online_education": {
        "ko-KR": ("온라인 교육", "PLACEHOLDER_ID_ONLINE_EDUCATION"),
        "en-US": ("Higher education", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtVnVLQUFQAQ")
    },
    "higher_education": {
        "ko-KR": ("고등교육", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtdHZLQUFQAQ"),
        "en-US": ("Higher education", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE55TlRVU0FtVnVLQUFQAQ")
    },
    
    # 라이프스타일 뉴스
    "lifestyle": {
        "ko-KR": ("라이프스타일", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRE55YXpBU0FtdHZHZ0pMVWlnQVAB"),
        "en-US": ("Lifestyle", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRE55YXpBU0FtVnVHZ0pMVWlnQVAB")
    },
    "automotive": {
        "ko-KR": ("차량", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ2EyOG9BQVAB"),
        "en-US": ("Vehicles", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3MwYWhJQ1pXNG9BQVAB")
    },
    "art_design": {
        "ko-KR": ("예술/디자인", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ2EyOG9BQVAB"),
        "en-US": ("Arts & design", "CAAqIAgKIhpDQkFTRFFvSEwyMHZNR3BxZHhJQ1pXNG9BQVAB")
    },
    "beauty": {
        "ko-KR": ("미용", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtdHZLQUFQAQ"),
        "en-US": ("Beauty", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREZtTkRNU0FtVnVLQUFQAQ")
    },
    "food": {
        "ko-KR": ("음식", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtdHZLQUFQAQ"),
        "en-US": ("Food", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNREozWW0wU0FtVnVLQUFQAQ")
    },
    "travel": {
        "ko-KR": ("여행", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSnJieWdBUAE"),
        "en-US": ("Travel", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREUwWkhONEVnSmxiaWdBUAE")
    },
    "shopping": {
        "ko-KR": ("쇼핑", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtdHZLQUFQAQ"),
        "en-US": ("Shopping", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2hvWkdJU0FtVnVLQUFQAQ")
    },
    "home": {
        "ko-KR": ("홈", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSnJieWdBUAE"),
        "en-US": ("Home", "CAAqIggKIhxDQkFTRHdvSkwyMHZNREZzTUcxM0VnSmxiaWdBUAE")
    },
    "outdoor": {
        "ko-KR": ("야외 활동", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNhMjhvQUFQAQ"),
        "en-US": ("Outdoors", "CAAqJAgKIh5DQkFTRUFvS0wyMHZNRFZpTUc0M2F4SUNaVzRvQUFQAQ")
    },
    "fashion": {
        "ko-KR": ("패션", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtdHZLQUFQAQ"),
        "en-US": ("Fashion", "CAAqIQgKIhtDQkFTRGdvSUwyMHZNRE15ZEd3U0FtVnVLQUFQAQ")
    }
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

def check_env_variables():
    """환경 변수가 설정되어 있는지 확인합니다."""
    if not DISCORD_WEBHOOK_TOPIC:
        raise ValueError("환경 변수가 설정되지 않았습니다: DISCORD_WEBHOOK_TOPIC")
    if TOPIC_MODE:
        if TOPIC_KEYWORD not in TOPIC_MAP:
            raise ValueError(f"유효하지 않은 토픽 키워드입니다: {TOPIC_KEYWORD}")
        hl, gl, ceid = parse_topic_params(TOPIC_PARAMS)
        logging.info(f"토픽 모드 활성화: {TOPIC_KEYWORD}, 파라미터: {TOPIC_PARAMS}")
    else:
        if not RSS_URL_TOPIC:
            raise ValueError("토픽 모드가 비활성화되었을 때는 RSS_URL_TOPIC을 설정해야 합니다.")
        hl, gl, ceid = parse_topic_params(RSS_URL_TOPIC)
        logging.info(f"일반 모드 활성화, RSS 피드 URL: {RSS_URL_TOPIC}")
    
    return hl, gl, ceid

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

def extract_topic_id(url):
    """RSS URL에서 토픽 ID를 추출합니다."""
    parsed_url = urlparse(url)
    path_parts = parsed_url.path.split('/')
    if 'topics' in path_parts:
        return path_parts[path_parts.index('topics') + 1]
    return None

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
            "keywords": ["headlines", "korea", "world", "politics"]
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
    
    lang_key = 'ko' if lang.startswith('ko') else 'en'
    topic_map_lang_key = 'ko-KR' if lang.startswith('ko') else 'en-US'
    
    logging.info(f"get_topic_category called with keyword: {keyword}, lang: {lang}")
    
    for category, data in categories.items():
        if keyword in data["keywords"]:
            return data[lang_key]
    
    # TOPIC_MAP에서 ID로 검색
    for topic, topic_data in TOPIC_MAP.items():
        if keyword == topic or keyword == topic_data[topic_map_lang_key][1]:
            # topic에 해당하는 카테고리 찾기
            for category, data in categories.items():
                if topic in data["keywords"]:
                    return data[lang_key]
    
    logging.warning(f"No matching category found for keyword: {keyword}")
    
    return "기타 뉴스" if lang_key == 'ko' else "Other News"

def get_topic_display_name(keyword_or_id, lang):
    """토픽 키워드 또는 ID에 해당하는 표시 이름을 반환합니다."""
    lang_key = 'ko-KR' if lang.startswith('ko') else 'en-US'
    for topic, data in TOPIC_MAP.items():
        if keyword_or_id == topic or keyword_or_id == data[lang_key][1]:
            return data[lang_key][0]
    return keyword_or_id  # 일치하는 항목이 없으면 원래 값을 반환

def get_country_emoji(country_code):
    """국가 코드를 유니코드 플래그 이모지로 변환합니다."""
    if len(country_code) != 2:
        return ''
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)

def parse_topic_params(url):
    """URL에서 언어, 국가 코드, ceid 값을 추출합니다."""
    params = urlparse(url).query
    parsed_params = parse_qs(params)
    hl = parsed_params.get('hl', ['ko'])[0]
    gl = parsed_params.get('gl', ['KR'])[0]
    ceid = parsed_params.get('ceid', [f'{gl}:{hl}'])[0]
    return hl, gl, ceid

def is_korean_params(params):
    """파라미터가 한국어 설정인지 확인합니다."""
    return 'hl=ko' in params and 'gl=KR' in params and 'ceid=KR%3Ako' in params

def main():
    init_db(reset=INITIALIZE_TOPIC)

    session = requests.Session()

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_TOPIC)

    # 로깅 추가
    logging.info(f"TOPIC_MODE: {TOPIC_MODE}")
    logging.info(f"TOPIC_KEYWORD: {TOPIC_KEYWORD}")

    if TOPIC_MODE:
        try:
            topic_id = TOPIC_MAP[TOPIC_KEYWORD]['ko-KR'][1]  # 'ko-KR' 또는 'en-US' 선택
        except KeyError:
            logging.error(f"Invalid TOPIC_KEYWORD: {TOPIC_KEYWORD}")
            return
        rss_url = f"https://news.google.com/rss/topics/{topic_id}"
        if TOPIC_PARAMS:
            rss_url += TOPIC_PARAMS
    else:
        rss_url = RSS_URL_TOPIC
        topic_id = extract_topic_id(rss_url)

    logging.info(f"RSS URL: {rss_url}")
    logging.info(f"Topic ID: {topic_id}")

    hl, gl, ceid = parse_topic_params(rss_url)
    logging.info(f"Parsed parameters - hl: {hl}, gl: {gl}, ceid: {ceid}")

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

        # 초기화 모드가 아닌 경우에만 중복 검사
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

        news_prefix = get_news_prefix(hl)
        
        if TOPIC_MODE or topic_id:
            category_input = TOPIC_KEYWORD if TOPIC_MODE else topic_id
            logging.info(f"Calling get_topic_category with: {category_input}, {hl}")
            category = get_topic_category(category_input, hl)
            topic_name = get_topic_display_name(category_input, hl)
        else:
            category = "일반 뉴스" if hl.startswith('ko') else "General news"
            topic_name = "RSS 피드" if hl.startswith('ko') else "RSS Feed"

        country_emoji = get_country_emoji(gl)

        discord_message = f"`{news_prefix} - {category} - {topic_name} {country_emoji}`\n**{title}**\n{link}"
        if description:
            discord_message += f"\n>>> {description}\n\n"
        else:
            discord_message += "\n\n"
        discord_message += f"📅 {formatted_date}"

        logging.info(f"Sending message to Discord: {discord_message[:100]}...")  # 로그 메시지 길이 제한

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