import os
import requests
import html
import time
import sqlite3
from googleapiclient.discovery import build
import isodate
from datetime import datetime, timezone, timedelta
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 필요한 정보를 가져옵니다.
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_YOUTUBE_WEBHOOK = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
LANGUAGE = os.getenv('LANGUAGE', 'English')
INIT_MAX_RESULTS = int(os.getenv('INIT_MAX_RESULTS', '30'))
MAX_RESULTS = int(os.getenv('MAX_RESULTS') or '10')
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', 'false').lower() == 'true'

# DB 설정
DB_PATH = 'youtube_videos.db'

# 환경 변수가 설정되었는지 확인하는 함수
def check_env_variables():
    required_vars = ['YOUTUBE_CHANNEL_ID', 'YOUTUBE_API_KEY', 'DISCORD_YOUTUBE_WEBHOOK']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"환경 변수가 설정되지 않았습니다: {', '.join(missing_vars)}")

# DB 초기화 함수
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS videos
                 (published_at TEXT,
                  channel_title TEXT,
                  title TEXT,
                  video_id TEXT PRIMARY KEY,
                  video_url TEXT,
                  description TEXT,
                  category TEXT,
                  duration TEXT,
                  thumbnail_url TEXT)''')
    conn.commit()
    conn.close()
    logging.info("데이터베이스 초기화 완료")

# DB에 새로운 동영상 저장 함수
def save_video(video_data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO videos 
                 (published_at, channel_title, title, video_id, video_url, description, category, duration, thumbnail_url) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (video_data['published_at'], video_data['channel_title'], video_data['title'],
               video_data['video_id'], video_data['video_url'], video_data['description'], 
               video_data['category'], video_data['duration'], video_data['thumbnail_url']))
    conn.commit()
    conn.close()
    logging.info(f"새 비디오 저장: {video_data['video_id']}")

# DB에서 저장된 동영상 불러오기 함수
def load_videos():
    if not os.path.exists(DB_PATH):
        logging.info("데이터베이스 파일이 없습니다. 새로 생성합니다.")
        init_db()
        return []
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM videos ORDER BY published_at DESC")
        rows = c.fetchall()
    except sqlite3.OperationalError:
        logging.info("테이블이 존재하지 않습니다. 새로 생성합니다.")
        conn.close()
        init_db()
        return []
    finally:
        conn.close()
    
    logging.info(f"저장된 비디오 수: {len(rows)}")
    return rows

# Discord에 메시지를 게시하는 함수
def post_to_discord(message):
    payload = {"content": message}
    headers = {'Content-Type': 'application/json'}
    response = requests.post(DISCORD_YOUTUBE_WEBHOOK, json=payload, headers=headers)
    if response.status_code != 204:
        logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        logging.error(response.text)
    else:
        logging.info("Discord에 메시지 게시 완료")
        time.sleep(3)  # 메시지 게시 후 3초 대기

# ISO 8601 기간을 사람이 읽기 쉬운 형식으로 변환하는 함수
def parse_duration(duration):
    parsed_duration = isodate.parse_duration(duration)
    total_seconds = int(parsed_duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if LANGUAGE == 'Korean':
        if hours > 0:
            return f"{hours}시간 {minutes}분 {seconds}초"
        elif minutes > 0:
            return f"{minutes}분 {seconds}초"
        else:
            return f"{seconds}초"
    else:
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

# 카테고리 ID를 이름으로 변환하는 캐시를 이용한 함수
category_cache = {}

def get_category_name(category_id):
    if category_id in category_cache:
        return category_cache[category_id]
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    categories = youtube.videoCategories().list(part="snippet", regionCode="US").execute()
    for category in categories['items']:
        category_cache[category['id']] = category['snippet']['title']
        if category['id'] == category_id:
            return category['snippet']['title']
    return "Unknown"

# 게시일을 한국 시간(KST)으로 변환하고 형식을 지정하는 함수
def convert_to_kst_and_format(published_at):
    utc_time = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
    kst_time = utc_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=9)))
    return kst_time.strftime("%Y-%m-%d %H:%M:%S")

# YouTube 동영상 가져오고 Discord에 게시하는 함수
def fetch_and_post_videos():
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    
    # DB 초기화 (필요한 경우)
    if not os.path.exists(DB_PATH):
        init_db()

    # DB에서 저장된 동영상 불러오기
    saved_videos = load_videos()
    
    # 가장 최근에 저장된 비디오의 게시 시간을 가져옵니다.
    latest_saved_time = saved_videos[0][0] if saved_videos else None

    # YouTube API로 최신 비디오 목록을 가져옵니다.
    response = youtube.search().list(
        channelId=YOUTUBE_CHANNEL_ID,
        order='date',
        type='video',
        part='snippet,id',
        maxResults=INIT_MAX_RESULTS if IS_FIRST_RUN else MAX_RESULTS
    ).execute()

    if 'items' not in response:
        logging.warning("동영상을 찾을 수 없습니다.")
        return

    video_ids = [item['id']['videoId'] for item in response['items']]

    video_details_response = youtube.videos().list(
        part="snippet,contentDetails",
        id=','.join(video_ids)
    ).execute()

    new_videos = []

    for video_detail in video_details_response['items']:
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']

        video_id = video_detail['id']
        published_at = snippet['publishedAt']
        
        # 이미 저장된 비디오는 건너뜁니다.
        if any(saved_video[3] == video_id for saved_video in saved_videos):
            continue

        # 이미 저장된 비디오보다 새로운 비디오만 처리합니다.
        if latest_saved_time and published_at <= latest_saved_time:
            continue

        video_title = html.unescape(snippet['title'])
        channel_title = html.unescape(snippet['channelTitle'])
        description = html.unescape(snippet.get('description', ''))
        category_id = snippet.get('categoryId', '')
        category_name = get_category_name(category_id)
        thumbnail_url = snippet['thumbnails']['high']['url']
        duration = parse_duration(content_details['duration'])
        video_url = f"https://youtu.be/{video_detail['id']}"

        video_data = {
            'published_at': published_at,
            'channel_title': channel_title,
            'title': video_title,
            'video_id': video_id,
            'video_url': video_url,
            'description': description,
            'category': category_name,
            'duration': duration,
            'thumbnail_url': thumbnail_url
        }

        new_videos.append(video_data)

    # 새로운 동영상을 오래된 순서로 정렬합니다.
    new_videos.sort(key=lambda x: x['published_at'])
    logging.info(f"새로운 비디오 수: {len(new_videos)}")

    # 새로운 동영상 정보를 Discord에 전송하고 DB에 저장 (오래된 순서대로)
    for video in new_videos:
        formatted_published_at = convert_to_kst_and_format(video['published_at'])
        if LANGUAGE == 'Korean':
            message = (
                f"`{video['channel_title']} - YouTube`\n"
                f"**{video['title']}**\n"
                f"{video['video_url']}\n\n"
                f"📁 카테고리: `{video['category']}`\n"
                f"⌛️ 영상시간: `{video['duration']}`\n"
                f"📅 게시일: `{formatted_published_at} (KST)`\n"
                f"🖼️ [썸네일](<{video['thumbnail_url']}>)"
            )
        else:
            message = (
                f"`{video['channel_title']} - YouTube`\n"
                f"**{video['title']}**\n"
                f"{video['video_url']}\n\n"
                f"📁 Category: `{video['category']}`\n"
                f"⌛️ Duration: `{video['duration']}`\n"
                f"📅 Published: `{formatted_published_at}`\n"
                f"🖼️ [Thumbnail](<{video['thumbnail_url']}>)"
            )

        post_to_discord(message)
        save_video(video)

# 프로그램 실행
if __name__ == "__main__":
    try:
        check_env_variables()
        fetch_and_post_videos()
        
        # 디버그 정보 출력
        logging.info(f"IS_FIRST_RUN: {IS_FIRST_RUN}")
        logging.info(f"Database file size: {os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 'File not found'}")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM videos")
        count = c.fetchone()[0]
        logging.info(f"Number of videos in database: {count}")
        conn.close()
        
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
    finally:
        logging.info("프로그램 실행 종료")
