# Multi-channel Google News Design

## Goal

Deliver Google News notifications to the eleven existing Discord channels shown by
the user while keeping Google request volume, Discord message volume, credentials,
and duplicate delivery under control.

The unified automation runs every 30 minutes. It processes all profiles in a fixed,
sequential order and shares one Google request circuit across them. The first live
test sends at most one current article to each channel and seeds the rest as the
baseline.

## User-visible channels

| Order | Profile | Discord channel | Feed definition | Feed locale | Webhook management name | GitHub Secret |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `top_us` | `gn-top-us` | Top stories | `en-US`, `US`, `US:en` | `Google News - TOP - US` | `DISCORD_WEBHOOK_GN_TOP_US` |
| 2 | `top_kr` | `gn-top-kr` | Top stories | `ko`, `KR`, `KR:ko` | `Google News - TOP - KR` | `DISCORD_WEBHOOK_GN_TOP_KR` |
| 3 | `top_jp` | `gn-top-jp` | Top stories | `ja`, `JP`, `JP:ja` | `Google News - TOP - JP` | `DISCORD_WEBHOOK_GN_TOP_JP` |
| 4 | `top_cn` | `gn-top-cn` | Top stories | `zh-CN`, `CN`, `CN:zh-Hans` | `Google News - TOP - CN` | `DISCORD_WEBHOOK_GN_TOP_CN` |
| 5 | `topic_korea` | `gn-topic-korea` | Stable `korea` topic | Korean | `Google News - TOPIC - KOREA` | `DISCORD_WEBHOOK_GN_TOPIC_KOREA` |
| 6 | `topic_seoul` | `gn-topic-seoul` | Search for `서울` | Korean | `Google News - TOPIC - SEOUL` | `DISCORD_WEBHOOK_GN_TOPIC_SEOUL` |
| 7 | `topic_ent` | `gn-topic-ent` | Stable `entertainment` topic | Korean | `Google News - TOPIC - ENT` | `DISCORD_WEBHOOK_GN_TOPIC_ENT` |
| 8 | `topic_tech` | `gn-topic-tech` | Stable `technology` topic | Korean | `Google News - TOPIC - TECH` | `DISCORD_WEBHOOK_GN_TOPIC_TECH` |
| 9 | `topic_scitech` | `gn-topic-scitech` | Stable `science_technology` topic | Korean | `Google News - TOPIC - SCITECH` | `DISCORD_WEBHOOK_GN_TOPIC_SCITECH` |
| 10 | `keyword_nocode` | `gn-keyword-nocode` | `노코드 OR "no-code" OR nocode` | Korean | `Google News - KEYWORD - NOCODE` | `DISCORD_WEBHOOK_GN_KEYWORD_NOCODE` |
| 11 | `keyword_iu` | `gn-keyword-iu` | `아이유 OR "IU 가수"` | Korean | `Google News - KEYWORD - IU` | `DISCORD_WEBHOOK_GN_KEYWORD_IU` |

The webhook name above is the management name shown in Discord integrations. Every
posted message overrides the visible sender name to `Google News`.

## Scope

### Included

- One profile configuration file containing only non-secret settings.
- One 30-minute GitHub Actions workflow.
- Sequential dispatch in Top, Topic, Keyword order.
- Reuse of dedicated existing webhooks and creation of only missing webhooks.
- Unique GitHub Action Secrets for the eleven webhook URLs.
- Independent article history per profile.
- A shared original-URL cache and shared persistent Google 403/429 circuit.
- Safe first-run baseline, bounded scheduled delivery, safe logs, state artifacts,
  tests, staged activation, and operational verification.

### Excluded

- YouTube workflows and channels.
- A Discord bot or bot token.
- Deletion of the three existing Google News workflows.
- Direct pushes to `main`, force pushes, or automatic PR merging.
- Changes to message styling that are unrelated to multi-channel routing.

## Architecture

### Profile configuration

`.github/config/google_news_profiles.json` is the source of truth for routing. Each
profile contains:

- stable profile id and processing order;
- kind (`top`, `topic`, or `keyword`);
- feed parameters or search query;
- webhook environment key and expected Discord webhook management name;
- visible sender name (`Google News`);
- independent article database path;
- scheduled freshness and item limits.

The file never contains a webhook URL, token, cookie, channel invitation, or other
credential. Profile ids, database paths, webhook environment keys, and expected
webhook names must all be unique.

### Unified dispatcher

`.github/scripts/google_news_dispatcher.py` owns a complete run. It:

1. loads and validates all profiles before delivery;
2. verifies that all webhook environment variables exist;
3. performs a read-only Discord webhook metadata request and checks the unique
   management name without logging the URL, token, or returned ids;
4. stops before any message if the preflight is incomplete or mismatched;
5. invokes the existing Top, Topic, or Keyword handler for each profile in order;
6. passes explicit environment values, independent article DB paths, the shared
   resolver DB path, and a per-profile URL-resolution budget;
7. continues scheduled processing after a profile-local error but records the
   failure;
8. stops new Google requests if the shared circuit opens;
9. writes a sanitized JSON summary containing only profile ids, counts, statuses,
   error codes, and timestamps;
10. returns failure if any profile fails, after preserving state.

The existing scripts keep their message formatting and feed-specific behavior. They
gain explicit path/budget inputs and use shared request helpers. They remain usable
by the disabled legacy workflows during rollback.

### Shared Google request guard

A small common request guard owns Google News HTTP safety for RSS and original-link
resolution. It stores the persistent circuit in the shared resolver SQLite database
and is used by `GoogleNewsUrlResolver` and RSS fetches.

- RSS profiles are started sequentially with a minimum delay between profiles.
- Each profile may start at most one uncached original-URL resolution per run.
- Across eleven profiles, at most eleven new article resolutions can start.
- Cached and legacy-direct URL results consume no network-resolution budget.
- Related-story URLs never start a new network resolution.
- Transient connection, timeout, and 5xx failures wait two seconds and retry once.
- HTTP 403 or 429 does not retry. It opens the shared circuit immediately.
- `Retry-After` seconds and HTTP dates are supported, clamped from one minute to six
  hours. A missing or invalid value defaults to one hour.
- Once open, the circuit prevents remaining Google requests in the current run and
  new runs until it expires. Already fetched articles can still use their Google News
  links as a fallback.

## State and artifacts

State lives under `.google-news-state/` during a workflow run:

- one article DB per profile, such as `top_us.db`;
- one shared `resolver.db` for successful original links and the circuit;
- one sanitized run summary.

The workflow downloads the newest state artifact from the latest completed run that
contains it, regardless of whether that run succeeded. This matters because an
earlier profile may have sent a message before a later profile fails. The workflow
uploads the updated state with `if: always()` so successful profile state is not lost.

The initialization switch resets article history only. It never drops the shared URL
cache or circuit state.

## Delivery behavior

### First operational test

- Workflow dispatch explicitly enables manual test mode.
- Preflight for all eleven webhooks succeeds before the first message.
- Each profile selects the newest currently unposted article.
- Other current articles are stored as the baseline in one transaction.
- At most one message is sent to each channel, for at most eleven messages total.
- A profile with no unposted article succeeds without sending a duplicate.
- State is uploaded even if a later profile fails.

### Scheduled runs

- Schedule: every 30 minutes.
- A profile considers only unseen articles no older than two hours.
- At most three articles per profile are sent in one run.
- Older or excess backlog is stored as baseline instead of being emitted later as a
  flood.
- Current articles are processed from oldest to newest within the selected set so
  Discord chronology remains understandable.

### Discord delivery state

Discord calls use `wait=true` so a successful response is explicit. The article DB
records a pending intent before delivery and a sent result after success. An
ambiguous pending record is not blindly resent; it is surfaced in the run summary for
manual reconciliation. This favors avoiding duplicate Discord messages after a
runner crash.

Discord 429 handling is independent from the Google circuit. It honors Discord's
retry delay within a small bounded retry policy. A webhook failure affects only its
profile during scheduled operation.

## Workflow and rollback

The new `.github/workflows/googlenews-to-discord.yml`:

- runs every 30 minutes at a minute offset that does not collide with other project
  workflows;
- has workflow-level concurrency with `cancel-in-progress: false`;
- uses Python 3.8 and the repository requirements file;
- maps the eleven Secrets to environment variables explicitly;
- restores state, executes the dispatcher, uploads state with `if: always()`, and
  publishes a sanitized step summary;
- exposes a boolean `manual_test` input defaulting to true;
- remains disabled until the code is merged, all webhooks are verified, and the user
  approves the live test.

The existing Top, Topic, and Keyword workflows stay disabled and unchanged as a
rollback path. Rollback means disabling the unified workflow; it does not require
deleting new state or re-enabling legacy workflows automatically.

## Webhook and Secret rollout

After code review and merge:

1. inspect the Discord integration list for each channel;
2. reuse only a webhook dedicated to that channel's Google News automation;
3. rename it to the exact management name in the profile table;
4. create a webhook only where no dedicated webhook exists;
5. set the corresponding GitHub Secret without printing or storing the URL locally;
6. run the read-only webhook preflight and verify all eleven names;
7. keep the unified workflow disabled until the manual live test is approved.

Existing webhooks shared with another automation are not renamed or reused.

## Logging and credential safety

Logs may contain profile ids, item counts, resolution statuses, safe error codes,
retry timestamps, and HTTP exception class names. They must not contain:

- webhook URLs or tokens;
- RSS query strings;
- full Google or publisher URLs;
- response bodies;
- Discord ids returned by webhook metadata;
- Secret values.

Raised exceptions use fixed safe error codes and suppress request exception chaining
when a URL could otherwise appear in a traceback.

## Testing

Offline standard-library `unittest` coverage includes:

- exactly eleven valid, uniquely routed profiles in the fixed order;
- correct Top locales, Topic ids, Seoul search, and keyword queries;
- duplicate id, DB, webhook key, or management-name rejection;
- missing or mismatched webhook preflight causing zero deliveries;
- dispatcher environment isolation and sequential execution;
- independent article histories and shared resolver state;
- first-run one-item selection and transactional baseline seeding;
- scheduled two-hour freshness, three-item cap, and excess baseline behavior;
- shared 403/429 circuit across RSS and resolver instances;
- per-profile one-resolution budget and related-story no-network behavior;
- failed-run artifact restore selection and always-upload workflow behavior;
- Discord bounded 429 retry and ambiguous pending delivery handling;
- sanitized logs and summaries;
- Python 3.8 compilation of every changed script;
- legacy resolver, manual-test, and three existing script regressions.

Bounded live validation performs no Discord send. It fetches all eleven RSS sources
sequentially, validates that each returns current items, resolves at most one current
article per profile, and repeats against the cache with zero new resolver attempts.

## Deployment acceptance

1. Local tests, compile checks, diff review, secret scan, and bounded live validation
   pass on the reviewed branch.
2. A Draft PR is published only through the approved safe Git workflow.
3. GitHub Python tests pass on the exact PR head.
4. The user separately approves Squash merge.
5. The merged `main` tree and tests are verified.
6. Existing webhooks are safely reused, missing webhooks are created, names are
   normalized, and eleven GitHub Secrets are set.
7. All eleven preflight checks pass without posting.
8. The user separately approves the manual live test.
9. The manual run sends no more than one message per channel and preserves state.
10. Discord destinations, visible sender name, original/fallback links, state artifact,
    SQLite integrity, and run summary are verified.
11. The user separately approves scheduled operation.
12. The unified workflow is enabled; the three legacy Google News workflows remain
    disabled. The first scheduled run is observed and verified.

## Success criteria

- All eleven channels receive only their configured news source.
- The visible sender name is `Google News`; management names and Secret names remain
  unambiguous.
- The first live run sends at most eleven messages total.
- Scheduled runs cannot overlap and cannot flood old backlog.
- Google 403/429 state stops the remaining Google requests across profiles and runs.
- Repeated articles are not posted, and cached original links do not cause new Google
  resolution requests.
- No credential or full query URL appears in code, artifacts, or logs.
- YouTube automation is unchanged.
