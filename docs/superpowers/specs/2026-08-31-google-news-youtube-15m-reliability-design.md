# Google News and YouTube 15-Minute Reliability Design

## Goal

Deliver new Google News articles and YouTube videos to Discord every 15 minutes
without notification floods, repeated articles, stale Google News links, or
inconsistent sender branding.

Google News messages use the visible sender name `Google News` and this avatar:

`https://discordactions.github.io/logo/media/original/news/googlenews.png`

YouTube messages use the visible sender name `YouTube` and this avatar:

`https://discordactions.github.io/logo/media/original/youtube/youtube_social_circle_red.png`

Discord webhook management names and webhook URLs remain unchanged.

## Scope

- Run Google News and YouTube checks every 15 minutes on staggered schedules.
- Force the approved sender name and avatar at each Discord delivery boundary.
- Resolve Google News main links when possible and display related links only when
  they resolve to non-Google publisher URLs.
- Prevent repeat delivery when Google changes an RSS GUID or wrapping URL for the
  same article.
- Use the exact Korean keyword `아이유`, keep `when:3d` as a feed-side bound, and
  preserve the stricter application-side recent-article bound.
- Format the IU source line as `Google 뉴스 - 아이유 - 한국 🇰🇷`.
- Preserve the science/technology source line as
  `Google 뉴스 - 기술 뉴스 - 과학/기술 🇰🇷`.
- Make a missing YouTube state database safe by baselining existing videos instead
  of sending the whole channel history.

This change does not rename Discord channels or webhooks, replace webhook secrets,
add an external URL-decoding service, or remove the existing request circuit breaker.

## Scheduling

Google News runs at minutes `07`, `22`, `37`, and `52` of every hour. YouTube runs
at minutes `11`, `26`, `41`, and `56`. Both intervals are 15 minutes, while the
four-minute offset prevents the two network-heavy workflows from starting together.

The unified Google News workflow is the only Google News workflow with a schedule.
The legacy Top, Topic, and Keyword workflows are manual-only and contain no schedule
trigger, preventing accidental duplicate delivery even if their GitHub workflow state
is later enabled.

## Google News Article Identity

RSS GUIDs are transport identifiers, not stable article identities. Each profile
database therefore gains a separate article-identity table. Before reserving a
Discord delivery, the handler derives two SHA-256 identities:

1. A canonical publisher URL identity. Canonicalization lowercases the host, removes
   the fragment and known tracking parameters, sorts remaining query parameters, and
   never changes the URL displayed to the user.
2. A normalized title identity. Normalization uses Unicode NFKC, case folding, HTML
   unescaping, and collapsed whitespace while retaining the publisher suffix.

Both identities are scoped to the profile database. An atomic reservation succeeds
only when the GUID and both available identities are unseen. Existing `news_items`
rows are backfilled into the identity table without rewriting their stored content.
This blocks resurfaced articles even when Google supplies a new GUID or wrapper URL,
while allowing the same article to appear independently in different Discord
channels.

The IU profile uses `KEYWORD=아이유` and `WHEN=3d`. The existing 120-minute
application limit stays in force, so `when:3d` reduces feed noise but is not trusted
as the delivery-age rule.

## Related Publisher URLs

The supplied modern related-news links do not redirect directly to publishers; they
require the same signed Google decoding flow as a main link. Related links therefore
share the existing permanent cache, per-profile network budget, one-second spacing,
failure backoff, and cross-profile HTTP 429 circuit breaker.

The per-profile network budget increases only from one to two new decodes per run.
The main article is resolved first. Cached and legacy related links cost no network
budget, and at most the remaining budget is used for new related links. A related
entry is displayed only when its final URL is HTTP(S) and not `news.google.com`.
Unresolved entries are omitted instead of exposing another Google wrapper URL. This
keeps the main notification timely and guarantees that every related link shown in
Discord is a publisher URL, without an unbounded decoding burst.

At most four related items are included in one message. Existing Discord content
length limiting remains the final guard.

## Discord Branding

The shared Google News delivery boundary continues to overwrite caller-provided
branding with the approved Google News values.

YouTube gains an equivalent final delivery boundary. It copies both plain and embed
payloads, sets `username=YouTube` and the approved avatar on every webhook request,
and uses the same approved image in the YouTube embed footer. Environment variables
may remain for backward compatibility but cannot override the visible branding.

## YouTube State Safety

The workflow restores the newest unexpired `youtube_database` artifact rather than
assuming the latest successful run owns a usable artifact. If no database can be
restored, the scheduled run fetches the configured current videos, saves them as a
baseline, and sends zero Discord messages.

Manual dispatch receives a safe boolean test mode. It sends at most the newest one
unseen video and baselines the remaining current videos. This provides a controlled
branding test without replaying channel history. Video IDs remain the primary
deduplication key after initialization.

## Error Handling

- A Google News HTTP 429 opens the existing shared circuit and stops further Google
  decoding for that run.
- A failed related-link conversion cannot fail or suppress the main notification;
  that related entry is omitted.
- A failed main-link conversion preserves the current Google News fallback behavior
  so the main notification is not lost.
- A YouTube state-restore failure enters baseline mode and cannot replay historical
  videos.
- Discord delivery failures do not mark an item as sent.
- Logs report counts and error codes without printing webhook URLs, URL queries,
  response bodies, API keys, or tokens.

## Verification

- Unit-test canonical URL and title identity deduplication, including changed GUIDs,
  tracking queries, and genuinely distinct articles.
- Unit-test related-link network budgeting, cache reuse, Google-link omission, and
  HTTP 429 circuit behavior.
- Unit-test the exact IU and science/technology source lines.
- Unit-test Google News and YouTube sender branding for plain and embed payloads.
- Unit-test both staggered 15-minute cron schedules.
- Unit-test YouTube missing-state baseline mode and one-item manual test mode.
- Run the complete standard-library test suite, compile all changed Python files,
  validate workflow YAML expectations, run `git diff --check`, and scan the changed
  files for credential patterns.
- After review and Squash merge, verify the default-branch CI result, run controlled
  manual tests, then enable only the unified Google News and YouTube workflows.
- Confirm a real `schedule` event for each workflow and inspect safe state artifacts.

## Release Boundaries

Implementation uses `codex/feat/google-news-youtube-15m-reliability` in its dedicated
permanent worktree. It is reviewed and published as a Draft PR without direct or
force pushes to `main`. Schedule activation occurs only after the merged default
branch and controlled manual tests pass. Existing worktrees and branches are retained
until separately approved for cleanup.
