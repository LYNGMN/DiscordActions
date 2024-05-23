import os
import requests
import html
import time
import sqlite3
from googleapiclient.discovery import build
import isodate

# 환경 변수에서 필요한 정보를 가져옵니다.
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_YOUTUBE_WEBHOOK = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
RESET_DB = os.getenv('RESET_DB', '0')

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
    print("환경 변수 확인 완료")

# YouTube Data API 초기화
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# SQLite 데이터베이스 연결
conn = sqlite3.connect('videos.db')
cursor = conn.cursor()

# 데이터베이스 초기화 (RESET_DB가 설정된 경우)
if RESET_DB == '1':
    cursor.execute('DROP TABLE IF EXISTS posted_videos')
    conn.commit()
    print("데이터베이스 초기화 완료")

# 테이블 생성 (존재하지 않을 경우)
cursor.execute('''
CREATE TABLE IF NOT EXISTS posted_videos (
    video_id TEXT PRIMARY KEY,
    channel_title TEXT,
    title TEXT,
    video_url TEXT,
    description TEXT,
    duration TEXT,
    published_at TEXT,
    tags TEXT,
    category TEXT,
    thumbnail_url TEXT
)
''')
conn.commit()
print("테이블 생성 완료")

# 데이터베이스에서 동영상 ID 목록을 가져오는 함수
def get_posted_videos():
    cursor.execute('SELECT video_id FROM posted_videos')
    return [row[0] for row in cursor.fetchall()]

# 데이터베이스에 동영상 정보를 추가하는 함수
def update_posted_videos(videos):
    cursor.executemany('''
        INSERT OR IGNORE INTO posted_videos 
        (video_id, channel_title, title, video_url, description, duration, published_at, tags, category, thumbnail_url) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', [(video['video_id'], video['channel_title'], video['title'], video['video_url'], video['description'], video['duration'], video['published_at'], video['tags'], video['category'], video['thumbnail_url']) for video in videos])
    conn.commit()
    print(f"{len(videos)}개의 새로운 동영상 정보 업데이트 완료")

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
    categories = youtube.videoCategories().list(part="snippet", regionCode="US").execute()
    for category in categories['items']:
        category_cache[category['id']] = category['snippet']['title']
        if category['id'] == category_id:
            return category['snippet']['title']
    return "Unknown"

# YouTube 동영상 가져오고 Discord에 게시하는 함수
def fetch_and_post_videos():
    posted_video_ids = get_posted_videos()
    print("기존에 게시된 동영상 ID를 데이터베이스에서 가져왔습니다.")

    # YouTube에서 동영상을 가져옵니다.
    videos = youtube.search().list(
        channelId=YOUTUBE_CHANNEL_ID,
        order='date',
        type='video',
        part='snippet',
        maxResults=50
    ).execute()
    print("YouTube에서 동영상 목록을 가져왔습니다.")

    if 'items' not in videos:
        print("동영상을 찾을 수 없습니다.")
        return

    new_videos = []

    for video in videos['items']:
        video_id = video['id']['videoId']

        # 동영상이 이미 게시된 경우 건너뜁니다.
        if video_id in posted_video_ids:
            continue

        video_details = youtube.videos().list(
            part="snippet,contentDetails",
            id=video_id
        ).execute()

        if not video_details['items']:
            continue

        video_detail = video_details['items'][0]
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']

        video_title = html.unescape(snippet['title'])
        channel_title = html.unescape(snippet['channelTitle'])
        description = html.unescape(snippet.get('description', ''))
        published_at = snippet['publishedAt']
        tags = ','.join(snippet.get('tags', []))
        category_id = snippet.get('categoryId', '')
        category_name = get_category_name(category_id)
        thumbnail_url = snippet['thumbnails']['high']['url']
        duration = parse_duration(content_details['duration'])
        video_url = f"https://youtu.be/{video_id}"

        message = (
            f"`{channel_title} - YouTube`\n"
            f"**{video_title}**\n"
            f"{video_url}\n\n"
            f"📁 Category: `{category_name}`\n"
            f"⌛️ Duration: `{duration}`\n"
            f"📅 Published: `{published_at}`\n"
            f"🖼️ [Thumbnail](<{thumbnail_url}>)"
        )
        post_to_discord(message)
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
        print(f"새로운 동영상 발견: {video_title}")

    # 새로운 동영상 ID를 데이터베이스에 업데이트합니다.
    if new_videos:
        update_posted_videos(new_videos)

# 메인 함수 실행
def main():
    try:
        check_env_variables()
        fetch_and_post_videos()
        print_database_content()
    except Exception as e:
        print(f"오류 발생: {str(e)}")

# 데이터베이스 내용 출력 함수
def print_database_content():
    cursor.execute('SELECT * FROM posted_videos')
    rows = cursor.fetchall()
    for row in rows:
        print(row)

if __name__ == "__main__":
    main()
