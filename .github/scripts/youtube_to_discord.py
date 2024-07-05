import os
import requests
import html
import time
import sqlite3
from googleapiclient.discovery import build
import isodate
from datetime import datetime, timezone, timedelta

# 환경 변수에서 필요한 정보를 가져옵니다.
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_YOUTUBE_WEBHOOK = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
LANGUAGE = os.getenv('LANGUAGE', 'English')  # 기본값은 영어, Korean을 지정 가능
INIT_MAX_RESULTS = int(os.getenv('INIT_MAX_RESULTS', '30'))  # 초기 실행 시 가져올 영상 개수, 기본값은 30
MAX_RESULTS = 10  # 초기 실행 이후 가져올 영상 개수
INIT_RUN = os.getenv('INIT_RUN', '0')  # 초기 실행 여부를 결정하는 변수, 기본값은 0

# DB 설정
DB_PATH = 'youtube_videos.db'

# 환경 변수가 설정되었는지 확인하는 함수
def check_env_variables():
    missing_vars = []
    if not YOUTUBE_CHANNEL_ID:
        missing_vars.append('YOUTUBE_CHANNEL_ID')
    if not YOUTUBE_API_KEY:
        missing_vars.append('YOUTUBE_API_KEY')
    if not DISCORD_YOUTUBE_WEBHOOK:
        missing_vars.append('DISCORD_YOUTUBE_WEBHOOK')
    
    if missing_vars:
        raise ValueError(f"환경 변수가 설정되지 않았습니다: {', '.join(missing_vars)}")

# Discord에 메시지를 게시하는 함수
def post_to_discord(message):
    payload = {"content": message}
    headers = {'Content-Type': 'application/json'}
    response = requests.post(DISCORD_YOUTUBE_WEBHOOK, json=payload, headers=headers)
    if response.status_code != 204:
        print(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        print(response.text)
    else:
        print("Discord에 메시지 게시 완료")
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

# DB 초기화 함수
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS videos
                 (video_id TEXT PRIMARY KEY, published_at TEXT)''')
    conn.commit()
    conn.close()

# DB에 새로운 동영상 저장 함수
def save_video(video_id, published_at):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO videos (video_id, published_at) VALUES (?, ?)", (video_id, published_at))
    conn.commit()
    conn.close()

# DB에서 저장된 동영상 불러오기 함수
def load_videos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT video_id, published_at FROM videos ORDER BY published_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

# YouTube 동영상 가져오고 Discord에 게시하는 함수
def fetch_and_post_videos():
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    
    # DB 초기화
    init_db()

    # DB에서 저장된 동영상 불러오기
    saved_videos = load_videos()
    last_published_at = saved_videos[0][1] if saved_videos else None

    # 초기 실행 여부에 따라 maxResults 값을 설정합니다.
    if INIT_RUN == '1' or last_published_at is None:
        max_results = INIT_MAX_RESULTS
    else:
        max_results = MAX_RESULTS

    # 디버깅 로그 추가
    print(f"INIT_RUN: {INIT_RUN}")
    print(f"max_results: {max_results}")
    print(f"last_published_at: {last_published_at}")

    response = youtube.search().list(
        channelId=YOUTUBE_CHANNEL_ID,
        order='date',
        type='video',
        part='snippet,id',
        maxResults=max_results
    ).execute()

    if 'items' not in response:
        print("동영상을 찾을 수 없습니다.")
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
        video_title = html.unescape(snippet['title'])
        channel_title = html.unescape(snippet['channelTitle'])
        description = html.unescape(snippet.get('description', ''))
        tags = ','.join(snippet.get('tags', []))
        category_id = snippet.get('categoryId', '')
        category_name = get_category_name(category_id)
        thumbnail_url = snippet['thumbnails']['high']['url']
        duration = parse_duration(content_details['duration'])
        video_url = f"https://youtu.be/{video_detail['id']}"

        # 새로운 영상인지 확인합니다.
        if not any(saved_video[0] == video_id for saved_video in saved_videos):
            new_videos.append({
                'video_id': video_id,
                'channel_title': channel_title,
                'title': video_title,
                'video_url': video_url,
                'description': description,
                'duration': duration,
                'published_at': published_at,
                'tags': tags,
                'category': category_name,
                'thumbnail_url': thumbnail_url
            })

    # 새로운 동영상을 오래된 순서로 정렬합니다.
    new_videos.sort(key=lambda x: x['published_at'])

    # 새로운 동영상 정보를 Discord에 전송 (오래된 순서대로)
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
        save_video(video['video_id'], video['published_at'])

# 프로그램 실행
if __name__ == "__main__":
    try:
        check_env_variables()
        fetch_and_post_videos()
    except Exception as e:
        print(f"오류 발생: {e}")
    finally:
        print("프로그램 실행 종료")
