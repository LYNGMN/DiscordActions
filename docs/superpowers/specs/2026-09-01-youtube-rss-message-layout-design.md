# YouTube RSS Message Layout Design

## Goal

Make Discord notifications clearly distinguish the information supplied by a
YouTube Atom RSS feed from the richer information supplied by the YouTube Data
API. RSS notifications must not imply that duration or category data is
available, while every fixed label in API messages and API detail embeds uses
the same selected display language.

## Chosen Approach

Use explicit RSS and API message layouts at the shared YouTube message boundary.
Keep all fixed YouTube labels in the existing shared ten-language localization
table and make both plain messages and API detail embeds consume that table.
This keeps the no-API-key RSS path simple, avoids hidden API requests, and
prevents language drift between the primary and detail webhooks.

The alternatives were rejected because one generic optional-field layout makes
the source difference unclear, while enriching RSS through the API would require
an API key and remove the main advantage of RSS mode.

## RSS Playlist Layout

An RSS playlist notification keeps the playlist header, a blank line, the video
channel header, the bold video title, and the short video URL. Its lower section
contains a localized linked channel name, localized publication date, and linked
thumbnail.

```text
`📃 RESCENE Archive - YouTube Playlist by. RESCENE`

`안녕하세요원이입니다잘부탁드립니다 - YouTube`
**원이 근황**
https://youtu.be/EsKmhBMmqIM

👤 Channel: [안녕하세요원이입니다잘부탁드립니다](https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)
📅 Published: `August 28, 2026`
🖼️ [Thumbnail](https://i2.ytimg.com/vi/EsKmhBMmqIM/hqdefault.jpg)
```

The channel link is derived locally from the required Atom `yt:channelId` value.
No extra network request is needed.

## RSS Channel Layout

An RSS channel notification uses the current channel header, bold video title,
short video URL, localized publication date, and linked thumbnail. It does not
repeat the channel as a separate lower field because the configured source is
already that channel.

```text
`RESCENE - YouTube`
**Video title**
https://youtu.be/VIDEO_ID

📅 Published: `August 28, 2026`
🖼️ [Thumbnail](https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg)
```

## API Layout

API mode keeps its existing layout and continues to show duration and category
when YouTube supplies them. Optional API detail embeds localize these fixed
labels through `DISPLAY_LANGUAGE`: Video ID, Category, Tags, Duration,
Subtitle, Play Video, Download, Embed, and Not Available.

```text
⏳ Duration: `07:13`
📅 Published: `August 28, 2026`
📁 Category: `Music`
🖼️ [Thumbnail](https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg)
```

RSS mode never displays placeholder duration or category lines because the Atom
feed does not provide those fields. It also does not display or link the source
feed URL; the supplied `view-source` example was reference material only.
Detail embeds remain an API-only feature.

## Localization and Documentation

The existing ten-language label system gains localized labels for Channel,
Video ID, Category, Tags, Duration, Published Date, Subtitle, Thumbnail, Play
Video, Download, Embed, and Not Available. `DISPLAY_LANGUAGE=ko` renders the
corresponding fixed labels in Korean; `ja`, `zh-CN`, `zh-TW`, `es`, `pt-BR`,
`fr`, `de`, and `id` render their own labels instead of falling back to Korean.

Video titles, channel names, playlist names, descriptions, tags, and category
values remain source data and are not translated. The category value continues
to use the localized title returned by the YouTube API when one is available.
The legacy `LANGUAGE_YOUTUBE` setting remains a fallback only when
`DISPLAY_LANGUAGE` is not set.

`README.md` and `README.ko.md` will show separate RSS channel, RSS playlist, and
API examples. The comparison table and nearby guidance will explicitly state
that duration and category require API mode and are unavailable in RSS mode.

## Data Flow and Error Handling

- The RSS parser already requires `yt:channelId`; the message formatter builds a
  canonical HTTPS channel URL from it.
- Playlist RSS messages require a valid channel ID before being queued.
- Channel RSS messages do not add a redundant lower channel field.
- `create_embed_message(video, youtube, display_language)` normalizes the
  selected language and reads every fixed label from `labels_for(language)`.
- Empty API tags display the localized Not Available value.
- API payload structure, source values, and resumable Discord delivery state are
  unchanged.
- No webhook, schedule, database schema, feed URL display, or API request behavior
  changes as part of this work.

## Verification

- Start with failing tests for the exact RSS playlist and channel layouts.
- Verify the playlist channel name is linked to the correct channel URL.
- Verify RSS messages omit duration, category, and source-feed URLs.
- Verify API messages still include duration and category.
- Verify every supported language supplies the complete fixed-label set.
- Verify exact English, Korean, and Japanese API detail embed labels, including
  localized Download, Embed, and Not Available text.
- Verify the legacy `LANGUAGE_YOUTUBE` fallback remains compatible when
  `DISPLAY_LANGUAGE` is unset.
- Verify English and Korean documentation examples explain that fixed labels,
  including API detail embed fields, follow `DISPLAY_LANGUAGE`.
- Run the complete Python unit suite, `py_compile`, `git diff --check`, structured
  file checks, and the changed-file credential scan before publication.
- Do not send a live Discord message during implementation or review.

## Git and Cleanup Boundaries

Implementation uses `codex/fix/youtube-rss-message-layout` in its dedicated
permanent worktree. It will be published only as a verified Draft PR and merged
only after a separate exact-state Squash approval.

The already merged PR #12, #13, and #14 worktrees and their matching local and
remote branches are cleanup candidates. They remain untouched until their exact
paths, branch names, and recoverable `main` commits are reported and the user gives
separate deletion approval.
