import copy
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
PROFILES_PATH = Path(__file__).resolve().parents[1] / "config" / "google_news_profiles.json"
FAKE_WEBHOOK_BASE = "https://" + "discord.com/api/webhooks"


def load_profiles_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("google_news_profiles", None)
        return importlib.import_module("google_news_profiles")
    finally:
        sys.path.pop(0)


def valid_registry():
    return [
        {
            "id": "top_us",
            "handler": "top",
            "webhook_env": "DISCORD_WEBHOOK_GN_TOP_US",
            "expected_webhook_name": "Google News - TOP - US",
            "state_db": "top_us.db",
            "visible_username": "Google News",
            "environment": {"TOP_MODE": "true", "TOP_COUNTRY": "US"},
        },
        {
            "id": "keyword_iu",
            "handler": "keyword",
            "webhook_env": "DISCORD_WEBHOOK_GN_KEYWORD_IU",
            "expected_webhook_name": "Google News - KEYWORD - IU",
            "state_db": "keyword_iu.db",
            "visible_username": "Google News",
            "environment": {
                "KEYWORD_MODE": "true",
                "KEYWORD": "아이유",
                "HL": "ko",
                "GL": "KR",
                "CEID": "KR:ko",
                "WHEN": "3d",
                "KEYWORD_MATCH_MODE": "title",
                "KEYWORD_MATCH_ALIASES": 'IU | "Lee Ji-eun" | 이지은',
            },
        },
    ]


class GoogleNewsProfileTests(unittest.TestCase):
    def setUp(self):
        self.module = load_profiles_module()

    def write_registry(self, data):
        temporary = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        self.addCleanup(lambda: os.unlink(temporary.name))
        with temporary:
            json.dump(data, temporary, ensure_ascii=False)
        return temporary.name

    def test_real_registry_contains_exact_routes(self):
        profiles = self.module.load_profiles(str(PROFILES_PATH))

        self.assertEqual(
            [
                "top_us",
                "top_kr",
                "top_jp",
                "top_cn",
                "topic_korea",
                "topic_seoul",
                "topic_ent",
                "topic_tech",
                "topic_scitech",
                "keyword_nocode",
                "keyword_iu",
            ],
            [profile.profile_id for profile in profiles],
        )
        self.assertEqual(11, len({profile.webhook_env for profile in profiles}))
        self.assertEqual(11, len({profile.expected_webhook_name for profile in profiles}))
        self.assertEqual(11, len({profile.state_db for profile in profiles}))
        self.assertTrue(all(profile.visible_username == "Google News" for profile in profiles))
        self.assertEqual(
            [
                "DISCORD_WEBHOOK_GN_TOP_US",
                "DISCORD_WEBHOOK_GN_TOP_KR",
                "DISCORD_WEBHOOK_GN_TOP_JP",
                "DISCORD_WEBHOOK_GN_TOP_CN",
                "DISCORD_WEBHOOK_GN_TOPIC_KOREA",
                "DISCORD_WEBHOOK_GN_TOPIC_SEOUL",
                "DISCORD_WEBHOOK_GN_TOPIC_ENT",
                "DISCORD_WEBHOOK_GN_TOPIC_TECH",
                "DISCORD_WEBHOOK_GN_TOPIC_SCITECH",
                "DISCORD_WEBHOOK_GN_KEYWORD_NOCODE",
                "DISCORD_WEBHOOK_GN_KEYWORD_IU",
            ],
            [profile.webhook_env for profile in profiles],
        )
        self.assertEqual(
            [
                "Google News - TOP - US",
                "Google News - TOP - KR",
                "Google News - TOP - JP",
                "Google News - TOP - CN",
                "Google News - TOPIC - KOREA",
                "Google News - TOPIC - SEOUL",
                "Google News - TOPIC - ENT",
                "Google News - TOPIC - TECH",
                "Google News - TOPIC - SCITECH",
                "Google News - KEYWORD - NOCODE",
                "Google News - KEYWORD - IU",
            ],
            [profile.expected_webhook_name for profile in profiles],
        )

    def test_real_registry_has_the_approved_feed_definitions(self):
        profiles = {
            profile.profile_id: profile
            for profile in self.module.load_profiles(str(PROFILES_PATH))
        }

        self.assertEqual(
            {
                "TOP_MODE": "true",
                "TOP_COUNTRY": "US",
                "FEED_COUNTRY": "US",
                "DISPLAY_LANGUAGE": "en",
            },
            profiles["top_us"].environment,
        )
        self.assertEqual("ko", profiles["top_kr"].environment["DISPLAY_LANGUAGE"])
        self.assertEqual("ja", profiles["top_jp"].environment["DISPLAY_LANGUAGE"])
        self.assertEqual("zh-CN", profiles["top_cn"].environment["DISPLAY_LANGUAGE"])
        self.assertEqual("korea", profiles["topic_korea"].environment["TOPIC_KEYWORD"])
        self.assertEqual("서울", profiles["topic_seoul"].environment["KEYWORD"])
        self.assertEqual(
            '노코드 OR "no-code" OR nocode',
            profiles["keyword_nocode"].environment["KEYWORD"],
        )
        self.assertEqual(
            "아이유",
            profiles["keyword_iu"].environment["KEYWORD"],
        )
        self.assertEqual("3d", profiles["keyword_iu"].environment["WHEN"])
        self.assertEqual(
            "title", profiles["keyword_iu"].environment["KEYWORD_MATCH_MODE"]
        )
        self.assertEqual(
            'IU | "Lee Ji-eun" | 이지은',
            profiles["keyword_iu"].environment["KEYWORD_MATCH_ALIASES"],
        )

    def test_duplicate_routing_fields_are_rejected(self):
        for field in ("id", "webhook_env", "expected_webhook_name", "state_db"):
            with self.subTest(field=field):
                data = valid_registry()
                data[1][field] = data[0][field]
                with self.assertRaisesRegex(ValueError, "duplicate {}".format(field)):
                    self.module.validate_profile_data(data)

    def test_invalid_handler_unknown_field_and_path_traversal_are_rejected(self):
        invalid_handler = valid_registry()
        invalid_handler[0]["handler"] = "video"
        with self.assertRaisesRegex(ValueError, "invalid handler"):
            self.module.validate_profile_data(invalid_handler)

        unknown_field = valid_registry()
        unknown_field[0]["channel_id"] = "secret-looking-id"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            self.module.validate_profile_data(unknown_field)

        unsafe_path = valid_registry()
        unsafe_path[0]["state_db"] = "../top.db"
        with self.assertRaisesRegex(ValueError, "safe database filename"):
            self.module.validate_profile_data(unsafe_path)

    def test_missing_handler_keys_and_non_string_environment_are_rejected(self):
        missing = valid_registry()
        del missing[0]["environment"]["TOP_COUNTRY"]
        with self.assertRaisesRegex(ValueError, "missing environment keys"):
            self.module.validate_profile_data(missing)

        non_string = valid_registry()
        non_string[0]["environment"]["TOP_MODE"] = True
        with self.assertRaisesRegex(ValueError, "environment values must be strings"):
            self.module.validate_profile_data(non_string)

    def test_secret_shaped_configuration_is_rejected(self):
        webhook_url = valid_registry()
        webhook_url[0]["environment"]["RSS_URL_TOP"] = FAKE_WEBHOOK_BASE + "/123/token"
        with self.assertRaisesRegex(ValueError, "credential-like"):
            self.module.validate_profile_data(webhook_url)

        token_key = valid_registry()
        token_key[0]["environment"]["API_TOKEN"] = "not-a-real-token"
        with self.assertRaisesRegex(ValueError, "credential-like"):
            self.module.validate_profile_data(token_key)

    def test_build_handler_environment_uses_only_the_selected_secret(self):
        profile = self.module.validate_profile_data(valid_registry())[0]
        base_env = {
            "PATH": "/usr/bin",
            "LANG": "ko_KR.UTF-8",
            "DISCORD_WEBHOOK_GN_TOP_US": FAKE_WEBHOOK_BASE + "/1/redacted",
            "DISCORD_WEBHOOK_GN_KEYWORD_IU": FAKE_WEBHOOK_BASE + "/2/redacted",
            "DISCORD_WEBHOOK_ADMIN": FAKE_WEBHOOK_BASE + "/3/redacted",
            "UNRELATED_SECRET": "must-not-be-forwarded",
        }

        environment = self.module.build_handler_environment(
            profile,
            base_env,
            "/state",
            "/state/resolver.db",
            True,
        )

        self.assertEqual(FAKE_WEBHOOK_BASE + "/1/redacted", environment["DISCORD_WEBHOOK_TOP"])
        self.assertEqual("Google News", environment["DISCORD_USERNAME_TOP"])
        self.assertEqual("/state/top_us.db", environment["GOOGLE_NEWS_DB_PATH"])
        self.assertEqual("/state/resolver.db", environment["GOOGLE_NEWS_RESOLVER_DB_PATH"])
        self.assertEqual("true", environment["MANUAL_TEST_MODE"])
        self.assertEqual("1000", environment["GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS"])
        self.assertEqual(
            FAKE_WEBHOOK_BASE + "/3/redacted", environment["DISCORD_WEBHOOK_ADMIN"]
        )
        self.assertNotIn("DISCORD_WEBHOOK_GN_KEYWORD_IU", environment)
        self.assertNotIn("UNRELATED_SECRET", environment)

    def test_keyword_match_mode_is_validated(self):
        invalid = valid_registry()
        invalid[1]["environment"]["KEYWORD_MATCH_MODE"] = "raw_html"

        with self.assertRaisesRegex(ValueError, "KEYWORD_MATCH_MODE"):
            self.module.validate_profile_data(invalid)

    def test_common_filter_language_and_timezone_settings_are_allowed_per_profile(self):
        data = valid_registry()
        data[0]["environment"].update(
            {
                "FEED_DATE_FILTER": "calendar:7d",
                "FEED_KEYWORD_FILTER": "technology NOT rumor",
                "FEED_KEYWORD_SCOPE": "title_or_description",
                "FEED_TIMEZONE": "Asia/Tokyo",
                "FEED_COUNTRY": "JP",
                "DISPLAY_LANGUAGE": "ja",
            }
        )

        profiles = self.module.validate_profile_data(data)

        self.assertEqual("calendar:7d", profiles[0].environment["FEED_DATE_FILTER"])
        self.assertEqual("ja", profiles[0].environment["DISPLAY_LANGUAGE"])

    def test_profile_common_settings_override_global_common_settings(self):
        data = valid_registry()
        data[0]["environment"]["DISPLAY_LANGUAGE"] = "ja"
        data[0]["environment"]["FEED_TIMEZONE"] = "Asia/Tokyo"
        profile = self.module.validate_profile_data(data)[0]

        environment = self.module.build_handler_environment(
            profile,
            {
                profile.webhook_env: FAKE_WEBHOOK_BASE + "/1/redacted",
                "DISPLAY_LANGUAGE": "ko",
                "FEED_TIMEZONE": "Asia/Seoul",
                "FEED_DATE_FILTER": "calendar:1d",
            },
            "/state",
            "/state/resolver.db",
            False,
        )

        self.assertEqual("ja", environment["DISPLAY_LANGUAGE"])
        self.assertEqual("Asia/Tokyo", environment["FEED_TIMEZONE"])
        self.assertEqual("calendar:1d", environment["FEED_DATE_FILTER"])

    def test_empty_display_language_uses_country_default(self):
        self.module.validate_common_feed_environment(
            {
                "DISPLAY_LANGUAGE": "",
                "FEED_COUNTRY": "JP",
                "FEED_KEYWORD_SCOPE": "title",
            }
        )

    def test_missing_selected_webhook_is_rejected(self):
        profile = self.module.validate_profile_data(copy.deepcopy(valid_registry()))[0]
        with self.assertRaisesRegex(ValueError, "missing webhook environment"):
            self.module.build_handler_environment(
                profile, {"PATH": "/usr/bin"}, "/state", "/state/resolver.db", False
            )


if __name__ == "__main__":
    unittest.main()
