# Changelog

All notable changes to this project are recorded here. The format follows
Keep a Changelog, and the project uses date-based versions until the first
tagged release.

## Unreleased

### Added

- `ops/state-trigger`: a Cloudflare Worker cron that dispatches the Google
  News and YouTube production workflows every 15 minutes through
  `workflow_dispatch`. The GitHub `schedule` entries remain as a fallback.
- `--check-config` on the Google News dispatcher for offline profile and
  repository-variable validation.
- `.github/requirements-dev.in` / `requirements-dev.txt` with hashed
  `ruff`, `yamllint` and `coverage` locks.
- `docs/architecture.md`, `docs/README.md`, `AGENTS.md` and this changelog.
- `profile-rotation.json`: the next run starts at the first profile skipped by
  the time budget.
- `ops/state-artifact/select-state-artifact.cjs`: one tested selector for the
  newest non-expired state artifact, shared by the five stateful workflows.
- local HTTP contract tests for Discord 429/400/5xx handling, including the
  `allowed_mentions` payload boundary.
- `GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS` (default 40) to bound original-URL
  resolution per profile per run.
- `GOOGLE_NEWS_HEALTH_MAX_AGE_HOURS` (default 6) for the health workflow.
  Lower it to 3 after the external trigger is stable.

### Changed

- The production workflows accept `workflow_dispatch` again. The button is
  used by the Worker and for emergencies; it sends real messages.
- Google News job timeout is 35 minutes. State pruning and VACUUM are skipped
  when less than three minutes remain.
- State artifacts are kept for 3 days (YouTube: 14 days). The unmapped
  publisher review artifact stays at 90 days.
- `GOOGLE_NEWS_VALIDATE_ONLY` is no longer used for offline checks; it still
  fetches RSS and resolves URLs. Use `--check-config` instead.
- CI installs both runtime locks and the dev lock, runs `compileall`, `ruff`,
  `yamllint`, coverage and the Worker unit tests.
- All GitHub Actions references are pinned to 40-character commit SHAs with a
  `# vN` comment. Checkout no longer persists credentials.
- README now documents the actual scheduler behaviour, the external trigger,
  the 3-day state retention, the URL-resolution cap and the backlog expiry
  rule.
- Historical design and plan documents under `docs/superpowers/` are marked
  as historical.
- The three Google News handlers now share `google_news_handler_runtime.py`
  for the queue delivery loop, module-deadline handling and permanent-failure
  notification. Unused copies of the old date-filter helpers were removed.

### Fixed

- A failed state restore no longer publishes an empty state artifact. The
  restore is retried once and the run fails closed; the previous artifact is
  kept for the next run.
- YouTube and backlog-reset state uploads now retry once and fail closed like
  the Google News workflow.
- Permanently failing YouTube targets (400/401/403/404) are abandoned after
  three attempts instead of blocking the channel forever. 429, 5xx and network
  errors stay pending.
- Discord payloads set `allowed_mentions: {"parse": []}`, so article or video
  titles cannot ping `@everyone` or roles.
- The RSS circuit and the URL-resolution circuit are independent. A 403 while
  resolving links no longer stops RSS collection and Discord delivery.
- 403 circuits block for 30 minutes by default; 429 circuits keep the 60-minute
  default and still honour `Retry-After`.
- The health workflow checks both Google News and YouTube, looks at the last
  five completed runs, and alerts when there is no success within the
  threshold. Repeated failure alerts are throttled to one per hour per
  workflow.
- Profile validation rejects `TOP_MODE=true` with `RSS_URL_TOP`, `"True"`,
  empty `HL`, unknown countries or topics, malformed `TOPIC_PARAMS`,
  `WHEN` combined with `AFTER_DATE`/`BEFORE_DATE`, and non-Google RSS hosts.
- YouTube run summaries carry `run_id`; the workflow ignores a stale summary
  left by a previous run.
- Mutable action tags and missing `persist-credentials: false` were removed.
- A corrupt SQLite state file is quarantined outside the state directory, the
  run summary records the repair, and the profile starts from a fresh database
  instead of blocking every later run.
