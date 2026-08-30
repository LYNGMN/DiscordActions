"""Bounded article selection and crash-safe Discord delivery state."""

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Sequence
from xml.etree.ElementTree import Element

from google_news_manual_test import prepare_baseline_item


DISCORD_MESSAGE_ID = re.compile(r"^[0-9]+$")


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
        (entry for entry in prepared if entry[0] >= cutoff),
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


def reserve_delivery(db_path: str, guid: str) -> bool:
    if not isinstance(guid, str) or not guid.strip():
        raise ValueError("invalid delivery guid")
    with sqlite3.connect(db_path) as connection:
        _ensure_delivery_columns(connection)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO news_items (guid, delivery_status) "
            "VALUES (?, 'pending')",
            (guid,),
        )
        return cursor.rowcount == 1


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


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
