import os
import requests
import html
import time
from googleapiclient.discovery import build
import isodate
from datetime import datetime, timezone, timedelta
import json

# 환경 변수에서 필요한 정보를 가져옵니다.
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_YOUTUBE_WEBHOOK = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
LANGUAGE = os.getenv('LANGUAGE', 'English')  # 기본값은 영어, Korean을 지정 가능
INIT_MAX_RESULTS = int(os.getenv('INIT_MAX_RESULTS', '30'))  # 초기 실행 시 가져올 영상 개수, 기본값은 30
MAX_RESULTS = 10  # 초기 실행 이후 가져올 영상 개수
INIT_RUN = os.getenv('INIT_RUN', '0')  # 초기 실행 여부를 결정하는 변수, 기본값은 0

# 이전 실행에서 가장 최근에 게시된 영상의 게시일을 저장할 변수
last_published_at = None

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

# last_published_at 값을 파일에 저장하는 함수
def save_last_published_at():
    global last_published_at
    with open('last_published_at.json', 'w') as f:
        json.dump({'last_published_at': last_published_at}, f)

# 프로그램 시작 시 last_published_at 값을 파일에서 로드하는 함수
def load_last_published_at():
    global last_published_at
    try:
        with open('last_published_at.json', 'r') as f:
            data = json.load(f)
            last_published_at = data['last_published_at']
    except FileNotFoundError:
        last_published_at = None

# YouTube 동영상 가져오고 Discord에 게시하는 함수
def fetch_and_post_videos():
    global last_published_at
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    
    # 초기 실행 여부에 따라 last_published_at을 초기화합니다.
    if INIT_RUN == '1':
        last_published_at = None

    # YouTube에서 동영상을 가져옵니다.
    new_videos = []

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

    for video_detail in video_details_response['items']:
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']

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
        if last_published_at is None or published_at > last_published_at:
            new_videos.append({
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

    # 새로운 영상이 있다면, 가장 최신 영상의 게시일을 저장합니다.
    if new_videos:
        last_published_at = new_videos[-1]['published_at']
        save_last_published_at()

# 프로그램 실행
if __name__ == "__main__":
    try:
        check_env_variables()
        load_last_published_at()  # 프로그램 시작 시 last_published_at 값을 로드합니다.
        fetch_and_post_videos()
    except Exception as e:
        print(f"오류 발생: {e}")
    finally:
        print("프로그램 실행 종료")
