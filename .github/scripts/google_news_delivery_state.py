"""Bounded article selection and crash-safe Discord delivery state."""

import hashlib
import html
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree.ElementTree import Element

from google_news_manual_test import prepare_baseline_item


DISCORD_MESSAGE_ID = re.compile(r"^[0-9]+$")
TRACKING_QUERY_KEYS = {
    "dclid",
    "fbclid",
    "gclid",
    "msclkid",
    "oc",
    "ved",
}


@dataclass(frozen=True)
class QueueDeliveryOutcome:
    ambiguous_retry_count: int


def prepare_scheduled_items(
    items: Sequence[Element],
    db_path: str,
    now: Optional[datetime] = None,
    max_items: Optional[int] = None,
    max_age_minutes: Optional[int] = None,
    delivery_order: str = "feed_oldest_first",
) -> List[Element]:
    item_list = list(items)
    if delivery_order == "feed_oldest_first":
        item_list.reverse()
    elif delivery_order != "feed_newest_first":
        raise ValueError("invalid delivery order")
    return item_list


def is_item_handled(
    db_path: str,
    guid: str,
    filter_fingerprint: Optional[str] = None,
) -> bool:
    if not isinstance(guid, str) or not guid.strip():
        raise ValueError("invalid delivery guid")
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        row = connection.execute(
            "SELECT delivery_status, filter_fingerprint FROM news_items WHERE guid = ?",
            (guid,),
        ).fetchone()
    if row is None:
        return False
    status, stored_fingerprint = row
    if status in {"pending", "retryable"}:
        return False
    if status == "filtered" and filter_fingerprint is not None:
        return stored_fingerprint == filter_fingerprint
    return True


def record_filtered_item(
    db_path: str,
    item: Element,
    filter_fingerprint: str,
) -> None:
    if not isinstance(filter_fingerprint, str) or not filter_fingerprint:
        raise ValueError("invalid filter fingerprint")
    _published_at, baseline_row = prepare_baseline_item(item)
    pub_date, guid, title, link, related_news = baseline_row
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        connection.execute(
            "INSERT OR IGNORE INTO news_items "
            "(pub_date, guid, title, link, related_news, delivery_status, filter_fingerprint) "
            "VALUES (?, ?, ?, ?, ?, 'filtered', ?)",
            (pub_date, guid, title, link, related_news, filter_fingerprint),
        )
        connection.execute(
            "UPDATE news_items SET pub_date = ?, title = ?, link = ?, related_news = ?, "
            "delivery_status = 'filtered', filter_fingerprint = ?, discord_message_id = NULL "
            "WHERE guid = ? AND "
            "(delivery_status IN ('filtered', 'retryable') OR delivery_status IS NULL)",
            (pub_date, title, link, related_news, filter_fingerprint, guid),
        )


def canonicalize_article_url(url: str) -> Optional[str]:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not hostname:
        return None
    if hostname == "news.google.com" or hostname.endswith(".news.google.com"):
        return None

    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else "{}:{}".format(hostname, port)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.casefold()
        if normalized_key.startswith("utm_") or normalized_key in TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def article_identity_keys(title: str, url: str) -> Tuple[str, ...]:
    values = []
    normalized_title = _normalize_title(title)
    if normalized_title:
        values.append("title:" + _sha256(normalized_title))
    canonical_url = canonicalize_article_url(url)
    if canonical_url:
        values.append("url:" + _sha256(canonical_url))
    return tuple(values)


def reserve_delivery(
    db_path: str,
    guid: str,
    title: str = "",
    link: str = "",
) -> bool:
    if not isinstance(guid, str) or not guid.strip():
        raise ValueError("invalid delivery guid")
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        _ensure_identity_table(connection)
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        return _reserve_delivery_in_connection(connection, guid, title, link)


def reserve_delivery_with_messages(
    db_path: str,
    guid: str,
    title: str,
    link: str,
    messages: Sequence[str],
) -> bool:
    if not isinstance(guid, str) or not guid.strip():
        raise ValueError("invalid delivery guid")
    prepared = list(messages)
    if not prepared or any(not isinstance(message, str) or not message for message in prepared):
        raise ValueError("invalid delivery messages")
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        _ensure_identity_table(connection)
        _ensure_message_table(connection)
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        if not _reserve_delivery_in_connection(connection, guid, title, link):
            return False
        connection.executemany(
            "INSERT OR IGNORE INTO google_news_delivery_messages "
            "(guid, sequence, content, status, attempt_count) "
            "VALUES (?, ?, ?, 'pending', 0)",
            [(guid, index, content) for index, content in enumerate(prepared)],
        )
        return True


def _reserve_delivery_in_connection(
    connection: sqlite3.Connection,
    guid: str,
    title: str,
    link: str,
) -> bool:
    _backfill_article_identities(connection)

    existing_guid = connection.execute(
        "SELECT delivery_status, delivery_sequence FROM news_items WHERE guid = ?",
        (guid,),
    ).fetchone()
    if existing_guid is not None and existing_guid[0] == "pending":
        if existing_guid[1] is None:
            connection.execute(
                "UPDATE news_items SET delivery_sequence = ? WHERE guid = ?",
                (_next_delivery_sequence(connection), guid),
            )
        return True
    if existing_guid is not None and existing_guid[0] not in {"filtered", "retryable"}:
        return False

    identity_keys = article_identity_keys(title, link)
    if identity_keys:
        placeholders = ",".join("?" for _ in identity_keys)
        existing_identity = connection.execute(
            "SELECT 1 FROM google_news_article_identity "
            "WHERE identity_key IN ({}) AND guid != ? LIMIT 1".format(placeholders),
            identity_keys + (guid,),
        ).fetchone()
        if existing_identity is not None:
            return False

    delivery_sequence = _next_delivery_sequence(connection)
    if existing_guid is None:
        connection.execute(
            "INSERT INTO news_items "
            "(guid, title, link, delivery_status, filter_fingerprint, delivery_sequence) "
            "VALUES (?, ?, ?, 'pending', NULL, ?)",
            (guid, title, link, delivery_sequence),
        )
    else:
        connection.execute(
            "DELETE FROM google_news_article_identity WHERE guid = ?",
            (guid,),
        )
        connection.execute(
            "UPDATE news_items SET title = ?, link = ?, delivery_status = 'pending', "
            "filter_fingerprint = NULL, discord_message_id = NULL, delivery_sequence = ? "
            "WHERE guid = ?",
            (title, link, delivery_sequence, guid),
        )
    created_at = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        "INSERT INTO google_news_article_identity "
        "(identity_key, guid, created_at) VALUES (?, ?, ?)",
        [(key, guid, created_at) for key in identity_keys],
    )
    return True


def mark_delivery_sent(db_path: str, guid: str, message_id: str) -> None:
    if not isinstance(message_id, str) or not DISCORD_MESSAGE_ID.fullmatch(message_id):
        raise ValueError("invalid Discord message id")
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        cursor = connection.execute(
            "UPDATE news_items "
            "SET delivery_status = 'sent', discord_message_id = ? "
            "WHERE guid = ?",
            (message_id, guid),
        )
        if cursor.rowcount != 1:
            raise ValueError("delivery reservation not found")


def enqueue_delivery_messages(
    db_path: str,
    guid: str,
    messages: Sequence[str],
) -> None:
    if not isinstance(guid, str) or not guid.strip():
        raise ValueError("invalid delivery guid")
    prepared = list(messages)
    if not prepared or any(not isinstance(message, str) or not message for message in prepared):
        raise ValueError("invalid delivery messages")
    with sqlite3.connect(db_path) as connection:
        _ensure_message_table(connection)
        reservation = connection.execute(
            "SELECT delivery_status FROM news_items WHERE guid = ?",
            (guid,),
        ).fetchone()
        if reservation is None or reservation[0] != "pending":
            raise ValueError("delivery reservation not found")
        connection.executemany(
            "INSERT OR IGNORE INTO google_news_delivery_messages "
            "(guid, sequence, content, status, attempt_count) "
            "VALUES (?, ?, ?, 'pending', 0)",
            [(guid, index, content) for index, content in enumerate(prepared)],
        )


def pending_delivery_messages(db_path: str, guid: str) -> List[Tuple[int, str]]:
    with sqlite3.connect(db_path) as connection:
        _ensure_message_table(connection)
        rows = connection.execute(
            "SELECT sequence, content FROM google_news_delivery_messages "
            "WHERE guid = ? AND status = 'pending' ORDER BY sequence",
            (guid,),
        ).fetchall()
    return [(int(sequence), content) for sequence, content in rows]


def pending_delivery_guids(db_path: str) -> List[str]:
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        _ensure_message_table(connection)
        connection.execute(
            "UPDATE news_items SET delivery_status = 'retryable', delivery_sequence = NULL "
            "WHERE delivery_status = 'pending' AND NOT EXISTS ("
            "SELECT 1 FROM google_news_delivery_messages AS messages "
            "WHERE messages.guid = news_items.guid)"
        )
        rows = connection.execute(
            "SELECT guid FROM news_items WHERE delivery_status = 'pending' "
            "ORDER BY CASE WHEN delivery_sequence IS NULL THEN 0 ELSE 1 END, "
            "delivery_sequence, rowid"
        ).fetchall()
    return [row[0] for row in rows]


def deliver_queued_item(
    db_path: str,
    guid: str,
    send_message: Callable[[str], str],
) -> QueueDeliveryOutcome:
    ambiguous_count = 0
    for sequence, content in pending_delivery_messages(db_path, guid):
        try:
            message_id = send_message(content)
        except Exception as error:
            mark_delivery_message_failed(
                db_path,
                guid,
                sequence,
                getattr(error, "error_code", "final_failure"),
                getattr(error, "attempt_count", 1),
            )
            raise
        ambiguous = bool(getattr(message_id, "ambiguous_retry", False))
        mark_delivery_message_sent(
            db_path,
            guid,
            sequence,
            message_id,
            last_error_code="ambiguous_retry" if ambiguous else None,
            attempt_count=getattr(message_id, "attempt_count", 1),
        )
        if ambiguous:
            ambiguous_count += 1
    if not finalize_delivery(db_path, guid):
        raise RuntimeError("delivery_not_complete")
    return QueueDeliveryOutcome(ambiguous_count)


def mark_delivery_message_sent(
    db_path: str,
    guid: str,
    sequence: int,
    message_id: str,
    last_error_code: Optional[str] = None,
    attempt_count: int = 1,
) -> None:
    if not isinstance(message_id, str) or not DISCORD_MESSAGE_ID.fullmatch(message_id):
        raise ValueError("invalid Discord message id")
    with sqlite3.connect(db_path) as connection:
        _ensure_message_table(connection)
        cursor = connection.execute(
            "UPDATE google_news_delivery_messages "
            "SET status = 'sent', discord_message_id = ?, attempt_count = attempt_count + ?, "
            "last_error_code = CASE WHEN last_error_code = 'ambiguous_retry' "
            "THEN last_error_code ELSE ? END WHERE guid = ? AND sequence = ?",
            (message_id, max(1, int(attempt_count)), last_error_code, guid, sequence),
        )
        if cursor.rowcount != 1:
            raise ValueError("delivery message not found")


def mark_delivery_message_failed(
    db_path: str,
    guid: str,
    sequence: int,
    error_code: str,
    attempt_count: int = 1,
) -> None:
    if error_code not in {"ambiguous_retry", "final_failure"}:
        error_code = "final_failure"
    with sqlite3.connect(db_path) as connection:
        _ensure_message_table(connection)
        cursor = connection.execute(
            "UPDATE google_news_delivery_messages "
            "SET attempt_count = attempt_count + ?, last_error_code = ? "
            "WHERE guid = ? AND sequence = ? AND status = 'pending'",
            (max(1, int(attempt_count)), error_code, guid, sequence),
        )
        if cursor.rowcount != 1:
            raise ValueError("delivery message not found")


def finalize_delivery(db_path: str, guid: str) -> bool:
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        _ensure_message_table(connection)
        counts = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) "
            "FROM google_news_delivery_messages WHERE guid = ?",
            (guid,),
        ).fetchone()
        total = int(counts[0] or 0)
        pending = int(counts[1] or 0)
        if total == 0 or pending:
            return False
        row = connection.execute(
            "SELECT discord_message_id FROM google_news_delivery_messages "
            "WHERE guid = ? ORDER BY sequence DESC LIMIT 1",
            (guid,),
        ).fetchone()
        if row is None or not isinstance(row[0], str) or not DISCORD_MESSAGE_ID.fullmatch(row[0]):
            return False
        connection.execute(
            "UPDATE news_items SET delivery_status = 'sent', discord_message_id = ? "
            "WHERE guid = ?",
            (row[0], guid),
        )
        return True


def count_pending_deliveries(db_path: str) -> int:
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        row = connection.execute(
            "SELECT COUNT(*) FROM news_items WHERE delivery_status = 'pending'"
        ).fetchone()
        return int(row[0])


def count_ambiguous_retries(db_path: str) -> int:
    with sqlite3.connect(db_path) as connection:
        _ensure_message_table(connection)
        row = connection.execute(
            "SELECT COUNT(*) FROM google_news_delivery_messages "
            "WHERE last_error_code = 'ambiguous_retry'"
        ).fetchone()
        return int(row[0])


def _ensure_delivery_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(news_items)").fetchall()
    }
    if "delivery_status" not in columns:
        connection.execute("ALTER TABLE news_items ADD COLUMN delivery_status TEXT")
    if "discord_message_id" not in columns:
        connection.execute("ALTER TABLE news_items ADD COLUMN discord_message_id TEXT")
    if "filter_fingerprint" not in columns:
        connection.execute("ALTER TABLE news_items ADD COLUMN filter_fingerprint TEXT")
    if "delivery_sequence" not in columns:
        connection.execute("ALTER TABLE news_items ADD COLUMN delivery_sequence INTEGER")


def _ensure_identity_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS google_news_article_identity (
            identity_key TEXT PRIMARY KEY,
            guid TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _ensure_message_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS google_news_delivery_messages (
            guid TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            discord_message_id TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error_code TEXT,
            PRIMARY KEY (guid, sequence)
        )
        """
    )


def _backfill_article_identities(connection: sqlite3.Connection) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    rows = connection.execute(
        "SELECT guid, title, link FROM news_items WHERE guid IS NOT NULL"
    ).fetchall()
    identity_rows = []
    for guid, title, link in rows:
        for key in article_identity_keys(title or "", link or ""):
            identity_rows.append((key, guid, created_at))
    connection.executemany(
        "INSERT OR IGNORE INTO google_news_article_identity "
        "(identity_key, guid, created_at) VALUES (?, ?, ?)",
        identity_rows,
    )


def _next_delivery_sequence(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(delivery_sequence), 0) + 1 FROM news_items"
    ).fetchone()
    return int(row[0])


def _normalize_title(title: str) -> str:
    if not isinstance(title, str):
        return ""
    value = html.unescape(title)
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(value.split())


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
