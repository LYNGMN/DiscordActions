"""Persistent review queue for unmapped Google News publisher domains."""

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional, Set, Tuple

from google_news_publisher_names import (
    PublisherRegistry,
    PublisherResolution,
    publisher_label_from_title,
)


TABLE_NAME = "google_news_unmapped_publisher_occurrences"
METADATA_TABLE_NAME = "google_news_publisher_review_metadata"
BACKFILL_KEY = "legacy_news_items_backfill_v1"
VALID_LOCATIONS = {"main", "related"}


def record_unmapped_publisher(
    db_path,
    profile_id: str,
    occurrence_id: str,
    location: str,
    resolution: PublisherResolution,
    observed_at: Optional[datetime] = None,
) -> bool:
    if resolution.mapped or not resolution.domain_like:
        return False
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("invalid publisher profile")
    if not isinstance(occurrence_id, str) or not occurrence_id:
        raise ValueError("invalid publisher occurrence")
    if location not in VALID_LOCATIONS:
        raise ValueError("invalid publisher location")
    timestamp = _timestamp(observed_at)
    occurrence_key = hashlib.sha256(
        "\0".join(
            (
                profile_id,
                occurrence_id,
                location,
                resolution.normalized_label,
                resolution.hostname,
            )
        ).encode("utf-8")
    ).hexdigest()
    with sqlite3.connect(str(db_path)) as connection:
        _ensure_table(connection)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO {} "
            "(occurrence_key, normalized_label, display_label, hostname, profile_id, "
            "location, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)".format(
                TABLE_NAME
            ),
            (
                occurrence_key,
                resolution.normalized_label,
                resolution.display_name,
                resolution.hostname,
                profile_id,
                location,
                timestamp,
                timestamp,
            ),
        )
        inserted = cursor.rowcount == 1
        if not inserted:
            connection.execute(
                "UPDATE {} SET last_seen_at = ? WHERE occurrence_key = ?".format(
                    TABLE_NAME
                ),
                (timestamp, occurrence_key),
            )
    return inserted


def backfill_unmapped_publishers(
    db_path,
    profile_id: str,
    registry: PublisherRegistry,
    observed_at: Optional[datetime] = None,
) -> int:
    with sqlite3.connect(str(db_path)) as connection:
        _ensure_table(connection)
        _ensure_metadata_table(connection)
        if connection.execute(
            "SELECT 1 FROM {} WHERE metadata_key = ?".format(
                METADATA_TABLE_NAME
            ),
            (BACKFILL_KEY,),
        ).fetchone():
            return 0
        if not _table_exists(connection, "news_items"):
            rows = []
        else:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(news_items)"
                )
            }
            required = {"guid", "title", "link", "related_news"}
            rows = (
                connection.execute(
                    "SELECT guid, title, link, related_news FROM news_items"
                ).fetchall()
                if required.issubset(columns)
                else []
            )

    inserted = 0
    for guid, title, link, related_news in rows:
        label = publisher_label_from_title(title or "")
        if label:
            resolution = registry.resolve(label, link or "")
            inserted += int(
                record_unmapped_publisher(
                    db_path,
                    profile_id,
                    "{}:main".format(guid),
                    "main",
                    resolution,
                    observed_at,
                )
            )
        try:
            related_items = json.loads(related_news or "[]")
        except (TypeError, ValueError):
            related_items = []
        if not isinstance(related_items, list):
            continue
        for index, item in enumerate(related_items):
            if not isinstance(item, dict):
                continue
            publisher_name = item.get("press", "")
            resolution = registry.resolve(publisher_name, item.get("link", ""))
            inserted += int(
                record_unmapped_publisher(
                    db_path,
                    profile_id,
                    "{}:related:{}".format(guid, index),
                    "related",
                    resolution,
                    observed_at,
                )
            )
    with sqlite3.connect(str(db_path)) as connection:
        _ensure_metadata_table(connection)
        connection.execute(
            "INSERT OR IGNORE INTO {} (metadata_key, completed_at) "
            "VALUES (?, ?)".format(METADATA_TABLE_NAME),
            (BACKFILL_KEY, _timestamp(observed_at)),
        )
    return inserted


def unmapped_publisher_keys(
    state_dir,
    profile_databases: Mapping[str, str],
    registry: PublisherRegistry,
) -> Set[Tuple[str, str]]:
    return set(
        _aggregate_unmapped_publishers(state_dir, profile_databases, registry)
    )


def export_unmapped_publishers(
    state_dir,
    profile_databases: Mapping[str, str],
    registry: PublisherRegistry,
    output_path=None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, object]:
    grouped = _aggregate_unmapped_publishers(state_dir, profile_databases, registry)
    publishers = []
    for key in sorted(grouped):
        item = grouped[key]
        publishers.append(
            {
                "label": sorted(item["labels"], key=lambda value: (value.casefold(), value))[0],
                "hostname": key[1],
                "occurrence_count": item["occurrence_count"],
                "profiles": sorted(item["profiles"]),
                "locations": sorted(item["locations"]),
                "first_seen_at": item["first_seen_at"],
                "last_seen_at": item["last_seen_at"],
            }
        )
    payload = {
        "schema_version": 1,
        "generated_at": _timestamp(generated_at),
        "unmapped_publisher_count": len(publishers),
        "publishers": publishers,
    }
    target = Path(output_path or Path(state_dir) / "unmapped-google-news-publishers.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=".unmapped-publishers-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, str(target))
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return payload


def _aggregate_unmapped_publishers(
    state_dir,
    profile_databases: Mapping[str, str],
    registry: PublisherRegistry,
):
    grouped = {}
    for expected_profile, database_name in sorted(profile_databases.items()):
        database_path = Path(state_dir) / database_name
        if not database_path.is_file():
            continue
        with sqlite3.connect(str(database_path)) as connection:
            if not _table_exists(connection, TABLE_NAME):
                continue
            rows = connection.execute(
                "SELECT normalized_label, display_label, hostname, profile_id, location, "
                "first_seen_at, last_seen_at FROM {}".format(TABLE_NAME)
            ).fetchall()
        for (
            normalized_label,
            display_label,
            hostname,
            profile_id,
            location,
            first_seen_at,
            last_seen_at,
        ) in rows:
            if profile_id != expected_profile:
                continue
            article_url = "https://{}/".format(hostname) if hostname else ""
            if registry.resolve(display_label, article_url).mapped:
                continue
            key = (normalized_label, hostname)
            item = grouped.setdefault(
                key,
                {
                    "labels": set(),
                    "profiles": set(),
                    "locations": set(),
                    "first_seen_at": first_seen_at,
                    "last_seen_at": last_seen_at,
                    "occurrence_count": 0,
                },
            )
            item["labels"].add(display_label)
            item["profiles"].add(profile_id)
            item["locations"].add(location)
            item["first_seen_at"] = min(item["first_seen_at"], first_seen_at)
            item["last_seen_at"] = max(item["last_seen_at"], last_seen_at)
            item["occurrence_count"] += 1
    return grouped


def _ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS google_news_unmapped_publisher_occurrences (
            occurrence_key TEXT PRIMARY KEY,
            normalized_label TEXT NOT NULL,
            display_label TEXT NOT NULL,
            hostname TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            location TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )


def _ensure_metadata_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS google_news_publisher_review_metadata (
            metadata_key TEXT PRIMARY KEY,
            completed_at TEXT NOT NULL
        )
        """
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _timestamp(value: Optional[datetime]) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("publisher observation time must be timezone-aware")
    return moment.astimezone(timezone.utc).isoformat()
