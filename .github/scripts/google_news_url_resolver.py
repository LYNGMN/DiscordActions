import base64
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Literal, Optional, Tuple
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


class BlockedRequestError(requests.RequestException):
    def __init__(
        self,
        error_code: str,
        retry_after_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds


class RateLimitError(BlockedRequestError):
    def __init__(self, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__("http_429", retry_after_seconds)


class AccessDeniedError(BlockedRequestError):
    def __init__(self, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__("http_403", retry_after_seconds)


class GoogleNewsUrlResolver:
    DEFAULT_MAX_NETWORK_RESOLUTIONS = 5
    DEFAULT_CIRCUIT_SECONDS = 60 * 60
    MIN_CIRCUIT_SECONDS = 60
    MAX_CIRCUIT_SECONDS = 6 * 60 * 60
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
        max_network_resolutions: int = DEFAULT_MAX_NETWORK_RESOLUTIONS,
    ) -> None:
        if max_network_resolutions < 0:
            raise ValueError("max_network_resolutions must be non-negative")
        self.session = session
        self.db_path = db_path
        self.enabled = enabled
        self.min_interval_seconds = min_interval_seconds
        self.timeout = timeout
        self.max_network_resolutions = max_network_resolutions
        self._network_resolution_attempts = 0
        self._last_resolution_started_at: Optional[float] = None
        self._stats: Dict[str, object] = {
            "resolution_calls": 0,
            "network_resolution_attempts": 0,
            "resolved": 0,
            "cache_hits": 0,
            "legacy": 0,
            "fallbacks": 0,
            "budget_exhausted": 0,
            "related_network_skipped": 0,
            "circuit_skipped": 0,
            "circuit_opened": 0,
            "circuit_blocked_until": None,
        }
        self._init_cache()

    def resolve(self, source_url: str) -> UrlResolution:
        return self._resolve(source_url, allow_network=True)

    def resolve_related(self, source_url: str) -> UrlResolution:
        return self._resolve(source_url, allow_network=False)

    def get_stats(self) -> Dict[str, object]:
        return dict(self._stats)

    def _resolve(
        self,
        source_url: str,
        allow_network: bool,
    ) -> UrlResolution:
        self._increment_stat("resolution_calls")
        article_id = self._extract_article_id(source_url)
        if not self.enabled:
            return UrlResolution(source_url, "disabled", article_id)
        if article_id is None:
            return UrlResolution(source_url, "passthrough", None)

        cached_result = self._get_cached_success(article_id)
        if cached_result is not None:
            self._increment_stat("cache_hits")
            return cached_result

        legacy_url = self._decode_legacy_url(article_id)
        if legacy_url is not None and self._is_valid_original_url(legacy_url):
            self._save_success(article_id, source_url, legacy_url)
            self._increment_stat("legacy")
            return UrlResolution(legacy_url, "legacy", article_id)

        deferred_result = self._get_deferred_failure(article_id, source_url)
        if deferred_result is not None:
            self._increment_stat("fallbacks")
            return deferred_result

        if not allow_network:
            self._increment_stat("related_network_skipped")
            self._increment_stat("fallbacks")
            return UrlResolution(
                source_url,
                "fallback",
                article_id,
                "related_network_skipped",
            )

        open_circuit = self._get_open_circuit()
        if open_circuit is not None:
            blocked_until, _ = open_circuit
            self._stats["circuit_blocked_until"] = blocked_until.isoformat()
            self._increment_stat("circuit_skipped")
            self._increment_stat("fallbacks")
            return UrlResolution(source_url, "fallback", article_id, "circuit_open")

        if self._network_resolution_attempts >= self.max_network_resolutions:
            self._increment_stat("budget_exhausted")
            self._increment_stat("fallbacks")
            return UrlResolution(
                source_url,
                "fallback",
                article_id,
                "budget_exhausted",
            )

        self._network_resolution_attempts += 1
        self._increment_stat("network_resolution_attempts")
        self._throttle()
        try:
            signature, timestamp = self._fetch_decoding_params(article_id)
            resolved_url = self._decode_url(article_id, signature, timestamp)
        except BlockedRequestError as error:
            blocked_until = self._open_circuit(
                error.error_code,
                error.retry_after_seconds,
            )
            self._stats["circuit_blocked_until"] = blocked_until.isoformat()
            self._increment_stat("circuit_opened")
            self._increment_stat("fallbacks")
            self._save_failure(article_id, source_url, error.error_code)
            return UrlResolution(
                source_url,
                "fallback",
                article_id,
                error.error_code,
            )
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            self._save_failure(article_id, source_url, "decode_failed")
            self._increment_stat("fallbacks")
            return UrlResolution(source_url, "fallback", article_id, "decode_failed")

        if not self._is_valid_original_url(resolved_url):
            self._save_failure(article_id, source_url, "invalid_url")
            self._increment_stat("fallbacks")
            return UrlResolution(source_url, "fallback", article_id, "invalid_url")
        self._save_success(article_id, source_url, resolved_url)
        self._clear_circuit()
        self._stats["circuit_blocked_until"] = None
        self._increment_stat("resolved")
        return UrlResolution(resolved_url, "resolved", article_id)

    def _increment_stat(self, name: str) -> None:
        self._stats[name] = int(self._stats[name]) + 1

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS google_news_resolver_state (
                    state_key TEXT PRIMARY KEY,
                    blocked_until TEXT,
                    last_error_code TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _get_open_circuit(self) -> Optional[Tuple[datetime, Optional[str]]]:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT blocked_until, last_error_code
                FROM google_news_resolver_state
                WHERE state_key = 'global'
                """
            ).fetchone()

        if not row or not row[0]:
            return None
        try:
            blocked_until = datetime.fromisoformat(row[0])
        except ValueError:
            return None
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        if blocked_until <= self._utc_now():
            return None
        return blocked_until, row[1]

    def _open_circuit(
        self,
        error_code: str,
        retry_after_seconds: Optional[int],
    ) -> datetime:
        delay_seconds = (
            retry_after_seconds
            if retry_after_seconds is not None
            else self.DEFAULT_CIRCUIT_SECONDS
        )
        delay_seconds = max(
            self.MIN_CIRCUIT_SECONDS,
            min(delay_seconds, self.MAX_CIRCUIT_SECONDS),
        )
        updated_at = self._utc_now()
        blocked_until = updated_at + timedelta(seconds=delay_seconds)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO google_news_resolver_state (
                    state_key,
                    blocked_until,
                    last_error_code,
                    updated_at
                ) VALUES ('global', ?, ?, ?)
                """,
                (
                    blocked_until.isoformat(),
                    error_code,
                    updated_at.isoformat(),
                ),
            )
        return blocked_until

    def _clear_circuit(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DELETE FROM google_news_resolver_state WHERE state_key = 'global'"
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
                    self._utc_now().isoformat(),
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
        if next_retry_at.tzinfo is None:
            next_retry_at = next_retry_at.replace(tzinfo=timezone.utc)
        if next_retry_at <= self._utc_now():
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
            updated_at = self._utc_now()
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
            except BlockedRequestError:
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
                    raise RateLimitError(
                        self._parse_retry_after(response.headers.get("Retry-After"))
                    )
                if response.status_code == 403:
                    raise AccessDeniedError(
                        self._parse_retry_after(response.headers.get("Retry-After"))
                    )
                if 500 <= response.status_code < 600 and attempt == 0:
                    time.sleep(2.0)
                    continue
                response.raise_for_status()
                return response
            except BlockedRequestError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 0:
                    time.sleep(2.0)
                    continue
                raise
        raise requests.RequestException("request_failed")

    def _parse_retry_after(self, value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            return max(0, int(value))
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0, int((retry_at - self._utc_now()).total_seconds()))

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
