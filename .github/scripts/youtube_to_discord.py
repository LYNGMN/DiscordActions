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
from feed_filters import (
    compile_feed_filter,
    resolve_feed_date_filter,
    resolve_feed_keyword_filter,
    resolve_feed_timezone,
)
from feed_localization import normalize_display_language
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
    record_filtered_youtube_video,
    save_youtube_video,
    is_youtube_item_handled,
    youtube_delivery_metrics,
)
from youtube_discord_delivery import YOUTUBE_AVATAR_URL, send_youtube_webhook
from youtube_messages import build_youtube_message, resolve_playlist_layout
from youtube_video_source import (
    fetch_rss_videos,
    fetch_source_videos,
    fetch_video_details as fetch_source_video_details,
)

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
YOUTUBE_SOURCE = os.getenv('YOUTUBE_SOURCE', 'api').lower()
YOUTUBE_MODE = os.getenv('YOUTUBE_MODE', 'channels').lower()
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_PLAYLIST_ID = os.getenv('YOUTUBE_PLAYLIST_ID')
YOUTUBE_SEARCH_KEYWORD = os.getenv('YOUTUBE_SEARCH_KEYWORD')
INITIALIZE_MODE_YOUTUBE = os.getenv('INITIALIZE_MODE_YOUTUBE', 'false').lower() == 'true'
ADVANCED_FILTER_YOUTUBE = os.getenv('ADVANCED_FILTER_YOUTUBE', '')
DATE_FILTER_YOUTUBE = os.getenv('DATE_FILTER_YOUTUBE', '')
FEED_DATE_FILTER = os.getenv('FEED_DATE_FILTER', '')
FEED_KEYWORD_FILTER = os.getenv('FEED_KEYWORD_FILTER', '')
FEED_KEYWORD_SCOPE = os.getenv('FEED_KEYWORD_SCOPE', 'title').lower()
FEED_TIMEZONE = os.getenv('FEED_TIMEZONE', '')
FEED_COUNTRY = os.getenv('FEED_COUNTRY', '')
YOUTUBE_SERVICE_TIMEZONE = os.getenv('YOUTUBE_SERVICE_TIMEZONE', '')
YOUTUBE_REGION_CODE = os.getenv('YOUTUBE_REGION_CODE', '')
DISCORD_WEBHOOK_YOUTUBE = os.getenv('DISCORD_WEBHOOK_YOUTUBE')
DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW = os.getenv('DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW')
DISCORD_WEBHOOK_ADMIN = os.getenv('DISCORD_WEBHOOK_ADMIN', '')
LANGUAGE_YOUTUBE = os.getenv('LANGUAGE_YOUTUBE', 'English')
DISPLAY_LANGUAGE = os.getenv('DISPLAY_LANGUAGE', '') or LANGUAGE_YOUTUBE
YOUTUBE_DETAILVIEW = os.getenv('YOUTUBE_DETAILVIEW', 'false').lower() == 'true'
YOUTUBE_PLAYLIST_LAYOUT = os.getenv('YOUTUBE_PLAYLIST_LAYOUT', 'auto').lower()
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
    if YOUTUBE_SOURCE not in {'rss', 'api'}:
        raise ValueError("YOUTUBE_SOURCE must be 'rss' or 'api'")
    if not DISCORD_WEBHOOK_YOUTUBE:
        raise ValueError("DISCORD_WEBHOOK_YOUTUBE is required")
    if YOUTUBE_SOURCE == 'api' and not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY is required for the API source")
    if YOUTUBE_MODE not in ['channels', 'playlists', 'search']:
        raise ValueError("invalid YOUTUBE_MODE")
    if YOUTUBE_SOURCE == 'rss' and YOUTUBE_MODE == 'search':
        raise ValueError("YouTube RSS does not support search mode")
    if YOUTUBE_SOURCE == 'rss' and YOUTUBE_DETAILVIEW:
        raise ValueError("YouTube RSS does not support YOUTUBE_DETAILVIEW")
    if YOUTUBE_MODE == 'channels':
        if not YOUTUBE_CHANNEL_ID:
            raise ValueError("YOUTUBE_CHANNEL_ID is required")
    elif YOUTUBE_MODE == 'playlists':
        if not YOUTUBE_PLAYLIST_ID:
            raise ValueError("YOUTUBE_PLAYLIST_ID is required")
    elif YOUTUBE_MODE == 'search':
        if not YOUTUBE_SEARCH_KEYWORD:
            raise ValueError("YOUTUBE_SEARCH_KEYWORD is required")
    normalize_display_language(DISPLAY_LANGUAGE)
    resolve_playlist_layout(YOUTUBE_PLAYLIST_LAYOUT, [])
    compile_runtime_feed_filter()


def compile_runtime_feed_filter():
    display_language = normalize_display_language(DISPLAY_LANGUAGE)
    timezone_name = resolve_feed_timezone(
        explicit_timezone=FEED_TIMEZONE,
        service_timezone=YOUTUBE_SERVICE_TIMEZONE,
        country_code=FEED_COUNTRY or YOUTUBE_REGION_CODE,
    )
    date_filter = resolve_feed_date_filter(FEED_DATE_FILTER, DATE_FILTER_YOUTUBE)
    keyword_filter = resolve_feed_keyword_filter(
        FEED_KEYWORD_FILTER,
        ADVANCED_FILTER_YOUTUBE,
    )
    return compile_feed_filter(
        date_filter=date_filter,
        keyword_filter=keyword_filter,
        keyword_scope=FEED_KEYWORD_SCOPE,
        timezone_name=timezone_name,
        display_language=display_language,
    )

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
                  delivery_sequence INTEGER,
                  filter_fingerprint TEXT)''')
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
    if hours > 0:
        return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)
    return "{:02d}:{:02d}".format(minutes, seconds)

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
def get_category_name(
    youtube,
    category_id,
    display_language=None,
    region_code=None,
):
    language = normalize_display_language(display_language or DISPLAY_LANGUAGE)
    region = (region_code or YOUTUBE_REGION_CODE or 'US').upper()
    cache_key = (language, region, category_id)
    if cache_key in category_cache:
        return category_cache[cache_key]
    try:
        categories = youtube.videoCategories().list(
            part="snippet",
            regionCode=region,
            hl=language,
        ).execute()
    except Exception as error:
        print(
            "Warning: optional YouTube category lookup failed ({})".format(
                type(error).__name__
            )
        )
        return ""
    for category in categories.get('items', []):
        current_id = category.get('id', '')
        current_title = (category.get('snippet') or {}).get('title', '')
        if not current_id or not current_title:
            continue
        current_key = (language, region, current_id)
        category_cache[current_key] = current_title
        if current_id == category_id:
            return current_title
    return ""

def fetch_playlist_info(youtube, playlist_id):
    playlist_response = youtube.playlists().list(
        part="snippet",
        id=playlist_id
    ).execute()
    
    if 'items' in playlist_response and playlist_response['items']:
        playlist_info = playlist_response['items'][0]['snippet']
        return {
            'title': playlist_info['title'],
            'owner_title': playlist_info['channelTitle']
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


def _best_thumbnail(snippet):
    thumbnails = snippet.get('thumbnails') or {}
    for name in ('maxres', 'standard', 'high', 'medium', 'default'):
        candidate = thumbnails.get(name) or {}
        url = candidate.get('url')
        if isinstance(url, str) and url.strip():
            return url.strip()
    raise ValueError("YouTube video thumbnail is missing")


def _api_video_data(youtube, video_detail):
    try:
        video_id = video_detail['id']
        snippet = video_detail['snippet']
        content_details = video_detail['contentDetails']
        published_at = snippet['publishedAt']
        channel_title = html.unescape(snippet['channelTitle'])
        channel_id = snippet['channelId']
        title = html.unescape(snippet['title'])
    except (KeyError, TypeError):
        raise ValueError("invalid YouTube API video item") from None
    category_id = snippet.get('categoryId', '')
    category_name = (
        get_category_name(
            youtube,
            category_id,
            display_language=normalize_display_language(DISPLAY_LANGUAGE),
            region_code=FEED_COUNTRY or YOUTUBE_REGION_CODE or 'US',
        )
        if category_id
        else ''
    )
    live_details = video_detail.get('liveStreamingDetails') or {}
    return {
        'published_at': published_at,
        'channel_title': channel_title,
        'channel_id': channel_id,
        'title': title,
        'video_id': video_id,
        'video_url': "https://youtu.be/{}".format(video_id),
        'description': html.unescape(snippet.get('description', '')),
        'category_id': category_id,
        'category_name': category_name,
        'duration': parse_duration(content_details['duration']),
        'thumbnail_url': _best_thumbnail(snippet),
        'tags': ','.join(snippet.get('tags', [])),
        'live_broadcast_content': snippet.get('liveBroadcastContent', ''),
        'scheduled_start_time': live_details.get('scheduledStartTime', ''),
        'caption': content_details.get('caption', ''),
        'source': 'api:{}'.format(YOUTUBE_MODE),
    }


def fetch_configured_video_data(youtube, known_video_ids):
    if YOUTUBE_SOURCE == 'rss':
        try:
            items, metadata = fetch_rss_videos(
                YOUTUBE_MODE,
                channel_id=YOUTUBE_CHANNEL_ID,
                playlist_id=YOUTUBE_PLAYLIST_ID,
            )
        except Exception as error:
            logging.error("YouTube RSS fetch failed (error type: %s)", type(error).__name__)
            raise RuntimeError("youtube_source_fetch_failed") from None
        return items, metadata

    videos = fetch_videos(
        youtube,
        YOUTUBE_MODE,
        YOUTUBE_CHANNEL_ID,
        YOUTUBE_PLAYLIST_ID,
        YOUTUBE_SEARCH_KEYWORD,
        known_video_ids=known_video_ids,
    )
    video_ids = [video[0] for video in videos]
    details = fetch_video_details(youtube, video_ids)
    details_by_id = {item.get('id'): item for item in details if isinstance(item, dict)}
    missing = [video_id for video_id in video_ids if video_id not in details_by_id]
    if missing:
        raise RuntimeError("youtube_video_details_incomplete")
    items = [_api_video_data(youtube, details_by_id[video_id]) for video_id in video_ids]
    metadata = None
    if YOUTUBE_MODE == 'playlists':
        metadata = fetch_playlist_info(youtube, YOUTUBE_PLAYLIST_ID)
        if metadata is None:
            raise RuntimeError("youtube_playlist_metadata_missing")
    return items, metadata


def fetch_and_post_videos(youtube):
    logging.info("YouTube feed processing started")
    compiled_filter = compile_runtime_feed_filter()
    display_language = normalize_display_language(DISPLAY_LANGUAGE)

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

    scan_checkpoint = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_items, playlist_info = fetch_configured_video_data(
        youtube,
        existing_video_ids,
    )
    new_videos = []
    source_channel_titles = [item['channel_title'] for item in source_items]
    for video_data in source_items:
        video_id = video_data['video_id']
        if is_youtube_item_handled(
            DB_PATH,
            video_id,
            compiled_filter.fingerprint,
        ):
            logging.info("Skipping handled YouTube video: %s", video_id)
            continue
        result = compiled_filter.matches(
            video_data['published_at'],
            video_data['title'],
            video_data['description'],
        )
        if not result.matched:
            record_filtered_youtube_video(
                DB_PATH,
                video_data,
                compiled_filter.fingerprint,
            )
            logging.info(
                "YouTube video excluded by %s filter: %s",
                result.reason,
                video_id,
            )
            continue
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
    playlist_layout = resolve_playlist_layout(
        YOUTUBE_PLAYLIST_LAYOUT,
        source_channel_titles,
    )
    for video in delivery_videos:
        message = build_youtube_message(
            video,
            source_type=YOUTUBE_MODE,
            display_language=display_language,
            timezone_name=compiled_filter.timezone_name,
            include_api_details=YOUTUBE_SOURCE == 'api',
            playlist=playlist_info,
            playlist_layout=playlist_layout,
            search_keyword=YOUTUBE_SEARCH_KEYWORD or '',
        )

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
    logging.info("YouTube feed processing completed")

if __name__ == "__main__":
    run_status = 'failed'
    try:
        check_env_variables()
        if INITIALIZE_MODE_YOUTUBE:
            init_db(reset=True)
            logging.info("초기화 모드로 실행 중: 데이터베이스를 재설정하고 모든 비디오를 다시 가져옵니다.")
        
        youtube = (
            build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
            if YOUTUBE_SOURCE == 'api'
            else None
        )
        
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
