# Multi-channel Google News Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run eleven independently routed Google News Discord channels from one sequential 30-minute workflow with shared Google rate-limit protection and safe state recovery.

**Architecture:** A validated JSON profile registry drives a Python dispatcher that runs the existing Top, Topic, and Keyword handlers as isolated subprocesses. Article history remains profile-specific, while a shared SQLite-backed request guard and resolver cache stop all later Google requests after 403/429. One Actions artifact preserves every profile DB, the shared resolver DB, and sanitized run results even after a partial failure.

**Tech Stack:** Python 3.8, standard `unittest`, `requests`, BeautifulSoup, SQLite, GitHub Actions, Discord webhooks.

## Global Constraints

- Exactly eleven profiles run in Top US/KR/JP/CN, Topic Korea/Seoul/ENT/TECH/SCITECH, Keyword NOCODE/IU order.
- The schedule is every 30 minutes with workflow concurrency and `cancel-in-progress: false`.
- The visible Discord sender is `Google News`; webhook management names use `Google News - GROUP - NAME`.
- Webhook URLs exist only in eleven GitHub Actions Secrets and never appear in code, artifacts, or logs.
- The first live test sends no more than one article per channel; scheduled runs send no more than three articles per channel from the last two hours.
- Each profile starts at most one uncached original-link resolution per run; related links never start network resolution.
- Google HTTP 403/429 opens one shared persistent circuit for all profiles and honors `Retry-After` from one minute to six hours.
- The three legacy Google News workflows remain unchanged and disabled as rollback paths.
- YouTube code and workflows are out of scope.
- Python 3.8 compatibility and existing resolver/manual-test behavior must be preserved.

---

### Task 1: Profile registry and validation

**Files:**
- Create: `.github/config/google_news_profiles.json`
- Create: `.github/scripts/google_news_profiles.py`
- Create: `.github/tests/test_google_news_profiles.py`

**Interfaces:**
- Produces: `GoogleNewsProfile`, `load_profiles(path: str) -> List[GoogleNewsProfile]`, and `build_handler_environment(profile, base_env, state_dir, resolver_db, manual_test) -> Dict[str, str]`.
- Consumes: no new application interfaces.

- [ ] **Step 1: Write failing registry tests**

Create fixtures that load the real configuration and assert exact order, unique
profile ids, DB names, webhook keys, and management names. Include mutations that
duplicate each unique field and one profile with an invalid kind.

```python
def test_real_registry_contains_exact_routes(self):
    profiles = module.load_profiles(str(PROFILES_PATH))
    self.assertEqual(
        [
            "top_us", "top_kr", "top_jp", "top_cn",
            "topic_korea", "topic_seoul", "topic_ent",
            "topic_tech", "topic_scitech", "keyword_nocode",
            "keyword_iu",
        ],
        [profile.profile_id for profile in profiles],
    )
    self.assertEqual(11, len({profile.webhook_env for profile in profiles}))
    self.assertEqual(11, len({profile.state_db for profile in profiles}))

def test_duplicate_webhook_name_is_rejected(self):
    data = make_valid_registry()
    data[1]["expected_webhook_name"] = data[0]["expected_webhook_name"]
    with self.assertRaisesRegex(ValueError, "duplicate expected_webhook_name"):
        module.validate_profile_data(data)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m unittest .github/tests/test_google_news_profiles.py -v
```

Expected: import failure for `google_news_profiles`.

- [ ] **Step 3: Add the exact eleven-profile configuration**

Each JSON object contains `id`, `handler`, `webhook_env`,
`expected_webhook_name`, `state_db`, `visible_username`, and `environment`.
Use the exact routes and Secret names from the approved design. `topic_seoul`
uses the Keyword handler with `KEYWORD=서울`; its webhook group remains Topic.

```json
{
  "id": "topic_seoul",
  "handler": "keyword",
  "webhook_env": "DISCORD_WEBHOOK_GN_TOPIC_SEOUL",
  "expected_webhook_name": "Google News - TOPIC - SEOUL",
  "state_db": "topic_seoul.db",
  "visible_username": "Google News",
  "environment": {
    "KEYWORD_MODE": "true",
    "KEYWORD": "서울",
    "HL": "ko",
    "GL": "KR",
    "CEID": "KR:ko"
  }
}
```

- [ ] **Step 4: Implement strict immutable profile loading**

```python
@dataclass(frozen=True)
class GoogleNewsProfile:
    profile_id: str
    handler: str
    webhook_env: str
    expected_webhook_name: str
    state_db: str
    visible_username: str
    environment: Dict[str, str]

def load_profiles(path: str) -> List[GoogleNewsProfile]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return validate_profile_data(raw)
```

Validation rejects unknown fields, path traversal, non-string environment
values, missing handler-specific keys, duplicate routing fields, non-HTTPS
configuration values, and any key or value shaped like a webhook URL or token.
`build_handler_environment` starts from an allowlisted minimal environment and
maps the profile webhook into `DISCORD_WEBHOOK_TOP`,
`DISCORD_WEBHOOK_TOPIC`, or `DISCORD_WEBHOOK_KEYWORD`.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
python -m unittest .github/tests/test_google_news_profiles.py -v
python -m py_compile .github/scripts/google_news_profiles.py
git diff --check
```

Expected: all profile tests pass and both checks exit 0.

Commit:

```bash
git add .github/config/google_news_profiles.json .github/scripts/google_news_profiles.py .github/tests/test_google_news_profiles.py
git commit -m "feat: define Google News channel profiles"
```

### Task 2: Shared Google request guard

**Files:**
- Create: `.github/scripts/google_news_request_guard.py`
- Create: `.github/tests/test_google_news_request_guard.py`
- Modify: `.github/scripts/google_news_url_resolver.py`
- Modify: `.github/tests/test_google_news_url_resolver.py`

**Interfaces:**
- Produces: `GoogleNewsRequestGuard.request(method, url, **kwargs)`, `get_open_circuit()`, and `BlockedRequestError` subclasses.
- Consumes: an injected `requests.Session`, shared SQLite path, `(5.0, 15.0)` timeout, and UTC clock.

- [ ] **Step 1: Write failing shared-circuit tests**

```python
def test_rss_429_blocks_a_new_guard_using_the_same_database(self):
    first = module.GoogleNewsRequestGuard(first_session, self.db_path)
    with self.assertRaises(module.RateLimitError):
        first.request("get", "https://news.google.com/rss")

    second = module.GoogleNewsRequestGuard(second_session, self.db_path)
    with self.assertRaises(module.CircuitOpenError):
        second.request("get", "https://news.google.com/rss")
    second_session.get.assert_not_called()

def test_http_date_retry_after_is_capped_at_six_hours(self):
    guard = make_guard_with_response(429, {"Retry-After": far_future_date})
    with self.assertRaises(module.RateLimitError):
        guard.request("get", "https://news.google.com/rss")
    self.assertEqual(21600, guard.block_seconds())
```

Add resolver tests proving an injected guard is used for parameter GET and RPC
POST calls and that one blocked resolver makes a second resolver fall back without
network access.

- [ ] **Step 2: Run request-guard and resolver tests and verify RED**

Run:

```bash
python -m unittest .github/tests/test_google_news_request_guard.py .github/tests/test_google_news_url_resolver.py -v
```

Expected: missing `google_news_request_guard` and missing resolver injection.

- [ ] **Step 3: Implement the SQLite-backed request guard**

```python
class GoogleNewsRequestGuard:
    def __init__(self, session, db_path, timeout=(5.0, 15.0), utc_now=None):
        self.session = session
        self.db_path = db_path
        self.timeout = timeout
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._init_state()

    def request(self, method, url, **kwargs):
        open_state = self.get_open_circuit()
        if open_state is not None:
            raise CircuitOpenError(open_state.error_code, open_state.blocked_until)
        return self._request_with_one_transient_retry(method, url, **kwargs)
```

Use parameterized SQLite statements. Persist `blocked_until`,
`last_error_code`, and `updated_at` under the existing global state key.
Parse numeric and HTTP-date `Retry-After`; clamp to 60..21600 seconds and
default to 3600. Never put URLs, response bodies, or query strings in an
exception message.

- [ ] **Step 4: Inject the guard into the resolver**

Add `request_guard=None` to `GoogleNewsUrlResolver.__init__`. Create a guard
using the existing session and DB path when it is omitted. Delegate HTTP calls
to the guard while keeping resolver-level article budget, cache, legacy decode,
related-link behavior, and sanitized stats unchanged.

- [ ] **Step 5: Run focused and existing resolver tests and commit**

Run:

```bash
python -m unittest .github/tests/test_google_news_request_guard.py .github/tests/test_google_news_url_resolver.py -v
python -m py_compile .github/scripts/google_news_request_guard.py .github/scripts/google_news_url_resolver.py
git diff --check
```

Commit:

```bash
git add .github/scripts/google_news_request_guard.py .github/scripts/google_news_url_resolver.py .github/tests/test_google_news_request_guard.py .github/tests/test_google_news_url_resolver.py
git commit -m "feat: share Google News request circuit state"
```

### Task 3: Bounded article and delivery state

**Files:**
- Create: `.github/scripts/google_news_delivery_state.py`
- Create: `.github/tests/test_google_news_delivery_state.py`
- Modify: `.github/scripts/google_news_manual_test.py`
- Modify: `.github/tests/test_google_news_manual_test.py`

**Interfaces:**
- Produces: `prepare_scheduled_items(items, db_path, now, max_items=3, max_age_minutes=120) -> list`, `reserve_delivery(db_path, guid)`, `mark_delivery_sent(db_path, guid, message_id)`, and `count_pending_deliveries(db_path) -> int`.
- Consumes: the existing common `news_items` columns and XML item fields.

- [ ] **Step 1: Write failing scheduled-selection tests**

```python
def test_scheduled_mode_selects_three_recent_items_and_baselines_the_rest(self):
    items = [
        make_item("old", "Sun, 30 Aug 2026 08:00:00 GMT"),
        make_item("r1", "Sun, 30 Aug 2026 11:10:00 GMT"),
        make_item("r2", "Sun, 30 Aug 2026 11:20:00 GMT"),
        make_item("r3", "Sun, 30 Aug 2026 11:30:00 GMT"),
        make_item("r4", "Sun, 30 Aug 2026 11:40:00 GMT"),
    ]
    selected = module.prepare_scheduled_items(
        items, self.db_path, datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    )
    self.assertEqual(["r2", "r3", "r4"], guids(selected))
    self.assertEqual({"old", "r1"}, baseline_guids(self.db_path))
```

Add rollback tests for invalid XML fields and tests that reserve creates a
pending row, sent marking stores only the Discord message id, and a pending
row is treated as already known.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m unittest .github/tests/test_google_news_manual_test.py .github/tests/test_google_news_delivery_state.py -v
```

Expected: missing scheduled and delivery-state interfaces.

- [ ] **Step 3: Implement transactional selection and baseline seeding**

Reuse the existing required-field validation. Sort selected current items from
oldest to newest. Validate every input before opening the write transaction.
Insert old and excess rows using `INSERT OR IGNORE` so previous article data is
never overwritten.

- [ ] **Step 4: Implement pending and sent delivery state**

```python
def reserve_delivery(db_path: str, guid: str) -> bool:
    with sqlite3.connect(db_path) as connection:
        ensure_delivery_columns(connection)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO news_items (guid, delivery_status) VALUES (?, 'pending')",
            (guid,),
        )
        return cursor.rowcount == 1

def mark_delivery_sent(db_path: str, guid: str, message_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE news_items SET delivery_status='sent', discord_message_id=? WHERE guid=?",
            (message_id, guid),
        )
```

Reject non-numeric or empty Discord message ids without logging them. Do not
automatically resend pending rows.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python -m unittest .github/tests/test_google_news_manual_test.py .github/tests/test_google_news_delivery_state.py -v
python -m py_compile .github/scripts/google_news_manual_test.py .github/scripts/google_news_delivery_state.py
git diff --check
```

Commit:

```bash
git add .github/scripts/google_news_manual_test.py .github/scripts/google_news_delivery_state.py .github/tests/test_google_news_manual_test.py .github/tests/test_google_news_delivery_state.py
git commit -m "feat: bound Google News delivery state"
```

### Task 4: Existing handler runtime contract

**Files:**
- Create: `.github/scripts/google_news_profile_result.py`
- Create: `.github/tests/test_google_news_profile_result.py`
- Modify: `.github/scripts/googlenews-top_to_discord.py`
- Modify: `.github/scripts/googlenews-topic_to_discord.py`
- Modify: `.github/scripts/googlenews-keyword_to_discord.py`
- Modify: `.github/tests/test_google_news_script_integration.py`

**Interfaces:**
- Produces: handler support for `GOOGLE_NEWS_DB_PATH`, `GOOGLE_NEWS_RESOLVER_DB_PATH`, `GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS`, `GOOGLE_NEWS_PROFILE_ID`, `GOOGLE_NEWS_RESULT_PATH`, `GOOGLE_NEWS_MAX_ITEMS`, and `GOOGLE_NEWS_MAX_AGE_MINUTES`.
- Consumes: Task 2 request guard and Task 3 selection/delivery helpers.

- [ ] **Step 1: Write failing integration and result tests**

Assert all three scripts:

- read article and resolver DB paths from the new variables with legacy defaults;
- create the request guard before RSS fetch;
- pass the same guard to RSS and resolver calls;
- use scheduled selection only outside manual mode;
- reserve before Discord send and mark sent after DB save;
- call Discord with `params={"wait": "true"}` and return a message id;
- write a safe profile result on success and failure;
- never log request exception strings, webhook URLs, RSS URLs, or response bodies.

```python
def test_all_handlers_use_shared_runtime_contract(self):
    for path in HANDLER_PATHS:
        source = path.read_text(encoding="utf-8")
        self.assertIn("GOOGLE_NEWS_RESOLVER_DB_PATH", source)
        self.assertIn("GoogleNewsRequestGuard", source)
        self.assertIn("prepare_scheduled_items", source)
        self.assertIn("reserve_delivery", source)
        self.assertIn("params={'wait': 'true'}", source)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m unittest .github/tests/test_google_news_script_integration.py .github/tests/test_google_news_profile_result.py -v
```

- [ ] **Step 3: Implement the sanitized profile result writer**

```python
def write_profile_result(path, profile_id, status, processed_count, pending_count, error_code=None):
    payload = {
        "profile_id": validate_profile_id(profile_id),
        "status": status,
        "processed_count": int(processed_count),
        "pending_count": int(pending_count),
        "error_code": error_code,
    }
    atomic_json_write(path, payload)
```

Allow only fixed status and error-code character sets. Write via a sibling
temporary file and `os.replace`.

- [ ] **Step 4: Update all three handlers with the same bounded flow**

Create session, guard, and resolver before RSS fetch. Use article DB for
article state and the shared resolver DB for cache/circuit. On scheduled runs,
apply the two-hour and three-item selection. Before sending, reserve the GUID;
after a successful `wait=true` Discord response, save the article and mark it
sent. Leave a pending row on ambiguous failure. Set visible username from the
profile environment, defaulting to the legacy value when absent.

When the shared circuit is already open before RSS, write
`status=skipped`, `error_code=circuit_open`, and exit with a dedicated safe
code. Use fixed exceptions `rss_fetch_failed`, `discord_delivery_failed`, and
`profile_run_failed` with no request exception chaining.

- [ ] **Step 5: Run all handler-related tests and commit**

Run:

```bash
python -m unittest .github/tests/test_google_news_script_integration.py .github/tests/test_google_news_profile_result.py .github/tests/test_google_news_manual_test.py .github/tests/test_google_news_url_resolver.py -v
python -m py_compile .github/scripts/google_news_profile_result.py .github/scripts/googlenews-top_to_discord.py .github/scripts/googlenews-topic_to_discord.py .github/scripts/googlenews-keyword_to_discord.py
git diff --check
```

Commit:

```bash
git add .github/scripts/google_news_profile_result.py .github/scripts/googlenews-top_to_discord.py .github/scripts/googlenews-topic_to_discord.py .github/scripts/googlenews-keyword_to_discord.py .github/tests/test_google_news_profile_result.py .github/tests/test_google_news_script_integration.py
git commit -m "feat: add bounded Google News handler runtime"
```

### Task 5: Sequential dispatcher and webhook preflight

**Files:**
- Create: `.github/scripts/google_news_dispatcher.py`
- Create: `.github/tests/test_google_news_dispatcher.py`

**Interfaces:**
- Produces: `validate_webhooks(profiles, env, session)`, `run_profiles(profiles, env, state_dir, manual_test)`, and CLI `main() -> int`.
- Consumes: Task 1 registry, Task 2 circuit reader, handler subprocesses, and sanitized result files.

- [ ] **Step 1: Write failing preflight and sequencing tests**

```python
def test_preflight_mismatch_runs_zero_handlers(self):
    session.get.side_effect = [webhook_response("wrong-name")]
    with self.assertRaisesRegex(RuntimeError, "webhook_name_mismatch"):
        dispatcher.run_dispatch(self.profiles, self.env, self.state_dir, session)
    subprocess_run.assert_not_called()

def test_handlers_run_in_registry_order_with_isolated_environments(self):
    result = dispatcher.run_profiles(
        self.profiles, self.env, self.state_dir, manual_test=True
    )
    self.assertEqual(EXPECTED_IDS, [call.profile_id for call in result.profiles])
    self.assertEqual(11, subprocess_run.call_count)
```

Cover missing Secret, non-HTTPS webhook, metadata 429, metadata invalid JSON,
one local profile failure followed by later profiles, and shared Google circuit
stopping remaining subprocesses. Assert safe summaries contain no environment
values or URLs.

- [ ] **Step 2: Run dispatcher tests and verify RED**

Run:

```bash
python -m unittest .github/tests/test_google_news_dispatcher.py -v
```

- [ ] **Step 3: Implement all-webhook preflight**

Use GET requests against webhook URLs only in memory. Require HTTP 200 and an
exact metadata `name` match. Do not return or log webhook ids, channel ids,
tokens, response text, or URL-bearing exceptions. Complete all validation
before invoking the first handler.

- [ ] **Step 4: Implement sequential subprocess dispatch**

```python
for profile in profiles:
    if request_guard.get_open_circuit() is not None:
        results.append(ProfileResult.skipped(profile.profile_id, "circuit_open"))
        continue
    child_env = build_handler_environment(
        profile, env, state_dir, resolver_db, manual_test
    )
    completed = subprocess.run(
        [sys.executable, str(HANDLERS[profile.handler])],
        env=child_env,
        check=False,
    )
    results.append(read_safe_result(profile, completed.returncode))
    sleep_between_profiles()
```

Scheduled mode continues after a profile-local failure. A shared Google circuit
marks all remaining profiles skipped. Manual mode also preserves completed
results and exits nonzero after the run summary.

- [ ] **Step 5: Run dispatcher and registry tests and commit**

Run:

```bash
python -m unittest .github/tests/test_google_news_dispatcher.py .github/tests/test_google_news_profiles.py .github/tests/test_google_news_request_guard.py -v
python -m py_compile .github/scripts/google_news_dispatcher.py
git diff --check
```

Commit:

```bash
git add .github/scripts/google_news_dispatcher.py .github/tests/test_google_news_dispatcher.py
git commit -m "feat: dispatch Google News profiles sequentially"
```

### Task 6: Unified GitHub Actions workflow and state artifact

**Files:**
- Create: `.github/workflows/googlenews-to-discord.yml`
- Create: `.github/tests/test_google_news_unified_workflow.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Produces: one disabled-by-default operational workflow with manual test input, 30-minute schedule, sequential dispatcher invocation, restore-latest-state logic, always-upload state, and step summary.
- Consumes: the eleven exact Secret names, profile registry, dispatcher CLI, and `.google-news-state/` directory.

- [ ] **Step 1: Write failing workflow contract tests**

Read YAML as text to avoid adding a YAML dependency. Assert:

- cron is one 30-minute schedule at an unused minute offset;
- `manual_test` is boolean and defaults true;
- concurrency exists and does not cancel in progress;
- all eleven exact Secrets are mapped;
- the dispatcher is the only Google News execution command;
- previous state lookup accepts completed failed runs with the named artifact;
- upload uses `if: always()` and retention 90 days;
- existing three workflows are not modified by this task;
- CI compiles every new module.

```python
def test_unified_workflow_maps_all_webhook_secrets(self):
    source = WORKFLOW.read_text(encoding="utf-8")
    for secret_name in EXPECTED_WEBHOOK_SECRETS:
        self.assertIn("secrets.%s" % secret_name, source)
```

- [ ] **Step 2: Run workflow tests and verify RED**

Run:

```bash
python -m unittest .github/tests/test_google_news_unified_workflow.py -v
```

- [ ] **Step 3: Add the unified workflow**

Use checkout v4, setup-python v5 with Python 3.8, requirements installation,
workflow-run/artifact lookup through `actions/github-script@v7`,
`actions/download-artifact@v4`, dispatcher execution, and
`actions/upload-artifact@v4` with `if: always()`.

The workflow remains disabled on GitHub until merge and operational approval.
It contains no webhook value, URL, or hard-coded Discord id.

- [ ] **Step 4: Extend CI compilation and run workflow tests**

Run:

```bash
python -m unittest .github/tests/test_google_news_unified_workflow.py .github/tests/test_google_news_manual_workflows.py -v
python -m py_compile .github/scripts/google_news_profiles.py .github/scripts/google_news_request_guard.py .github/scripts/google_news_delivery_state.py .github/scripts/google_news_profile_result.py .github/scripts/google_news_dispatcher.py .github/scripts/google_news_url_resolver.py .github/scripts/googlenews-top_to_discord.py .github/scripts/googlenews-topic_to_discord.py .github/scripts/googlenews-keyword_to_discord.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/googlenews-to-discord.yml .github/workflows/test.yml .github/tests/test_google_news_unified_workflow.py
git commit -m "feat: add unified Google News workflow"
```

### Task 7: Full verification, review, and publication

**Files:**
- Modify only files required by findings from fresh verification or review.

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: one reviewed, verified branch checkpoint and Draft PR; no operational Discord change.

- [ ] **Step 1: Run the entire offline suite and compile check**

```bash
python -m unittest discover -s .github/tests -v
python -m py_compile .github/scripts/google_news_*.py .github/scripts/googlenews-*_to_discord.py
git diff --check origin/main
```

Expected: zero failures and zero compile/diff errors.

- [ ] **Step 2: Inspect scope and scan added lines for credentials**

```bash
git status --short --branch
git diff --name-status origin/main...HEAD
git diff --no-color --unified=0 origin/main | rg '^\+.*(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY)'
```

Expected: only intended Google News files and no secret-pattern matches.

- [ ] **Step 3: Run bounded live Google validation without Discord**

Run the dispatcher in a validation-only mode with webhook preflight disabled and
Discord delivery replaced by a no-send adapter. Fetch all eleven profiles
sequentially, resolve at most one current article per profile, verify every feed
has current items, then repeat against the same temporary shared DB and assert
zero new resolution attempts. Delete the temporary state after the report.

- [ ] **Step 4: Run pre-landing review and fix findings with RED/GREEN tests**

Review the complete diff against `origin/main` for request amplification,
cross-channel routing, artifact recovery, secret leakage, SQL correctness,
Python 3.8 compatibility, and legacy workflow regression. Any code fix requires
a failing test first and a focused green run before the full suite.

- [ ] **Step 5: Commit verification fixes if needed**

```bash
git add .github/config .github/scripts .github/tests .github/workflows docs/superpowers
git commit -m "fix: address multi-channel Google News review"
```

Skip this commit when review changes no files.

- [ ] **Step 6: Publish only through the safe Draft PR gate**

Show the user the exact branch, HEAD, included files, public remote identity,
and fresh checks before publication. Use only:

```bash
skill-governance git publish-draft /Users/youngmin/개발자/worktrees/DiscordActions/codex-feat-multi-channel-google-news --execute
```

Wait for GitHub Python Tests on the exact PR head. Report the Draft PR and ask
for a separate Squash merge approval. Do not merge on publication approval.

### Task 8: Post-merge webhook and operational rollout

**Files:**
- No repository file changes unless a verified channel mapping contradicts the reviewed configuration; such a contradiction requires a new branch and review.

**Interfaces:**
- Consumes: merged `main`, Discord channel integration permissions, eleven profile definitions, and GitHub Actions Secret management.
- Produces: verified webhook metadata, eleven configured Secrets, one bounded manual run, and separately approved scheduled activation.

- [ ] **Step 1: Verify the merged main checkpoint**

Confirm the PR is Squash-merged, the main workflow tests pass, the merged tree
matches the reviewed branch tree, and the legacy Google News workflows remain
disabled.

- [ ] **Step 2: Reuse or create webhook integrations safely**

For each channel, inspect existing webhooks. Reuse only a Google News-dedicated
webhook, rename it to its exact configured management name, and create one only
when none exists. Do not rename or reuse a webhook shared with another
automation. Do not print or persist copied URLs.

- [ ] **Step 3: Set eleven GitHub Secrets**

Set each URL directly into its exact Secret. List Secret names and update times
afterward, never values. Run dispatcher webhook preflight in no-send mode and
require all eleven name matches.

- [ ] **Step 4: Obtain manual live-test approval and run once**

Keep the new workflow disabled except for the controlled dispatch. Run
`manual_test=true` at `ref=main`. Verify event, SHA, success, at most one message
per channel, visible sender `Google News`, correct destinations, state artifact,
SQLite integrity, safe summary, and no legacy workflow run.

- [ ] **Step 5: Obtain scheduled-operation approval**

Only after the manual run report, ask separately to enable the 30-minute
schedule. If approved, enable only the unified workflow, observe the first
scheduled run, and verify all three legacy workflows remain disabled.

- [ ] **Step 6: Preserve rollback evidence**

Report workflow id, manual and scheduled run URLs, merge SHA, artifact name,
message counts, Secret names, workflow states, and rollback action. Branch and
worktree cleanup requires separate exact-target approval after recovery proof.
