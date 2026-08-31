# YouTube RSS Message Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RSS playlist notifications include a localized linked channel field, keep RSS channel notifications concise, and make API detail embed labels follow the same ten-language setting as primary messages.

**Architecture:** Keep the existing shared `build_youtube_message` boundary and branch only its lower metadata section by `include_api_details` and `source_type`. Reuse the RSS item `channel_id` to build the playlist channel link locally, and move API detail embed fixed text into the existing `feed_localization` table so primary and detail payloads share `DISPLAY_LANGUAGE`; do not add an API request, feed-source link, database change, or new dependency.

**Tech Stack:** Python 3.8, standard `urllib.parse`, Babel localization already in the repository, standard `unittest`, Markdown documentation.

## Global Constraints

- Do not display or link the RSS feed source URL in Discord messages.
- RSS mode must not show duration or category placeholders because Atom does not supply those fields.
- API mode must preserve the existing duration, published date, category, and thumbnail layout.
- RSS playlist mode adds a localized linked channel field; RSS channel mode does not repeat that field.
- Preserve the existing ten display languages and do not translate video, channel, or playlist names.
- Localize API detail embed field and link labels without translating video descriptions, tags, category values, or other YouTube source data.
- Keep API detail embeds unavailable in RSS mode.
- Do not change schedules, webhooks, database schemas, delivery state, or network request behavior.
- Do not send live Discord messages during implementation or review.

---

### Task 1: Source-Specific YouTube Metadata Layouts

**Files:**
- Modify: `.github/tests/test_feed_localization.py`
- Modify: `.github/scripts/feed_localization.py`
- Modify: `.github/scripts/youtube_messages.py`

**Interfaces:**
- Consumes: RSS/API video dictionaries already passed to `build_youtube_message(video, source_type, display_language, timezone_name, include_api_details, ...)`.
- Produces: `labels_for(language)["channel"]` and an RSS-playlist-only `👤 <label>: [<channel title>](https://www.youtube.com/channel/<encoded channel id>)` line.

- [ ] **Step 1: Write failing localization and exact-layout tests**

Add `channel_id` to the shared video fixture and require the new label in all ten languages:

```python
self.video["channel_id"] = "UCWpY0eSJtyO-qNAPbKFRSSg"

expected_channel_labels = {
    "ko": "채널명",
    "en": "Channel",
    "ja": "チャンネル",
    "zh-CN": "频道",
    "zh-TW": "頻道",
    "es": "Canal",
    "pt-BR": "Canal",
    "fr": "Chaîne",
    "de": "Kanal",
    "id": "Saluran",
}
```

Replace the RSS assertion with exact channel output and add an exact playlist assertion:

```python
self.assertEqual(
    "`BBC News 코리아 - YouTube`\n"
    "**2030 청년들 올림픽 공원 시위를 말하다- BBC News 코리아**\n"
    "https://youtu.be/dv74X0spCm0\n\n"
    "📅 Published: `June 29, 2026`\n"
    "🖼️ [Thumbnail](https://i.ytimg.com/vi/qdq9GpInFLY/hqdefault.jpg)",
    channel_rss_message,
)

self.assertIn(
    "👤 Channel: [BBC News 코리아]"
    "(https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)\n"
    "📅 Published: `June 29, 2026`",
    playlist_rss_message,
)
self.assertNotIn("Duration:", playlist_rss_message)
self.assertNotIn("Category:", playlist_rss_message)
self.assertNotIn("feeds/videos.xml", playlist_rss_message)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/discordactions-rss-layout-pycache \
  /private/tmp/discordactions-pr14-venv/bin/python \
  -m unittest discover -s .github/tests -p 'test_feed_localization.py' -v
```

Expected: FAIL because `channel` labels and the RSS playlist channel link do not exist.

- [ ] **Step 3: Add the ten localized channel labels**

Add a `channel` key beside the other YouTube labels in every `_LABELS` entry:

```python
"ko": {"channel": "채널명", ...}
"en": {"channel": "Channel", ...}
"ja": {"channel": "チャンネル", ...}
"zh-CN": {"channel": "频道", ...}
"zh-TW": {"channel": "頻道", ...}
"es": {"channel": "Canal", ...}
"pt-BR": {"channel": "Canal", ...}
"fr": {"channel": "Chaîne", ...}
"de": {"channel": "Kanal", ...}
"id": {"channel": "Saluran", ...}
```

- [ ] **Step 4: Add the RSS-playlist-only linked channel line**

Import `quote` and add a focused helper in `youtube_messages.py`:

```python
from urllib.parse import quote


def _youtube_channel_url(video: Dict[str, str]) -> str:
    channel_id = _required(video, "channel_id")
    return "https://www.youtube.com/channel/{}".format(
        quote(channel_id, safe="")
    )
```

In the `include_api_details is False` branch, add the playlist channel line before the publication date:

```python
if source_type == "playlists":
    lines.append(
        "👤 {}: [{}]({})".format(
            labels["channel"],
            channel_title,
            _youtube_channel_url(video),
        )
    )
lines.append(
    "📅 {}: `{}`".format(
        labels["published_date"],
        format_feed_date(published_at, language, timezone_name),
    )
)
```

Do not change the `include_api_details is True` branch.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the focused command from Step 2.

Expected: all `FeedLocalizationTests` pass, including the unchanged exact API message test.

- [ ] **Step 6: Commit the source-specific layout**

```bash
git add .github/tests/test_feed_localization.py \
  .github/scripts/feed_localization.py \
  .github/scripts/youtube_messages.py
git commit -m "fix: clarify YouTube RSS notification details"
```

---

### Task 2: English and Korean RSS/API Documentation

**Files:**
- Modify: `.github/tests/test_youtube_rss_documentation.py`
- Modify: `README.md`
- Modify: `README_KR.md`

**Interfaces:**
- Consumes: the exact layouts produced by Task 1.
- Produces: matching English and Korean setup examples and an explicit RSS/API field explanation backed by YouTube's official documentation.

- [ ] **Step 1: Write failing documentation assertions**

Require the English and Korean playlist examples to contain the linked channel fields:

```python
self.assertIn(
    "👤 Channel: [안녕하세요원이입니다잘부탁드립니다]"
    "(https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)",
    self.english,
)
self.assertIn(
    "👤 채널명: [안녕하세요원이입니다잘부탁드립니다]"
    "(https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)",
    self.korean,
)
```

Also require both documents to explain that Atom RSS lacks duration/category and that API values come from `contentDetails.duration` and `snippet.categoryId`:

```python
for document in (self.english, self.korean):
    self.assertIn("contentDetails.duration", document)
    self.assertIn("snippet.categoryId", document)
```

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```bash
/private/tmp/discordactions-pr14-venv/bin/python \
  -m unittest discover -s .github/tests -p 'test_youtube_rss_documentation.py' -v
```

Expected: FAIL because the linked channel examples and field-source explanation are absent.

- [ ] **Step 3: Update the English documentation**

In the RESCENE Archive RSS example, insert:

```text
👤 Channel: [안녕하세요원이입니다잘부탁드립니다](https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)
```

Explain immediately after the RSS examples that the Atom notification includes video/channel identity, title, author, and publication metadata but not the API-only details. Link to the official pages:

- `https://developers.google.com/youtube/v3/guides/push_notifications`
- `https://developers.google.com/youtube/v3/docs/videos`
- `https://developers.google.com/youtube/v3/docs/videoCategories/list`

State that duration is read from `contentDetails.duration`, the category ID from `snippet.categoryId`, and the localized category name from `videoCategories.list` only in API mode.

- [ ] **Step 4: Update the Korean documentation with matching meaning**

Insert the Korean field:

```text
👤 채널명: [안녕하세요원이입니다잘부탁드립니다](https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)
```

Translate the same RSS/API field explanation accurately. Do not add a source-feed line to either message example.

- [ ] **Step 5: Run documentation tests and verify GREEN**

Run the focused command from Step 2.

Expected: all `YouTubeRssDocumentationTests` pass.

- [ ] **Step 6: Commit the bilingual documentation**

```bash
git add .github/tests/test_youtube_rss_documentation.py README.md README_KR.md
git commit -m "docs: explain YouTube RSS and API message fields"
```

---

### Task 3: Shared API Detail Embed Labels

**Files:**
- Modify: `.github/tests/test_feed_localization.py`
- Modify: `.github/tests/test_youtube_workflow.py`
- Modify: `.github/scripts/feed_localization.py`
- Modify: `.github/scripts/youtube_to_discord.py`
- Modify: `.github/tests/test_youtube_rss_documentation.py`
- Modify: `README.md`
- Modify: `README_KR.md`

**Interfaces:**
- Consumes: `normalize_display_language(language)` and `labels_for(language)` from `feed_localization.py`.
- Produces: `create_embed_message(video, youtube, display_language)` with localized fixed labels and unchanged YouTube source values.

- [ ] **Step 1: Write failing label-completeness and embed tests**

Extend `test_every_language_has_all_required_labels` to require these keys in
every supported language:

```python
for key in (
    "channel",
    "video_id",
    "category",
    "tags",
    "duration",
    "published_date",
    "subtitle",
    "thumbnail",
    "play_video",
    "download",
    "embed",
    "not_available",
):
    self.assertTrue(labels[key])
```

Add focused embed tests in `test_youtube_workflow.py` using a fake
`channels().list().execute()` response. Assert exact English, Korean, and
Japanese field names, localized Download/Embed links, and localized empty-tag
text. Also assert that the video title, description, category value, and tag
value remain unchanged.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/discordactions-rss-layout-pycache \
  /private/tmp/discordactions-pr14-venv/bin/python \
  -m unittest discover -s .github/tests \
  -p 'test_feed_localization.py' -v

PYTHONPYCACHEPREFIX=/private/tmp/discordactions-rss-layout-pycache \
  /private/tmp/discordactions-pr14-venv/bin/python \
  -m unittest discover -s .github/tests \
  -p 'test_youtube_workflow.py' -v
```

Expected: FAIL because the new shared label keys and the explicit
`display_language` embed interface do not exist.

- [ ] **Step 3: Add complete fixed labels to the shared localization table**

Add these keys to every `_LABELS` language entry in
`feed_localization.py`: `video_id`, `tags`, `subtitle`, `play_video`,
`download`, `embed`, and `not_available`. Keep the existing `channel`,
`duration`, `published_date`, `category`, and `thumbnail` keys. Use native
fixed-label translations for `ko`, `en`, `ja`, `zh-CN`, `zh-TW`, `es`,
`pt-BR`, `fr`, `de`, and `id`.

- [ ] **Step 4: Make API detail embeds consume `DISPLAY_LANGUAGE`**

Import `labels_for` beside `normalize_display_language`, change the interface,
and replace every `LANGUAGE_YOUTUBE` conditional:

```python
def create_embed_message(video, youtube, display_language):
    language = normalize_display_language(display_language)
    labels = labels_for(language)
    channel_thumbnail = get_channel_thumbnail(youtube, video['channel_id'])
    tags = video['tags'].split(',') if video['tags'] else []
    formatted_tags = ' '.join(f'`{tag.strip()}`' for tag in tags)
```

Construct fields with `labels["video_id"]`, `labels["category"]`,
`labels["tags"]`, `labels["duration"]`, `labels["subtitle"]`, and
`labels["play_video"]`. Use `labels["not_available"]` for empty tags,
`labels["download"]` for the subtitle link, and `labels["embed"]` for the
player link. Pass the already normalized runtime value at the call site:

```python
embed_message = create_embed_message(video, youtube, display_language)
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run both focused commands from Step 2.

Expected: all feed-localization and YouTube workflow tests pass.

- [ ] **Step 6: Add failing documentation assertions, then update both READMEs**

Require `README.md` and `README_KR.md` to state that API detail embed field and
link labels follow `DISPLAY_LANGUAGE`, source values are not translated, and
detail embeds remain API-only. Update both documents with equivalent English
and Korean explanations, then run:

```bash
/private/tmp/discordactions-pr14-venv/bin/python \
  -m unittest discover -s .github/tests \
  -p 'test_youtube_rss_documentation.py' -v
```

Expected after the documentation edit: all documentation tests pass.

- [ ] **Step 7: Commit the localized API detail labels**

```bash
git add .github/tests/test_feed_localization.py \
  .github/tests/test_youtube_workflow.py \
  .github/scripts/feed_localization.py \
  .github/scripts/youtube_to_discord.py \
  .github/tests/test_youtube_rss_documentation.py \
  README.md README_KR.md
git commit -m "fix: localize YouTube detail labels"
```

---

### Task 4: Full Regression and Publication Checkpoint

**Files:**
- Verify all files changed in Tasks 1 through 3.
- Do not modify runtime behavior unless a failing test exposes a regression caused by this branch.

**Interfaces:**
- Consumes: the verified implementation and documentation commits.
- Produces: one clean local branch checkpoint eligible for full review and later Draft PR publication.

- [ ] **Step 1: Run the complete unit suite**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/discordactions-rss-layout-pycache \
  /private/tmp/discordactions-pr14-venv/bin/python \
  -m unittest discover -s .github/tests -v
```

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 2: Compile all Python scripts and tests**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/discordactions-rss-layout-pycache \
  /private/tmp/discordactions-pr14-venv/bin/python \
  -m py_compile .github/scripts/*.py .github/tests/*.py
```

Expected: exit code 0.

- [ ] **Step 3: Validate the final diff and repository state**

```bash
git diff --check origin/main...HEAD
git status --short
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected: no whitespace errors, no uncommitted files, and only the approved design, plan, runtime, tests, and README changes.

- [ ] **Step 4: Scan changed files for credential-shaped values**

```bash
git diff --name-only origin/main...HEAD | xargs rg -l -i \
  '(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+)'
```

Expected: no matching files.

- [ ] **Step 5: Review before any publication**

Compare `origin/main...HEAD`, verify that API formatting is unchanged, and report the exact branch, commits, included files, and fresh checks. Do not Push until the repository's publication gate is satisfied.
