import base64
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


ResolutionStatus = Literal[
    "disabled",
    "passthrough",
    "legacy",
    "resolved",
    "cache_hit",
    "fallback",
]


@dataclass(frozen=True)
class UrlResolution:
    url: str
    status: ResolutionStatus
    article_id: Optional[str]
    error_code: Optional[str] = None


class RateLimitError(requests.RequestException):
    pass


class GoogleNewsUrlResolver:
    PARAMETER_URLS = (
        "https://news.google.com/articles/{article_id}",
        "https://news.google.com/rss/articles/{article_id}",
    )
    BATCH_EXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        session: requests.Session,
        db_path: str,
        enabled: bool = True,
        min_interval_seconds: float = 1.0,
        timeout: Tuple[float, float] = (5.0, 15.0),
    ) -> None:
        self.session = session
        self.db_path = db_path
        self.enabled = enabled
        self.min_interval_seconds = min_interval_seconds
        self.timeout = timeout
        self._rate_limited = False
        self._last_resolution_started_at: Optional[float] = None
        self._init_cache()

    def resolve(self, source_url: str) -> UrlResolution:
        article_id = self._extract_article_id(source_url)
        if not self.enabled:
            return UrlResolution(source_url, "disabled", article_id)
        if article_id is None:
            return UrlResolution(source_url, "passthrough", None)

        cached_result = self._get_cached_success(article_id)
        if cached_result is not None:
            return cached_result

        legacy_url = self._decode_legacy_url(article_id)
        if legacy_url is not None and self._is_valid_original_url(legacy_url):
            self._save_success(article_id, source_url, legacy_url)
            return UrlResolution(legacy_url, "legacy", article_id)

        deferred_result = self._get_deferred_failure(article_id, source_url)
        if deferred_result is not None:
            return deferred_result

        if self._rate_limited:
            return UrlResolution(source_url, "fallback", article_id, "rate_limited")

        self._throttle()
        try:
            signature, timestamp = self._fetch_decoding_params(article_id)
            resolved_url = self._decode_url(article_id, signature, timestamp)
        except RateLimitError:
            self._rate_limited = True
            self._save_failure(article_id, source_url, "http_429")
            return UrlResolution(source_url, "fallback", article_id, "http_429")
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            self._save_failure(article_id, source_url, "decode_failed")
            return UrlResolution(source_url, "fallback", article_id, "decode_failed")

        if not self._is_valid_original_url(resolved_url):
            self._save_failure(article_id, source_url, "invalid_url")
            return UrlResolution(source_url, "fallback", article_id, "invalid_url")
        self._save_success(article_id, source_url, resolved_url)
        return UrlResolution(resolved_url, "resolved", article_id)

    def _throttle(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_resolution_started_at is not None:
            elapsed = now - self._last_resolution_started_at
            delay = self.min_interval_seconds - elapsed
            if delay > 0:
                time.sleep(delay)
        self._last_resolution_started_at = time.monotonic()

    def _init_cache(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS google_news_url_cache (
                    article_id TEXT PRIMARY KEY,
                    google_url TEXT NOT NULL,
                    resolved_url TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    next_retry_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _get_cached_success(self, article_id: str) -> Optional[UrlResolution]:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT resolved_url, status
                FROM google_news_url_cache
                WHERE article_id = ?
                """,
                (article_id,),
            ).fetchone()

        if row and row[1] == "resolved" and self._is_valid_original_url(row[0]):
            return UrlResolution(row[0], "cache_hit", article_id)
        return None

    def _save_success(
        self, article_id: str, google_url: str, resolved_url: str
    ) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO google_news_url_cache (
                    article_id,
                    google_url,
                    resolved_url,
                    status,
                    attempt_count,
                    last_error_code,
                    next_retry_at,
                    updated_at
                ) VALUES (?, ?, ?, 'resolved', 0, NULL, NULL, ?)
                """,
                (
                    article_id,
                    google_url,
                    resolved_url,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _get_deferred_failure(
        self, article_id: str, source_url: str
    ) -> Optional[UrlResolution]:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT status, last_error_code, next_retry_at
                FROM google_news_url_cache
                WHERE article_id = ?
                """,
                (article_id,),
            ).fetchone()

        if not row or row[0] != "failed" or not row[2]:
            return None
        try:
            next_retry_at = datetime.fromisoformat(row[2])
        except ValueError:
            return None
        if next_retry_at <= datetime.now(timezone.utc):
            return None
        return UrlResolution(source_url, "fallback", article_id, row[1])

    def _save_failure(
        self, article_id: str, google_url: str, error_code: str
    ) -> None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT attempt_count
                FROM google_news_url_cache
                WHERE article_id = ?
                """,
                (article_id,),
            ).fetchone()
            attempt_count = (row[0] if row else 0) + 1
            delay_minutes = min(
                30 * (2 ** min(attempt_count - 1, 4)),
                360,
            )
            updated_at = datetime.now(timezone.utc)
            next_retry_at = updated_at + timedelta(minutes=delay_minutes)
            connection.execute(
                """
                INSERT OR REPLACE INTO google_news_url_cache (
                    article_id,
                    google_url,
                    resolved_url,
                    status,
                    attempt_count,
                    last_error_code,
                    next_retry_at,
                    updated_at
                ) VALUES (?, ?, NULL, 'failed', ?, ?, ?, ?)
                """,
                (
                    article_id,
                    google_url,
                    attempt_count,
                    error_code,
                    next_retry_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )

    @classmethod
    def _decode_legacy_url(cls, article_id: str) -> Optional[str]:
        try:
            padded_id = article_id + "=" * ((4 - len(article_id) % 4) % 4)
            decoded = base64.urlsafe_b64decode(padded_id)
        except (ValueError, base64.binascii.Error):
            return None

        payload = decoded
        prefix = b'\x08\x13"'
        if decoded.startswith(prefix):
            try:
                length, start = cls._read_varint(decoded, len(prefix))
            except ValueError:
                return None
            payload = decoded[start : start + length]

        if payload.startswith(b"AU_yqL"):
            return None

        youtube_match = re.search(
            rb'\x08 "\x0b([\w-]{11})\x98\x01\x01',
            decoded,
        )
        if youtube_match is not None:
            youtube_id = youtube_match.group(1).decode("ascii")
            return f"https://www.youtube.com/watch?v={youtube_id}"

        match = re.search(rb"https?://[^\s\x00-\x1f]+", payload)
        if match is None:
            return None
        try:
            return match.group(0).decode("utf-8")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _read_varint(data: bytes, start: int) -> Tuple[int, int]:
        value = 0
        shift = 0
        position = start
        while position < len(data) and shift < 64:
            byte = data[position]
            value |= (byte & 0x7F) << shift
            position += 1
            if byte < 0x80:
                return value, position
            shift += 7
        raise ValueError("invalid_varint")

    def _fetch_decoding_params(self, article_id: str) -> Tuple[str, int]:
        for url_template in self.PARAMETER_URLS:
            try:
                response = self._request_with_retry(
                    "get",
                    url_template.format(article_id=article_id),
                    headers={"User-Agent": self.USER_AGENT},
                    timeout=self.timeout,
                )
            except RateLimitError:
                raise
            except requests.RequestException:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            data_element = soup.select_one(
                "c-wiz > div[data-n-a-sg][data-n-a-ts]"
            )
            if data_element is None:
                continue

            signature = data_element.get("data-n-a-sg")
            timestamp = data_element.get("data-n-a-ts")
            if signature and timestamp and str(timestamp).isdigit():
                return str(signature), int(str(timestamp))

        raise ValueError("decoding_parameters_unavailable")

    def _decode_url(self, article_id: str, signature: str, timestamp: int) -> str:
        request_data = [
            "garturlreq",
            [
                [
                    "X",
                    "X",
                    ["X", "X"],
                    None,
                    None,
                    1,
                    1,
                    "US:en",
                    None,
                    1,
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    1,
                ],
                "X",
                "X",
                1,
                [1, 1, 1],
                1,
                1,
                None,
                0,
                0,
                None,
                0,
            ],
            article_id,
            timestamp,
            signature,
        ]
        rpc_request = ["Fbv4je", json.dumps(request_data, separators=(",", ":"))]
        response = self._request_with_retry(
            "post",
            self.BATCH_EXECUTE_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": self.USER_AGENT,
            },
            data={"f.req": json.dumps([[rpc_request]], separators=(",", ":"))},
            timeout=self.timeout,
        )

        for block in response.text.split("\n\n"):
            block = block.strip()
            if not block or block == ")]}'":
                continue
            try:
                entries = json.loads(block)
            except json.JSONDecodeError:
                continue
            for entry in entries:
                if (
                    isinstance(entry, list)
                    and len(entry) >= 3
                    and entry[0] == "wrb.fr"
                    and entry[1] == "Fbv4je"
                    and entry[2]
                ):
                    decoded_payload = json.loads(entry[2])
                    if (
                        isinstance(decoded_payload, list)
                        and len(decoded_payload) > 1
                        and isinstance(decoded_payload[1], str)
                    ):
                        return decoded_payload[1]
        raise ValueError("decoded_url_missing")

    def _request_with_retry(self, method: str, url: str, **kwargs):
        request_method = getattr(self.session, method)
        for attempt in range(2):
            try:
                response = request_method(url, **kwargs)
                if response.status_code == 429:
                    raise RateLimitError("http_429")
                if 500 <= response.status_code < 600 and attempt == 0:
                    time.sleep(2.0)
                    continue
                response.raise_for_status()
                return response
            except RateLimitError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 0:
                    time.sleep(2.0)
                    continue
                raise
        raise requests.RequestException("request_failed")

    @staticmethod
    def _extract_article_id(source_url: str) -> Optional[str]:
        parsed_url = urlparse(source_url)
        path = [part for part in parsed_url.path.split("/") if part]
        if parsed_url.hostname != "news.google.com" or len(path) < 2:
            return None
        if path[-2] not in {"articles", "read"}:
            return None
        return path[-1]

    @staticmethod
    def _is_valid_original_url(url: str) -> bool:
        parsed_url = urlparse(url)
        return (
            parsed_url.scheme in {"http", "https"}
            and bool(parsed_url.hostname)
            and parsed_url.hostname != "news.google.com"
        )
