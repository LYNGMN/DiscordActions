"""Durable Discord cooldowns. Store only hashed targets and safe timing data."""

import hashlib
import logging
import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone


class DeliveryDeferred(RuntimeError):
    error_code = 'discord_delivery_deferred'

    def __init__(self, retry_epoch, scope, attempt_count=0):
        super().__init__(self.error_code)
        self.retry_epoch = retry_epoch
        self.retry_at = datetime.fromtimestamp(retry_epoch, timezone.utc).isoformat()
        self.rate_limit_scope = scope
        self.attempt_count = attempt_count


class RateLimitStateError(RuntimeError):
    error_code = 'discord_rate_limit_state_failed'

    def __init__(self):
        super().__init__(self.error_code)


def _seconds(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def retry_after_seconds(response):
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = {}
    values = [_seconds(response.headers.get('Retry-After')),
              _seconds(body.get('retry_after')) if isinstance(body, dict) else None]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else _seconds(response.headers.get('X-RateLimit-Reset-After'))


def rate_limit_scope(response):
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = {}
    scope = response.headers.get('X-RateLimit-Scope', 'unknown')
    if (scope == 'global' or response.headers.get('X-RateLimit-Global', '').lower() == 'true'
            or isinstance(body, dict) and body.get('global') is True):
        return 'global'
    return scope if scope in {'user', 'shared'} else 'unknown'


class RateLimitStore:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock

    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS discord_rate_limits ('
                               'target_hash TEXT PRIMARY KEY, retry_at REAL NOT NULL, '
                               'scope TEXT NOT NULL)')
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    @staticmethod
    def _key(webhook):
        return hashlib.sha256(webhook.strip().encode('utf-8')).hexdigest()

    def active(self, webhook):
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    'SELECT retry_at, scope FROM discord_rate_limits '
                    'WHERE target_hash IN (?, ?) AND retry_at > ? '
                    'ORDER BY retry_at DESC LIMIT 1',
                    (self._key(webhook), 'global', self.clock()),
                ).fetchone()
            return DeliveryDeferred(*row) if row else None
        except (sqlite3.Error, ValueError, OverflowError, OSError):
            raise RateLimitStateError() from None

    def save(self, webhook, seconds, scope, attempt_count=0, http_status=429):
        delay = _seconds(seconds)
        if delay is None or scope not in {'user', 'shared', 'global', 'unknown'}:
            raise ValueError('invalid_rate_limit')
        try:
            deferred = DeliveryDeferred(self.clock() + delay, scope, attempt_count)
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    'INSERT INTO discord_rate_limits VALUES (?, ?, ?) '
                    'ON CONFLICT(target_hash) DO UPDATE SET '
                    'retry_at = MAX(retry_at, excluded.retry_at), '
                    'scope = CASE WHEN excluded.retry_at >= retry_at THEN excluded.scope ELSE scope END',
                    ('global' if scope == 'global' else self._key(webhook), deferred.retry_epoch, scope),
                )
            logging.info('Discord cooldown: http_status=%s wait_seconds=%s scope=%s attempt_count=%s retry_at=%s',
                         http_status, delay, scope, attempt_count, deferred.retry_at)
            return deferred
        except (sqlite3.Error, ValueError, OverflowError, OSError):
            raise RateLimitStateError() from None

    def check(self, webhook):
        active = self.active(webhook)
        if active:
            raise active
