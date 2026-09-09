import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from discord_rate_limit_state import RateLimitStore, DeliveryDeferred, retry_after_seconds
from google_news_discord_delivery import send_webhook_message
import requests
from delivery_admin_alert import notify_admin


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'resolver.db')
        self.now = 1000.0
        self.store = RateLimitStore(self.path, clock=lambda: self.now)

    def response(self, status=429, headers=None, body=None):
        response = Mock(status_code=status, headers=headers or {})
        response.json.return_value = body or {}
        return response

    def test_delay_precedence(self):
        self.assertEqual(retry_after_seconds(self.response(headers={
            'Retry-After': '12', 'X-RateLimit-Reset-After': '999'},
            body={'retry_after': 15})), 15)
        self.assertEqual(retry_after_seconds(self.response(headers={
            'Retry-After': 'nan', 'X-RateLimit-Reset-After': '8'},
            body={'retry_after': True})), 8)
        self.assertIsNone(retry_after_seconds(self.response(body={'retry_after': -1})))

    def test_restore_expiry_scope_and_no_secrets(self):
        self.store.save('https://discord.com/api/webhooks/123/secret', 600, 'unknown')
        restored = RateLimitStore(self.path, clock=lambda: self.now)
        self.assertIsNotNone(restored.active('https://discord.com/api/webhooks/123/secret'))
        self.assertIsNone(restored.active('different'))
        with sqlite3.connect(self.path) as db:
            self.assertNotIn('secret', str(db.execute('SELECT * FROM discord_rate_limits').fetchall()))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.now = 1600
        self.assertIsNone(restored.active('https://discord.com/api/webhooks/123/secret'))
        self.store.save('one', 600, 'global')
        self.assertEqual(restored.active('other').rate_limit_scope, 'global')

    def test_existing_shared_database_tables_remain_intact(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE google_news_url_cache (article_id TEXT, status TEXT)')
            db.execute("INSERT INTO google_news_url_cache VALUES ('existing', 'resolved')")
        self.store.save('one', 600, 'user')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM google_news_url_cache').fetchall(), [('existing', 'resolved')])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_long_limit_saved_and_blocks_next_request(self):
        with patch('google_news_discord_delivery.requests.post', return_value=self.response(
            body={'retry_after': 601, 'global': True})) as post:
            with self.assertRaises(DeliveryDeferred):
                send_webhook_message('one', {}, resolver_db_path=self.path, sleep=Mock())
            with self.assertRaises(DeliveryDeferred):
                send_webhook_message('two', {}, resolver_db_path=self.path, sleep=Mock())
            self.assertEqual(post.call_count, 1)

    def test_success_cooldown_only_saved_after_message_recorded(self):
        with patch('google_news_discord_delivery.requests.post', return_value=self.response(
            200, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset-After': '601'}, {'id': '123'})):
            sleep = Mock()
            message = send_webhook_message('one', {}, resolver_db_path=self.path, sleep=sleep)
            self.assertIsNone(RateLimitStore(self.path).active('one'))
            message.after_recorded()
            self.assertIsNotNone(RateLimitStore(self.path).active('one'))
            sleep.assert_not_called()

    def test_repeated_short_limits_defer_after_four_retries(self):
        with patch('google_news_discord_delivery.requests.post', return_value=self.response(
            body={'retry_after': 1})) as post:
            sleep = Mock()
            with self.assertRaises(DeliveryDeferred) as caught:
                send_webhook_message('one', {}, resolver_db_path=self.path, sleep=sleep)
            self.assertEqual(post.call_count, 5)
            self.assertEqual(sleep.call_count, 4)
            self.assertEqual(caught.exception.attempt_count, 5)

    def test_invalid_delay_is_failure_not_deferral(self):
        response = self.response(body={'retry_after': 'nan'})
        response.raise_for_status.side_effect = requests.HTTPError('unsafe')
        with patch('google_news_discord_delivery.requests.post', return_value=response) as post:
            with self.assertRaises(requests.HTTPError):
                send_webhook_message('one', {}, resolver_db_path=self.path, sleep=Mock())
        self.assertEqual(post.call_count, 5)
        self.assertIsNone(self.store.active('one'))

    def test_state_write_failure_is_not_successful_deferral(self):
        with patch('google_news_discord_delivery.requests.post', return_value=self.response(
            body={'retry_after': 600})), patch.object(RateLimitStore, '_connect', side_effect=sqlite3.OperationalError):
            with self.assertRaisesRegex(RuntimeError, 'discord_rate_limit_state_failed'):
                send_webhook_message('one', {}, resolver_db_path=self.path, sleep=Mock())

    def test_unknown_network_response_evidence_survives_deferral(self):
        with patch('google_news_discord_delivery.requests.post', side_effect=[
            requests.ConnectionError('unsafe'), self.response(body={'retry_after': 601})]):
            with self.assertRaises(DeliveryDeferred) as caught:
                send_webhook_message('one', {}, resolver_db_path=self.path, sleep=Mock())
            self.assertTrue(caught.exception.ambiguous_retry)
            self.assertEqual(caught.exception.attempt_count, 2)

    def test_short_saved_bucket_waits_before_next_request(self):
        self.store.save('one', 2, 'user')
        def advance(seconds):
            self.now += seconds
        with patch('google_news_discord_delivery.RateLimitStore', return_value=self.store), \
                patch('google_news_discord_delivery.requests.post', return_value=self.response(200, body={'id': '123'})) as post:
            self.assertEqual(send_webhook_message('one', {}, resolver_db_path=self.path, sleep=advance), '123')
            self.assertEqual(self.now, 1002)
            post.assert_called_once()

    def test_global_limit_suppresses_admin_but_local_does_not(self):
        RateLimitStore(self.path).save('news', 600, 'user')
        post = Mock(return_value=self.response(204))
        with patch.dict('os.environ', {'GOOGLE_NEWS_RESOLVER_DB_PATH': self.path}):
            self.assertTrue(notify_admin('admin', 'Google News', 'test', 'item', 'failed', post=post))
            RateLimitStore(self.path).save('news', 600, 'global')
            self.assertFalse(notify_admin('admin', 'Google News', 'test', 'item', 'failed', post=post))
        self.assertEqual(post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
