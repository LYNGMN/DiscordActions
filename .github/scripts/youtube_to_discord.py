import os
import html
import time
import sqlite3
from googleapiclient.discovery import build
import isodate
from datetime import datetime, timezone, timedelta
import logging
import re
import json
import sys
from delivery_admin_alert import notify_admin
from youtube_delivery_state import (
    finalize_youtube_delivery,
    get_search_published_after,
    initialize_delivery_state,
    mark_search_checkpoint,
    mark_youtube_target_failed,
    mark_youtube_target_sent,
    partition_youtube_items,
    pending_youtube_targets,
    pending_youtube_video_ids,
    queue_youtube_delivery,
    save_youtube_video,
    youtube_delivery_metrics,
)
from youtube_discord_delivery import YOUTUBE_AVATAR_URL, send_youtube_webhook
from youtube_video_source import (
    fetch_source_videos,
    fetch_video_details as fetch_source_video_details,
)

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
YOUTUBE_MODE = os.getenv('YOUTUBE_MODE', 'channels').lower()
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_PLAYLIST_ID = os.getenv('YOUTUBE_PLAYLIST_ID')
YOUTUBE_SEARCH_KEYWORD = os.getenv('YOUTUBE_SEARCH_KEYWORD')
INITIALIZE_MODE_YOUTUBE = os.getenv('INITIALIZE_MODE_YOUTUBE', 'false').lower() == 'true'
ADVANCED_FILTER_YOUTUBE = os.getenv('ADVANCED_FILTER_YOUTUBE', '')
DATE_FILTER_YOUTUBE = os.getenv('DATE_FILTER_YOUTUBE', '')
DISCORD_WEBHOOK_YOUTUBE = os.getenv('DISCORD_WEBHOOK_YOUTUBE')
DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW = os.getenv('DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW')
DISCORD_WEBHOOK_ADMIN = os.getenv('DISCORD_WEBHOOK_ADMIN', '')
LANGUAGE_YOUTUBE = os.getenv('LANGUAGE_YOUTUBE', 'English')
YOUTUBE_DETAILVIEW = os.getenv('YOUTUBE_DETAILVIEW', 'false').lower() == 'true'
YOUTUBE_BASELINE_ONLY = os.getenv('YOUTUBE_BASELINE_ONLY', 'false').lower() == 'true'
YOUTUBE_MANUAL_TEST_MODE = os.getenv('YOUTUBE_MANUAL_TEST_MODE', 'false').lower() == 'true'
YOUTUBE_DELIVERY_ORDER = os.getenv(
    'YOUTUBE_DELIVERY_ORDER', 'feed_oldest_first'
).lower()
YOUTUBE_RUN_SUMMARY_PATH = os.getenv(
    'YOUTUBE_RUN_SUMMARY_PATH', 'youtube-run-summary.json'
)

# DB 설정
DB_PATH = os.getenv('YOUTUBE_DB_PATH', 'youtube_videos.db')

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
        c.execute("DROP TABLE IF EXISTS youtube_delivery_targets")
        c.execute("DROP TABLE IF EXISTS youtube_source_state")
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
                  source TEXT,
                  delivery_status TEXT NOT NULL DEFAULT 'sent',
                  delivery_sequence INTEGER)''')
    conn.commit()
    conn.close()
    initialize_delivery_state(DB_PATH)
    logging.info("데이터베이스 초기화 완료")

def save_video(video_data, delivery_status='sent'):
    save_youtube_video(DB_PATH, video_data, delivery_status)
    logging.info(f"새 비디오 저장됨: {video_data['video_id']}")

def get_channel_thumbnail(youtube, channel_id):
    try:
        response = youtube.channels().list(
            part="snippet",
            id=channel_id
        ).execute()
        return response['items'][0]['snippet']['thumbnails']['default']['url']
    except Exception as error:
        logging.error("채널 썸네일 조회 실패 (오류 유형: %s)", type(error).__name__)
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
            "icon_url": YOUTUBE_AVATAR_URL
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

def deliver_queued_video(video_id):
    for target, payload in pending_youtube_targets(DB_PATH, video_id):
        webhook_url = (
            DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW
            if target == 'detail' and DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW
            else DISCORD_WEBHOOK_YOUTUBE
        )
        try:
            result = send_youtube_webhook(webhook_url, payload)
        except Exception as error:
            error_code = getattr(error, 'error_code', 'final_failure')
            mark_youtube_target_failed(
                DB_PATH,
                video_id,
                target,
                error_code,
                attempt_count=getattr(error, 'attempt_count', 1),
            )
            print("::warning title=YouTube delivery failed::A queued delivery remains pending")
            notify_admin(
                DISCORD_WEBHOOK_ADMIN,
                'YouTube',
                YOUTUBE_MODE,
                video_id,
                error_code,
            )
            raise
        error_code = 'ambiguous_retry' if result.ambiguous_retry else None
        if error_code:
            logging.warning(
                "Discord 응답 불명 재전송 완료: video_id=%s target=%s",
                video_id,
                target,
            )
            print("::warning title=YouTube ambiguous retry::A response-unknown delivery was retried")
            notify_admin(
                DISCORD_WEBHOOK_ADMIN,
                'YouTube',
                YOUTUBE_MODE,
                video_id,
                error_code,
            )
        mark_youtube_target_sent(
            DB_PATH,
            video_id,
            target,
            result.message_id,
            last_error_code=error_code,
            attempt_count=result.attempt_count,
        )
        logging.info("Discord 전송 완료: video_id=%s target=%s", video_id, target)
        time.sleep(2)
    if not finalize_youtube_delivery(DB_PATH, video_id):
        raise RuntimeError("youtube_delivery_not_complete")


def resume_pending_deliveries():
    pending_ids = pending_youtube_video_ids(DB_PATH)
    if pending_ids:
        logging.info("미완료 YouTube 전송 재개: %s개", len(pending_ids))
    for video_id in pending_ids:
        deliver_queued_video(video_id)


def write_run_summary(status):
    metrics = {
        'pending_count': 0,
        'ambiguous_retry_count': 0,
    }
    if os.path.exists(DB_PATH):
        metrics = youtube_delivery_metrics(DB_PATH)
    payload = {
        'status': status,
        'pending_count': metrics['pending_count'],
        'ambiguous_retry_count': metrics['ambiguous_retry_count'],
    }
    with open(YOUTUBE_RUN_SUMMARY_PATH, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write('\n')

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

def fetch_videos(
    youtube,
    mode,
    channel_id,
    playlist_id,
    search_keyword,
    known_video_ids=None,
):
    published_after = (
        get_search_published_after(DB_PATH) if mode == 'search' else None
    )
    try:
        return fetch_source_videos(
            youtube,
            mode,
            channel_id=channel_id,
            playlist_id=playlist_id,
            search_keyword=search_keyword,
            published_after=published_after,
            known_video_ids=known_video_ids,
        )
    except Exception as error:
        logging.error("YouTube 목록 조회 실패 (오류 유형: %s)", type(error).__name__)
        raise RuntimeError("youtube_source_fetch_failed") from None

def fetch_video_details(youtube, video_ids):
    try:
        return fetch_source_video_details(youtube, video_ids)
    except Exception as error:
        logging.error("비디오 세부 정보 조회 실패 (오류 유형: %s)", type(error).__name__)
        raise RuntimeError("youtube_video_details_failed") from None

def fetch_and_post_videos(youtube):
    logging.info(f"fetch_and_post_videos 함수 시작")
    logging.info(f"YOUTUBE_DETAILVIEW 설정: {YOUTUBE_DETAILVIEW}")
    logging.info(f"YOUTUBE_DELIVERY_ORDER 설정: {YOUTUBE_DELIVERY_ORDER}")

    if not os.path.exists(DB_PATH):
        init_db()
    else:
        initialize_delivery_state(DB_PATH)

    # 저장된 payload를 먼저 처리하므로 피드에서 사라진 항목도 누락되지 않습니다.
    resume_pending_deliveries()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT video_id FROM videos WHERE delivery_status = 'sent'")
    existing_video_ids = set(row[0] for row in c.fetchall())
    conn.close()

    since_date, until_date, past_date = parse_date_filter(DATE_FILTER_YOUTUBE)

    scan_checkpoint = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    videos = fetch_videos(
        youtube,
        YOUTUBE_MODE,
        YOUTUBE_CHANNEL_ID,
        YOUTUBE_PLAYLIST_ID,
        YOUTUBE_SEARCH_KEYWORD,
        known_video_ids=existing_video_ids,
    )
    video_ids = [video[0] for video in videos]

    video_details = fetch_video_details(youtube, video_ids)

    # 비디오 세부 정보를 딕셔너리로 변환
    video_details_dict = {video['id']: video for video in video_details}

    new_videos = []

    playlist_info = None
    if YOUTUBE_MODE == 'playlists':
        playlist_info = fetch_playlist_info(youtube, YOUTUBE_PLAYLIST_ID)

    # videos 리스트의 순서를 유지하면서 처리
    for video_id, snippet in videos:
        if video_id not in video_details_dict:
            logging.warning(f"비디오 세부 정보를 찾을 수 없음: {video_id}")
            continue

        video_detail = video_details_dict[video_id]
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']
        live_streaming_details = video_detail.get('liveStreamingDetails', {})

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

    delivery_videos, baseline_videos = partition_youtube_items(
        new_videos,
        baseline_only=YOUTUBE_BASELINE_ONLY,
        manual_test=YOUTUBE_MANUAL_TEST_MODE,
        delivery_order=YOUTUBE_DELIVERY_ORDER,
    )
    logging.info(
        "새 비디오 선별 완료: 전송 %s개, 기준선 %s개",
        len(delivery_videos),
        len(baseline_videos),
    )

    for video in baseline_videos:
        save_video(video)
    if baseline_videos:
        logging.info("안전 기준선 저장 완료: %s개", len(baseline_videos))

    queued_videos = []
    for video in delivery_videos:
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

        targets = [('primary', {'content': message})]
        if YOUTUBE_DETAILVIEW:
            logging.info(f"YOUTUBE_DETAILVIEW가 True입니다. 임베드 메시지 생성 및 전송 시도")
            embed_message = create_embed_message(video, youtube)
            targets.append(('detail', embed_message))
            logging.info(f"임베드 메시지 생성 완료: {video['title']}")
        else:
            logging.info("YOUTUBE_DETAILVIEW가 False이므로 임베드 메시지를 전송하지 않습니다.")

        # 첫 Discord 요청 전에 영상과 모든 대상 payload를 원자적으로 준비합니다.
        queue_youtube_delivery(
            DB_PATH,
            video['video_id'],
            targets,
            video_data=video,
        )
        queued_videos.append((video['video_id'], video['title']))
        logging.info(f"비디오 대기열 저장 완료: {video['title']}")

    for video_id, video_title in queued_videos:
        deliver_queued_video(video_id)
        logging.info(f"비디오 전송 완료: {video_title}")

    if YOUTUBE_MODE == 'search':
        mark_search_checkpoint(DB_PATH, scan_checkpoint)
    logging.info("fetch_and_post_videos 함수 종료")

if __name__ == "__main__":
    run_status = 'failed'
    try:
        check_env_variables()
        if INITIALIZE_MODE_YOUTUBE:
            init_db(reset=True)
            logging.info("초기화 모드로 실행 중: 데이터베이스를 재설정하고 모든 비디오를 다시 가져옵니다.")
        
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        
        fetch_and_post_videos(youtube)
        
        logging.info(f"YOUTUBE_MODE: {YOUTUBE_MODE}")
        logging.info(f"INITIALIZE_MODE_YOUTUBE: {INITIALIZE_MODE_YOUTUBE}")
        logging.info(f"YOUTUBE_DETAILVIEW: {YOUTUBE_DETAILVIEW}")
        logging.info(f"데이터베이스 파일 크기: {os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else '파일 없음'}")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM videos")
        count = c.fetchone()[0]
        logging.info(f"데이터베이스의 비디오 수: {count}")
        conn.close()
        run_status = 'success'
        
    except Exception as error:
        logging.error("실행 실패 (오류 유형: %s)", type(error).__name__)
        sys.exit(1)
    finally:
        try:
            write_run_summary(run_status)
        except Exception as error:
            logging.error("실행 요약 저장 실패 (오류 유형: %s)", type(error).__name__)
        logging.info("스크립트 실행 완료")
