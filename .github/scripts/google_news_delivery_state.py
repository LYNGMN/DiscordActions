"""Bounded article selection and crash-safe Discord delivery state."""

import hashlib
import html
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple
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


def prepare_scheduled_items(
    items: Sequence[Element],
    db_path: str,
    now: datetime,
    max_items: int = 3,
    max_age_minutes: int = 120,
) -> List[Element]:
    if max_items < 0:
        raise ValueError("max_items must be non-negative")
    if max_age_minutes < 0:
        raise ValueError("max_age_minutes must be non-negative")
    normalized_now = _aware_utc(now)
    item_list = list(items)

    prepared = []
    for index, item in enumerate(item_list):
        published_at, baseline_row = prepare_baseline_item(item)
        prepared.append((published_at.astimezone(timezone.utc), index, item, baseline_row))

    cutoff = normalized_now - timedelta(minutes=max_age_minutes)
    recent = sorted(
        (entry for entry in prepared if cutoff <= entry[0] <= normalized_now),
        key=lambda entry: (entry[0], entry[1]),
    )
    selected = recent[-max_items:] if max_items else []
    selected_indexes = {entry[1] for entry in selected}
    baseline_rows = [entry[3] for entry in prepared if entry[1] not in selected_indexes]

    if baseline_rows:
        with sqlite3.connect(db_path) as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO news_items (
                    pub_date, guid, title, link, related_news
                ) VALUES (?, ?, ?, ?, ?)
                """,
                baseline_rows,
            )
    return [entry[2] for entry in selected]


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
        _backfill_article_identities(connection)

        existing_guid = connection.execute(
            "SELECT 1 FROM news_items WHERE guid = ?",
            (guid,),
        ).fetchone()
        if existing_guid is not None:
            return False

        identity_keys = article_identity_keys(title, link)
        if identity_keys:
            placeholders = ",".join("?" for _ in identity_keys)
            existing_identity = connection.execute(
                "SELECT 1 FROM google_news_article_identity "
                "WHERE identity_key IN ({}) LIMIT 1".format(placeholders),
                identity_keys,
            ).fetchone()
            if existing_identity is not None:
                return False

        connection.execute(
            "INSERT OR IGNORE INTO news_items (guid, delivery_status) "
            "VALUES (?, 'pending')",
            (guid,),
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


def count_pending_deliveries(db_path: str) -> int:
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        row = connection.execute(
            "SELECT COUNT(*) FROM news_items WHERE delivery_status = 'pending'"
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
