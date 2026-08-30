import sqlite3
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Sequence, Tuple
from xml.etree.ElementTree import Element


BaselineRow = Tuple[str, str, str, str, str]


def prepare_manual_test_items(
    items: Sequence[Element], db_path: str, enabled: bool
) -> List[Element]:
    item_list = list(items)
    if not enabled or not item_list:
        return item_list

    prepared_items = [prepare_baseline_item(item) for item in item_list]
    latest_index = max(
        range(len(prepared_items)),
        key=lambda index: prepared_items[index][0],
    )
    baseline_rows = [
        prepared[1]
        for index, prepared in enumerate(prepared_items)
        if index != latest_index
    ]

    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO news_items (
                pub_date, guid, title, link, related_news
            ) VALUES (?, ?, ?, ?, ?)
            """,
            baseline_rows,
        )

    return [item_list[latest_index]]


def validate_manual_test_result(
    enabled: bool, expected_count: int, processed_count: int
) -> None:
    if enabled and processed_count != expected_count:
        raise RuntimeError(
            "manual test item count mismatch: "
            f"expected {expected_count}, processed {processed_count}"
        )


def prepare_baseline_item(item: Element) -> Tuple[datetime, BaselineRow]:
    pub_date = _required_text(item, "pubDate")
    guid = _required_text(item, "guid")
    title = _required_text(item, "title")
    link = _required_text(item, "link")
    try:
        parsed_date = parsedate_to_datetime(pub_date)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid required field: pubDate") from error
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
    return parsed_date, (pub_date, guid, title, link, "[]")


def _required_text(item: Element, field_name: str) -> str:
    value = item.findtext(field_name)
    if value is None or not value.strip():
        raise ValueError(f"missing required field: {field_name}")
    return value.strip()
