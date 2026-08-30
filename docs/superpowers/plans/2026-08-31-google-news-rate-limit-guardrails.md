# Google News Rate Limit Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound Google News URL conversion traffic, persist server cooldowns, protect main article links from related-link amplification, and keep notifications flowing through safe fallbacks.

**Architecture:** Extend the shared SQLite-backed resolver with a five-item run budget, a cache-only related-link path, a persistent global circuit breaker, and sanitized counters. Wire the three scripts to the new related path and summary, then stagger their existing 30-minute schedules.

**Tech Stack:** Python 3.8, `requests`, BeautifulSoup, SQLite, standard `unittest`, GitHub Actions YAML.

## Global Constraints

- Do not add packages, proxies, browser automation, or external decoding services.
- Preserve the existing `UrlResolution` statuses and fall back to the Google News URL rather than dropping a notification.
- Never log response bodies, article URLs, query strings, webhook values, or secrets.
- Keep Keyword, Top, and Topic scheduled workflows disabled after deployment.
- Do not modify Discord formatting, filters, YouTube code, or the Python version.

---

### Task 1: Resolver request budget and related-link priority

**Files:**
- Modify: `.github/tests/test_google_news_url_resolver.py`
- Modify: `.github/scripts/google_news_url_resolver.py`

**Interfaces:**
- Consumes: existing `GoogleNewsUrlResolver.resolve(source_url: str) -> UrlResolution`
- Produces: `GoogleNewsUrlResolver.resolve_related(source_url: str) -> UrlResolution`, constructor argument `max_network_resolutions: int = 5`

- [ ] **Step 1: Write failing tests for the five-item budget**

  Add a resolver with `max_network_resolutions=1`, resolve two uncached modern URLs, and assert the second result is `fallback / budget_exhausted` with no additional GET or POST call.

- [ ] **Step 2: Write failing tests for related-link priority**

  Assert `resolve_related()` returns cached and legacy originals without network, but returns `fallback / related_network_skipped` for an uncached modern URL.

- [ ] **Step 3: Run the focused tests and confirm failure**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v`

  Expected: failures because the new constructor behavior and `resolve_related()` do not exist.

- [ ] **Step 4: Implement the minimum shared resolution path**

  Route `resolve()` and `resolve_related()` through one private method. Perform disabled, passthrough, cache, legacy, and deferred checks before deciding whether a network request is allowed. Increment the run budget exactly once immediately before `_throttle()`.

- [ ] **Step 5: Run the resolver tests**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v`

  Expected: all resolver tests pass.

### Task 2: Persistent circuit breaker and Retry-After

**Files:**
- Modify: `.github/tests/test_google_news_url_resolver.py`
- Modify: `.github/scripts/google_news_url_resolver.py`

**Interfaces:**
- Produces: SQLite table `google_news_resolver_state(state_key, blocked_until, last_error_code, updated_at)`
- Produces: internal retry parser accepting delta-seconds and RFC HTTP dates

- [ ] **Step 1: Write failing persistence tests**

  Return a 429 with `Retry-After: 120`, create a second resolver over the same DB, and assert it makes zero requests and returns `fallback / circuit_open` until the recorded time.

- [ ] **Step 2: Write failing header and 403 tests**

  Cover HTTP-date parsing, the one-hour default, six-hour maximum, and 403 opening the same persistent circuit.

- [ ] **Step 3: Run the focused tests and confirm failure**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v`

  Expected: failures because the state table and persistent breaker are absent.

- [ ] **Step 4: Implement the state table and breaker**

  Initialize the table beside the URL cache. Check it after cache/legacy/deferred paths but before the budget. On 429/403, clamp the server delay to 60–21600 seconds, persist `blocked_until`, save the article failure, and return fallback. Clear an expired breaker after the next successful network conversion.

- [ ] **Step 5: Run the resolver tests**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v`

  Expected: all resolver tests pass with no live network access.

### Task 3: Sanitized statistics and script integration

**Files:**
- Modify: `.github/tests/test_google_news_url_resolver.py`
- Modify: `.github/tests/test_google_news_script_integration.py`
- Modify: `.github/scripts/google_news_url_resolver.py`
- Modify: `.github/scripts/googlenews-keyword_to_discord.py`
- Modify: `.github/scripts/googlenews-top_to_discord.py`
- Modify: `.github/scripts/googlenews-topic_to_discord.py`

**Interfaces:**
- Produces: `GoogleNewsUrlResolver.get_stats() -> dict`
- Consumes: `resolve_related()` for every related article URL

- [ ] **Step 1: Write failing statistics tests**

  Exercise cache hit, network success, budget exhaustion, related skip, and circuit skip. Assert exact integer counters and that the returned keys and values contain no source URL, resolved URL, response body, or RPC payload.

- [ ] **Step 2: Write failing script integration tests**

  Give the stub both `resolve()` and `resolve_related()`. Assert related parsers call only `resolve_related()` and all three scripts reference `resolver.get_stats()`.

- [ ] **Step 3: Run focused tests and confirm failure**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_*integration.py' -v` and `python -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v`

  Expected: failures because counters and script wiring are absent.

- [ ] **Step 4: Implement counters and wire scripts**

  Keep counters in memory, return a new dictionary from `get_stats()`, and expose only counts plus an ISO `circuit_blocked_until`. Replace related-link calls with `resolve_related()` and log the dictionary once before each normal exit.

- [ ] **Step 5: Run focused tests**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_*integration.py' -v` and `python -m unittest discover -s .github/tests -p 'test_google_news_url_resolver.py' -v`

  Expected: all focused tests pass.

### Task 4: Staggered workflow schedules

**Files:**
- Modify: `.github/tests/test_google_news_manual_workflows.py`
- Modify: `.github/workflows/googlenews-top_to_discord.yml`
- Modify: `.github/workflows/googlenews-keyword_to_discord.yml`
- Modify: `.github/workflows/googlenews-topic_to_discord.yml`

**Interfaces:**
- Produces: Top `2,32 * * * *`, Keyword `12,42 * * * *`, Topic `22,52 * * * *`

- [ ] **Step 1: Write a failing exact-schedule test**

  Read each workflow as text and assert it contains only its assigned cron expression rather than `*/30 * * * *`.

- [ ] **Step 2: Run the workflow test and confirm failure**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_manual_workflows.py' -v`

  Expected: three schedule assertions fail.

- [ ] **Step 3: Change only the cron expressions and comments**

  Preserve `workflow_dispatch`, environment variables, permissions, jobs, and message execution steps.

- [ ] **Step 4: Run the workflow test**

  Run: `python -m unittest discover -s .github/tests -p 'test_google_news_manual_workflows.py' -v`

  Expected: all workflow tests pass.

### Task 5: Full verification, review, and safe publication

**Files:**
- Verify all files changed since `origin/main`

**Interfaces:**
- Produces: one verified implementation checkpoint and one Draft PR; does not merge it

- [ ] **Step 1: Run all offline checks**

  Run:

  ```bash
  python -m unittest discover -s .github/tests -v
  python -m py_compile .github/scripts/google_news_manual_test.py .github/scripts/google_news_url_resolver.py .github/scripts/googlenews-*_to_discord.py
  git diff --check
  ```

  Expected: all tests pass, compilation succeeds, and diff check has no output.

- [ ] **Step 2: Run bounded live verification without Discord**

  Resolve at most three current Korean Google News items sequentially into a temporary SQLite DB, print only statuses and hostname classes, rerun them for cache hits, and do not stress-test or send messages.

- [ ] **Step 3: Review the complete diff and sensitive patterns**

  Compare against `origin/main`, confirm no webhook values or response bodies were added, and verify the only YAML changes are the three cron expressions.

- [ ] **Step 4: Create one-intent verified commits**

  Commit the design/plan documentation and the tested implementation with messages that state their intent. Leave no unrelated uncommitted files.

- [ ] **Step 5: Publish through the safe Draft PR gate**

  Use only `skill-governance git publish-draft` for the approved GitHub remote. Never push directly to `main`, never force-push, and do not merge without a separate user approval after CI and review identify the exact commit.
