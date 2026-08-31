# Discord Actions

Discord Actions checks Google News and YouTube with GitHub Actions and sends new items to Discord webhooks. No separate server is required. The default polling interval is 15 minutes.

## Behavior

- The Discord bot shown as the author of each Google News message always uses the display name `Google News` and the [Google News icon](https://discordactions.github.io/logo/media/original/news/googlenews.png) as its profile icon.
- The Discord bot shown as the author of each YouTube message always uses the display name `YouTube` and the [YouTube icon](https://discordactions.github.io/logo/media/original/youtube/youtube_social_circle_red.png) as its profile icon.
- New items are ordered by their position in the RSS/API response, not by publication timestamps. The default sends older feed positions before newer ones.
- Every newly discovered item is queued; scheduled runs no longer truncate a batch to a small result limit.
- A first YouTube run stores the current videos as a baseline instead of flooding Discord with history.
- If Discord delivery stops partway through an item, the next run resumes from the saved unsent message or webhook target.

## Quick setup

1. Fork this repository or create a repository from the template.
2. Open **Settings → Secrets and variables → Actions**.
3. Add only the Secrets and Variables required by the service you use. Never paste their values into documentation, issues, or Actions logs.
4. Open **Actions**, choose the workflow, and use **Run workflow** first. With `manual_test=true`, each channel sends at most one current item and baselines the rest.
5. After the manual test, leave the workflow enabled. Scheduled runs then continue automatically; no separate enable variable is required.

## Shared date and keyword filters

Google News and YouTube use the same optional Repository Variables. A profile value in `.github/config/google_news_profiles.json` overrides the repository-wide value for that Google News profile.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FEED_DATE_FILTER` | empty | Keep only items inside a relative or fixed publication-date range |
| `FEED_KEYWORD_FILTER` | empty | Keep only items that satisfy a Boolean keyword expression |
| `FEED_KEYWORD_SCOPE` | `title` | Use `title` or `title_or_description` |
| `FEED_TIMEZONE` | automatic | Timezone used by calendar filters and displayed dates |
| `FEED_COUNTRY` | service setting | Country used to select a timezone when no explicit timezone is set |
| `DISPLAY_LANGUAGE` | service setting or `en` | Fixed labels and dates; supported values are listed below |

Date filters are inclusive. They decide whether an item may be delivered; they never reorder the feed.

| Example | Meaning |
| --- | --- |
| `calendar:1d` | From midnight today in the resolved timezone |
| `calendar:7d` | Today and the previous six local calendar days |
| `calendar:1mo` | From the same local calendar date one month earlier, with month-end correction |
| `rolling:24h` | The exact previous 24 hours |
| `rolling:7d` | The exact previous 168 hours |
| `rolling:30d` | The exact previous 30 days |
| `from:2026-06-01 to:2026-08-15` | June 1 through August 15, including both full local dates |
| `from:2026-06-01` | On or after June 1 |
| `to:2026-08-15` | On or before August 15 |

`calendar:7d` follows local date boundaries; `rolling:7d` always means exactly 168 hours. Timezone selection is explicit `FEED_TIMEZONE` first, then a timezone supplied by the service, then `FEED_COUNTRY`/the service country, and finally `UTC`. Display language is never used to guess a country. For example, use `FEED_TIMEZONE=Asia/Tokyo` or `FEED_COUNTRY=JP` for a Japanese calendar boundary.

Some countries span multiple timezones. In that case, set `FEED_TIMEZONE` explicitly instead of relying on `FEED_COUNTRY`; for example, choose the timezone of the intended U.S. audience.

Keyword filters support `OR`/`|`, `AND`/`&`/adjacent terms, `NOT`/`!`/`-`, parentheses, and exact phrases such as `"Lee Ji-eun"`. When both date and keyword filters are set, an item must pass both. Examples:

```text
FEED_KEYWORD_FILTER=(AI OR "artificial intelligence") NOT rumor
FEED_KEYWORD_SCOPE=title
FEED_DATE_FILTER=calendar:7d
FEED_TIMEZONE=Asia/Seoul
```

With `title_or_description`, Google News checks the main title plus related-story link titles; YouTube checks the video title plus its actual description. Publisher names, URLs, and HTML attributes are not keyword inputs. An invalid filter, language, or timezone stops before RSS/API requests and Discord delivery.

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

Scheduled delivery continues automatically while the workflow is enabled. The optional `GOOGLE_NEWS_DELIVERY_ORDER` variable accepts:

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

Set the Repository Variable `YOUTUBE_SOURCE` to `rss` or `api`. Existing setups that omit it continue to use `api`.

| Capability | RSS (`YOUTUBE_SOURCE=rss`) | API (`YOUTUBE_SOURCE=api`) |
| --- | --- | --- |
| Setup | Easiest; no API key | Requires a YouTube Data API key |
| Channel uploads | Yes, from the current Atom feed | Yes, with paginated uploads-playlist history |
| Playlists | Yes, from the current Atom feed | Yes, every playlist page |
| Search results | No | Yes, every returned page after the saved checkpoint |
| Duration and category | Not supplied, so omitted | Included when YouTube supplies them |
| Older items no longer in the current feed | Cannot recover them | Can page through channel/playlist data |
| Quota | No YouTube API quota | Uses YouTube Data API quota |

Both sources use the same video ID and SQLite state, so switching from RSS to API or back does not resend an already handled video. RSS has no page token: if a video disappears from the current feed before a run sees it, RSS cannot recover it.

RSS does not provide the fields required by `YOUTUBE_DETAILVIEW`, so keep that setting disabled when `YOUTUBE_SOURCE=rss`.

Required settings are `YOUTUBE_MODE` and `DISCORD_WEBHOOK_YOUTUBE`, plus one mode-specific value:

- `channels`: `YOUTUBE_CHANNEL_ID`
- `playlists`: `YOUTUBE_PLAYLIST_ID`
- `search`: `YOUTUBE_SEARCH_KEYWORD` (API only)

The API source additionally requires the `YOUTUBE_API_KEY` Secret. Optional Secrets are `DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW`, `YOUTUBE_DETAILVIEW`, `ADVANCED_FILTER_YOUTUBE`, `DATE_FILTER_YOUTUBE`, and `LANGUAGE_YOUTUBE`. The optional Repository Variables `YOUTUBE_DELIVERY_ORDER` and `YOUTUBE_PLAYLIST_LAYOUT` accept `feed_oldest_first|feed_newest_first` and `auto|channel|curated` respectively.

### YouTube RSS quick start with RESCENE

The RSS source is the simplest choice when you want new uploads from one channel or one public playlist. It does not require a YouTube API key. The current workflow has one `YOUTUBE_MODE`, so choose the channel example or the playlist example for a run; it does not monitor both at the same time.

Open **Settings → Secrets and variables → Actions → Variables** and add:

| Name | Value | Why |
| --- | --- | --- |
| `YOUTUBE_SOURCE` | `rss` | Use the no-API-key Atom feed source |
| `DISPLAY_LANGUAGE` | `en` | Show the fixed message labels and date in English; use `ko` for Korean |
| `FEED_TIMEZONE` | your audience's timezone, optional | Apply the intended local date to filters and displayed dates |

The rows below use `NAME=value` notation only to make the finished setup easy to check. Enter the name and value in separate GitHub fields.

#### Example A: RESCENE channel

Source page: https://www.youtube.com/channel/UCtKtCiaWRz-d3EZn2xd1mdA

The channel ID is the text after `/channel/`: `UCtKtCiaWRz-d3EZn2xd1mdA`. The workflow builds this feed automatically, so you do not need a separate RSS URL setting:

https://www.youtube.com/feeds/videos.xml?channel_id=UCtKtCiaWRz-d3EZn2xd1mdA

Under **Actions → Secrets**, add or update:

| Finished setting | Purpose |
| --- | --- |
| `YOUTUBE_MODE=channels` | Read a channel upload feed |
| `YOUTUBE_CHANNEL_ID=UCtKtCiaWRz-d3EZn2xd1mdA` | Select the RESCENE channel |
| `DISCORD_WEBHOOK_YOUTUBE=your existing Discord webhook` | Choose the destination Discord channel |

Do not add `YOUTUBE_API_KEY` for this RSS setup. Leave `YOUTUBE_DETAILVIEW` unset or set it to `false`, because the Atom feed does not supply the API-only detail fields.

With `DISPLAY_LANGUAGE=en`, a channel item uses this layout. This is a real feed example checked on September 1, 2026; future video titles and dates will naturally differ.

```text
`RESCENE - YouTube`
**Let’s go**
https://youtu.be/JPAKX4X_9WU

📅 Published: `August 31, 2026`
🖼️ [Thumbnail](https://i3.ytimg.com/vi/JPAKX4X_9WU/hqdefault.jpg)
```

#### Example B: RESCENE Archive playlist

Source page: https://www.youtube.com/playlist?list=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt

The playlist ID is the value after `list=`: `PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt`. The workflow builds this feed automatically:

https://www.youtube.com/feeds/videos.xml?playlist_id=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt

Under **Actions → Secrets**, add or update:

| Finished setting | Purpose |
| --- | --- |
| `YOUTUBE_MODE=playlists` | Read a public playlist feed |
| `YOUTUBE_PLAYLIST_ID=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt` | Select the RESCENE Archive playlist |
| `DISCORD_WEBHOOK_YOUTUBE=your existing Discord webhook` | Choose the destination Discord channel |

Under **Actions → Variables**, also set `YOUTUBE_PLAYLIST_LAYOUT=curated`. `RESCENE Archive` contains videos from more than one channel, so this keeps the playlist owner in a stable curated-playlist header. The default `auto` currently reaches the same layout after inspecting the feed.

```text
`📃 RESCENE Archive - YouTube Playlist by. RESCENE`

`안녕하세요원이입니다잘부탁드립니다 - YouTube`
**원이 근황**
https://youtu.be/EsKmhBMmqIM

📅 Published: `August 28, 2026`
🖼️ [Thumbnail](https://i2.ytimg.com/vi/EsKmhBMmqIM/hqdefault.jpg)
```

#### Run and verify the RSS setup

1. Open **Actions → YouTube to Discord Notification → Run workflow**.
2. Keep `manual_test=true` for the first run. It sends at most the newest matching item and stores the other current items as a baseline, preventing an old-video flood.
3. Confirm that the run succeeds and that Discord receives no more than one test message. Leave the workflow enabled; later scheduled runs check every 15 minutes and send every newly discovered item in feed order, oldest position first by default.

Common RSS errors are deliberate configuration checks:

- `YOUTUBE_API_KEY is required` means `YOUTUBE_SOURCE` is missing or is not exactly `rss` in the Variables tab.
- `YouTube RSS does not support search mode` means RSS was combined with `YOUTUBE_MODE=search`; use the API source for search.
- `YouTube RSS does not support YOUTUBE_DETAILVIEW` means the API-only detail view is still enabled.
- An invalid feed usually means the channel or playlist ID was copied incorrectly, is unavailable, or is not public. Open the generated feed URL above to check it.

RSS only sees the finite set of entries currently published in the Atom feed and has no next page. A video that disappears before a scheduled run sees it cannot be recovered by RSS. Use the API source when history recovery, search, duration, category, or full pagination matters.

For either service, the optional `DISCORD_WEBHOOK_ADMIN` Secret reports response-unknown retries and final delivery failures to an admin channel. Alerts contain only the service, profile, a hashed item identifier, and the Actions run link.

- Channel mode reads the channel uploads playlist to the stored-video boundary or the final page.
- Playlist mode scans every page because videos can be inserted at arbitrary positions.
- Search mode scans every page from the previous successful checkpoint with a 24-hour safety overlap. YouTube search-index completeness is not guaranteed.
- Video details are fetched in batches of 50.
- `YOUTUBE_MAX_RESULTS` and date-based `YOUTUBE_PLAYLIST_SORT` no longer truncate or reorder scheduled channel/playlist collection.

Weekly and monthly runs still queue every new video discovered by the API in that run.

The API message layout is:

```text
`BBC News Korea - YouTube`
**Video title**
https://youtu.be/VIDEO_ID

⏳ Duration: `07:13`
📅 Published: `June 29, 2026`
📁 Category: `News & Politics`
🖼️ [Thumbnail](https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg)
```

RSS messages omit duration and category. Playlist messages add one blank line after their first line. `channel` layout uses `` `📃 Playlist title by. Channel - YouTube Playlist` ``, while `curated` uses `` `📃 Playlist title - YouTube Playlist by. Owner` ``. `auto` selects `channel` for a single-channel list and `curated` for a mixed-channel list.

## Display languages

`DISPLAY_LANGUAGE` changes fixed labels and localized dates, not article, video, channel, or playlist titles. Supported values are `ko`, `en`, `ja`, `zh-CN`, `zh-TW`, `es`, `pt-BR`, `fr`, `de`, and `id`. YouTube API category names are requested in the selected language and omitted when unavailable. The legacy `LANGUAGE_YOUTUBE` setting remains compatible, but `DISPLAY_LANGUAGE` takes priority.

## Schedule examples

Edit `cron` under the workflow's `schedule`. Each expression has exactly five fields: minute, hour, day of month, month, and day of week. The workflows do not declare a schedule timezone.

| Interval | Google News | YouTube |
| --- | --- | --- |
| Every 15 minutes (default) | `*/15 * * * *` | `*/15 * * * *` |
| Every 30 minutes | `*/30 * * * *` | `*/30 * * * *` |
| Hourly | `0 * * * *` | `0 * * * *` |
| Every 6 hours | `0 */6 * * *` | `0 */6 * * *` |
| Daily at 09:00 | `0 9 * * *` | `0 9 * * *` |
| Every Monday at 09:00 | `0 9 * * 1` | `0 9 * * 1` |
| First day of each month at 09:00 | `0 9 1 * *` | `0 9 1 * *` |

Scheduled GitHub Actions runs can start late. Weekly and monthly examples are calendar schedules, not fixed 7-day or 30-day durations. Google News RSS is not an archive: with long intervals, an article that has already disappeared from the feed cannot be recovered. Use the default 15-minute schedule when minimizing missed news matters.

## Troubleshooting

- Check the Actions result and its uploaded SQLite state artifact first.
- Never publish webhook URLs, API keys, or tokens in logs or support posts.
- A successful manual test does not disable scheduling. If no scheduled run appears, confirm that the workflow is enabled and that the five-field `schedule` exists on the default branch.
- Distinguish GitHub scheduling delays and external API limits from code failures. Saved incomplete deliveries resume in sequence on the next run.

## Contributing and license

Use [Discussions](https://github.com/LYNGMN/DiscordActions/discussions) for feature ideas and [Issues](https://github.com/LYNGMN/DiscordActions/issues) for reproducible defects. This project is available under the [MIT License](LICENSE).

*한국어 문서: [README_KR.md](README_KR.md)*
