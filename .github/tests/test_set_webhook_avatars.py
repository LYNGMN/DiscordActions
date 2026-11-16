import importlib
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
PNG = b"\x89PNG\r\n\x1a\n" + b"avatar-bytes"
WEBHOOK = "https://discord.com/api/webhooks/123456789/abcdef"


def load_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("set_webhook_avatars", None)
        return importlib.import_module("set_webhook_avatars")
    finally:
        sys.path.pop(0)


def profile(profile_id="top_kr", webhook_env="DISCORD_WEBHOOK_GN_TOP_KR"):
    from google_news_profiles import GoogleNewsProfile

    return GoogleNewsProfile(
        profile_id=profile_id,
        handler="top",
        webhook_env=webhook_env,
        expected_webhook_name="Google News - TOP - KR",
        state_db=profile_id + ".db",
        visible_username="Google News",
        environment={},
    )


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        body=None,
        headers=None,
        content=b"",
        content_type="image/png",
    ):
        self.status_code = status_code
        self._body = {} if body is None else body
        self.headers = dict(headers or {})
        if content_type:
            self.headers.setdefault("Content-Type", content_type)
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError("HTTP {}".format(self.status_code))
            error.response = self
            raise error

    def json(self):
        return self._body


class SetWebhookAvatarsTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_image_rejects_non_image_content_type(self):
        response = FakeResponse(content=b"<html></html>", content_type="text/html")

        with self.assertRaises(ValueError) as raised:
            self.module.fetch_avatar_image(
                "https://example.com/logo.png", get=lambda *a, **k: response
            )

        self.assertIn("avatar_url_not_an_image", str(raised.exception))

    def test_image_rejects_body_that_is_not_png(self):
        response = FakeResponse(content=b"<html></html>", content_type="image/png")

        with self.assertRaises(ValueError) as raised:
            self.module.fetch_avatar_image(
                "https://example.com/logo.png", get=lambda *a, **k: response
            )

        self.assertIn("avatar_image_not_png", str(raised.exception))

    def test_apply_patches_avatar_and_verifies_it(self):
        calls = {}

        def patch(url, **kwargs):
            calls["patch"] = (url, kwargs)
            return FakeResponse()

        def get(url, **kwargs):
            calls["get"] = url
            return FakeResponse(body={"avatar": "abc123"})

        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": WEBHOOK},
            PNG,
            patch=patch,
            get=get,
        )

        self.assertEqual("set", results[0]["status"])
        url, kwargs = calls["patch"]
        self.assertEqual(WEBHOOK, url)
        self.assertEqual({"payload_json": "{}"}, kwargs["data"])
        self.assertNotIn("name", kwargs.get("json", {}))
        filename, content, content_type = kwargs["files"]["avatar"]
        self.assertEqual("avatar.png", filename)
        self.assertEqual(PNG, content)
        self.assertEqual("image/png", content_type)
        self.assertEqual(WEBHOOK, calls["get"])

    def test_multipart_rejection_falls_back_to_json_image_data(self):
        calls = []
        responses = [FakeResponse(status_code=400), FakeResponse()]

        def patch(url, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": WEBHOOK},
            PNG,
            patch=patch,
            get=lambda *a, **k: FakeResponse(body={"avatar": "hash"}),
        )

        self.assertEqual("set", results[0]["status"])
        self.assertEqual(2, len(calls))
        self.assertIn("files", calls[0])
        self.assertTrue(
            calls[1]["json"]["avatar"].startswith("data:image/png;base64,")
        )

    def test_rejected_update_reports_the_discord_api_code(self):
        def patch(url, **kwargs):
            return FakeResponse(status_code=400, body={"code": 50035})

        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": WEBHOOK},
            PNG,
            patch=patch,
            get=lambda *a, **k: FakeResponse(body={"avatar": "hash"}),
        )

        self.assertEqual("failed", results[0]["status"])
        self.assertEqual("http_400_api_50035", results[0]["error"])

    def test_dry_run_never_contacts_discord(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("Discord must not be called during a dry run")

        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": WEBHOOK},
            PNG,
            dry_run=True,
            patch=forbidden,
            get=forbidden,
        )

        self.assertEqual("would_set", results[0]["status"])

    def test_missing_webhook_is_reported_without_a_request(self):
        results = self.module.apply_avatars([profile()], {}, PNG, patch=None, get=None)

        self.assertEqual("missing_webhook", results[0]["status"])

    def test_invalid_webhook_is_reported_without_a_request(self):
        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": "https://example.com/api/webhooks/1/x"},
            PNG,
        )

        self.assertEqual("invalid_webhook", results[0]["status"])

    def test_rejected_update_reports_status_without_the_webhook_url(self):
        def patch(url, **kwargs):
            return FakeResponse(status_code=403)

        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": WEBHOOK},
            PNG,
            patch=patch,
            get=lambda *a, **k: FakeResponse(body={"avatar": "abc"}),
        )

        self.assertEqual("failed", results[0]["status"])
        self.assertEqual("http_403", results[0]["error"])
        self.assertNotIn(WEBHOOK, str(results))

    def test_update_without_a_stored_avatar_is_a_failure(self):
        results = self.module.apply_avatars(
            [profile()],
            {"DISCORD_WEBHOOK_GN_TOP_KR": WEBHOOK},
            PNG,
            patch=lambda *a, **k: FakeResponse(),
            get=lambda *a, **k: FakeResponse(body={"avatar": None}),
        )

        self.assertEqual("failed", results[0]["status"])
        self.assertEqual("avatar_not_applied", results[0]["error"])

    def test_select_profiles_keeps_registry_order_and_rejects_unknown_ids(self):
        profiles = [profile("top_kr"), profile("top_us", "DISCORD_WEBHOOK_GN_TOP_US")]

        selected = self.module.select_profiles(profiles, "top_us,top_kr")
        self.assertEqual(["top_kr", "top_us"], [item.profile_id for item in selected])

        with self.assertRaises(ValueError):
            self.module.select_profiles(profiles, "missing")

    def test_main_defaults_to_dry_run_without_printing_webhook_urls(self):
        output = io.StringIO()
        with mock.patch.object(
            self.module, "load_profiles", return_value=[profile()]
        ), mock.patch.object(
            self.module, "fetch_avatar_image", return_value=PNG
        ), redirect_stdout(output):
            exit_code = self.module.main([])

        self.assertEqual(0, exit_code)
        self.assertIn("mode=dry_run", output.getvalue())
        self.assertNotIn("discord.com/api/webhooks", output.getvalue())

    def test_main_applies_only_with_the_confirmation(self):
        seen = {}

        def fake_apply(profiles, env, image, dry_run=False, **kwargs):
            seen["dry_run"] = dry_run
            return [{"profile_id": "top_kr", "status": "set"}]

        output = io.StringIO()
        with mock.patch.object(
            self.module, "load_profiles", return_value=[profile()]
        ), mock.patch.object(
            self.module, "fetch_avatar_image", return_value=PNG
        ), mock.patch.object(
            self.module, "apply_avatars", side_effect=fake_apply
        ), redirect_stdout(output):
            exit_code = self.module.main(["--confirm", "SET", "--profile", "top_kr"])

        self.assertEqual(0, exit_code)
        self.assertFalse(seen["dry_run"])
        self.assertIn("mode=apply", output.getvalue())

    def test_main_rejects_an_unknown_profile_before_touching_discord(self):
        output = io.StringIO()
        with mock.patch.object(
            self.module, "load_profiles", return_value=[profile()]
        ), redirect_stdout(output):
            exit_code = self.module.main(["--profile", "missing", "--confirm", "SET"])

        self.assertEqual(2, exit_code)
        self.assertIn("::error", output.getvalue())


if __name__ == "__main__":
    unittest.main()
