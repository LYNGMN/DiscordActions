# Discord Actions 구조

이 문서는 현재 동작하는 구조와 지켜야 할 계약을 설명합니다. 작성 당시의 설계 문서는 `docs/superpowers/` 아래에 있으며, 그 문서들은 역사 기록입니다.

## 1. 전체 흐름

```text
Cloudflare Worker cron (*/15)
        │  workflow_dispatch
        ▼
GitHub Actions ── 최신 상태 artifact 복원 ──► dispatcher
        │                                      │
        │                                      ├─ 프로필 설정 검증·preflight
        │                                      ├─ 프로필별 handler subprocess
        │                                      │    ├─ RSS 수집
        │                                      │    ├─ 날짜·키워드 필터
        │                                      │    ├─ 원문 URL 해석(상한 40)
        │                                      │    ├─ SQLite 대기열 예약
        │                                      │    └─ Discord 전송
        │                                      ├─ 상태 정리·회전 저장
        │                                      └─ run-summary.json
        ▼
상태 artifact 업로드(3일 보존) ──► 다음 실행이 복원
```

GitHub `schedule`은 백업 트리거로 남아 있습니다. Worker가 없거나 실패해도 하루 몇 회는 실행됩니다. 자세한 설정은 `ops/state-trigger/README.md`를 참고하세요.

## 2. 구성 요소

| 구성 | 책임 | 위치 |
| --- | --- | --- |
| 운영 워크플로 | 상태 복원, dispatcher 실행, 상태·리뷰 artifact 업로드, 실패 알림 | `.github/workflows/googlenews-to-discord.yml`, `youtube_to_discord.yml` |
| 수동 시험 | 실제 전송 1건(Google News는 프로필 선택, YouTube는 영상 1건) | `googlenews-manual-test.yml`, `youtube-manual-test.yml` |
| 리셋 | 대기 만료와 채널 구분선 전송 | `googlenews-reset.yml` |
| 건강 모니터 | Google News·YouTube의 마지막 성공 실행 확인 | `googlenews-health.yml` |
| 디스패처 | 프로필 검증·preflight·subprocess·예산·회전·정리·요약 | `.github/scripts/google_news_dispatcher.py` |
| 핸들러 | `top`/`topic`/`keyword`별 RSS URL·라벨·메시지 구성 | `googlenews-*_to_discord.py` |
| 공용 상태 | SQLite 스키마, 대기열, 중복 판정, 보존 정리 | `google_news_delivery_state.py`, `youtube_delivery_state.py` |
| 공용 전송 | Discord webhook 호출, 429/5xx 재시도, 2,000자 분할 | `google_news_discord_delivery.py`, `youtube_discord_delivery.py` |
| 핸들러 런타임 | 대기열 전송 루프, 예산 중단, 영구 실패 알림 | `google_news_handler_runtime.py` |
| 설정 | 프로필 JSON과 공통 Repository Variable 검증 | `google_news_profiles.py`, `feed_filters.py` |

## 3. 상태 artifact 계약

한 실행의 상태 디렉터리에는 다음이 들어갑니다.

- 프로필별 SQLite DB(`state_db`): `news_items`, `google_news_delivery_messages`, `google_news_article_identity`.
- `resolver.db`: URL 원문 캐시와 `rss`/`resolver` circuit 상태.
- `profile-rotation.json`: 다음 실행이 시작할 프로필 위치.
- `run-summary.json`: 이번 실행의 프로필별 결과(민감 정보 없음).
- `unmapped-google-news-publishers.json`: 미등록 언론사 검토용(제목·URL·웹훅 없음).
- `youtube_videos.db`, `youtube-run-summary.json`(YouTube).

계약:

1. **복원이 실패하면 업로드하지 않는다.** 복원 단계는 `continue-on-error`로 1회 재시도하고, 최종 실패 시 실행을 실패시킨다. 빈 상태가 최신 artifact가 되면 중복 방지와 백로그가 사라진다.
2. **업로드는 복원 성공 또는 첫 실행일 때만 한다.** 첫 실행은 artifact가 없는 경우만 허용한다.
3. **업로드 실패는 1회 재시도하고, 두 번 모두 실패하면 실행을 실패시킨다.** 다음 실행이 이전 상태를 복원해 중복 전송할 수 있음을 운영자가 알 수 있어야 한다.
4. 상태 artifact 보존은 3일이다. 복원은 항상 최신 1개만 사용한다. 리뷰 artifact만 90일 보관한다.
5. SQLite는 WAL을 켜지 않는다(기본 rollback journal). 프로세스 종료 후 디렉터리를 통째로 올리므로 DB와 journal이 함께 보존된다.
6. dispatcher는 각 DB에 `PRAGMA quick_check`를 실행한다. 손상된 파일은 상태 디렉터리 밖으로 격리하고, 실행 요약 `state_repairs`에 기록한 뒤 해당 프로필은 새 DB로 시작한다. 오래된 항목이 다시 전송될 수 있지만 채널 전체가 영구히 멈추지는 않는다.

## 4. 대기열과 전송 의미

- 새 기사는 먼저 `news_items`와 `google_news_delivery_messages`에 예약된다. 메시지는 2,000자(UTF-16) 단위로 나뉜다.
- 상태: `pending`, `sent`, `filtered`, `failed`, `expired`. `pending`은 다음 실행에서 이어서 보낸다.
- 영구 4xx는 같은 메시지에서 3회까지 시도한 뒤 `failed`로 종결하고 다음 항목으로 넘어간다. 429·5xx·네트워크 오류는 pending으로 남긴다.
- 응답을 받지 못한 전송은 `ambiguous_retry`로 기록하고 한 번 재전송한다. Discord webhook에는 멱등 키가 없으므로 **정확히 한 번** 전송은 보장하지 않는다. 중복이 생길 수 있는 대신, 상태 기록 실패 시 재전송을 우선한다.
- `GOOGLE_NEWS_MAX_DELIVERIES_PER_PROFILE`(기본 25)이 한 실행의 전송 상한이다. 발견한 항목은 모두 대기열에 넣고, 상한을 넘은 항목은 다음 실행으로 넘긴다.
- 백로그가 500건 이상이면 3일 지난 대기 항목을 자동 만료한다. 이 동작은 의도적으로 손실을 감수하는 안전장치이며, 실행 요약과 관리자 알림에 남는다.
- 프로필 시작 위치는 `profile-rotation.json`으로 회전한다. 예산 때문에 뒤 프로필이 굶지 않게 하기 위한 것이다.

## 5. Circuit과 예산

- `GoogleNewsRequestGuard`는 `rss`와 `resolver` 두 scope를 가진다. RSS 403/429는 `rss` circuit을, URL 원문 해석 실패는 `resolver` circuit을 연다.
- resolver circuit이 열려도 RSS 수집과 Discord 전송은 계속한다. 링크만 Google News 기사 URL로 fallback한다.
- dispatcher는 `rss` circuit만 보고 프로필을 건너뛴다. 403 기본 차단은 30분, 429는 60분, `Retry-After`가 있으면 그 값을 최대 6시간까지 존중한다.
- 실행 예산(`GOOGLE_NEWS_RUN_BUDGET_SECONDS`, 기본 1080초)이 다 되면 남은 프로필을 건너뛰고 상태를 저장한다. 남은 시간이 3분 미만이면 정리·VACUUM을 건너뛴다. 워크플로 타임아웃은 35분이다.

## 6. 설정과 비밀값

- 프로필은 `.github/config/google_news_profiles.json`에 있다. `google_news_profiles.py`가 다음을 네트워크 요청 전에 검증한다.
  - 필수 키·알 수 없는 키·중복 ID
  - `TOP_MODE`/`TOPIC_MODE`/`KEYWORD_MODE`는 정확히 `"true"`/`"false"`
  - 모드별 필수·금지 항목(예: `TOP_MODE=true`면 `RSS_URL_TOP` 금지)
  - 지원 국가·토픽, `TOPIC_PARAMS`의 `hl`/`gl`/`ceid`
  - `WHEN`과 `AFTER_DATE`/`BEFORE_DATE` 배타, 날짜 형식
  - `FEED_COUNTRY`는 `feed_country_timezones.json`에 있는 코드
- Webhook URL과 API 키는 GitHub Secrets에만 둔다. 프로필 JSON, 로그, 요약, artifact에는 넣지 않는다.
- 모든 Discord payload는 `allowed_mentions: {"parse": []}`로 멘션을 끈다.

## 7. 실패 의미

| 상황 | 실행 상태 | 다음 실행 |
| --- | --- | --- |
| RSS 503/네트워크 | 해당 프로필 failed | 같은 프로필을 다시 시도 |
| Discord 429(대기 한도 초과) | 해당 프로필 failed, 메시지 pending | pending부터 재개 |
| Discord 영구 4xx 3회 | 메시지 failed, 프로필 failed | 다음 항목으로 진행 |
| 복원 실패 | 실행 failed, 업로드 안 함 | 직전 정상 artifact 복원 |
| 업로드 2회 실패 | 실행 failed | 이전 artifact 복원(중복 가능) |
| 시간 예산 소진 | 남은 프로필 skipped, 실행 success | 회전된 시작점에서 재개 |
| 모든 프로필 circuit/open | 실행 failed(`all_profiles_skipped`) | circuit 만료 후 재개 |

## 8. 새 프로필 추가 체크리스트

1. `.github/config/google_news_profiles.json`에 7개 최상위 키를 모두 넣는다.
2. 같은 `handler`의 기존 프로필을 복사하고 `id`, `webhook_env`, `expected_webhook_name`, `state_db`, `environment`만 바꾼다.
3. `environment`는 해당 handler의 필수·허용 키만 사용한다.
4. `.github/workflows/googlenews-to-discord.yml`과 `googlenews-manual-test.yml`의 env·secret 목록에 webhook을 추가한다.
5. 수동 시험 workflow의 `profile` choice에 ID를 추가한다.
6. `README.md`/`README.ko.md`의 프로필 표와 secret 목록을 갱신한다.
7. `python .github/scripts/google_news_dispatcher.py --check-config`로 오프라인 검증한다.
8. 수동 시험으로 실제 1건을 확인한 뒤 예약 실행에 맡긴다.

## 9. 검증 명령

```sh
python3.12 -m venv /tmp/discordactions-venv
/tmp/discordactions-venv/bin/pip install --require-hashes \
  -r .github/requirements.txt \
  -r .github/requirements-youtube.txt \
  -r .github/requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 /tmp/discordactions-venv/bin/python -m unittest discover -s .github/tests
/tmp/discordactions-venv/bin/ruff check .github/scripts .github/tests
/tmp/discordactions-venv/bin/yamllint -c .yamllint .github/workflows
node --test ops/state-trigger/test/*.test.mjs
python .github/scripts/google_news_dispatcher.py --check-config
```
