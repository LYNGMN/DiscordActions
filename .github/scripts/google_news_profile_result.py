"""Sanitized, atomic per-profile result files for the unified dispatcher."""

import json
import os
import re
import tempfile
from typing import Dict, Optional


PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
STATUSES = {"success", "failed", "skipped"}


def write_profile_result(
    path: str,
    profile_id: str,
    status: str,
    processed_count: int,
    pending_count: int,
    error_code: Optional[str] = None,
    ambiguous_retry_count: int = 0,
) -> Dict[str, object]:
    if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id):
        raise ValueError("invalid profile id")
    if status not in STATUSES:
        raise ValueError("invalid profile status")
    processed = _non_negative_count(processed_count, "processed_count")
    pending = _non_negative_count(pending_count, "pending_count")
    ambiguous = _non_negative_count(
        ambiguous_retry_count, "ambiguous_retry_count"
    )
    if error_code is not None and (
        not isinstance(error_code, str) or not ERROR_CODE.fullmatch(error_code)
    ):
        raise ValueError("invalid profile error code")

    payload = {
        "profile_id": profile_id,
        "status": status,
        "processed_count": processed,
        "pending_count": pending,
        "ambiguous_retry_count": ambiguous,
        "error_code": error_code,
    }
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=".profile-result-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return payload


def _non_negative_count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("{} must be a non-negative integer".format(name))
    return value
