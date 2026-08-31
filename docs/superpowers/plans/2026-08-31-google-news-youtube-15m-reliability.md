# Google News and YouTube 15-Minute Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Google News and YouTube updates every 15 minutes with fixed Discord branding, bounded publisher-link conversion, stable article deduplication, and safe first-run state handling.

**Architecture:** Keep the existing unified Google News dispatcher and legacy handlers, but add stable identities at the shared delivery-state boundary and a small shared related-link filter. Add two focused YouTube modules so branding and first-run selection can be tested without importing the Google API client. Stagger the two workflows and preserve their SQLite artifacts across runs.

**Tech Stack:** Python 3.8, standard `unittest`, SQLite, `requests`, BeautifulSoup, GitHub Actions YAML, existing Google API client dependencies.

## Global Constraints

- Google News sender is exactly `Google News` with `https://discordactions.github.io/logo/media/original/news/googlenews.png`.
- YouTube sender is exactly `YouTube` with `https://discordactions.github.io/logo/media/original/youtube/youtube_social_circle_red.png`.
- Google News runs at `07,22,37,52`; YouTube runs at `11,26,41,56`.
- Legacy Google News Top, Topic, and Keyword workflows remain disabled.
- No new external package, proxy, browser automation, secret, or URL-decoding service.
- Display at most four related articles and never display a `news.google.com` related link.
- Google News network decoding remains sequential, uses one-second spacing, and is capped at two new decodes per profile per run.
- IU uses `KEYWORD=아이유`, `WHEN=3d`, and the existing 120-minute application age bound.
- Never print webhook URLs, API keys, tokens, response bodies, or URL queries.
- Direct and force pushes to `main` are forbidden; release only through a reviewed Draft PR and approved Squash merge.

---

## File Structure

- Modify `.github/scripts/google_news_delivery_state.py`: canonical article identities and atomic duplicate-safe reservation.
- Create `.github/scripts/google_news_related_links.py`: original-only related-link resolution and four-item bound.
- Modify `.github/scripts/google_news_url_resolver.py`: allow related links to use the existing bounded network path.
- Modify the three `.github/scripts/googlenews-*_to_discord.py` handlers: pass stable identities and omit unresolved related links.
- Modify `.github/scripts/google_news_profiles.py` and `.github/config/google_news_profiles.json`: two-request budget and exact IU query.
- Modify `.github/workflows/googlenews-to-discord.yml`: staggered 15-minute Google News schedule.
- Create `.github/scripts/youtube_discord_delivery.py`: fixed YouTube branding and bounded webhook delivery.
- Create `.github/scripts/youtube_delivery_state.py`: pure safe baseline/manual selection.
- Modify `.github/scripts/youtube_to_discord.py`: use the shared YouTube boundaries and fail the workflow on errors.
- Modify `.github/workflows/youtube_to_discord.yml`: artifact-aware restore, safe manual input, and staggered 15-minute schedule.
- Modify `.github/workflows/test.yml`: compile every new runtime module.
- Extend `.github/tests/`: focused offline tests for each boundary and workflow contract.

---

### Task 1: Stable Google News Article Identity

**Files:**
- Modify: `.github/scripts/google_news_delivery_state.py`
- Test: `.github/tests/test_google_news_delivery_state.py`

**Interfaces:**
- Produces: `canonicalize_article_url(url: str) -> Optional[str]`
- Produces: `article_identity_keys(title: str, url: str) -> Tuple[str, ...]`
- Changes: `reserve_delivery(db_path: str, guid: str, title: str = "", link: str = "") -> bool`
- Preserves: `mark_delivery_sent(db_path: str, guid: str, message_id: str) -> None`

- [ ] **Step 1: Write failing identity and atomic reservation tests**

Add tests proving that tracking-only URL changes and new GUIDs are duplicates, an
exact normalized title with a new Google wrapper is a duplicate, distinct titles are
accepted, and existing `news_items` rows are backfilled:

```python
def test_changed_guid_and_tracking_query_are_one_article(self):
    first = "https://publisher.example/story?id=7&utm_source=google"
    second = "https://PUBLISHER.example/story?utm_medium=rss&id=7#section"
    self.assertTrue(self.module.reserve_delivery(self.db_path, "g1", "Same - Press", first))
    self.assertFalse(self.module.reserve_delivery(self.db_path, "g2", "Same - Press", second))

def test_changed_google_wrapper_is_deduped_by_normalized_title(self):
    self.assertTrue(self.module.reserve_delivery(
        self.db_path, "g1", "아이유   새 소식 - 언론사",
        "https://news.google.com/rss/articles/first",
    ))
    self.assertFalse(self.module.reserve_delivery(
        self.db_path, "g2", "아이유 새 소식 - 언론사",
        "https://news.google.com/rss/articles/second",
    ))
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `python3 -m unittest discover -s .github/tests -p 'test_google_news_delivery_state.py' -v`

Expected: FAIL because `reserve_delivery` does not accept title/link and no identity table exists.

- [ ] **Step 3: Implement canonical identities and atomic reservation**

Use Unicode NFKC/case-folded title text and a canonical publisher URL. Skip URL
identities for `news.google.com`; remove fragments, `utm_*`, `gclid`, `fbclid`,
`dclid`, `msclkid`, `oc`, and `ved` only in the identity copy. Hash values with
SHA-256 and store them in:

```sql
CREATE TABLE IF NOT EXISTS google_news_article_identity (
    identity_key TEXT PRIMARY KEY,
    guid TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

Run `BEGIN IMMEDIATE`, backfill identities from existing `news_items`, reject any
matching identity, insert the pending `news_items` row, then insert all identities in
one transaction.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run: `python3 -m unittest discover -s .github/tests -p 'test_google_news_delivery_state.py' -v`

Expected: all delivery-state tests PASS, including legacy GUID-only callers.

- [ ] **Step 5: Commit the independently verified state change**

```bash
git add .github/scripts/google_news_delivery_state.py .github/tests/test_google_news_delivery_state.py
git commit -m "fix: deduplicate resurfaced Google News articles"
```

---

### Task 2: Bounded Original-Only Related Links and Exact IU Profile

**Files:**
- Create: `.github/scripts/google_news_related_links.py`
- Modify: `.github/scripts/google_news_url_resolver.py`
- Modify: `.github/scripts/google_news_profiles.py`
- Modify: `.github/config/google_news_profiles.json`
- Modify: `.github/scripts/googlenews-top_to_discord.py`
- Modify: `.github/scripts/googlenews-topic_to_discord.py`
- Modify: `.github/scripts/googlenews-keyword_to_discord.py`
- Test: `.github/tests/test_google_news_related_links.py`
- Test: `.github/tests/test_google_news_url_resolver.py`
- Test: `.github/tests/test_google_news_profiles.py`
- Test: `.github/tests/test_google_news_script_integration.py`

**Interfaces:**
- Produces: `resolve_related_url(resolver, source_url: str) -> Optional[str]`
- Produces: `MAX_RELATED_ITEMS = 4`
- Consumes: `GoogleNewsUrlResolver.resolve_related(source_url) -> UrlResolution`
- Consumes: Task 1 `reserve_delivery(db_path, guid, title, link)`

- [ ] **Step 1: Write failing resolver, filter, profile, and format tests**

Cover a modern related URL using one bounded GET/POST pair, a budget-exhausted
fallback returning `None`, cached/legacy URLs requiring no request, the four-item
bound, `GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS=2`, exact `KEYWORD=아이유` and
`WHEN=3d`, and these exact source strings:

```python
self.assertIn("`Google 뉴스 - 아이유 - 한국 🇰🇷`", keyword_message)
self.assertIn("`Google 뉴스 - 기술 뉴스 - 과학/기술 🇰🇷`", topic_message)
```

- [ ] **Step 2: Run focused tests and observe RED**

Run:

```bash
python3 -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v
python3 -m unittest discover -s .github/tests -p 'test_google_news_profiles.py' -v
python3 -m unittest discover -s .github/tests -p 'test_google_news_script_integration.py' -v
python3 -m unittest discover -s .github/tests -p 'test_google_news_related_links.py' -v
```

Expected: FAIL because related URLs skip network, the helper does not exist, and the IU profile is broader than `아이유`.

- [ ] **Step 3: Implement the smallest shared related-link boundary**

`resolve_related_url` calls the resolver, accepts only HTTP(S) URLs whose lowercase
hostname is not `news.google.com` or a subdomain, and otherwise returns `None`.
Change `resolve_related` to share `_resolve(..., allow_network=True)`. In each handler,
stop after four accepted related items and skip `None`. Pass `title` and resolved
main `link` to Task 1's reservation. Set the handler environment budget to `2` and
change only the IU registry entry to:

```json
{
  "KEYWORD_MODE": "true",
  "KEYWORD": "아이유",
  "HL": "ko",
  "GL": "KR",
  "CEID": "KR:ko",
  "WHEN": "3d"
}
```

- [ ] **Step 4: Run the focused suite and observe GREEN**

Run the command from Step 2.

Expected: all related-link, resolver, profile, and handler integration tests PASS.

- [ ] **Step 5: Commit the verified Google News content change**

```bash
git add .github/config/google_news_profiles.json .github/scripts/google_news_*.py \
  .github/scripts/googlenews-*_to_discord.py .github/tests/test_google_news_*.py
git commit -m "fix: resolve and deduplicate Google News article links"
```

---

### Task 3: Google News 15-Minute Schedule Contract

**Files:**
- Modify: `.github/workflows/googlenews-to-discord.yml`
- Test: `.github/tests/test_google_news_unified_workflow.py`
- Test: `.github/tests/test_google_news_manual_workflows.py`

**Interfaces:**
- Preserves: `GOOGLE_NEWS_SCHEDULE_ENABLED == 'true'` activation gate.
- Produces: cron `7,22,37,52 * * * *`.

- [ ] **Step 1: Change the workflow test expectation first**

```python
self.assertIn("cron: '7,22,37,52 * * * *'", source)
self.assertNotIn("cron: '7,37 * * * *'", source)
```

- [ ] **Step 2: Run and observe RED**

Run:

```bash
python3 -m unittest discover -s .github/tests -p 'test_google_news_unified_workflow.py' -v
python3 -m unittest discover -s .github/tests -p 'test_google_news_manual_workflows.py' -v
```

Expected: FAIL on the old 30-minute cron.

- [ ] **Step 3: Change only the unified cron**

```yaml
on:
  schedule:
    - cron: '7,22,37,52 * * * *'
```

Do not enable or alter the three legacy schedules.

- [ ] **Step 4: Run and observe GREEN**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit the schedule contract**

```bash
git add .github/workflows/googlenews-to-discord.yml .github/tests/test_google_news_unified_workflow.py .github/tests/test_google_news_manual_workflows.py
git commit -m "feat: check Google News every 15 minutes"
```

---

### Task 4: Fixed YouTube Discord Branding

**Files:**
- Create: `.github/scripts/youtube_discord_delivery.py`
- Modify: `.github/scripts/youtube_to_discord.py`
- Create: `.github/tests/test_youtube_discord_delivery.py`

**Interfaces:**
- Produces: `branded_youtube_payload(payload: dict) -> dict`
- Produces: `send_youtube_webhook(webhook_url: str, payload: dict, post=requests.post) -> None`
- Preserves: caller payload immutability.

- [ ] **Step 1: Write failing plain and embed branding tests**

```python
def test_branding_overrides_plain_and_embed_payloads_without_mutation(self):
    payload = {"content": "video", "username": "stale", "embeds": [{"footer": {"text": "YouTube"}}]}
    result = self.module.branded_youtube_payload(payload)
    self.assertEqual("YouTube", result["username"])
    self.assertEqual(self.module.YOUTUBE_AVATAR_URL, result["avatar_url"])
    self.assertEqual(self.module.YOUTUBE_AVATAR_URL, result["embeds"][0]["footer"]["icon_url"])
    self.assertNotIn("avatar_url", payload)
```

Also prove the webhook uses `(5.0, 15.0)`, raises on non-2xx, and never logs a response body.

- [ ] **Step 2: Run and observe RED**

Run: `python3 -m unittest discover -s .github/tests -p 'test_youtube_discord_delivery.py' -v`

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement the shared final boundary and wire the script**

Use `copy.deepcopy`, force the two top-level webhook branding fields, copy each embed
footer, and set the approved icon URL. Post JSON with the existing content type and
timeout, call `raise_for_status`, and return no response body. Replace direct
`requests.post` calls in `post_to_discord` with this boundary for both plain and embed
messages.

- [ ] **Step 4: Run and observe GREEN**

Run: `python3 -m unittest discover -s .github/tests -p 'test_youtube_discord_delivery.py' -v`

Expected: all YouTube branding/delivery tests PASS.

- [ ] **Step 5: Commit the verified branding boundary**

```bash
git add .github/scripts/youtube_discord_delivery.py .github/scripts/youtube_to_discord.py .github/tests/test_youtube_discord_delivery.py
git commit -m "fix: standardize YouTube Discord branding"
```

---

### Task 5: Safe YouTube State Restore, Manual Test, and 15-Minute Schedule

**Files:**
- Create: `.github/scripts/youtube_delivery_state.py`
- Modify: `.github/scripts/youtube_to_discord.py`
- Modify: `.github/workflows/youtube_to_discord.yml`
- Create: `.github/tests/test_youtube_delivery_state.py`
- Create: `.github/tests/test_youtube_workflow.py`

**Interfaces:**
- Produces: `partition_youtube_items(items: Sequence[dict], baseline_only: bool, manual_test: bool) -> Tuple[List[dict], List[dict]]`
- Consumes: Task 4 `send_youtube_webhook`.
- Produces workflow env: `YOUTUBE_BASELINE_ONLY` and `YOUTUBE_MANUAL_TEST_MODE`.

- [ ] **Step 1: Write failing selection and workflow contract tests**

Prove scheduled missing-state mode delivers zero and baselines all, manual mode
delivers only the newest and baselines the rest, normal mode delivers all unseen
items in publication order, inputs are not mutated, and the workflow contains:

```yaml
schedule:
  - cron: '11,26,41,56 * * * *'
workflow_dispatch:
  inputs:
    manual_test:
      default: true
      type: boolean
```

Also require artifact lookup by artifact name and ID, a concurrency group, and state
upload under `if: always()`.

- [ ] **Step 2: Run and observe RED**

Run:

```bash
python3 -m unittest discover -s .github/tests -p 'test_youtube_delivery_state.py' -v
python3 -m unittest discover -s .github/tests -p 'test_youtube_workflow.py' -v
```

Expected: module import failure and old hourly workflow assertions.

- [ ] **Step 3: Implement pure selection and artifact-aware workflow restore**

Sort a copied list by validated ISO `published_at`. Manual mode returns the newest
one for delivery and all others for baseline; baseline-only scheduled mode returns
no deliveries; normal mode returns all unseen items. Save baseline items before the
delivery loop. If no unexpired `youtube_database` artifact restores, set
`YOUTUBE_BASELINE_ONLY=true`. Set manual mode only for `workflow_dispatch` with a
true boolean input. Change the script's outer exception path to exit nonzero so
Actions cannot report a false success.

- [ ] **Step 4: Run focused YouTube tests and observe GREEN**

Run:

```bash
python3 -m unittest discover -s .github/tests -p 'test_youtube_delivery_state.py' -v
python3 -m unittest discover -s .github/tests -p 'test_youtube_discord_delivery.py' -v
python3 -m unittest discover -s .github/tests -p 'test_youtube_workflow.py' -v
```

Expected: all focused YouTube tests PASS.

- [ ] **Step 5: Commit the safe YouTube operation change**

```bash
git add .github/scripts/youtube_delivery_state.py .github/scripts/youtube_to_discord.py \
  .github/workflows/youtube_to_discord.yml .github/tests/test_youtube_delivery_state.py \
  .github/tests/test_youtube_workflow.py
git commit -m "feat: add safe 15-minute YouTube delivery"
```

---

### Task 6: Repository Verification and Release Checkpoint

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `.github/tests/test_google_news_unified_workflow.py`
- Review: every file changed since `b6917e1`

**Interfaces:**
- Adds compile coverage for `google_news_related_links.py`,
  `youtube_discord_delivery.py`, `youtube_delivery_state.py`, and
  `youtube_to_discord.py`.

- [ ] **Step 1: Write the failing CI compile-contract assertion**

Extend the workflow test's module list with the four runtime files and run:

`python3 -m unittest discover -s .github/tests -p 'test_google_news_unified_workflow.py' -v`

Expected: FAIL until `.github/workflows/test.yml` names every module.

- [ ] **Step 2: Add the exact Python 3.8 compile targets**

Append the four files to the existing `python -m py_compile` command without changing
the Python version or dependency installation.

- [ ] **Step 3: Run all fresh verification commands**

```bash
python3 -m unittest discover -s .github/tests -v
python3 -m py_compile .github/scripts/google_news_*.py .github/scripts/googlenews-*_to_discord.py .github/scripts/youtube_*.py
git diff --check b6917e1
```

Expected: all tests PASS, compilation exits 0, and diff check prints nothing.

- [ ] **Step 4: Inspect change scope and sensitive patterns**

Run `git status --short`, `git diff --stat b6917e1`, `git diff b6917e1`, and a
credential-pattern scan limited to changed files. Confirm no webhook URL, API key,
token, cookie, password, or private key was added.

- [ ] **Step 5: Create the verified implementation checkpoint**

```bash
git add .github/workflows/test.yml .github/tests/test_google_news_unified_workflow.py
git commit -m "test: cover scheduled Discord delivery reliability"
```

Then run the full verification commands once more after the final commit. Keep the
checkpoint local until review and the repository's publication gate are satisfied.

---

## Release Handoff

1. Run a pre-landing review against `origin/main` and fix only actionable findings.
2. Report the exact branch, head commit, changed files, checks, and public remote
   publication constraint before attempting a Draft PR.
3. Publish only through `skill-governance git publish-draft`; never use a generic
   push, direct `main` push, or force push.
4. After CI and full diff review, obtain explicit approval for the exact PR head and
   Squash merge through the PR.
5. Verify merged `main`, then run Google News and YouTube controlled manual tests.
6. Enable only unified Google News and YouTube schedules. Keep all legacy Google News
   workflows disabled.
7. Confirm one real `schedule` run for each workflow, state artifact integrity, and
   Discord branding without printing secret values.
