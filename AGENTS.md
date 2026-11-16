# Discord Actions 프로젝트 지침

이 파일은 이 저장소에서만 적용되는 규칙입니다. 상위 `~/Dev/AGENTS.md`와 `~/.dsh/AGENTS.md`의 공통 규칙을 먼저 따르고, 이 저장소에서는 아래를 추가로 지킵니다.

## 1. 읽는 순서

1. `docs/architecture.md` — 현재 데이터 흐름, artifact 계약, 실패 의미
2. `README.ko.md` — 운영 변수와 사용자에게 보이는 동작
3. 바꿀 기능을 맡은 모듈과 그 테스트
4. `docs/superpowers/`는 역사 기록이다. 현재 사양으로 쓰지 않는다.

## 2. 실행기와 파일 이름

- `googlenews-top_to_discord.py`, `googlenews-topic_to_discord.py`, `googlenews-keyword_to_discord.py`는 **레거시가 아니라 현행 운영 핸들러**다. `google_news_dispatcher.py`의 `HANDLERS`가 subprocess로 실행한다. 삭제하면 Google News 전 채널이 멈춘다.
- 새 공용 로직은 `google_news_*` 모듈에 둔다. 핸들러에는 RSS URL·라벨·메시지 구성처럼 그 handler에만 필요한 것을 남긴다.
- 파일명에 버전 접미사를 붙이지 않는다. 기존 파일을 인플레이스로 고친다.

## 3. 테스트와 검증

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s .github/tests
ruff check .github/scripts .github/tests
yamllint -c .yamllint .github/workflows
node --test ops/state-trigger/test/*.test.mjs
python .github/scripts/google_news_dispatcher.py --check-config
```

- 동작 변경은 실패하는 테스트를 먼저 추가한다.
- 워크플로 계약은 문자열 테스트로 고정되어 있다. YAML 단계 이름·조건을 바꾸면 `test_*workflow*.py`도 함께 고친다.
- 전체 테스트는 Python 3.12와 두 runtime lock, dev lock이 필요하다. 로컬 3.9로는 일부 테스트가 import 단계에서 실패한다.

## 4. 상태 artifact 불변식

- 복원이 최종 실패하면 **업로드하지 않는다.** 빈 상태가 최신 artifact가 되면 중복 방지·백로그가 사라진다.
- 업로드는 “복원 성공” 또는 “첫 실행(artifact 없음)”일 때만 한다.
- 업로드 실패는 1회 재시도하고, 두 번 모두 실패하면 실행을 실패시킨다.
- 상태 artifact 보존은 3일, 리뷰 artifact는 90일이다.
- SQLite 스키마 변경은 기존 DB를 읽을 수 있어야 한다. `ALTER TABLE`과 기본값을 사용하고, 기존 행을 지우는 migration을 만들지 않는다.

## 5. 전송 안전

- 모든 Discord payload에 `allowed_mentions: {"parse": []}`를 넣는다.
- Webhook URL, YouTube API 키, GitHub 토큰은 Secrets에만 둔다. 코드·README·로그·artifact·채팅에 출력하지 않는다.
- Discord 4xx를 무조건 반복하지 않는다. 영구 4xx는 3회 후 종결하고, 429·5xx·네트워크는 pending으로 남긴다.
- 원문 URL 해석은 프로필당 실행당 `GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS`(기본 40)까지만 한다.

## 6. 프로필·설정

- 새 프로필 절차는 `docs/architecture.md` 8절을 따른다.
- `TOP_MODE`/`TOPIC_MODE`/`KEYWORD_MODE`는 `"true"`/`"false"`만 허용한다.
- `FEED_COUNTRY`, `TOP_COUNTRY`, `GL`은 `feed_country_timezones.json`에 있는 코드만 쓴다.
- 설정 오류는 네트워크 요청 전에 `--check-config`로 잡는다.

## 7. 배포와 Git

- 배포(`wrangler deploy`, `clasp`, Worker secret 등록)는 사용자가 직접 실행한다. 에이전트는 대신 실행하지 않는다.
- `main` 직접 수정·Push·병합을 하지 않는다. 작업 브랜치에서 커밋하고 사용자에게 diff를 보여 준다.
- 커밋은 한 가지 의도만 담고, 변경 이유를 본문에 적는다.

## 8. 작업하며 배운 것

- GitHub `schedule`은 보장된 cron이 아니다 — 2026-11-16 — 15분 예약이 하루 4~5회만 실행되는 것을 확인. 외부 트리거(`ops/state-trigger`)와 `workflow_dispatch`를 함께 쓰고, 건강 모니터는 마지막 성공 실행을 본다.
- 상태 복원 실패 시 `if: always()` 업로드가 빈 상태를 게시할 수 있다 — 2026-11-16 — 복원 단계에 id·재시도·가드를 두고 업로드 조건을 복원 성공에 묶는다.
- `googlenews-*_to_discord.py`는 현행 실행기다 — 2026-11-16 — 디스패처 `HANDLERS`가 subprocess로 호출한다. “레거시 정리”로 삭제하지 않는다.
- `GOOGLE_NEWS_VALIDATE_ONLY`는 Discord 전송만 생략하고 RSS·URL 해석은 계속한다 — 2026-11-16 — 오프라인 설정 검사는 `--check-config`를 쓴다.
