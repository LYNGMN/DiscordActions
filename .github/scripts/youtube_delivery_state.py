"""Pure selection rules for safe YouTube baseline and delivery behavior."""

from datetime import datetime
from typing import List, Sequence, Tuple


def partition_youtube_items(
    items: Sequence[dict],
    baseline_only: bool,
    manual_test: bool,
) -> Tuple[List[dict], List[dict]]:
    prepared = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("invalid YouTube item")
        published_at = item.get("published_at")
        if not isinstance(published_at, str) or not published_at.strip():
            raise ValueError("invalid published_at")
        prepared.append((_parse_published_at(published_at), index, item))

    prepared.sort(key=lambda entry: (entry[0], entry[1]))
    ordered = [entry[2] for entry in prepared]
    if manual_test and ordered:
        return [ordered[-1]], ordered[:-1]
    if baseline_only:
        return [], ordered
    return ordered, []


def _parse_published_at(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("invalid published_at") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid published_at")
    return parsed
