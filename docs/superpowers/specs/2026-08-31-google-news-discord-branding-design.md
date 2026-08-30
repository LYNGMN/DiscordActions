# Google News Discord Branding Design

## Goal

Every Google News notification must appear in Discord with the visible sender name
`Google News` and this public avatar image:

`https://discordactions.github.io/logo/media/original/news/googlenews.png`

Discord webhook management names such as `Google News - TOP - US` remain unchanged.

## Scope

- Apply the same visible branding to the unified 11-profile workflow.
- Apply the same visible branding to the legacy Top, Topic, and Keyword workflows.
- Preserve webhook URLs, webhook management names, message content, delivery state,
  retry behavior, URL resolution, and workflow schedules.
- Do not add a new secret or dependency for a public, non-sensitive image URL.

## Design

The shared Google News Discord delivery module is the final boundary used by all
three handlers. It will own two constants: the visible sender name and avatar URL.
Immediately before each webhook request, the module will copy the caller's payload
and set those two fields to the approved values. Setting the fields at this boundary
guarantees consistent branding even if a legacy workflow supplies an empty, stale,
or different avatar environment value.

The caller-owned payload will not be mutated. Existing webhook preflight validation
continues to compare Discord's management name with each profile's expected name;
the visible sender override is independent of that validation.

## Failure Behavior

Branding does not add a network request. Discord receives the public image URL in the
normal webhook payload and resolves it as part of message delivery. Existing bounded
retry and error handling remains responsible for webhook failures.

## Verification

- Add a focused unit test proving that missing or conflicting caller branding is
  replaced with the approved sender name and avatar URL.
- Keep the existing message-length test, including caller-payload immutability.
- Run the full standard-library unit test suite and compile all Google News scripts.
- After review and Squash merge, run the unified manual test with state restoration.
  Previously delivered profiles must not duplicate messages; the remaining US Top
  item must show the approved sender name and avatar.
- Disable every Google News schedule workflow immediately after the live test.

## Release Boundaries

This change is released through a Draft PR from `codex/fix/google-news-branding`.
It does not directly push to `main`, delete branches or worktrees, or permanently
enable scheduled Google News delivery.
