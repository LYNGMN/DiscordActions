# Google News Country-Specific Date and Time Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render Google News publication times in the exact approved Korean, Japanese, Chinese, and US formats without changing YouTube dates.

**Architecture:** Add one country-aware Google News formatter to `feed_localization.py`, reusing the existing strict timezone and aware-datetime parsers. Wire the Top, Keyword, and Topic scripts to that formatter while retaining the existing general formatter as the fallback for countries without a newly specified layout.

**Tech Stack:** Python 3.8, `unittest`, `python-dateutil`, `pytz`, Babel, existing Google News scripts.

## Global Constraints

- Korea: `2026년 08월 31일 오후 05:41:00 (KST)` with a 12-hour clock and `오전`/`오후`.
- Japan: `2026年09月01日 13:51:11 (JST)` with a 24-hour clock.
- China: `2026年09月01日 09:50:00 (CST)` with a 24-hour clock.
- United States: `August 31, 2026, 05:41:00 PM (EDT)` with a full month name, 12-hour clock, and automatic `EST`/`EDT` selection from `America/New_York`.
- Numeric month, day, hour, minute, and second components are always two digits.
- The date line contains no country name, flag, or newline.
- Top, Keyword, and Topic use the same formatter.
- Existing YouTube date formatting remains unchanged.
- No new dependency, database migration, schedule change, or live Discord delivery is included.

---

### Task 1: Add and Verify the Shared Google News Formatter

**Files:**
- Modify: `.github/tests/test_feed_localization.py`
- Modify: `.github/scripts/feed_localization.py`

**Interfaces:**
- Consumes: existing `_timezone(timezone_name)` and `_aware_datetime(value)` helpers.
- Produces: `format_google_news_datetime(value: str, country_code: str, timezone_name: str, fallback_language: str = "en") -> str`.

- [ ] **Step 1: Write failing exact-format and compatibility tests**

Add a parameterized subtest for the four country formats, dedicated Korean morning/noon assertions, US winter/summer assertions, and an unchanged YouTube/general formatter assertion:

```python
def test_google_news_datetime_uses_country_specific_formats(self):
    cases = (
        ("2026-08-31T08:41:00Z", "KR", "Asia/Seoul", "ko", "2026년 08월 31일 오후 05:41:00 (KST)"),
        ("2026-09-01T04:51:11Z", "JP", "Asia/Tokyo", "ja", "2026年09月01日 13:51:11 (JST)"),
        ("2026-09-01T01:50:00Z", "CN", "Asia/Shanghai", "zh-CN", "2026年09月01日 09:50:00 (CST)"),
        ("2026-08-31T21:41:00Z", "US", "America/New_York", "en", "August 31, 2026, 05:41:00 PM (EDT)"),
    )
    for value, country, timezone_name, language, expected in cases:
        with self.subTest(country=country):
            actual = self.localization.format_google_news_datetime(
                value, country, timezone_name, language
            )
            self.assertEqual(expected, actual)
            self.assertNotIn("\n", actual)

def test_google_news_datetime_handles_korean_periods_and_us_dst(self):
    self.assertEqual(
        "2026년 01월 02일 오전 12:03:04 (KST)",
        self.localization.format_google_news_datetime(
            "2026-01-01T15:03:04Z", "KR", "Asia/Seoul", "ko"
        ),
    )
    self.assertEqual(
        "2026년 01월 02일 오후 12:03:04 (KST)",
        self.localization.format_google_news_datetime(
            "2026-01-02T03:03:04Z", "KR", "Asia/Seoul", "ko"
        ),
    )
    self.assertEqual(
        "January 02, 2026, 05:03:04 AM (EST)",
        self.localization.format_google_news_datetime(
            "2026-01-02T10:03:04Z", "US", "America/New_York", "en"
        ),
    )
    self.assertEqual(
        "July 02, 2026, 06:03:04 AM (EDT)",
        self.localization.format_google_news_datetime(
            "2026-07-02T10:03:04Z", "US", "America/New_York", "en"
        ),
    )
```

- [ ] **Step 2: Run the focused tests and confirm the missing-interface failure**

Run:

```bash
python -m unittest .github/tests/test_feed_localization.py -v
```

Expected: FAIL because `feed_localization` has no `format_google_news_datetime` attribute.

- [ ] **Step 3: Implement the minimal formatter**

Add this function without changing `format_feed_datetime`:

```python
def format_google_news_datetime(
    value: str,
    country_code: str,
    timezone_name: str,
    fallback_language: str = "en",
) -> str:
    country = country_code.strip().upper() if isinstance(country_code, str) else ""
    zone = _timezone(timezone_name)
    local_dt = _aware_datetime(value).astimezone(zone)
    timezone_abbreviation = local_dt.tzname()

    if country == "KR":
        period = "오전" if local_dt.hour < 12 else "오후"
        hour = local_dt.hour % 12 or 12
        return (
            f"{local_dt.year:04d}년 {local_dt.month:02d}월 {local_dt.day:02d}일 "
            f"{period} {hour:02d}:{local_dt.minute:02d}:{local_dt.second:02d} "
            f"({timezone_abbreviation})"
        )
    if country in {"JP", "CN"}:
        return (
            f"{local_dt.year:04d}年{local_dt.month:02d}月{local_dt.day:02d}日 "
            f"{local_dt.hour:02d}:{local_dt.minute:02d}:{local_dt.second:02d} "
            f"({timezone_abbreviation})"
        )
    if country == "US":
        return (
            f"{local_dt.strftime('%B')} {local_dt.day:02d}, {local_dt.year:04d}, "
            f"{local_dt.strftime('%I:%M:%S %p')} ({timezone_abbreviation})"
        )
    return format_feed_datetime(value, fallback_language, timezone_name)
```

- [ ] **Step 4: Run the localization tests and confirm all pass**

Run:

```bash
python -m unittest .github/tests/test_feed_localization.py -v
```

Expected: all localization and YouTube message tests PASS.

- [ ] **Step 5: Commit the verified shared formatter**

```bash
git add .github/tests/test_feed_localization.py .github/scripts/feed_localization.py
git commit -m "fix: format Google News dates by country"
```

### Task 2: Wire All Google News Message Paths and Run Regression Checks

**Files:**
- Modify: `.github/tests/test_google_news_script_integration.py`
- Modify: `.github/scripts/googlenews-top_to_discord.py`
- Modify: `.github/scripts/googlenews-keyword_to_discord.py`
- Modify: `.github/scripts/googlenews-topic_to_discord.py`

**Interfaces:**
- Consumes: `format_google_news_datetime(value, country_code, timezone_name, fallback_language)` from Task 1.
- Produces: exact country-specific `📅 ...` lines from every Google News message formatter.

- [ ] **Step 1: Write failing integration tests for Top, Keyword, and Topic**

Add tests that set each module's country, timezone, and display language, then assert the exact final date line. Include a source inspection assertion that all three scripts import and call `format_google_news_datetime` and no longer call `format_feed_datetime`.

```python
def test_all_google_news_messages_use_country_specific_datetime(self):
    item = {
        "title": "Test story",
        "link": "https://publisher.example/story",
        "description": "",
        "pub_date": "Mon, 31 Aug 2026 08:41:00 GMT",
    }
    keyword = load_script(SCRIPT_PATHS[0])
    top = load_script(SCRIPT_PATHS[1])
    topic = load_script(SCRIPT_PATHS[2])

    keyword.DISPLAY_LANGUAGE = "ko"
    keyword.FEED_TIMEZONE = "Asia/Seoul"
    keyword.FEED_COUNTRY = "KR"
    top.DISPLAY_LANGUAGE = "ko"
    top.FEED_TIMEZONE = "Asia/Seoul"
    top.FEED_COUNTRY = "KR"
    topic.DISPLAY_LANGUAGE = "ko"
    topic.FEED_TIMEZONE = "Asia/Seoul"
    topic.FEED_COUNTRY = "KR"

    self.assertTrue(
        keyword.format_discord_message(item, "테스트", "KR").endswith(
            "📅 2026년 08월 31일 오후 05:41:00 (KST)"
        )
    )
    self.assertTrue(
        top.format_discord_message(item, "`Google 뉴스`", "Asia/Seoul", "").endswith(
            "📅 2026년 08월 31일 오후 05:41:00 (KST)"
        )
    )
    self.assertTrue(
        topic.format_discord_message(
            item, "Google 뉴스", "테스트", "주제", "🇰🇷", "KR"
        ).endswith("📅 2026년 08월 31일 오후 05:41:00 (KST)")
    )
```

- [ ] **Step 2: Run the focused integration test and confirm old output fails**

Run:

```bash
python -m unittest .github/tests/test_google_news_script_integration.py -v
```

Expected: FAIL because the scripts still use Babel's general long date-time format.

- [ ] **Step 3: Replace the formatter import and calls in all three scripts**

Use the shared interface with the effective profile country and display language:

```python
formatted_date = format_google_news_datetime(
    news_item["pub_date"],
    FEED_COUNTRY or country_code,
    timezone_name,
    display_language,
)
```

For Top, use `FEED_COUNTRY or TOP_COUNTRY or ""` as the effective country.

- [ ] **Step 4: Run focused and complete verification**

Run:

```bash
python -m unittest .github/tests/test_feed_localization.py -v
python -m unittest .github/tests/test_google_news_script_integration.py -v
python -m unittest discover -s .github/tests -v
python -m py_compile .github/scripts/*.py
python -m json.tool .github/config/google_news_profiles.json
git diff --check
```

Expected: all tests PASS; compilation, JSON parsing, and whitespace checks exit 0.

- [ ] **Step 5: Check the exact change scope and sensitive-data patterns**

Run:

```bash
git status --short
git diff --stat 5766c0c6165da9cec7b0eb2e84a8fadddc5d27b9
rg -n --hidden -g '!*.db' -g '!*.sqlite*' '(discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9._-]+|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9_]{20,})' .github/scripts .github/tests docs/superpowers
```

Expected: only the approved plan, tests, shared localization module, and three Google News scripts are changed; the credential scan returns no matches.

- [ ] **Step 6: Commit the verified Google News integration**

```bash
git add .github/tests/test_google_news_script_integration.py \
  .github/scripts/googlenews-top_to_discord.py \
  .github/scripts/googlenews-keyword_to_discord.py \
  .github/scripts/googlenews-topic_to_discord.py
git commit -m "fix: use country dates in Google News messages"
```

## 한국어 실행 요약

1. 공통 현지화 모듈에 Google 뉴스 전용 날짜·시간 함수를 추가합니다.
2. 한국·일본·중국·미국의 정확한 출력과 미국 `EST`·`EDT` 자동 전환을
   실패 테스트부터 검증합니다.
3. Google 뉴스 Top, Keyword, Topic이 같은 함수를 사용하도록 연결합니다.
4. 기존 YouTube 날짜 형식이 바뀌지 않는지 포함해 전체 테스트를 다시
   실행합니다.
5. 실제 Discord 메시지는 보내지 않으며 검증된 변경만 의도별 Commit으로
   보존합니다.
