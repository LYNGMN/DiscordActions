"""Shared HTTP safety guard for all Google News requests in a workflow run."""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional, Tuple

import requests


DEFAULT_CIRCUIT_SECONDS = 60 * 60
DEFAULT_FORBIDDEN_SECONDS = 30 * 60
MIN_CIRCUIT_SECONDS = 60
MAX_CIRCUIT_SECONDS = 6 * 60 * 60
CIRCUIT_SCOPES = {"rss", "resolver"}


@dataclass(frozen=True)
class CircuitState:
    blocked_until: datetime
    error_code: str


class BlockedRequestError(requests.RequestException):
    def __init__(self, error_code: str, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds


class RateLimitError(BlockedRequestError):
    def __init__(self, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__("http_429", retry_after_seconds)


class AccessDeniedError(BlockedRequestError):
    def __init__(self, retry_after_seconds: Optional[int] = None) -> None:
        super().__init__("http_403", retry_after_seconds)


class CircuitOpenError(BlockedRequestError):
    def __init__(self, source_error_code: str, blocked_until: datetime) -> None:
        super().__init__("circuit_open")
        self.source_error_code = source_error_code
        self.blocked_until = blocked_until


class GoogleNewsRequestGuard:
    def __init__(
        self,
        session: requests.Session,
        db_path: str,
        timeout: Tuple[float, float] = (5.0, 15.0),
        utc_now: Optional[Callable[[], datetime]] = None,
        scope: str = "rss",
    ) -> None:
        if scope not in CIRCUIT_SCOPES:
            raise ValueError("invalid circuit scope")
        self.session = session
        self.db_path = db_path
        self.timeout = timeout
        self.scope = scope
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._init_state()

    def _init_state(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
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
            # Older versions stored one global circuit for RSS and URL
            # resolution. That coupling stopped news delivery when only link
            # resolution was blocked, so the legacy row is discarded once.
            connection.execute(
                "DELETE FROM google_news_resolver_state WHERE state_key = 'global'"
            )

    def request(self, method: str, url: str, scope: Optional[str] = None, **kwargs):
        request_scope = self._scope(scope)
        open_state = self.get_open_circuit(request_scope)
        if open_state is not None:
            raise CircuitOpenError(open_state.error_code, open_state.blocked_until)

        request_method = getattr(self.session, method.lower(), None)
        if request_method is None or method.lower() not in {"get", "post"}:
            raise ValueError("unsupported request method")
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(2):
            try:
                response = request_method(url, **kwargs)
                if response.status_code == 429:
                    delay = self._circuit_delay(
                        response.headers.get("Retry-After"),
                        DEFAULT_CIRCUIT_SECONDS,
                    )
                    self._open_circuit("http_429", delay, request_scope)
                    raise RateLimitError(delay)
                if response.status_code == 403:
                    delay = self._circuit_delay(
                        response.headers.get("Retry-After"),
                        DEFAULT_FORBIDDEN_SECONDS,
                    )
                    self._open_circuit("http_403", delay, request_scope)
                    raise AccessDeniedError(delay)
                if 500 <= response.status_code < 600 and attempt == 0:
                    time.sleep(2.0)
                    continue
                try:
                    response.raise_for_status()
                except requests.HTTPError as error:
                    # Avoid logging raw request URLs or response bodies.
                    error.error_code = "http_{}".format(response.status_code)
                    raise
                return response
            except BlockedRequestError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 0:
                    time.sleep(2.0)
                    continue
                raise
        raise requests.RequestException("request_failed")

    def get_open_circuit(self, scope: Optional[str] = None) -> Optional[CircuitState]:
        state_key = self._scope(scope)
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT blocked_until, last_error_code
                FROM google_news_resolver_state
                WHERE state_key = ?
                """,
                (state_key,),
            ).fetchone()
        if not row or not row[0] or not row[1]:
            return None
        try:
            blocked_until = datetime.fromisoformat(row[0])
        except (TypeError, ValueError):
            return None
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        if blocked_until <= self._now():
            return None
        return CircuitState(blocked_until=blocked_until, error_code=row[1])

    def clear_circuit(self, scope: Optional[str] = None) -> None:
        state_key = self._scope(scope)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DELETE FROM google_news_resolver_state WHERE state_key = ?",
                (state_key,),
            )

    def _open_circuit(
        self, error_code: str, delay_seconds: int, scope: Optional[str] = None
    ) -> CircuitState:
        state_key = self._scope(scope)
        updated_at = self._now()
        blocked_until = updated_at + timedelta(seconds=delay_seconds)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO google_news_resolver_state (
                    state_key,
                    blocked_until,
                    last_error_code,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    state_key,
                    blocked_until.isoformat(),
                    error_code,
                    updated_at.isoformat(),
                ),
            )
        return CircuitState(blocked_until=blocked_until, error_code=error_code)

    def _circuit_delay(
        self, retry_after: Optional[str], default_seconds: int
    ) -> int:
        parsed = self._parse_retry_after(retry_after)
        delay = default_seconds if parsed is None else parsed
        return max(MIN_CIRCUIT_SECONDS, min(delay, MAX_CIRCUIT_SECONDS))

    def _scope(self, scope: Optional[str]) -> str:
        if scope is None:
            return self.scope
        if scope not in CIRCUIT_SCOPES:
            raise ValueError("invalid circuit scope")
        return scope

    def _parse_retry_after(self, value: Optional[str]) -> Optional[int]:
        if value is None or not value.strip():
            return None
        value = value.strip()
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
        return max(0, int((retry_at - self._now()).total_seconds()))

    def _now(self) -> datetime:
        current = self._utc_now()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current
