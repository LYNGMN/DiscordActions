# Discord Actions

Google News와 YouTube의 새 항목을 GitHub Actions로 확인하고 Discord 웹훅으로 전송합니다. 서버를 따로 운영하지 않아도 되며, 기본 확인 간격은 15분입니다.

## 주요 동작

- Google News 이름은 `Google News`, 아이콘은 프로젝트의 Google News 아이콘으로 고정됩니다.
- YouTube 이름은 `YouTube`, 아이콘은 프로젝트의 YouTube 아이콘으로 고정됩니다.
- 새 항목은 게시일을 다시 정렬하지 않고 RSS/API 목록의 위치를 기준으로 처리합니다. 기본값은 피드의 오래된 위치부터 최신 위치 순서입니다.
- 한 번에 여러 항목이 발견되면 일부만 자르지 않고 모두 순차 전송합니다.
- 첫 YouTube 실행은 현재 영상을 기준선으로만 저장하여 과거 영상이 한꺼번에 전송되는 일을 막습니다.
- Discord 전송 도중 실패하면 저장된 대기열의 미완료 메시지부터 다음 실행에서 재개합니다.

## 빠른 설정

1. 이 저장소를 Fork하거나 Template으로 새 저장소를 만듭니다.
2. 저장소의 **Settings → Secrets and variables → Actions**로 이동합니다.
3. 아래의 Secret과 Variable을 사용하려는 기능에 맞게 등록합니다. 값은 README, 이슈, Actions 로그에 붙여 넣지 마세요.
4. **Actions**에서 해당 워크플로를 선택하고 **Run workflow**로 먼저 시험합니다. `manual_test=true`이면 채널별 최신 항목 1개만 전송하고 나머지는 기준선으로 저장합니다.
5. 수동 시험 후에는 워크플로를 활성 상태로 두세요. 별도 활성화 변수 없이 예약 실행이 자동으로 이어집니다.

## 공통 날짜·키워드 필터

Google News와 YouTube는 같은 선택 Repository Variable을 사용합니다. Google News 프로필의 `.github/config/google_news_profiles.json` 값이 있으면 저장소 공통 값보다 우선합니다.

| 설정 | 기본값 | 용도 |
| --- | --- | --- |
| `FEED_DATE_FILTER` | 비움 | 상대 기간 또는 고정 날짜 범위의 항목만 전송 |
| `FEED_KEYWORD_FILTER` | 비움 | 불리언 키워드 식을 통과한 항목만 전송 |
| `FEED_KEYWORD_SCOPE` | `title` | `title` 또는 `title_or_description` |
| `FEED_TIMEZONE` | 자동 | 달력 필터와 표시 날짜에 사용할 시간대 |
| `FEED_COUNTRY` | 서비스 설정 | 명시적 시간대가 없을 때 시간대를 선택할 국가 |
| `DISPLAY_LANGUAGE` | 서비스 설정 또는 `en` | 고정 문구와 날짜의 표시 언어 |

날짜 필터의 시작·종료 경계는 모두 포함합니다. 날짜는 전송 여부만 판정하며 피드 순서를 바꾸지 않습니다.

| 예시 | 의미 |
| --- | --- |
| `calendar:1d` | 결정된 시간대의 오늘 0시부터 |
| `calendar:7d` | 오늘과 지난 6개 현지 날짜 |
| `calendar:1mo` | 현지 달력의 한 달 전 같은 날부터. 말일은 자동 보정 |
| `rolling:24h` | 현재로부터 정확히 지난 24시간 |
| `rolling:7d` | 정확히 지난 168시간 |
| `rolling:30d` | 정확히 지난 30일 |
| `from:2026-06-01 to:2026-08-15` | 6월 1일부터 8월 15일까지, 양쪽 현지 날짜 전체 포함 |
| `from:2026-06-01` | 6월 1일 이후 |
| `to:2026-08-15` | 8월 15일 이전 |

`calendar:7d`는 현지 달력 날짜 경계를 따르고, `rolling:7d`는 항상 정확히 168시간을 의미합니다. 시간대는 `FEED_TIMEZONE` → 서비스가 제공한 시간대 → `FEED_COUNTRY`/서비스 국가 → `UTC` 순으로 결정합니다. 표시 언어로 국가를 추측하지 않습니다. 일본 달력 기준이면 `FEED_TIMEZONE=Asia/Tokyo` 또는 `FEED_COUNTRY=JP`를 사용하세요.

미국처럼 여러 시간대를 사용하는 국가는 `FEED_COUNTRY`에만 의존하지 말고 대상 사용자 지역에 맞는 `FEED_TIMEZONE`을 직접 지정하세요.

키워드는 `OR`/`|`, `AND`/`&`/띄어쓰기, `NOT`/`!`/`-`, 괄호, `"Lee Ji-eun"`같은 정확한 구문을 지원합니다. 날짜와 키워드를 모두 설정하면 두 조건을 모두 통과해야 합니다.

```text
FEED_KEYWORD_FILTER=(AI OR "artificial intelligence") NOT 루머
FEED_KEYWORD_SCOPE=title
FEED_DATE_FILTER=calendar:7d
FEED_TIMEZONE=Asia/Seoul
```

`title_or_description`에서 Google News는 메인 제목과 연관뉴스 링크 제목을, YouTube는 영상 제목과 실제 설명을 검사합니다. 언론사명, URL, HTML 속성은 검사하지 않습니다. 잘못된 필터·언어·시간대 설정은 RSS/API 요청과 Discord 전송 전에 실패합니다.

## Google News 설정

Google News 통합 워크플로는 [프로필 설정 파일](.github/config/google_news_profiles.json)에 등록된 프로필을 순서대로 실행합니다. 현재 프로필에 필요한 Discord Secret 이름은 다음과 같습니다.

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

워크플로가 활성 상태이면 Google News 예약 실행이 자동으로 이어집니다. 선택적으로 `GOOGLE_NEWS_DELIVERY_ORDER`를 설정할 수 있습니다.

| 값 | 동작 |
| --- | --- |
| `feed_oldest_first` | 기본값. 현재 RSS 목록의 오래된 위치부터 전송 |
| `feed_newest_first` | 현재 RSS 목록의 최신 위치부터 전송 |

### 키워드 뉴스 정확도

키워드 프로필의 기본 `KEYWORD_MATCH_MODE`는 `title`입니다. 예를 들어 `아이유` 검색 피드에 연관뉴스 때문에 “이솔이…” 기사가 섞여도, 메인 제목에 판정어가 없으면 전송하지 않습니다. 제외 결과와 설정 지문을 저장하므로 같은 설정에서는 반복 검사하지 않고, 모드나 별칭을 바꾸면 현재 RSS에 남은 항목을 다시 판정합니다.

```json
{
  "KEYWORD_MATCH_MODE": "title",
  "KEYWORD_MATCH_ALIASES": "IU | \"Lee Ji-eun\" | 이지은"
}
```

- `title`: 메인 RSS 제목만 검사합니다. 제목 끝의 언론사명은 검사 대상에서 제외합니다.
- `title_or_description`: 메인 제목과 RSS `description`에 들어 있는 모든 연관뉴스의 **링크 제목**을 검사합니다. URL, HTML 속성, 언론사명은 검사하지 않습니다.
- 지원 연산자: `OR`/`|`, `AND`/`&`/띄어쓰기, `NOT`/`!`/`-`, 괄호, `"정확한 구문"`.
- `when:`, `after:`, `before:` 날짜 연산자는 키워드 판정어에서 제외됩니다.
- 잘못된 검색식은 뉴스 조회나 Discord 전송 전에 설정 오류로 종료됩니다.

통과한 항목에는 기존 `ADVANCED_FILTER_KEYWORD`가 추가 조건으로 적용됩니다. 메인 기사와 모든 연관뉴스는 원문 URL 변환을 먼저 시도하며, 변환하지 못한 연관뉴스는 검증된 Google News 기사 링크로 전송합니다. Discord 2,000자 한도를 넘으면 연관뉴스 순서를 유지한 후속 메시지로 나눕니다.

## YouTube 설정

Repository Variable `YOUTUBE_SOURCE`를 `rss` 또는 `api`로 설정합니다. 설정하지 않은 기존 사용자는 계속 `api`를 사용합니다.

| 항목 | RSS (`YOUTUBE_SOURCE=rss`) | API (`YOUTUBE_SOURCE=api`) |
| --- | --- | --- |
| 설정 난이도 | 가장 쉬움. API 키 불필요 | YouTube Data API 키 필요 |
| 채널 업로드 | 현재 Atom 피드에서 가능 | 업로드 재생목록의 전체 페이지 조회 |
| 재생목록 | 현재 Atom 피드에서 가능 | 모든 재생목록 페이지 조회 |
| 검색 결과 | 불가 | 저장된 검색 기준 이후의 반환 페이지 전체 처리 |
| 재생시간·카테고리 | 피드가 제공하지 않아 생략 | YouTube가 제공하면 표시 |
| 현재 피드에서 사라진 과거 항목 | 복구 불가 | 채널·재생목록 페이지를 계속 조회 가능 |
| 할당량 | YouTube API 할당량 없음 | YouTube Data API 할당량 사용 |

RSS와 API는 같은 영상 ID와 SQLite 상태를 사용하므로 방식을 바꿔도 이미 처리한 영상을 다시 보내지 않습니다. RSS에는 다음 페이지가 없으므로, 실행 전에 영상이 현재 피드에서 사라지면 복구할 수 없습니다.

RSS에는 `YOUTUBE_DETAILVIEW`에 필요한 상세 필드가 없으므로 `YOUTUBE_SOURCE=rss`일 때는 이 설정을 꺼 두세요.

필수 설정은 `YOUTUBE_MODE`, `DISCORD_WEBHOOK_YOUTUBE`와 모드별 값입니다.

- `channels`: `YOUTUBE_CHANNEL_ID`
- `playlists`: `YOUTUBE_PLAYLIST_ID`
- `search`: `YOUTUBE_SEARCH_KEYWORD` (API 전용)

API 방식은 `YOUTUBE_API_KEY` Secret도 필요합니다. 선택 Secret은 `DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW`, `YOUTUBE_DETAILVIEW`, `ADVANCED_FILTER_YOUTUBE`, `DATE_FILTER_YOUTUBE`, `LANGUAGE_YOUTUBE`입니다. Repository Variable `YOUTUBE_DELIVERY_ORDER`는 `feed_oldest_first|feed_newest_first`, `YOUTUBE_PLAYLIST_LAYOUT`은 `auto|channel|curated`를 사용합니다.

두 서비스 모두 선택 Secret `DISCORD_WEBHOOK_ADMIN`을 등록하면 응답 불명 재전송이나 최종 전송 실패를 관리자 채널에 알립니다. 알림에는 서비스, 프로필, 해시 처리된 항목 식별자, Actions 실행 링크만 포함됩니다.

- 채널 모드는 채널의 업로드 재생목록을 조회하고, 저장된 영상 경계 또는 페이지 끝까지 읽습니다.
- 일반 재생목록은 중간 위치에 영상이 추가될 수 있어 매번 모든 페이지를 확인합니다.
- 검색 모드는 이전 성공 체크포인트와 24시간 안전 중첩 구간부터 API의 모든 결과 페이지를 처리합니다. 다만 YouTube 검색 색인이 모든 영상을 보장하는 것은 아닙니다.
- 영상 상세 정보는 API 제한에 맞춰 50개씩 조회합니다.
- `YOUTUBE_MAX_RESULTS`와 날짜 기반 `YOUTUBE_PLAYLIST_SORT`는 채널·재생목록 예약 실행의 수집 개수나 순서를 제한하지 않습니다.

주간·월간 실행에서도 API에서 발견한 신규 영상은 모두 같은 실행 대기열에 들어갑니다.

API 메시지 형식은 다음과 같습니다.

```text
`BBC News 코리아 - YouTube`
**영상 제목**
https://youtu.be/VIDEO_ID

⏳ 재생시간: `07:13`
📅 게시일자: `2026년 6월 29일`
📁 카테고리: `뉴스 및 정치`
🖼️ [썸네일](https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg)
```

RSS 메시지는 재생시간과 카테고리를 생략합니다. 재생목록은 첫 줄 다음에 항상 한 줄을 비웁니다. `channel`은 `` `📃 재생목록명 by. 채널명 - YouTube 재생목록` ``, `curated`는 `` `📃 재생목록명 - YouTube 재생목록 by. 소유자` `` 형식입니다. `auto`는 단일 채널 목록을 `channel`, 혼합 채널 목록을 `curated`로 자동 선택합니다.

## 표시 언어

`DISPLAY_LANGUAGE`는 고정 문구와 날짜만 바꾸며 기사·영상·채널·재생목록의 고유 제목은 번역하지 않습니다. 지원 값은 `ko`, `en`, `ja`, `zh-CN`, `zh-TW`, `es`, `pt-BR`, `fr`, `de`, `id`입니다. YouTube API 카테고리는 선택 언어로 요청하고, 얻지 못하면 그 줄을 생략합니다. 기존 `LANGUAGE_YOUTUBE`도 호환되지만 `DISPLAY_LANGUAGE`가 우선합니다.

## 실행 간격 바꾸기

워크플로의 `schedule` 아래 `cron`을 바꾸면 됩니다. 표현식은 분, 시, 일, 월, 요일의 다섯 칸만 사용하며 워크플로에는 예약 시간대를 별도로 적지 않습니다.

| 간격 | Google News | YouTube |
| --- | --- | --- |
| 15분마다(기본) | `*/15 * * * *` | `*/15 * * * *` |
| 30분마다 | `*/30 * * * *` | `*/30 * * * *` |
| 1시간마다 | `0 * * * *` | `0 * * * *` |
| 6시간마다 | `0 */6 * * *` | `0 */6 * * *` |
| 매일 9시 | `0 9 * * *` | `0 9 * * *` |
| 매주 월요일 9시 | `0 9 * * 1` | `0 9 * * 1` |
| 매월 1일 9시 | `0 9 1 * *` | `0 9 1 * *` |

GitHub Actions 예약 실행은 시스템 상황에 따라 늦게 시작될 수 있습니다. 주간·월간 예시는 “7일/30일 간격”이 아니라 달력의 월요일과 매월 1일 기준입니다. Google News RSS는 보관소가 아니므로 실행 간격이 길면 실행 시점에 피드에 남아 있지 않은 기사를 회수할 수 없습니다. 누락 최소화가 중요하면 기본 15분을 권장합니다.

## 문제 확인

- Actions 실행 결과와 업로드된 SQLite 상태 아티팩트를 먼저 확인합니다.
- 웹훅 URL, API 키, 토큰은 로그나 문의 글에 공개하지 마세요.
- 수동 시험 성공은 예약 실행을 끄지 않습니다. 예약 실행이 보이지 않으면 워크플로가 활성 상태인지, 기본 브랜치에 다섯 칸짜리 `schedule`이 들어 있는지 확인합니다.
- GitHub Actions의 지연과 외부 API의 일시적 제한은 코드 오류와 구분해야 합니다. 실패한 전송은 다음 실행에서 저장된 순번부터 재개됩니다.

## 기여와 라이선스

기능 제안은 [Discussions](https://github.com/LYNGMN/DiscordActions/discussions), 오류는 [Issues](https://github.com/LYNGMN/DiscordActions/issues)에 남겨주세요. 이 프로젝트는 [MIT 라이선스](LICENSE)를 사용합니다.

*English documentation: [README.md](README.md)*
