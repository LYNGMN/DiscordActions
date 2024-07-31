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
import json

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
YOUTUBE_MODE = os.getenv('YOUTUBE_MODE', 'channels').lower()
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_PLAYLIST_ID = os.getenv('YOUTUBE_PLAYLIST_ID')
YOUTUBE_SEARCH_KEYWORD = os.getenv('YOUTUBE_SEARCH_KEYWORD')
INIT_MAX_RESULTS = int(os.getenv('YOUTUBE_INIT_MAX_RESULTS') or '100')
MAX_RESULTS = int(os.getenv('YOUTUBE_MAX_RESULTS') or '10')
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', 'false').lower() == 'true'
INITIALIZE_MODE_YOUTUBE = os.getenv('INITIALIZE_MODE_YOUTUBE', 'false').lower() == 'true'
ADVANCED_FILTER_YOUTUBE = os.getenv('ADVANCED_FILTER_YOUTUBE', '')
DATE_FILTER_YOUTUBE = os.getenv('DATE_FILTER_YOUTUBE', '')
DISCORD_WEBHOOK_YOUTUBE = os.getenv('DISCORD_WEBHOOK_YOUTUBE')
DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW = os.getenv('DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW')
DISCORD_AVATAR_YOUTUBE = os.getenv('DISCORD_AVATAR_YOUTUBE', '').strip()
DISCORD_USERNAME_YOUTUBE = os.getenv('DISCORD_USERNAME_YOUTUBE', '').strip()
LANGUAGE_YOUTUBE = os.getenv('LANGUAGE_YOUTUBE', 'English')
YOUTUBE_DETAILVIEW = os.getenv('YOUTUBE_DETAILVIEW', 'false').lower() == 'true'

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

def get_channel_thumbnail(youtube, channel_id):
    try:
        response = youtube.channels().list(
            part="snippet",
            id=channel_id
        ).execute()
        return response['items'][0]['snippet']['thumbnails']['default']['url']
    except Exception as e:
        logging.error(f"채널 썸네일을 가져오는 데 실패했습니다: {e}")
        return ""

def create_embed_message(video, youtube):
    channel_thumbnail = get_channel_thumbnail(youtube, video['channel_id'])
    
    tags = video['tags'].split(',') if video['tags'] else []
    formatted_tags = ' '.join(f'`{tag.strip()}`' for tag in tags)
    
    play_text = "Play Video" if LANGUAGE_YOUTUBE == 'English' else "영상 재생"
    play_link = f"https://www.youtube.com/watch?v={video['video_id']}"
    embed_link = f"https://www.youtube.com/embed/{video['video_id']}"
    
    embed = {
        "title": video['title'],
        "description": video['description'][:4096],  # Discord 제한
        "url": video['video_url'],
        "color": 16711680,  # Red color
        "fields": [
            {
                "name": "🆔 Video ID" if LANGUAGE_YOUTUBE == 'English' else "🆔 영상 ID",
                "value": f"`{video['video_id']}`"
            },            
            {
                "name": "📁 Category" if LANGUAGE_YOUTUBE == 'English' else "📁 영상 분류",
                "value": video['category_name']
            },
            {
                "name": "🏷️ Tags" if LANGUAGE_YOUTUBE == 'English' else "🏷️ 영상 태그",
                "value": formatted_tags if formatted_tags else "N/A"
            },
            {
                "name": "⌛ Duration" if LANGUAGE_YOUTUBE == 'English' else "⌛ 영상 길이",
                "value": video['duration']
            },            
            {
                "name": "🔡 Subtitle" if LANGUAGE_YOUTUBE == 'English' else "🔡 영상 자막",
                "value": f"[Download](https://downsub.com/?url={video['video_url']})"
            },
            {
                "name": "▶️ " + play_text,
                "value": f"[Embed]({embed_link})"
            }
        ],
        "author": {
            "name": video['channel_title'],
            "url": f"https://www.youtube.com/channel/{video['channel_id']}",
            "icon_url": channel_thumbnail
        },
        "footer": {
            "text": "YouTube",
            "icon_url": "https://icon.dataimpact.ing/media/original/youtube/youtube_social_circle_red.png"
        },
        "timestamp": video['published_at'],
        "image": {
            "url": video['thumbnail_url']
        }
    }
    
    return {
        "content": None,
        "embeds": [embed],
        "attachments": []
    }

def post_to_discord(message, is_embed=False, is_detail=False):
    headers = {'Content-Type': 'application/json'}
    
    if is_embed:
        payload = message
    else:
        payload = {"content": message}
        if DISCORD_AVATAR_YOUTUBE:
            payload["avatar_url"] = DISCORD_AVATAR_YOUTUBE
        if DISCORD_USERNAME_YOUTUBE:
            payload["username"] = DISCORD_USERNAME_YOUTUBE
    
    webhook_url = DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW if is_detail and DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW else DISCORD_WEBHOOK_YOUTUBE
    
    response = requests.post(webhook_url, json=payload, headers=headers)
    if response.status_code != 204:
        logging.error(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        logging.error(response.text)
    else:
        logging.info(f"Discord에 메시지 게시 완료 ({'상세' if is_detail else '기본'} 웹훅)")
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
    utc_time = utc_time.replace(tzinfo=timezone.utc)
    
    if LANGUAGE_YOUTUBE == 'Korean':
        # KST는 UTC+9
        kst_time = utc_time + timedelta(hours=9)
        return kst_time.strftime("%Y년 %m월 %d일 %H시 %M분")
    else:
        local_time = utc_time.astimezone()
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
            if not next_page_token or (not IS_FIRST_RUN and not INITIALIZE_MODE_YOUTUBE and len(playlist_items) >= MAX_RESULTS):
                break

        if not IS_FIRST_RUN and not INITIALIZE_MODE_YOUTUBE:
            playlist_items = playlist_items[:MAX_RESULTS]
        
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

def fetch_video_details(youtube, video_ids):
    video_details = []
    chunk_size = 50
    for i in range(0, len(video_ids), chunk_size):
        chunk = video_ids[i:i+chunk_size]
        try:
            video_details_response = youtube.videos().list(
                part="snippet,contentDetails,liveStreamingDetails",
                id=','.join(chunk)
            ).execute()
            video_details.extend(video_details_response.get('items', []))
        except Exception as e:
            logging.error(f"비디오 세부 정보를 가져오는 중 오류 발생: {e}")
    return video_details

def fetch_and_post_videos(youtube):
    logging.info(f"fetch_and_post_videos 함수 시작")
    logging.info(f"YOUTUBE_DETAILVIEW 설정: {YOUTUBE_DETAILVIEW}")

    if not os.path.exists(DB_PATH):
        init_db()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT video_id FROM videos")
    existing_video_ids = set(row[0] for row in c.fetchall())
    conn.close()

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_YOUTUBE)

    videos = fetch_videos(youtube, YOUTUBE_MODE, YOUTUBE_CHANNEL_ID, YOUTUBE_PLAYLIST_ID, YOUTUBE_SEARCH_KEYWORD)
    video_ids = [video[0] for video in videos]

    video_details = fetch_video_details(youtube, video_ids)

    new_videos = []

    playlist_info = None
    if YOUTUBE_MODE == 'playlists':
        playlist_info = fetch_playlist_info(youtube, YOUTUBE_PLAYLIST_ID)

    for video_detail in video_details:
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']
        live_streaming_details = video_detail.get('liveStreamingDetails', {})

        video_id = video_detail['id']
        published_at = snippet['publishedAt']
        
        if video_id in existing_video_ids:
            logging.info(f"이미 존재하는 비디오 건너뛰기: {video_id}")
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
        
        if YOUTUBE_DETAILVIEW:
            logging.info(f"YOUTUBE_DETAILVIEW가 True입니다. 임베드 메시지 생성 및 전송 시도")
            try:
                embed_message = create_embed_message(video, youtube)
                logging.info(f"임베드 메시지 생성 완료: {video['title']}")
                time.sleep(1)  # Discord 웹훅 속도 제한 방지를 위한 대기
                post_to_discord(embed_message, is_embed=True, is_detail=True)
                logging.info(f"임베드 메시지 전송 완료: {video['title']}")
            except Exception as e:
                logging.error(f"임베드 메시지 생성 또는 전송 중 오류 발생: {e}")
        else:
            logging.info("YOUTUBE_DETAILVIEW가 False이므로 임베드 메시지를 전송하지 않습니다.")
        
        save_video(video)
        logging.info(f"비디오 정보 저장 완료: {video['title']}")

    logging.info("fetch_and_post_videos 함수 종료")

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
        logging.info(f"YOUTUBE_DETAILVIEW: {YOUTUBE_DETAILVIEW}")
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