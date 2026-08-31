"""Safe YouTube selection, checkpoints, and resumable Discord delivery state."""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple


DISCORD_MESSAGE_ID = re.compile(r"^[0-9]+$")


def partition_youtube_items(
    items: Sequence[dict],
    baseline_only: bool,
    manual_test: bool,
    delivery_order: str = "feed_oldest_first",
) -> Tuple[List[dict], List[dict]]:
    prepared = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid YouTube item")
        prepared.append(item)
    if delivery_order == "feed_oldest_first":
        ordered = list(reversed(prepared))
    elif delivery_order == "feed_newest_first":
        ordered = list(prepared)
    else:
        raise ValueError("invalid delivery order")
    if manual_test and prepared:
        return [prepared[0]], prepared[1:]
    if baseline_only:
        return [], ordered
    return ordered, []


def initialize_delivery_state(db_path: str) -> None:
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(videos)").fetchall()
        }
        if "video_id" not in columns:
            raise ValueError("videos table is missing")
        if "delivery_status" not in columns:
            connection.execute(
                "ALTER TABLE videos ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'sent'"
            )
        if "delivery_sequence" not in columns:
            connection.execute("ALTER TABLE videos ADD COLUMN delivery_sequence INTEGER")
        if "filter_fingerprint" not in columns:
            connection.execute("ALTER TABLE videos ADD COLUMN filter_fingerprint TEXT")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS youtube_delivery_targets ("
            "video_id TEXT NOT NULL, target TEXT NOT NULL, payload_json TEXT NOT NULL, "
            "status TEXT NOT NULL, discord_message_id TEXT, attempt_count INTEGER NOT NULL DEFAULT 0, "
            "last_error_code TEXT, PRIMARY KEY (video_id, target))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS youtube_source_state ("
            "state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL)"
        )


def queue_youtube_delivery(
    db_path: str,
    video_id: str,
    targets: Sequence[Tuple[str, Dict]],
    video_data: Optional[Dict] = None,
) -> None:
    if not isinstance(video_id, str) or not video_id:
        raise ValueError("invalid video id")
    prepared = []
    for target, payload in targets:
        if target not in {"primary", "detail"} or not isinstance(payload, dict):
            raise ValueError("invalid YouTube delivery target")
        prepared.append((target, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    if not prepared:
        raise ValueError("missing YouTube delivery targets")
    if video_data is not None and video_data.get("video_id") != video_id:
        raise ValueError("YouTube video reservation id mismatch")

    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if video_data is not None:
            _upsert_youtube_video(connection, video_data, "pending")
        row = connection.execute(
            "SELECT delivery_status, delivery_sequence FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if row is None:
            raise ValueError("video reservation not found")
        sequence = row[1]
        if sequence is None:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(delivery_sequence), 0) + 1 FROM videos"
            ).fetchone()[0]
        connection.execute(
            "UPDATE videos SET delivery_status = 'pending', delivery_sequence = ? "
            "WHERE video_id = ?",
            (sequence, video_id),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO youtube_delivery_targets "
            "(video_id, target, payload_json, status) VALUES (?, ?, ?, 'pending')",
            [(video_id, target, payload_json) for target, payload_json in prepared],
        )


def save_youtube_video(
    db_path: str,
    video_data: Dict,
    delivery_status: str = "sent",
) -> None:
    if delivery_status not in {"filtered", "pending", "sent"}:
        raise ValueError("invalid YouTube delivery status")
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        _upsert_youtube_video(connection, video_data, delivery_status)


def is_youtube_item_handled(
    db_path: str,
    video_id: str,
    filter_fingerprint: Optional[str] = None,
) -> bool:
    if not isinstance(video_id, str) or not video_id:
        raise ValueError("invalid video id")
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT delivery_status, filter_fingerprint FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    if row is None:
        return False
    status, stored_fingerprint = row
    if status == "filtered" and filter_fingerprint is not None:
        return stored_fingerprint == filter_fingerprint
    return status in {"filtered", "pending", "sent"}


def record_filtered_youtube_video(
    db_path: str,
    video_data: Dict,
    filter_fingerprint: str,
) -> None:
    if not isinstance(filter_fingerprint, str) or not filter_fingerprint:
        raise ValueError("invalid filter fingerprint")
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        _upsert_youtube_video(
            connection,
            video_data,
            "filtered",
            filter_fingerprint=filter_fingerprint,
        )


def _upsert_youtube_video(
    connection: sqlite3.Connection,
    video_data: Dict,
    delivery_status: str,
    filter_fingerprint: Optional[str] = None,
) -> None:
    required_fields = (
        "published_at",
        "channel_title",
        "channel_id",
        "title",
        "video_id",
        "video_url",
        "description",
        "category_id",
        "category_name",
        "duration",
        "thumbnail_url",
        "tags",
        "live_broadcast_content",
        "scheduled_start_time",
        "caption",
        "source",
    )
    try:
        values = tuple(video_data[field] for field in required_fields)
    except (KeyError, TypeError):
        raise ValueError("invalid YouTube video data") from None
    connection.execute(
        "INSERT INTO videos ("
        "published_at, channel_title, channel_id, title, video_id, video_url, "
        "description, category_id, category_name, duration, thumbnail_url, tags, "
        "live_broadcast_content, scheduled_start_time, caption, source, delivery_status, "
        "filter_fingerprint"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(video_id) DO UPDATE SET "
        "published_at=excluded.published_at, "
        "channel_title=excluded.channel_title, "
        "channel_id=excluded.channel_id, "
        "title=excluded.title, "
        "video_url=excluded.video_url, "
        "description=excluded.description, "
        "category_id=excluded.category_id, "
        "category_name=excluded.category_name, "
        "duration=excluded.duration, "
        "thumbnail_url=excluded.thumbnail_url, "
        "tags=excluded.tags, "
        "live_broadcast_content=excluded.live_broadcast_content, "
        "scheduled_start_time=excluded.scheduled_start_time, "
        "caption=excluded.caption, "
        "source=excluded.source, "
        "delivery_status=CASE "
        "WHEN videos.delivery_status IN ('pending', 'sent') THEN videos.delivery_status "
        "ELSE excluded.delivery_status END, "
        "filter_fingerprint=CASE "
        "WHEN videos.delivery_status IN ('pending', 'sent') THEN videos.filter_fingerprint "
        "ELSE excluded.filter_fingerprint END",
        values + (delivery_status, filter_fingerprint),
    )


def pending_youtube_video_ids(db_path: str) -> List[str]:
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT video_id FROM videos WHERE delivery_status = 'pending' "
            "ORDER BY delivery_sequence, rowid"
        ).fetchall()
    return [row[0] for row in rows]


def pending_youtube_targets(db_path: str, video_id: str) -> List[Tuple[str, Dict]]:
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT target, payload_json FROM youtube_delivery_targets "
            "WHERE video_id = ? AND status = 'pending' "
            "ORDER BY CASE target WHEN 'primary' THEN 0 ELSE 1 END",
            (video_id,),
        ).fetchall()
    return [(target, json.loads(payload_json)) for target, payload_json in rows]


def mark_youtube_target_sent(
    db_path: str,
    video_id: str,
    target: str,
    message_id: str,
    last_error_code: Optional[str] = None,
    attempt_count: int = 1,
) -> None:
    if not isinstance(message_id, str) or not DISCORD_MESSAGE_ID.fullmatch(message_id):
        raise ValueError("invalid Discord message id")
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            "UPDATE youtube_delivery_targets SET status = 'sent', discord_message_id = ?, "
            "attempt_count = attempt_count + ?, "
            "last_error_code = CASE WHEN last_error_code = 'ambiguous_retry' "
            "THEN last_error_code ELSE ? END "
            "WHERE video_id = ? AND target = ? AND status = 'pending'",
            (
                message_id,
                max(1, int(attempt_count)),
                last_error_code,
                video_id,
                target,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("YouTube delivery target not found")


def mark_youtube_target_failed(
    db_path: str,
    video_id: str,
    target: str,
    error_code: str,
    attempt_count: int = 1,
) -> None:
    if error_code not in {"ambiguous_retry", "final_failure"}:
        error_code = "final_failure"
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            "UPDATE youtube_delivery_targets SET attempt_count = attempt_count + ?, "
            "last_error_code = ? WHERE video_id = ? AND target = ? AND status = 'pending'",
            (max(1, int(attempt_count)), error_code, video_id, target),
        )
        if cursor.rowcount != 1:
            raise ValueError("YouTube delivery target not found")


def finalize_youtube_delivery(db_path: str, video_id: str) -> bool:
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        counts = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) "
            "FROM youtube_delivery_targets WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if int(counts[0] or 0) == 0 or int(counts[1] or 0):
            return False
        connection.execute(
            "UPDATE videos SET delivery_status = 'sent' WHERE video_id = ?",
            (video_id,),
        )
        return True


def youtube_delivery_metrics(db_path: str) -> Dict[str, int]:
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        pending = connection.execute(
            "SELECT COUNT(*) FROM videos WHERE delivery_status = 'pending'"
        ).fetchone()[0]
        ambiguous = connection.execute(
            "SELECT COUNT(*) FROM youtube_delivery_targets "
            "WHERE last_error_code = 'ambiguous_retry'"
        ).fetchone()[0]
    return {
        "pending_count": int(pending),
        "ambiguous_retry_count": int(ambiguous),
    }


def get_search_published_after(
    db_path: str,
    overlap_hours: int = 24,
) -> Optional[str]:
    if overlap_hours < 0:
        raise ValueError("invalid checkpoint overlap")
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT state_value FROM youtube_source_state "
            "WHERE state_key = 'search_success_checkpoint'"
        ).fetchone()
    if row is None:
        return None
    checkpoint = _parse_utc(row[0]) - timedelta(hours=overlap_hours)
    return checkpoint.strftime("%Y-%m-%dT%H:%M:%SZ")


def mark_search_checkpoint(db_path: str, checkpoint: str) -> None:
    parsed = _parse_utc(checkpoint)
    value = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    initialize_delivery_state(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO youtube_source_state (state_key, state_value) "
            "VALUES ('search_success_checkpoint', ?) "
            "ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value",
            (value,),
        )


def _parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except (AttributeError, ValueError):
        raise ValueError("invalid search checkpoint") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid search checkpoint")
    return parsed.astimezone(timezone.utc)
