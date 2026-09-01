# Google News Profile Display and Topic Filter Design

## Goal

Let a keyword profile use a complex Google News search expression while showing a short, reader-friendly keyword in Discord, and exclude Korean entertainment-topic items whose main RSS title contains `운세`.

## Decisions

- Add optional `KEYWORD_DISPLAY_NAME` only to keyword profiles.
- Keep `KEYWORD` as the Google News query and keyword-matching expression.
- Use `KEYWORD_DISPLAY_NAME` only for the Discord header. When it is absent, keep the existing `KEYWORD` display for backward compatibility.
- Reject a present but blank `KEYWORD_DISPLAY_NAME` during profile validation, before RSS or Discord requests.
- Configure `keyword_nocode` with `KEYWORD_DISPLAY_NAME: 노코드` while retaining `KEYWORD: 노코드 OR "no-code" OR nocode`.
- Configure `topic_ent` with `FEED_KEYWORD_FILTER: NOT 운세` and `FEED_KEYWORD_SCOPE: title`.
- The entertainment exclusion checks only the main RSS title. A related-news headline containing `운세` does not exclude an otherwise valid main item.
- Document the distinction in both `README.md` and `README_KR.md` with equivalent meaning.

## Data Flow

1. The profile registry validates and forwards both `KEYWORD` and the optional `KEYWORD_DISPLAY_NAME`.
2. The keyword handler builds the RSS URL and service keyword matcher from `KEYWORD` exactly as before.
3. Immediately before message formatting, the handler selects `KEYWORD_DISPLAY_NAME` when non-empty and otherwise falls back to `KEYWORD`.
4. The shared feed filter evaluates `topic_ent` using the existing negative-only Boolean expression support and title-only scope.

## Compatibility and Safety

- Existing keyword profiles without `KEYWORD_DISPLAY_NAME` keep their current Discord headers.
- No database migration, queue change, URL-resolution change, webhook change, schedule change, or YouTube change is included.
- Invalid display-name configuration fails during dispatcher preflight without exposing configuration values.

## Verification

- Profile tests verify the real registry values, allowed field, blank-value rejection, and environment forwarding.
- Keyword-handler integration tests verify that the display label can differ from the search expression and that fallback remains compatible.
- Feed-filter tests verify that a main title containing `운세` is rejected while a related-only occurrence remains allowed in `title` scope.
- The full Python unit suite, Python compilation, JSON validation, `git diff --check`, and secret-pattern scan must pass.
