# Google News Discord Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Google News Discord notification use the visible name `Google News` and the approved Google News avatar.

**Architecture:** Enforce branding at the shared `send_webhook_message` boundary used by the Top, Topic, and Keyword handlers. Copy and normalize each outgoing payload there so unified and legacy workflows behave identically without changing webhook management names or caller-owned data.

**Tech Stack:** Python 3.8, `requests`, standard-library `unittest`, GitHub Actions, Discord webhooks

## Global Constraints

- The visible sender name is exactly `Google News`.
- The avatar URL is exactly `https://discordactions.github.io/logo/media/original/news/googlenews.png`.
- The unified 11-profile workflow and legacy Top, Topic, and Keyword workflows must share the behavior.
- Webhook URLs, webhook management names, message content, delivery state, URL resolution, schedules, dependencies, and secrets remain unchanged.
- The caller-owned payload must not be mutated.
- Scheduled Google News workflows remain disabled after the live test.

---

### Task 1: Enforce Google News Branding at the Shared Delivery Boundary

**Files:**
- Modify: `.github/tests/test_google_news_discord_delivery.py`
- Modify: `.github/scripts/google_news_discord_delivery.py`

**Interfaces:**
- Consumes: `send_webhook_message(webhook_url: str, payload: Dict[str, str], sleep: Callable[[float], None] = time.sleep, max_rate_limit_wait_seconds: float = 60.0) -> str`
- Produces: `GOOGLE_NEWS_USERNAME: str`, `GOOGLE_NEWS_AVATAR_URL: str`, and an outgoing payload that always contains the approved `username` and `avatar_url`

- [ ] **Step 1: Write the failing branding test**

Add this test to `GoogleNewsDiscordDeliveryTests`:

```python
def test_approved_branding_overrides_caller_values_without_mutation(self):
    payload = {
        "content": "safe message",
        "username": "Stale Name",
        "avatar_url": "https://example.com/stale.png",
    }

    with mock.patch.object(
        self.delivery.requests,
        "post",
        return_value=FakeResponse(),
    ) as post:
        self.delivery.send_webhook_message(
            "https://example.com/webhook",
            payload,
        )

    posted_payload = post.call_args.kwargs["json"]
    self.assertEqual("Google News", posted_payload["username"])
    self.assertEqual(
        "https://discordactions.github.io/logo/media/original/news/googlenews.png",
        posted_payload["avatar_url"],
    )
    self.assertEqual("Stale Name", payload["username"])
    self.assertEqual("https://example.com/stale.png", payload["avatar_url"])
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
python -m unittest discover -s .github/tests -p 'test_google_news_discord_delivery.py' -v
```

Expected: `test_approved_branding_overrides_caller_values_without_mutation` fails because the posted payload still contains `Stale Name` and the stale avatar.

- [ ] **Step 3: Add the two branding constants**

Add beside the existing delivery constants in `.github/scripts/google_news_discord_delivery.py`:

```python
GOOGLE_NEWS_USERNAME = "Google News"
GOOGLE_NEWS_AVATAR_URL = (
    "https://discordactions.github.io/logo/media/original/news/googlenews.png"
)
```

- [ ] **Step 4: Normalize the copied payload before content limiting**

Immediately after `safe_payload = dict(payload)`, add:

```python
safe_payload["username"] = GOOGLE_NEWS_USERNAME
safe_payload["avatar_url"] = GOOGLE_NEWS_AVATAR_URL
```

Do not edit the three handler scripts or the workflow secrets; every handler already calls this shared boundary.

- [ ] **Step 5: Run the focused test and confirm GREEN**

Run:

```bash
python -m unittest discover -s .github/tests -p 'test_google_news_discord_delivery.py' -v
```

Expected: both Discord delivery tests pass.

- [ ] **Step 6: Commit the implementation intent**

```bash
git add .github/scripts/google_news_discord_delivery.py .github/tests/test_google_news_discord_delivery.py
git commit -m "fix: standardize Google News Discord branding"
```

### Task 2: Verify and Release the Branding Change

**Files:**
- Verify: `.github/scripts/google_news_discord_delivery.py`
- Verify: `.github/tests/test_google_news_discord_delivery.py`
- Verify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: the Task 1 branding constants and shared delivery behavior
- Produces: a reviewed Draft PR, a Squash merge commit on `main`, and a live manual run with no duplicate deliveries

- [ ] **Step 1: Run the full offline verification suite**

Run:

```bash
python -m unittest discover -s .github/tests -v
PYTHONPYCACHEPREFIX=/private/tmp/discordactions-google-news-branding-pycache python -m py_compile .github/scripts/google_news_delivery_state.py .github/scripts/google_news_discord_delivery.py .github/scripts/google_news_dispatcher.py .github/scripts/google_news_manual_test.py .github/scripts/google_news_profile_result.py .github/scripts/google_news_profiles.py .github/scripts/google_news_request_guard.py .github/scripts/google_news_url_resolver.py .github/scripts/googlenews-keyword_to_discord.py .github/scripts/googlenews-top_to_discord.py .github/scripts/googlenews-topic_to_discord.py
git diff --check origin/main
```

Expected: 91 tests pass, compilation succeeds, and `git diff --check` prints nothing.

- [ ] **Step 2: Review the exact branch diff**

Run an independent review against `origin/main`. Resolve every actionable issue, rerun Step 1 after any edit, and verify that the branch contains only the design, plan, shared delivery module, and focused test.

- [ ] **Step 3: Publish only through the safe Draft PR gate**

Run:

```bash
skill-governance git publish-draft "$PWD"
skill-governance git publish-draft "$PWD" --execute
```

Expected: the exact clean feature-branch checkpoint is pushed without force and a Draft PR targeting `main` is created.

- [ ] **Step 4: Gate the Squash merge**

Wait for the PR Python Tests, report the exact reviewed commit and included files, and obtain one explicit user approval. Mark the PR ready and Squash merge only that approved revision. Do not delete the branch or worktree.

- [ ] **Step 5: Verify the merged main revision**

Find the `Python Tests` run whose `headSha` equals the merge commit and wait for `success`. Treat any other run as insufficient evidence.

- [ ] **Step 6: Run the approved live Discord test safely**

Confirm all Google News workflows are disabled, no schedule-enabling variable exists, and all 11 webhook secret names exist without reading their values. Enable only the unified workflow, dispatch `manual_test=true` on `main`, wait for completion, and disable it in the same guarded shell path even when the run fails.

Expected: restored state prevents duplicate sends for the 10 profiles that already succeeded; only the pending US Top item is delivered, with visible name `Google News` and the approved avatar.

- [ ] **Step 7: Validate artifacts and final operating state**

Download the run's `google-news-state` artifact, require every SQLite `PRAGMA integrity_check` result to equal `ok`, require zero pending deliveries, and confirm all Google News workflows are disabled. Visually inspect the newest US Top Discord message in the authenticated browser without exposing webhook URLs or message identifiers.
