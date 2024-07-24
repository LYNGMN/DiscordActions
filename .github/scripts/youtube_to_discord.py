import os
import requests
import html
import time
import sqlite3
from googleapiclient.discovery import build
import isodate
from datetime import datetime, timezone, timedelta
import logging
import re

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
YOUTUBE_MODE = os.getenv('YOUTUBE_MODE', 'channels').lower()
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_PLAYLIST_ID = os.getenv('YOUTUBE_PLAYLIST_ID')
YOUTUBE_SEARCH_KEYWORD = os.getenv('YOUTUBE_SEARCH_KEYWORD')
INIT_MAX_RESULTS = int(os.getenv('YOUTUBE_INIT_MAX_RESULTS') or '50')
MAX_RESULTS = int(os.getenv('YOUTUBE_MAX_RESULTS') or '10')
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', 'false').lower() == 'true'
INITIALIZE_MODE_YOUTUBE = os.getenv('INITIALIZE_MODE_YOUTUBE', 'false').lower() == 'true'
ADVANCED_FILTER_YOUTUBE = os.getenv('ADVANCED_FILTER_YOUTUBE', '')
DATE_FILTER_YOUTUBE = os.getenv('DATE_FILTER_YOUTUBE', '')
DISCORD_WEBHOOK_YOUTUBE = os.getenv('DISCORD_WEBHOOK_YOUTUBE')
DISCORD_AVATAR_YOUTUBE = os.getenv('DISCORD_AVATAR_YOUTUBE', '').strip()
DISCORD_USERNAME_YOUTUBE = os.getenv('DISCORD_USERNAME_YOUTUBE', '').strip()
LANGUAGE_YOUTUBE = os.getenv('LANGUAGE_YOUTUBE', 'English')

# DB 설정
DB_PATH = 'youtube_videos.db'

def check_env_variables():
    required_vars = ['YOUTUBE_API_KEY', 'YOUTUBE_MODE', 'DISCORD_WEBHOOK_YOUTUBE']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"다음 환경 변수가 설정되지 않았습니다: {', '.join(missing_vars)}")
    
    if YOUTUBE_MODE not in ['channels', 'playlists', 'search']:
        raise ValueError("YOUTUBE_MODE는 'channels', 'playlists', 'search' 중 하나여야 합니다.")
    
    if YOUTUBE_MODE == 'channels':
        if not YOUTUBE_CHANNEL_ID:
            raise ValueError("YOUTUBE_MODE가 'channels'일 때 YOUTUBE_CHANNEL_ID는 필수입니다.")
    elif YOUTUBE_MODE == 'playlists':
        if not YOUTUBE_PLAYLIST_ID:
            raise ValueError("YOUTUBE_MODE가 'playlists'일 때 YOUTUBE_PLAYLIST_ID는 필수입니다.")
    elif YOUTUBE_MODE == 'search':
        if not YOUTUBE_SEARCH_KEYWORD:
            raise ValueError("YOUTUBE_MODE가 'search'일 때 YOUTUBE_SEARCH_KEYWORD는 필수입니다.")

def init_db(reset=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if reset:
        c.execute("DROP TABLE IF EXISTS videos")
        logging.info("기존 videos 테이블 삭제됨")
    c.execute('''CREATE TABLE IF NOT EXISTS videos
                 (published_at TEXT,
                  channel_title TEXT,
                  channel_id TEXT,
                  title TEXT,
                  video_id TEXT PRIMARY KEY,
                  video_url TEXT,
                  description TEXT,
                  category_id TEXT,
                  category_name TEXT,
                  duration TEXT,
                  thumbnail_url TEXT,
                  tags TEXT,
                  live_broadcast_content TEXT,
                  scheduled_start_time TEXT,
                  caption TEXT,
                  source TEXT)''')
    conn.commit()
    conn.close()
    logging.info("데이터베이스 초기화 완료")

def save_video(video_data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO videos 
                 (published_at, channel_title, channel_id, title, video_id, video_url, description, 
                 category_id, category_name, duration, thumbnail_url, tags, live_broadcast_content, 
                 scheduled_start_time, caption, source) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (video_data['published_at'], video_data['channel_title'], video_data['channel_id'], 
               video_data['title'], video_data['video_id'], video_data['video_url'], 
               video_data['description'], video_data['category_id'], video_data['category_name'], 
               video_data['duration'], video_data['thumbnail_url'], video_data['tags'], 
               video_data['live_broadcast_content'], video_data['scheduled_start_time'], 
               video_data['caption'], video_data['source']))
    conn.commit()
    conn.close()
    logging.info(f"새 비디오 저장됨: {video_data['video_id']}")

def load_videos():
    if not os.path.exists(DB_PATH):
        logging.info("데이터베이스 파일이 존재하지 않습니다. 새로 생성합니다.")
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

def post_to_discord(message):
    payload = {"content": message}
    
    if DISCORD_AVATAR_YOUTUBE:
        payload["avatar_url"] = DISCORD_AVATAR_YOUTUBE
    
    if DISCORD_USERNAME_YOUTUBE:
        payload["username"] = DISCORD_USERNAME_YOUTUBE
    
    headers = {'Content-Type': 'application/json'}
    response = requests.post(DISCORD_WEBHOOK_YOUTUBE, json=payload, headers=headers)
    if response.status_code != 204:
        logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        logging.error(response.text)
    else:
        logging.info("Discord에 메시지 게시 완료")
        time.sleep(2)  # 속도 제한

def parse_duration(duration):
    parsed_duration = isodate.parse_duration(duration)
    total_seconds = int(parsed_duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if LANGUAGE_YOUTUBE == 'Korean':
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

def convert_to_local_time(published_at):
    utc_time = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
    local_time = utc_time.replace(tzinfo=timezone.utc).astimezone()
    if LANGUAGE_YOUTUBE == 'Korean':
        return local_time.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    else:
        return local_time.strftime("%Y-%m-%d %H:%M:%S")

def apply_advanced_filter(title, advanced_filter):
    if not advanced_filter:
        return True

    text_to_check = title.lower()
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

    since_match = re.search(r'since:(\d{4}-\d{2}-\d{2})', filter_string)
    until_match = re.search(r'until:(\d{4}-\d{2}-\d{2})', filter_string)
    
    if since_match:
        since_date = datetime.strptime(since_match.group(1), '%Y-%m-%d')
    elif until_match:
        until_date = datetime.strptime(until_match.group(1), '%Y-%m-%d')

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

def is_within_date_range(published_at, since_date, until_date, past_date):
    pub_datetime = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
    
    if past_date:
        return pub_datetime >= past_date
    
    if since_date:
        return pub_datetime >= since_date
    if until_date:
        return pub_datetime <= until_date
    
    return True

# 카테고리 ID를 이름으로 변환하는 캐시를 이용한 함수
category_cache = {}
def get_category_name(youtube, category_id):
    if category_id in category_cache:
        return category_cache[category_id]
    
    categories = youtube.videoCategories().list(part="snippet", regionCode="US").execute()
    for category in categories['items']:
        category_cache[category['id']] = category['snippet']['title']
        if category['id'] == category_id:
            return category['snippet']['title']
    return "Unknown"

def fetch_playlist_info(youtube, playlist_id):
    playlist_response = youtube.playlists().list(
        part="snippet",
        id=playlist_id
    ).execute()
    
    if 'items' in playlist_response and playlist_response['items']:
        playlist_info = playlist_response['items'][0]['snippet']
        return {
            'title': playlist_info['title'],
            'channel_title': playlist_info['channelTitle']
        }
    return None

def fetch_videos(youtube, mode, channel_id, playlist_id, search_keyword):
    if mode == 'channels':
        response = youtube.search().list(
            channelId=channel_id,
            order='date',
            type='video',
            part='snippet,id',
            maxResults=INIT_MAX_RESULTS if IS_FIRST_RUN or INITIALIZE_MODE_YOUTUBE else MAX_RESULTS
        ).execute()
        return [(item['id']['videoId'], item['snippet']) for item in response.get('items', [])]
    elif mode == 'playlists':
        playlist_items = []
        next_page_token = None
        max_results = INIT_MAX_RESULTS if IS_FIRST_RUN or INITIALIZE_MODE_YOUTUBE else MAX_RESULTS

        while True:
            playlist_request = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            playlist_response = playlist_request.execute()
            
            playlist_items.extend(playlist_response['items'])
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token or len(playlist_items) >= max_results:
                break

        playlist_items = playlist_items[:max_results]
        return [(item['snippet']['resourceId']['videoId'], item['snippet']) for item in playlist_items]
    elif mode == 'search':
        response = youtube.search().list(
            q=search_keyword,
            order='date',
            type='video',
            part='snippet,id',
            maxResults=INIT_MAX_RESULTS if IS_FIRST_RUN or INITIALIZE_MODE_YOUTUBE else MAX_RESULTS
        ).execute()
        return [(item['id']['videoId'], item['snippet']) for item in response.get('items', [])]
    else:
        raise ValueError("잘못된 모드입니다.")

def fetch_and_post_videos(youtube):
    if not os.path.exists(DB_PATH):
        init_db()

    saved_videos = load_videos()
    latest_saved_time = saved_videos[0][0] if saved_videos else None

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_YOUTUBE)

    videos = fetch_videos(youtube, YOUTUBE_MODE, YOUTUBE_CHANNEL_ID, YOUTUBE_PLAYLIST_ID, YOUTUBE_SEARCH_KEYWORD)
    video_ids = [video[0] for video in videos]

    video_details_response = youtube.videos().list(
        part="snippet,contentDetails,liveStreamingDetails",
        id=','.join(video_ids)
    ).execute()

    new_videos = []

    playlist_info = None
    if YOUTUBE_MODE == 'playlists':
        playlist_info = fetch_playlist_info(youtube, YOUTUBE_PLAYLIST_ID)

    for video_detail in video_details_response['items']:
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']
        live_streaming_details = video_detail.get('liveStreamingDetails', {})

        video_id = video_detail['id']
        published_at = snippet['publishedAt']
        
        if any(saved_video[4] == video_id for saved_video in saved_videos):
            continue

        if latest_saved_time and published_at <= latest_saved_time:
            continue

        if not is_within_date_range(published_at, since_date, until_date, past_date):
            logging.info(f"날짜 필터에 의해 건너뛰어진 비디오: {snippet['title']}")
            continue

        video_title = html.unescape(snippet['title'])
        
        if not apply_advanced_filter(video_title, ADVANCED_FILTER_YOUTUBE):
            logging.info(f"고급 필터에 의해 건너뛰어진 비디오: {video_title}")
            continue

        channel_title = html.unescape(snippet['channelTitle'])
        description = html.unescape(snippet.get('description', ''))
        thumbnail_url = snippet['thumbnails']['high']['url']
        duration = parse_duration(content_details['duration'])
        category_id = snippet.get('categoryId', 'Unknown')
        category_name = get_category_name(youtube, category_id)
        tags = ','.join(snippet.get('tags', []))
        live_broadcast_content = snippet.get('liveBroadcastContent', '')
        scheduled_start_time = live_streaming_details.get('scheduledStartTime', '')
        caption = content_details.get('caption', '')

        video_data = {
            'published_at': published_at,
            'channel_title': channel_title,
            'channel_id': snippet['channelId'],
            'title': video_title,
            'video_id': video_id,
            'video_url': f"https://youtu.be/{video_id}",
            'description': description,
            'category_id': category_id,
            'category_name': category_name,
            'duration': duration,
            'thumbnail_url': thumbnail_url,
            'tags': tags,
            'live_broadcast_content': live_broadcast_content,
            'scheduled_start_time': scheduled_start_time,
            'caption': caption,
            'source': YOUTUBE_MODE
        }
        
        new_videos.append(video_data)

    new_videos.sort(key=lambda x: x['published_at'])
    logging.info(f"새로운 비디오 수: {len(new_videos)}")

    for video in new_videos:
        formatted_published_at = convert_to_local_time(video['published_at'])
        video_url = f"https://youtu.be/{video['video_id']}"
        
        if LANGUAGE_YOUTUBE == 'Korean':
            if YOUTUBE_MODE == 'channels':
                source_text = f"`{video['channel_title']} - YouTube`\n"
            elif YOUTUBE_MODE == 'playlists' and playlist_info:
                source_text = (
                    f"`📃 {playlist_info['title']} - YouTube 재생목록 by. {playlist_info['channel_title']}`\n\n"
                    f"`{video['channel_title']} - YouTube`\n"
                )
            elif YOUTUBE_MODE == 'search':
                source_text = f"`🔎 {YOUTUBE_SEARCH_KEYWORD} - YouTube 검색 결과`\n`{video['channel_title']} - YouTube`\n\n"
            else:
                source_text = f"`{video['channel_title']} - YouTube`\n"
            
            message = (
                f"{source_text}"
                f"**{video['title']}**\n"
                f"{video_url}\n\n"
                f"📁 카테고리: `{video['category_name']}`\n"
                f"⌛️ 영상 길이: `{video['duration']}`\n"
                f"📅 게시일: `{formatted_published_at}`\n"
                f"🖼️ [썸네일](<{video['thumbnail_url']}>)"
            )
            if video['scheduled_start_time']:
                formatted_start_time = convert_to_local_time(video['scheduled_start_time'])
                message += f"\n\n🔴 예정된 라이브 시작 시간: `{formatted_start_time}`"
        else:
            if YOUTUBE_MODE == 'channels':
                source_text = f"`{video['channel_title']} - YouTube`\n"
            elif YOUTUBE_MODE == 'playlists' and playlist_info:
                source_text = (
                    f"`📃 {playlist_info['title']} - YouTube Playlist by {playlist_info['channel_title']}`\n\n"
                    f"`{video['channel_title']} - YouTube`\n"
                )
            elif YOUTUBE_MODE == 'search':
                source_text = f"`🔎 {YOUTUBE_SEARCH_KEYWORD} - YouTube Search Result`\n`{video['channel_title']} - YouTube`\n\n"
            else:
                source_text = f"`{video['channel_title']} - YouTube`\n"
            
            message = (
                f"{source_text}"
                f"**{video['title']}**\n"
                f"{video_url}\n\n"
                f"📁 Category: `{video['category_name']}`\n"
                f"⌛️ Duration: `{video['duration']}`\n"
                f"📅 Published: `{formatted_published_at}`\n"
                f"🖼️ [Thumbnail](<{video['thumbnail_url']}>)"
            )
            if video['scheduled_start_time']:
                formatted_start_time = convert_to_local_time(video['scheduled_start_time'])
                message += f"\n\n🔴 Scheduled Live Start Time: `{formatted_start_time}`"

        post_to_discord(message)
        save_video(video)

if __name__ == "__main__":
    try:
        check_env_variables()
        if INITIALIZE_MODE_YOUTUBE:
            init_db(reset=True)
            logging.info("초기화 모드로 실행 중: 데이터베이스를 재설정하고 모든 비디오를 다시 가져옵니다.")
        
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        
        fetch_and_post_videos(youtube)
        
        logging.info(f"YOUTUBE_MODE: {YOUTUBE_MODE}")
        logging.info(f"INITIALIZE_MODE_YOUTUBE: {INITIALIZE_MODE_YOUTUBE}")
        logging.info(f"IS_FIRST_RUN: {IS_FIRST_RUN}")
        logging.info(f"데이터베이스 파일 크기: {os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else '파일 없음'}")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM videos")
        count = c.fetchone()[0]
        logging.info(f"데이터베이스의 비디오 수: {count}")
        conn.close()
        
    except Exception as e:
        logging.error(f"오류 발생: {e}", exc_info=True)
    finally:
        logging.info("스크립트 실행 완료")