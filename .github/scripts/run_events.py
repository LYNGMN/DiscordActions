"""Safe, structured delivery events for diagnosis.

Every delivery decision that can explain a missing or wrong message is written
as one ``event=`` line, so a run can be reconstructed from the Action log. When
``RUN_EVENTS_PATH`` is set the same record is appended as JSON Lines for a
machine-readable artifact.

Values are bounded and URLs (webhook or article) are redacted. Never pass
message content or credentials here.
"""

import datetime
import hashlib
import json
import logging
import os
import re


EVENTS_PATH_ENV = "RUN_EVENTS_PATH"
MAX_VALUE_LENGTH = 120
SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
SECRETISH = re.compile(r"https?://|discord(?:app)?\.com/api/webhooks", re.IGNORECASE)

LOGGER = logging.getLogger("delivery_events")


def item_ref(value) -> str:
    """Return a stable, short reference for an article or video id."""
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if SECRETISH.search(text):
        return "[redacted]"
    text = re.sub(r"\s+", "_", text.strip())
    return text[:MAX_VALUE_LENGTH]


def _safe_fields(event: str, fields) -> dict:
    record = {"event": event}
    for key in sorted(fields):
        if not SAFE_KEY.fullmatch(key):
            continue
        value = fields[key]
        if value is None or value == "":
            continue
        if isinstance(value, (bool, int, float)):
            record[key] = value
        else:
            text = str(value)
            record[key] = "[redacted]" if SECRETISH.search(text) else text[:MAX_VALUE_LENGTH]
    return record


def _append_record(record) -> None:
    path = os.environ.get(EVENTS_PATH_ENV)
    if not path:
        return
    payload = dict(record)
    payload["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not payload.get("run"):
        payload["run"] = os.environ.get("GITHUB_RUN_ID", "")
    if not payload.get("profile"):
        payload["profile"] = os.environ.get("GOOGLE_NEWS_PROFILE_ID", "")
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


def emit_event(event: str, level: str = "info", **fields) -> None:
    """Write one event line and, when configured, one JSON Lines record.

    ``level="debug"`` keeps per-item detail in the artifact and out of the
    human log, which is reserved for decisions worth reading.
    """
    if not isinstance(event, str) or not SAFE_KEY.fullmatch(event):
        return
    parts = ["event={}".format(event)]
    for key in sorted(fields):
        if not SAFE_KEY.fullmatch(key):
            continue
        value = _format_value(fields[key])
        if value:
            parts.append("{}={}".format(key, value))
    text = " ".join(parts)
    if level == "debug":
        LOGGER.debug(text)
    else:
        LOGGER.info(text)
    _append_record(_safe_fields(event, fields))


def truncate_events_file(path: str) -> None:
    """Start a new event file for this run."""
    if not path:
        return
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8"):
            pass
    except OSError:
        return
