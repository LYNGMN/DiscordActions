# Discord Actions

Discord Actions checks Google News and YouTube with GitHub Actions and sends new items to Discord webhooks. No separate server is required. The default polling interval is 15 minutes.

## Behavior

- Google News messages always use the name `Google News` and the project Google News icon.
- YouTube messages always use the name `YouTube` and the project YouTube icon.
- New items are ordered by their position in the RSS/API response, not by publication timestamps. The default sends older feed positions before newer ones.
- Every newly discovered item is queued; scheduled runs no longer truncate a batch to a small result limit.
- A first YouTube run stores the current videos as a baseline instead of flooding Discord with history.
- If Discord delivery stops partway through an item, the next run resumes from the saved unsent message or webhook target.

## Quick setup

1. Fork this repository or create a repository from the template.
2. Open **Settings → Secrets and variables → Actions**.
3. Add only the Secrets and Variables required by the service you use. Never paste their values into documentation, issues, or Actions logs.
4. Open **Actions**, choose the workflow, and use **Run workflow** first. With `manual_test=true`, each channel sends at most one current item and baselines the rest.
5. After testing, set the Repository Variable `GOOGLE_NEWS_SCHEDULE_ENABLED` to `true` if scheduled Google News delivery should run.

## Google News

The unified workflow runs profiles from [.github/config/google_news_profiles.json](.github/config/google_news_profiles.json). The current profiles use these Discord Secrets:

```text
DISCORD_WEBHOOK_GN_TOP_US
DISCORD_WEBHOOK_GN_TOP_KR
DISCORD_WEBHOOK_GN_TOP_JP
DISCORD_WEBHOOK_GN_TOP_CN
DISCORD_WEBHOOK_GN_TOPIC_KOREA
DISCORD_WEBHOOK_GN_TOPIC_SEOUL
DISCORD_WEBHOOK_GN_TOPIC_ENT
DISCORD_WEBHOOK_GN_TOPIC_TECH
DISCORD_WEBHOOK_GN_TOPIC_SCITECH
DISCORD_WEBHOOK_GN_KEYWORD_NOCODE
DISCORD_WEBHOOK_GN_KEYWORD_IU
```

Scheduled delivery requires the Repository Variable `GOOGLE_NEWS_SCHEDULE_ENABLED=true`. The optional `GOOGLE_NEWS_DELIVERY_ORDER` variable accepts:

| Value | Behavior |
| --- | --- |
| `feed_oldest_first` | Default. Send older positions in the current RSS response first |
| `feed_newest_first` | Send newer positions in the current RSS response first |

### Accurate keyword matching

Keyword profiles default to `KEYWORD_MATCH_MODE: title`. A main item whose title does not contain the configured expression is therefore filtered even when Google included it only because a related story matched.

```json
{
  "KEYWORD_MATCH_MODE": "title",
  "KEYWORD_MATCH_ALIASES": "IU | \"Lee Ji-eun\" | 이지은"
}
```

- `title` checks only the main RSS title and excludes its trailing publisher label.
- `title_or_description` checks the main title plus every linked related-story title in the RSS `description`. It does not match publisher names, URLs, or HTML attributes.
- Supported syntax: `OR`/`|`, `AND`/`&`/adjacent terms, `NOT`/`!`/`-`, parentheses, and `"exact phrases"`.
- Date operators such as `when:`, `after:`, and `before:` are removed from the match expression.
- Invalid expressions stop before fetching RSS or sending Discord messages.

Filtered items retain a configuration fingerprint. They are skipped under the same setting and re-evaluated while still present in RSS after the mode or aliases change. `ADVANCED_FILTER_KEYWORD` remains an additional narrowing condition after this match.

The main story and every related story attempt original-URL resolution. A related story that cannot be resolved uses only a validated Google News article fallback. Long related-story lists are split into follow-up messages without changing order.

## YouTube

Required Secrets are `YOUTUBE_API_KEY`, `YOUTUBE_MODE`, and `DISCORD_WEBHOOK_YOUTUBE`, plus one mode-specific value:

- `channels`: `YOUTUBE_CHANNEL_ID`
- `playlists`: `YOUTUBE_PLAYLIST_ID`
- `search`: `YOUTUBE_SEARCH_KEYWORD`

Optional Secrets are `DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW`, `YOUTUBE_DETAILVIEW`, `ADVANCED_FILTER_YOUTUBE`, `DATE_FILTER_YOUTUBE`, and `LANGUAGE_YOUTUBE`. The optional Repository Variable `YOUTUBE_DELIVERY_ORDER` uses `feed_oldest_first` or `feed_newest_first`.

For either service, the optional `DISCORD_WEBHOOK_ADMIN` Secret reports response-unknown retries and final delivery failures to an admin channel. Alerts contain only the service, profile, a hashed item identifier, and the Actions run link.

- Channel mode reads the channel uploads playlist to the stored-video boundary or the final page.
- Playlist mode scans every page because videos can be inserted at arbitrary positions.
- Search mode scans every page from the previous successful checkpoint with a 24-hour safety overlap. YouTube search-index completeness is not guaranteed.
- Video details are fetched in batches of 50.
- `YOUTUBE_MAX_RESULTS` and date-based `YOUTUBE_PLAYLIST_SORT` no longer truncate or reorder scheduled channel/playlist collection.

Weekly and monthly runs still queue every new video discovered by the API in that run.

## Schedule examples

Edit `cron` under the workflow's `schedule`. Keep the two services on different minutes to avoid simultaneous work. Each example also uses `timezone: 'Asia/Seoul'`.

| Interval | Google News | YouTube |
| --- | --- | --- |
| Every 15 minutes (default) | `7,22,37,52 * * * *` | `11,26,41,56 * * * *` |
| Every 30 minutes | `7,37 * * * *` | `11,41 * * * *` |
| Hourly | `7 * * * *` | `11 * * * *` |
| Every 6 hours | `7 */6 * * *` | `11 */6 * * *` |
| Daily at 09:00 | `7 9 * * *` | `11 9 * * *` |
| Every Monday at 09:00 | `7 9 * * 1` | `11 9 * * 1` |
| First day of each month at 09:00 | `7 9 1 * *` | `11 9 1 * *` |

Scheduled GitHub Actions runs can start late. Weekly and monthly examples are calendar schedules, not fixed 7-day or 30-day durations. Google News RSS is not an archive: with long intervals, an article that has already disappeared from the feed cannot be recovered. Use the default 15-minute schedule when minimizing missed news matters.

## Troubleshooting

- Check the Actions result and its uploaded SQLite state artifact first.
- Never publish webhook URLs, API keys, or tokens in logs or support posts.
- If scheduled Google News runs do not deliver, confirm that `GOOGLE_NEWS_SCHEDULE_ENABLED` is the string `true`.
- Distinguish GitHub scheduling delays and external API limits from code failures. Saved incomplete deliveries resume in sequence on the next run.

## Contributing and license

Use [Discussions](https://github.com/LYNGMN/DiscordActions/discussions) for feature ideas and [Issues](https://github.com/LYNGMN/DiscordActions/issues) for reproducible defects. This project is available under the [MIT License](LICENSE).

*한국어 문서: [README_KR.md](README_KR.md)*
