# Google News Profile Display Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate the Google News keyword shown in Discord from its search expression and exclude Korean entertainment-topic items whose main title contains `운세`.

**Architecture:** Extend the existing validated profile environment with an optional display-only value, select it only at keyword-message formatting time, and express the entertainment exclusion through the existing shared Boolean feed filter. Keep query construction, service matching, queues, URL resolution, webhooks, schedules, and YouTube unchanged.

**Tech Stack:** Python 3.8-compatible standard library, existing BeautifulSoup-based Google News parsing, JSON profile registry, standard `unittest`, Markdown documentation.

## Global Constraints

- `KEYWORD` remains the Google News query and keyword-matching expression.
- `KEYWORD_DISPLAY_NAME` affects only the Discord header and falls back to `KEYWORD` when absent.
- `topic_ent` excludes `운세` only when it appears in the main RSS title.
- English and Korean documentation must carry equivalent technical meaning.
- Do not change databases, delivery queues, URL resolution, webhooks, schedules, or YouTube behavior.

---

### Task 1: Validate and Configure Profile Fields

**Files:**
- Modify: `.github/scripts/google_news_profiles.py`
- Modify: `.github/config/google_news_profiles.json`
- Test: `.github/tests/test_google_news_profiles.py`

**Interfaces:**
- Consumes: existing `GoogleNewsProfile.environment` string mapping and shared common feed-filter validation.
- Produces: optional validated `KEYWORD_DISPLAY_NAME`, plus `topic_ent` title-only `NOT 운세` settings.

- [ ] **Step 1: Write failing profile tests**

Add assertions that the real `keyword_nocode` profile keeps the full `KEYWORD` and exposes `KEYWORD_DISPLAY_NAME == "노코드"`; assert `topic_ent` has `FEED_KEYWORD_FILTER == "NOT 운세"` and `FEED_KEYWORD_SCOPE == "title"`. Add a validation test that accepts a non-empty display name for a keyword handler and rejects a whitespace-only value.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
/private/tmp/discordactions-profile-filter-venv/bin/python -m unittest .github/tests/test_google_news_profiles.py -v
```

Expected: failure because `KEYWORD_DISPLAY_NAME` is unknown or missing from the real registry.

- [ ] **Step 3: Implement the minimal registry validation and configuration**

Add `KEYWORD_DISPLAY_NAME` to the keyword handler allowlist and reject it when present but blank after trimming. Update the real profiles with:

```json
"KEYWORD_DISPLAY_NAME": "노코드"
```

for `keyword_nocode`, and:

```json
"FEED_KEYWORD_FILTER": "NOT 운세",
"FEED_KEYWORD_SCOPE": "title"
```

for `topic_ent`.

- [ ] **Step 4: Run the focused profile tests**

Run the command from Step 2. Expected: all `test_google_news_profiles` tests pass.

### Task 2: Use the Display Name Only in Discord Headers

**Files:**
- Modify: `.github/scripts/googlenews-keyword_to_discord.py`
- Test: `.github/tests/test_google_news_script_integration.py`

**Interfaces:**
- Consumes: `KEYWORD` for query/filter behavior and optional `KEYWORD_DISPLAY_NAME` for presentation.
- Produces: `get_keyword_display_name(keyword: str) -> str`, used only by `format_discord_message` call sites.

- [ ] **Step 1: Write failing integration tests**

Add tests that set `KEYWORD_DISPLAY_NAME` to `노코드`, assert the helper returns `노코드` for the full expression, and assert an empty configured value falls back to the full keyword. Keep the existing message assertion for `아이유`.

- [ ] **Step 2: Run the focused integration tests and confirm failure**

Run:

```bash
/private/tmp/discordactions-profile-filter-venv/bin/python -m unittest .github/tests/test_google_news_script_integration.py -v
```

Expected: failure because no display-name environment or helper exists.

- [ ] **Step 3: Implement minimal display selection**

Read and trim `KEYWORD_DISPLAY_NAME` once at module load, add:

```python
def get_keyword_display_name(keyword):
    return KEYWORD_DISPLAY_NAME or keyword
```

and pass `get_keyword_display_name(keyword)` to `format_discord_message`. Do not use the display name in `get_rss_url`, `extract_keyword_query`, or `compile_google_news_feed_filter`.

- [ ] **Step 4: Run the focused integration tests**

Run the command from Step 2. Expected: all `test_google_news_script_integration` tests pass.

### Task 3: Prove Entertainment Filtering Semantics

**Files:**
- Test: `.github/tests/test_google_news_feed_filter.py`

**Interfaces:**
- Consumes: existing `compile_google_news_feed_filter(common_keyword, common_scope, ...)`.
- Produces: regression evidence for main-title-only negative filtering.

- [ ] **Step 1: Add the focused filter test**

Compile with `common_keyword="NOT 운세"` and `common_scope="title"`. Assert that `"오늘의 운세 - 언론사"` is rejected, `"연예계 소식 - 언론사"` is accepted, and the latter remains accepted when its description contains a related link titled `"오늘의 운세"`.

- [ ] **Step 2: Run the focused feed-filter tests**

Run:

```bash
/private/tmp/discordactions-profile-filter-venv/bin/python -m unittest .github/tests/test_google_news_feed_filter.py -v
```

Expected: all tests pass using the existing shared filter engine.

### Task 4: Document the User-Facing Settings

**Files:**
- Modify: `README.md`
- Modify: `README_KR.md`
- Test: `.github/tests/test_youtube_rss_documentation.py`

**Interfaces:**
- Consumes: approved `KEYWORD_DISPLAY_NAME` and `topic_ent` configuration semantics.
- Produces: equivalent English and Korean instructions and examples.

- [ ] **Step 1: Write failing documentation tests**

Assert both READMEs mention `KEYWORD_DISPLAY_NAME`, distinguish it from `KEYWORD`, show the `노코드` example, and explain that `NOT 운세` with `title` scope ignores related-only occurrences.

- [ ] **Step 2: Run the focused documentation tests and confirm failure**

Run:

```bash
/private/tmp/discordactions-profile-filter-venv/bin/python -m unittest .github/tests/test_youtube_rss_documentation.py -v
```

Expected: failure because the new settings are undocumented.

- [ ] **Step 3: Update both READMEs**

Add concise profile JSON examples and clearly state that `KEYWORD_DISPLAY_NAME` changes only the Discord heading. Explain that the entertainment profile's title-only negative filter excludes main titles containing `운세` but does not inspect related headlines for this exclusion.

- [ ] **Step 4: Run focused documentation tests**

Run the command from Step 2. Expected: all documentation tests pass.

### Task 5: Full Verification and Checkpoint

**Files:**
- Verify all modified files from Tasks 1–4.

**Interfaces:**
- Consumes: completed implementation and tests.
- Produces: one verified local feature checkpoint ready for review; no remote publication.

- [ ] **Step 1: Run the full unit suite**

```bash
/private/tmp/discordactions-profile-filter-venv/bin/python -m unittest discover -s .github/tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile and validate configuration**

```bash
/private/tmp/discordactions-profile-filter-venv/bin/python -m py_compile .github/scripts/*.py
/private/tmp/discordactions-profile-filter-venv/bin/python -m json.tool .github/config/google_news_profiles.json
git diff --check
```

Expected: every command exits with status 0.

- [ ] **Step 3: Inspect scope and secrets**

Review `git status --short`, `git diff origin/main`, and scan changed lines for webhook URLs, tokens, cookies, and private keys. Expected: only the planned profile, handler, tests, docs, specification, and plan files differ; no secret values appear.

- [ ] **Step 4: Create one local verified commit**

Stage only the planned files and commit with:

```text
feat: add Google News profile display filters
```

Do not push or create a PR until the user approves the exact branch, files, and verification evidence.
