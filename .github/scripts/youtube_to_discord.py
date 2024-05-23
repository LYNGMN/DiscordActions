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
RESET_DB = os.getenv('RESET_DB', '0')
LANGUAGE = os.getenv('LANGUAGE', 'English')  # 기본값은 영어, Korean을 지정 가능
MAX_RESULTS = int(os.getenv('MAX_RESULTS', '50'))  # 기본값은 50

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
    posted_video_ids = get_posted_videos()
    print("기존에 게시된 동영상 ID를 데이터베이스에서 가져왔습니다.")

    # YouTube에서 동영상을 가져옵니다.
    new_videos = []
    next_page_token = None

    while True:
        response = youtube.search().list(
            channelId=YOUTUBE_CHANNEL_ID,
            order='date',
            type='video',
            part='snippet',
            maxResults=MAX_RESULTS,
            pageToken=next_page_token
        ).execute()
        print("YouTube에서 동영상 목록을 가져왔습니다.")

        if 'items' not in response:
            print("동영상을 찾을 수 없습니다.")
            break

        for video in response['items'][::-1]:  # 오래된 순서부터 처리
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
            formatted_published_at = convert_to_kst_and_format(published_at)
            tags = ','.join(snippet.get('tags', []))
            category_id = snippet.get('categoryId', '')
            category_name = get_category_name(category_id)
            thumbnail_url = snippet['thumbnails']['high']['url']
            duration = parse_duration(content_details['duration'])
            video_url = f"https://youtu.be/{video_id}"

            new_videos.append({
                'video_id': video_id,
                'channel_title': channel_title,
                'title': video_title,
                'video_url': video_url,
                'description': description,
                'duration': duration,
                'published_at': formatted_published_at,
                'tags': tags,
                'category': category_name,
                'thumbnail_url': thumbnail_url
            })
            print(f"새로운 동영상 발견: {video_title}")

        # 다음 페이지 토큰을 가져옵니다.
        next_page_token = response.get('nextPageToken')

        # 다음 페이지가 없으면 중지합니다.
        if not next_page_token:
            break

    # 새로운 동영상 정보를 Discord에 전송
    for video in new_videos:
        if LANGUAGE == 'Korean':
            message = (
                f"`{video['channel_title']} - YouTube`\n"
                f"**{video['title']}**\n"
                f"{video['video_url']}\n\n"
                f"📁 카테고리: `{video['category']}`\n"
                f"⌛️ 영상시간: `{video['duration']}`\n"
                f"📅 게시일: `{video['published_at']} (KST)`\n"
                f"🖼️ [썸네일](<{video['thumbnail_url']}>)"
            )
        else:
            message = (
                f"`{video['channel_title']} - YouTube`\n"
                f"**{video['title']}**\n"
                f"{video['video_url']}\n\n"
                f"📁 Category: `{video['category']}`\n"
                f"⌛️ Duration: `{video['duration']}`\n"
                f"📅 Published: `{video['published_at']}`\n"
                f"🖼️ [Thumbnail](<{video['thumbnail_url']}>)"
            )

        post_to_discord(message)

    # 새로운 동영상 ID를 데이터베이스에 업데이트합니다.
    if new_videos:
        update_posted_videos(new_videos)

# 프로그램 실행
if __name__ == "__main__":
    try:
        check_env_variables()
        fetch_and_post_videos()
    except Exception as e:
        print(f"오류 발생: {e}")
    finally:
        conn.close()
        print("데이터베이스 연결 종료")
