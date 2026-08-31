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
5. 시험이 끝난 뒤 Google News 예약 전송을 사용하려면 Repository Variable `GOOGLE_NEWS_SCHEDULE_ENABLED`를 `true`로 설정합니다.

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

Google News 예약 실행에는 Repository Variable `GOOGLE_NEWS_SCHEDULE_ENABLED=true`가 필요합니다. 선택적으로 `GOOGLE_NEWS_DELIVERY_ORDER`를 설정할 수 있습니다.

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

필수 Secret은 `YOUTUBE_API_KEY`, `YOUTUBE_MODE`, `DISCORD_WEBHOOK_YOUTUBE`입니다. 모드에 따라 다음 중 하나도 필요합니다.

- `channels`: `YOUTUBE_CHANNEL_ID`
- `playlists`: `YOUTUBE_PLAYLIST_ID`
- `search`: `YOUTUBE_SEARCH_KEYWORD`

선택 Secret은 `DISCORD_WEBHOOK_YOUTUBE_DETAILVIEW`, `YOUTUBE_DETAILVIEW`, `ADVANCED_FILTER_YOUTUBE`, `DATE_FILTER_YOUTUBE`, `LANGUAGE_YOUTUBE`입니다. Repository Variable `YOUTUBE_DELIVERY_ORDER`는 Google News와 같은 `feed_oldest_first` 또는 `feed_newest_first` 값을 사용합니다.

두 서비스 모두 선택 Secret `DISCORD_WEBHOOK_ADMIN`을 등록하면 응답 불명 재전송이나 최종 전송 실패를 관리자 채널에 알립니다. 알림에는 서비스, 프로필, 해시 처리된 항목 식별자, Actions 실행 링크만 포함됩니다.

- 채널 모드는 채널의 업로드 재생목록을 조회하고, 저장된 영상 경계 또는 페이지 끝까지 읽습니다.
- 일반 재생목록은 중간 위치에 영상이 추가될 수 있어 매번 모든 페이지를 확인합니다.
- 검색 모드는 이전 성공 체크포인트와 24시간 안전 중첩 구간부터 API의 모든 결과 페이지를 처리합니다. 다만 YouTube 검색 색인이 모든 영상을 보장하는 것은 아닙니다.
- 영상 상세 정보는 API 제한에 맞춰 50개씩 조회합니다.
- `YOUTUBE_MAX_RESULTS`와 날짜 기반 `YOUTUBE_PLAYLIST_SORT`는 채널·재생목록 예약 실행의 수집 개수나 순서를 제한하지 않습니다.

주간·월간 실행에서도 API에서 발견한 신규 영상은 모두 같은 실행 대기열에 들어갑니다.

## 실행 간격 바꾸기

워크플로의 `schedule` 아래 `cron`을 바꾸면 됩니다. 두 서비스가 동시에 시작하지 않도록 Google News와 YouTube의 실행 분을 다르게 유지합니다. 아래 예시는 모두 `timezone: 'Asia/Seoul'`을 함께 사용합니다.

| 간격 | Google News | YouTube |
| --- | --- | --- |
| 15분마다(기본) | `7,22,37,52 * * * *` | `11,26,41,56 * * * *` |
| 30분마다 | `7,37 * * * *` | `11,41 * * * *` |
| 1시간마다 | `7 * * * *` | `11 * * * *` |
| 6시간마다 | `7 */6 * * *` | `11 */6 * * *` |
| 매일 오전 9시 | `7 9 * * *` | `11 9 * * *` |
| 매주 월요일 오전 9시 | `7 9 * * 1` | `11 9 * * 1` |
| 매월 1일 오전 9시 | `7 9 1 * *` | `11 9 1 * *` |

GitHub Actions 예약 실행은 시스템 상황에 따라 늦게 시작될 수 있습니다. 주간·월간 예시는 “7일/30일 간격”이 아니라 달력의 월요일과 매월 1일 기준입니다. Google News RSS는 보관소가 아니므로 실행 간격이 길면 실행 시점에 피드에 남아 있지 않은 기사를 회수할 수 없습니다. 누락 최소화가 중요하면 기본 15분을 권장합니다.

## 문제 확인

- Actions 실행 결과와 업로드된 SQLite 상태 아티팩트를 먼저 확인합니다.
- 웹훅 URL, API 키, 토큰은 로그나 문의 글에 공개하지 마세요.
- Google News 예약 실행이 보이지 않으면 `GOOGLE_NEWS_SCHEDULE_ENABLED`가 문자열 `true`인지 확인합니다.
- GitHub Actions의 지연과 외부 API의 일시적 제한은 코드 오류와 구분해야 합니다. 실패한 전송은 다음 실행에서 저장된 순번부터 재개됩니다.

## 기여와 라이선스

기능 제안은 [Discussions](https://github.com/LYNGMN/DiscordActions/discussions), 오류는 [Issues](https://github.com/LYNGMN/DiscordActions/issues)에 남겨주세요. 이 프로젝트는 [MIT 라이선스](LICENSE)를 사용합니다.

*English documentation: [README.md](README.md)*
