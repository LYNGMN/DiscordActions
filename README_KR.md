# Discord Actions

GitHub Actions를 사용해 Google News와 YouTube의 새 항목을 주기적으로 확인하고 Discord 웹훅으로 전송합니다. 별도의 서버는 필요하지 않으며, 기본 확인 주기는 15분입니다.

## 동작 방식

- Discord 메시지 작성자로 표시되는 Google News 봇은 표시 이름으로 `Google News`, 프로필 이미지로 [Google News 아이콘](https://discordactions.github.io/logo/media/original/news/googlenews.png)을 항상 사용합니다.
- Discord 메시지 작성자로 표시되는 YouTube 봇은 표시 이름으로 `YouTube`, 프로필 이미지로 [YouTube 아이콘](https://discordactions.github.io/logo/media/original/youtube/youtube_social_circle_red.png)을 항상 사용합니다.
- 새 항목을 게시 시각으로 다시 정렬하지 않고 RSS/API 응답에 나온 순서를 따릅니다. 기본값은 오래된 항목부터 새 항목 순입니다.
- 새로 발견한 항목은 모두 전송 대기열에 넣습니다. 예약 실행에서도 결과 개수를 적게 제한해 일부 항목을 버리지 않습니다.
- YouTube를 처음 실행할 때는 현재 영상을 초기 기준 상태로만 저장합니다. 기존 영상이 Discord로 한꺼번에 전송되는 것을 막기 위한 동작입니다.
- Discord 전송이 항목 처리 중간에서 멈추면, 다음 실행에서 저장해 둔 미전송 메시지 또는 웹훅 대상부터 이어서 전송합니다.

## 빠른 설정

1. 이 저장소를 Fork하거나 Template을 사용해 새 저장소를 만듭니다.
2. 저장소의 **Settings → Secrets and variables → Actions**로 이동합니다.
3. 사용할 서비스에 필요한 Secret과 Variable만 등록합니다. 설정값은 README, 이슈, Actions 로그에 붙여 넣지 마세요.
4. **Actions**에서 워크플로를 선택하고 **Run workflow**로 먼저 시험합니다. `manual_test=true`이면 채널별로 현재 항목을 최대 1건만 전송하고, 나머지는 초기 기준 상태로 저장합니다.
5. 수동 시험을 마친 뒤에는 워크플로를 활성 상태로 둡니다. 별도의 활성화 Variable 없이 예약 실행이 자동으로 이어집니다.

## 공통 날짜·키워드 필터

Google News와 YouTube는 선택 사항인 공통 Repository Variable을 사용합니다. Google News 프로필의 `.github/config/google_news_profiles.json`에 값이 있으면 해당 프로필에서는 저장소 공통 값보다 먼저 적용합니다.

| 설정 | 기본값 | 용도 |
| --- | --- | --- |
| `FEED_DATE_FILTER` | 비움 | 상대 기간 또는 고정된 게시일 범위에 속한 항목만 전송 |
| `FEED_KEYWORD_FILTER` | 비움 | 불리언 키워드 식을 통과한 항목만 전송 |
| `FEED_KEYWORD_SCOPE` | `title` | `title` 또는 `title_or_description` 중 판정 범위 선택 |
| `FEED_TIMEZONE` | 자동 | 달력 필터와 날짜 표시에 사용할 시간대 |
| `FEED_COUNTRY` | 서비스 설정 | 시간대를 직접 지정하지 않았을 때 시간대 선택에 사용할 국가 |
| `DISPLAY_LANGUAGE` | 서비스 설정 또는 `en` | 고정 문구와 날짜에 사용할 표시 언어 |

날짜 필터는 시작일과 종료일을 모두 포함합니다. 날짜는 전송 여부만 판정하며 RSS/API의 항목 순서는 바꾸지 않습니다.

| 예시 | 의미 |
| --- | --- |
| `calendar:1d` | 결정된 시간대의 오늘 0시부터 |
| `calendar:7d` | 오늘과 지난 6개의 현지 달력 날짜 |
| `calendar:1mo` | 현지 달력에서 한 달 전 같은 날부터. 말일은 자동 보정 |
| `rolling:24h` | 현재 시각을 기준으로 지난 24시간 |
| `rolling:7d` | 현재 시각을 기준으로 지난 168시간 |
| `rolling:30d` | 현재 시각을 기준으로 지난 30일 |
| `from:2026-06-01 to:2026-08-15` | 6월 1일부터 8월 15일까지. 현지 날짜 기준으로 양쪽 경계일을 모두 포함 |
| `from:2026-06-01` | 6월 1일부터 |
| `to:2026-08-15` | 8월 15일까지 |

`calendar:7d`는 현지 달력의 날짜 경계를 따르지만 `rolling:7d`는 항상 정확히 168시간을 의미합니다. 시간대는 `FEED_TIMEZONE` → 서비스가 제공한 시간대 → `FEED_COUNTRY` 또는 서비스 국가 → `UTC` 순으로 결정합니다. 표시 언어로 국가를 추정하지 않습니다. 예를 들어 일본 달력을 기준으로 삼으려면 `FEED_TIMEZONE=Asia/Tokyo` 또는 `FEED_COUNTRY=JP`를 사용하세요.

미국처럼 여러 시간대를 사용하는 국가에서는 `FEED_COUNTRY`만 지정하지 말고, 알림을 받을 사용자 지역에 맞는 `FEED_TIMEZONE`을 직접 설정하세요.

키워드 필터는 `OR`/`|`, `AND`/`&`/인접한 검색어, `NOT`/`!`/`-`, 괄호, `"Lee Ji-eun"`같이 따옴표로 묶은 완전 일치 구문을 지원합니다. 날짜와 키워드를 모두 설정하면 두 조건을 모두 통과한 항목만 전송합니다.

```text
FEED_KEYWORD_FILTER=(AI OR "artificial intelligence") NOT 루머
FEED_KEYWORD_SCOPE=title
FEED_DATE_FILTER=calendar:7d
FEED_TIMEZONE=Asia/Seoul
```

`title_or_description`을 선택하면 Google News는 메인 제목과 연관뉴스 링크 제목을 확인하고, YouTube는 영상 제목과 실제 설명을 확인합니다. 언론사명, URL, HTML 속성은 키워드 판정에 사용하지 않습니다. 필터·언어·시간대 설정이 잘못되면 RSS/API를 요청하거나 Discord로 전송하기 전에 실행을 중단합니다.

## Google News 설정

Google News 통합 워크플로는 [프로필 설정 파일](.github/config/google_news_profiles.json)에 등록된 프로필을 순서대로 실행합니다. 현재 프로필에서 사용하는 Discord Secret 이름은 다음과 같습니다.

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

워크플로가 활성 상태이면 Google News 예약 실행이 자동으로 이어집니다. 전송 순서를 바꾸려면 선택 Repository Variable인 `GOOGLE_NEWS_DELIVERY_ORDER`를 설정하세요.

| 값 | 동작 |
| --- | --- |
| `feed_oldest_first` | 기본값. 현재 RSS 응답에 들어 있는 항목을 오래된 항목부터 전송 |
| `feed_newest_first` | 현재 RSS 응답에 들어 있는 항목을 새 항목부터 전송 |

### 키워드 뉴스 판정 방식

키워드 프로필의 기본 `KEYWORD_MATCH_MODE`는 `title`입니다. Google News가 연관 기사 때문에 피드에 포함한 항목이라도 메인 제목에 설정한 판정어가 없으면 기본적으로 전송하지 않습니다.

```json
{
  "KEYWORD_MATCH_MODE": "title",
  "KEYWORD_MATCH_ALIASES": "IU | \"Lee Ji-eun\" | 이지은"
}
```

- `title`은 메인 RSS 제목만 확인합니다. 제목 끝의 언론사명은 판정 대상에서 제외합니다.
- `title_or_description`은 메인 제목과 RSS `description`에 들어 있는 모든 연관뉴스의 **링크 제목**을 확인합니다. URL, HTML 속성, 언론사명은 판정하지 않습니다.
- `OR`/`|`, `AND`/`&`/인접한 검색어, `NOT`/`!`/`-`, 괄호, `"완전 일치 구문"`을 사용할 수 있습니다.
- `when:`, `after:`, `before:`같은 날짜 연산자는 키워드 판정식에서 제외합니다.
- 판정식이 잘못되면 RSS를 가져오거나 Discord 메시지를 보내기 전에 설정 오류로 종료합니다.

필터에서 제외한 항목은 현재 필터 설정을 구분하는 설정 식별값과 함께 저장합니다. 같은 설정에서는 다시 판정하지 않지만, 판정 모드나 별칭을 바꾸면 RSS에 아직 남아 있는 항목을 다시 판정합니다. `ADVANCED_FILTER_KEYWORD`는 이 판정을 통과한 항목을 한 번 더 좁히는 추가 조건으로 계속 적용합니다.

메인 기사와 모든 연관뉴스는 먼저 원문 URL 변환을 시도합니다. 원문 URL을 확인하지 못한 연관뉴스는 검증된 Google News 기사 링크를 대신 사용합니다. 연관뉴스 목록이 Discord의 2,000자 한도를 넘으면 순서를 유지한 채 후속 메시지로 나눠 전송합니다.

## YouTube 설정

Repository Variable `YOUTUBE_SOURCE`를 `rss` 또는 `api`로 설정합니다. 기존 설정에 `YOUTUBE_SOURCE`가 없으면 기존 동작과 같이 `api`를 사용합니다.

| 항목 | RSS (`YOUTUBE_SOURCE=rss`) | API (`YOUTUBE_SOURCE=api`) |
| --- | --- | --- |
| 설정 난이도 | 가장 간단함. API 키 불필요 | YouTube Data API 키 필요 |
| 채널 업로드 | 현재 Atom 피드에 나온 항목 확인 | 업로드 재생목록의 전체 페이지 확인 |
| 재생목록 | 현재 Atom 피드에 나온 항목 확인 | 재생목록의 모든 페이지 확인 |
| 검색 결과 | 지원하지 않음 | 저장된 처리 기준점 이후 API가 반환한 모든 페이지 처리 |
| 재생시간·카테고리 | RSS가 제공하지 않아 생략 | YouTube가 제공하면 표시 |
| 현재 피드에서 사라진 과거 항목 | 복구할 수 없음 | 채널·재생목록 데이터를 페이지별로 조회 가능 |
| 할당량 | YouTube API 할당량을 사용하지 않음 | YouTube Data API 할당량 사용 |

RSS와 API의 메시지 형식이 다른 이유는 YouTube가 각 방식에서 제공하는 정보가 다르기 때문입니다. [공식 Atom 알림 형식](https://developers.google.com/youtube/v3/guides/push_notifications)은 영상·채널 ID, 제목, 작성자, 게시 시각을 제공하지만 API 전용 정보인 재생시간과 카테고리는 포함하지 않습니다. API 방식은 [video 리소스](https://developers.google.com/youtube/v3/docs/videos)의 `contentDetails.duration`에서 재생시간을, `snippet.categoryId`에서 카테고리 ID를 가져옵니다. 선택한 언어의 카테고리명은 [`videoCategories.list`](https://developers.google.com/youtube/v3/docs/videoCategories/list)로 조회합니다. 따라서 RSS 알림에 재생시간이나 카테고리가 없는 것은 오류가 아닙니다. 해당 정보가 필요하면 API 방식을 사용하세요.

RSS와 API는 같은 영상 ID와 SQLite 처리 상태를 사용합니다. RSS에서 API로, 또는 API에서 RSS로 바꿔도 이미 처리한 영상을 다시 전송하지 않습니다. RSS에는 다음 페이지가 없으므로 실행 전에 영상이 현재 피드에서 사라지면 RSS로는 복구할 수 없습니다.

RSS는 `YOUTUBE_DETAILVIEW`에 필요한 상세 정보를 제공하지 않습니다. `YOUTUBE_SOURCE=rss`를 사용할 때는 해당 설정을 꺼 두세요.

필수 설정은 `YOUTUBE_MODE`, `DISCORD_WEBHOOK_YOUTUBE`, 그리고 모드에 맞는 아래 값 하나입니다.

- `channels`: `YOUTUBE_CHANNEL_ID`
- `playlists`: `YOUTUBE_PLAYLIST_ID`
- `search`: `YOUTUBE_SEARCH_KEYWORD` (API 전용)

API 방식에서는 `YOUTUBE_API_KEY` Secret도 필요합니다. 선택 Secret은 `DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW`, `YOUTUBE_DETAILVIEW`, `ADVANCED_FILTER_YOUTUBE`, `DATE_FILTER_YOUTUBE`, `LANGUAGE_YOUTUBE`입니다. 선택 Repository Variable인 `YOUTUBE_DELIVERY_ORDER`는 `feed_oldest_first|feed_newest_first`, `YOUTUBE_PLAYLIST_LAYOUT`은 `auto|channel|curated`를 사용합니다.

### RESCENE 예제로 설정하는 YouTube RSS

RSS 방식은 채널 하나의 새 영상이나 공개 재생목록 하나의 새 영상을 간단하게 받고 싶을 때 적합합니다. YouTube API 키도 필요하지 않습니다. 현재 워크플로에서는 `YOUTUBE_MODE`를 하나만 사용하므로, 채널 예제와 재생목록 예제 중 하나를 선택하세요. 한 번의 실행에서 두 대상을 동시에 확인하지는 않습니다.

먼저 **Settings → Secrets and variables → Actions → Variables**에서 다음 값을 등록합니다.

| 이름 | 값 | 용도 |
| --- | --- | --- |
| `YOUTUBE_SOURCE` | `rss` | API 키가 필요 없는 Atom 피드 사용 |
| `DISPLAY_LANGUAGE` | `ko` | 고정 문구와 날짜를 한국어로 표시 |
| `FEED_TIMEZONE` | `Asia/Seoul` 또는 사용자 지역의 시간대, 선택 | 필터와 표시 날짜에 사용할 현지 시간 기준 지정 |

아래의 `이름=값` 형식은 설정이 완성된 모습을 한눈에 보여 주기 위한 표기입니다. GitHub 화면에서는 이름과 값을 각각의 입력란에 넣으세요.

#### 예시 A: RESCENE 채널

채널 페이지: https://www.youtube.com/channel/UCtKtCiaWRz-d3EZn2xd1mdA

`/channel/` 뒤의 `UCtKtCiaWRz-d3EZn2xd1mdA`가 채널 ID입니다. 워크플로가 아래 RSS 주소를 자동으로 만들기 때문에 RSS URL을 별도 설정으로 저장할 필요는 없습니다.

https://www.youtube.com/feeds/videos.xml?channel_id=UCtKtCiaWRz-d3EZn2xd1mdA

**Actions → Secrets**에서 다음 값을 등록하거나 바꿉니다.

| 완성된 설정 | 용도 |
| --- | --- |
| `YOUTUBE_MODE=channels` | 채널 업로드 피드 사용 |
| `YOUTUBE_CHANNEL_ID=UCtKtCiaWRz-d3EZn2xd1mdA` | RESCENE 채널 선택 |
| `DISCORD_WEBHOOK_YOUTUBE=기존 Discord 웹훅` | 알림을 받을 Discord 채널 선택 |

RSS 설정에는 `YOUTUBE_API_KEY`를 추가하지 않습니다. Atom 피드는 API 전용 상세 정보를 제공하지 않으므로 `YOUTUBE_DETAILVIEW`는 등록하지 않거나 `false`로 설정하세요.

`DISPLAY_LANGUAGE=ko`일 때 채널 알림은 다음과 같은 형식입니다. 아래 내용은 2026년 9월 1일 실제 피드로 확인한 예시이며, 이후에는 영상 제목과 날짜가 달라질 수 있습니다.

```text
`RESCENE - YouTube`
**Let’s go**
https://youtu.be/JPAKX4X_9WU

📅 게시일자: `2026년 8월 31일`
🖼️ [썸네일](https://i3.ytimg.com/vi/JPAKX4X_9WU/hqdefault.jpg)
```

#### 예시 B: RESCENE Archive 재생목록

재생목록 페이지: https://www.youtube.com/playlist?list=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt

`list=` 뒤의 `PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt`가 재생목록 ID입니다. 워크플로가 아래 RSS 주소를 자동으로 만듭니다.

https://www.youtube.com/feeds/videos.xml?playlist_id=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt

**Actions → Secrets**에서 다음 값을 등록하거나 바꿉니다.

| 완성된 설정 | 용도 |
| --- | --- |
| `YOUTUBE_MODE=playlists` | 공개 재생목록 피드 사용 |
| `YOUTUBE_PLAYLIST_ID=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt` | RESCENE Archive 재생목록 선택 |
| `DISCORD_WEBHOOK_YOUTUBE=기존 Discord 웹훅` | 알림을 받을 Discord 채널 선택 |

**Actions → Variables**에는 `YOUTUBE_PLAYLIST_LAYOUT=curated`도 등록합니다. `RESCENE Archive`에는 여러 채널의 영상이 들어 있으므로 소유자가 보이는 혼합 재생목록 형식을 계속 사용할 수 있습니다. 기본값인 `auto`도 현재 피드를 확인하면 같은 형식을 자동으로 선택합니다.

```text
`📃 RESCENE Archive - YouTube 재생목록 by. RESCENE`

`안녕하세요원이입니다잘부탁드립니다 - YouTube`
**원이 근황**
https://youtu.be/EsKmhBMmqIM

👤 채널명: [안녕하세요원이입니다잘부탁드립니다](https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)
📅 게시일자: `2026년 8월 28일`
🖼️ [썸네일](https://i2.ytimg.com/vi/EsKmhBMmqIM/hqdefault.jpg)
```

#### RSS 설정 실행 및 확인

1. **Actions → YouTube to Discord Notification → Run workflow**를 엽니다.
2. 첫 실행에서는 `manual_test=true`를 유지합니다. 조건에 맞는 최신 항목을 최대 1건만 전송하고, 나머지 현재 항목은 초기 기준 상태로 저장해 과거 영상이 한꺼번에 전송되는 것을 막습니다.
3. Actions 실행이 성공했고 Discord에 시험 알림이 1개 이하로 도착했는지 확인합니다. 워크플로는 활성 상태로 두세요. 이후 예약 실행은 15분마다 새 항목을 확인하고, 기본값에서는 오래된 항목부터 새 항목 순으로 모든 신규 영상을 전송합니다.

다음 오류는 잘못된 설정을 조기에 알려 주는 정상적인 검증 결과입니다.

- `YOUTUBE_API_KEY is required`: Variables 탭에 `YOUTUBE_SOURCE`가 없거나 값이 정확히 `rss`가 아닙니다.
- `YouTube RSS does not support search mode`: RSS와 `YOUTUBE_MODE=search`를 함께 사용했습니다. 검색은 API 방식을 사용하세요.
- `YouTube RSS does not support YOUTUBE_DETAILVIEW`: API 전용 상세 보기가 아직 켜져 있습니다.
- 피드가 유효하지 않다는 오류: 채널·재생목록 ID를 잘못 복사했거나 대상이 비공개·삭제 상태일 수 있습니다. 위의 RSS 주소를 브라우저에서 열어 확인하세요.

RSS는 현재 Atom 피드가 제공하는 제한된 항목만 확인할 수 있고 다음 페이지도 없습니다. 예약 실행이 확인하기 전에 피드에서 사라진 영상은 RSS 방식으로 복구할 수 없습니다. 과거 항목 복구, 검색, 재생시간·카테고리, 전체 페이지 조회가 필요하면 API 방식을 사용하세요.

Google News와 YouTube 모두 선택 Secret인 `DISCORD_WEBHOOK_ADMIN`을 등록하면 전송 결과를 확인할 수 없어 재시도한 경우와 최종 전송 실패를 관리자 채널에 알립니다. 알림에는 서비스, 프로필, 해시로 처리한 항목 식별자, Actions 실행 링크만 포함합니다.

- 채널 모드는 채널의 업로드 재생목록을 마지막으로 처리한 영상 지점 또는 최종 페이지까지 조회합니다.
- 일반 재생목록은 중간 위치에도 영상이 추가될 수 있으므로 매번 모든 페이지를 확인합니다.
- 검색 모드는 이전 성공 처리 지점에서 24시간을 겹쳐 조회하고 API가 반환한 모든 결과 페이지를 처리합니다. 다만 YouTube 검색 색인이 모든 영상을 포함한다고 보장할 수는 없습니다.
- 영상 상세 정보는 API 제한에 맞춰 50개씩 묶어서 조회합니다.
- `YOUTUBE_MAX_RESULTS`와 날짜 기준 `YOUTUBE_PLAYLIST_SORT`는 예약 실행에서 채널·재생목록의 수집 개수를 잘라내거나 순서를 바꾸지 않습니다.

주간·월간으로 실행하더라도 API가 발견한 신규 영상은 모두 해당 실행의 전송 대기열에 들어갑니다.

API 메시지는 다음 형식을 사용합니다.

```text
`BBC News 코리아 - YouTube`
**영상 제목**
https://youtu.be/VIDEO_ID

⏳ 재생시간: `07:13`
📅 게시일자: `2026년 6월 29일`
📁 카테고리: `뉴스 및 정치`
🖼️ [썸네일](https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg)
```

RSS 채널 메시지는 게시일자와 썸네일을 표시합니다. RSS 재생목록 메시지는 여러 채널이 섞인 목록에서 영상 소유자를 확인할 수 있도록 채널명 링크도 표시합니다. Atom은 재생시간과 카테고리를 제공하지 않으므로 RSS 메시지에서는 두 항목을 생략합니다. 재생목록 메시지는 첫 줄 뒤에 항상 한 줄을 비웁니다. `channel`은 `` `📃 재생목록명 by. 채널명 - YouTube 재생목록` ``, `curated`는 `` `📃 재생목록명 - YouTube 재생목록 by. 소유자` `` 형식을 사용합니다. `auto`는 단일 채널 목록을 `channel`, 혼합 채널 목록을 `curated`로 자동 선택합니다.

## 표시 언어

`DISPLAY_LANGUAGE`는 고정 문구와 현지화된 날짜만 바꿉니다. 기사·영상·채널·재생목록의 고유 제목은 번역하지 않습니다. 지원 값은 `ko`, `en`, `ja`, `zh-CN`, `zh-TW`, `es`, `pt-BR`, `fr`, `de`, `id`입니다. YouTube API 카테고리명은 선택한 언어로 요청하며, 해당 언어의 값을 얻지 못하면 카테고리 줄을 생략합니다. 기존 `LANGUAGE_YOUTUBE`도 계속 사용할 수 있지만 `DISPLAY_LANGUAGE`가 먼저 적용됩니다.

일반 메시지와 API 상세 임베드의 고정 항목명 및 링크 문구는 모두 `DISPLAY_LANGUAGE`를 따릅니다. 채널명, 영상 ID, 카테고리, 태그, 재생시간, 게시일자, 자막, 썸네일, 영상 재생, 다운로드, 임베드, 정보 없음 문구가 여기에 포함됩니다. 영상 제목, 채널명, 설명, 태그는 메시지 작성 과정에서 번역하지 않으며, 카테고리 값은 YouTube가 반환한 제목을 그대로 사용합니다. 상세 임베드는 API 방식에서만 사용할 수 있습니다.

## 예약 실행 주기 설정

예약 실행 주기를 바꾸려면 워크플로의 `schedule` 아래에 있는 `cron`을 수정합니다. cron 표현식은 분, 시, 일, 월, 요일의 다섯 칸으로 작성하며 워크플로에는 예약 시간대를 별도로 지정하지 않습니다.

| 실행 주기 | Google News | YouTube |
| --- | --- | --- |
| 15분마다(기본) | `*/15 * * * *` | `*/15 * * * *` |
| 30분마다 | `*/30 * * * *` | `*/30 * * * *` |
| 1시간마다 | `0 * * * *` | `0 * * * *` |
| 6시간마다 | `0 */6 * * *` | `0 */6 * * *` |
| 매일 9시 | `0 9 * * *` | `0 9 * * *` |
| 매주 월요일 9시 | `0 9 * * 1` | `0 9 * * 1` |
| 매월 1일 9시 | `0 9 1 * *` | `0 9 1 * *` |

GitHub Actions 예약 실행은 시스템 상황에 따라 시작이 늦어질 수 있습니다. 주간·월간 예시는 고정된 7일·30일 간격이 아니라 달력의 월요일과 매월 1일을 기준으로 합니다. Google News RSS는 기사 보관소가 아니므로 실행 간격이 길면 실행 시점에 피드에서 사라진 기사를 다시 가져올 수 없습니다. 뉴스 누락을 최소화하려면 기본 15분 주기를 권장합니다.

## 문제 해결

- 먼저 Actions 실행 결과와 업로드된 SQLite 상태 아티팩트를 확인합니다.
- 웹훅 URL, API 키, 토큰은 로그나 문의 글에 공개하지 마세요.
- 수동 시험이 성공해도 예약 실행은 꺼지지 않습니다. 예약 실행이 보이지 않으면 워크플로가 활성 상태인지, 기본 브랜치의 `schedule`에 다섯 칸으로 작성한 cron 표현식이 있는지 확인합니다.
- GitHub Actions의 예약 지연과 외부 API의 일시적 제한을 코드 오류와 구분하세요. 저장해 둔 미완료 전송은 다음 실행에서 기록된 순번부터 이어집니다.

## 기여와 라이선스

기능 제안은 [Discussions](https://github.com/LYNGMN/DiscordActions/discussions), 재현할 수 있는 오류는 [Issues](https://github.com/LYNGMN/DiscordActions/issues)에 남겨 주세요. 이 프로젝트는 [MIT 라이선스](LICENSE)로 제공합니다.

*English documentation: [README.md](README.md)*
