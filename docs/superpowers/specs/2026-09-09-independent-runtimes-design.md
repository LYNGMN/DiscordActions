# Independent Cloudflare and Google Apps Script runtimes

## English

### Decision and delivery status

On September 9, 2026, the user selected two independent versions. Either version must operate without the other and without GitHub Actions at runtime. The existing Python/GitHub Actions implementation remains supported and unchanged during development. This document records the detailed design for review; it is not evidence of implemented or deployed functionality.

Baseline: `LYNGMN/DiscordActions`, `main@26271a0570e4e1ec3a8a3eddafc8742c786acb9a`. Work branch: `codex/feat/independent-runtimes`. Writer: Codex. Existing `.gstack/` files and the two older reference worktrees remain untouched. No secret, remote publication, cloud resource creation, billing change, Discord delivery, or operational cutover is authorized by this design checkpoint.

### Architecture

Use a shared JavaScript domain library, a Cloudflare adapter, and an Apps Script adapter in this repository. Build the library into each distribution; neither distribution calls the other. Node.js is a development/build dependency, not an end-user runtime dependency for Apps Script. Keep platform APIs outside the domain library. Do not try to execute the existing Python code in Apps Script.

| Component | Cloudflare version | Apps Script version |
| --- | --- | --- |
| Scheduled entry point | Workers Cron Trigger, every 15 minutes | One time-based trigger using `everyMinutes(15)` |
| Configuration | Validated profile JSON and Worker bindings | A Profiles sheet with equivalent validated fields |
| Credentials | Worker Secrets | Script Properties; never cells or source code |
| Durable state | D1 tables and transactional batches | State sheets with an append-only journal and commit markers |
| Concurrent runs | Conditional D1 lease with owner token and renewal | Script-level LockService lock |
| Manual test | Authenticated request records a durable manual job | Spreadsheet menu records/runs a durable manual job |
| Review output | Authenticated unmapped-publisher JSON export | Unmapped Publishers sheet and JSON export |

Manual and scheduled operations use the same state and lock. No unauthenticated sending endpoint is provided. Cloudflare HTTP handlers must not rely on unbounded `waitUntil()` to finish delivery: persist the job first and let the scheduled processor finish it. Script editors can access Script Properties, so the installation guide must warn against sharing edit access with untrusted people. A hidden sheet is not a secret store.

### Scope preserved from the current implementation

1. Google News Top, Topic, and Keyword, including the existing 11 profile definitions, separate webhook destinations, display-only keyword labels, and topic exclusions.
2. YouTube channel and playlist RSS, and channel/playlist/search API modes. RSS/API transitions use the same video IDs. API channel mode uses the uploads playlist; playlist mode traverses all pages; search remains best-effort with a successful checkpoint and overlap. Fetch details in batches of 50. Preserve playlist layouts and optional detail webhook targets.
3. Shared inclusive date filters, Boolean keyword expressions, main-title matching by default, aliases, additional filters, and configuration fingerprints. Google News description scope examines linked related headlines, not publisher names, URLs, or HTML attributes. Retain existing environment-setting compatibility through a configuration importer.
4. Existing delivery-order settings: source-list positions, never publication-date sorting. The default reverses newest-first source positions. Queue all newly discovered matching items; a runtime budget defers work without discarding it.
5. Existing first-run behavior: YouTube scheduled initialization records a baseline. A manual test selects the newest matching current item and baselines the others. Later manual tests resume at most one item per selected profile, including all of that item's messages/targets. A limit of one item does not mean one Discord message.
6. Original URL resolution for main and every related story, legacy decoding, signature/timestamp RPC, success cache, failed-resolution backoff, request budget, and 429/access-denial circuit handling. Preserve encoded URL queries. Fall back to validated Google News links without inventing original URLs. Google News's unofficial RPC can change or reject either platform; report fallback counts.
7. All related stories, ordered Discord message splitting, publisher-name mappings, pending-message normalization, and privacy-safe unknown-publisher collection. Preserve already-sent messages and persist observations before queue publication.
8. Discord display names and icons remain `Google News` and `YouTube` with the project's existing icon URLs. Retain the requested title, inline-code, blank-line, thumbnail, playlist, and metadata layouts. RSS omits API-only duration/category. Never fabricate unavailable metadata.
9. Ten display languages: `ko`, `en`, `ja`, `zh-CN`, `zh-TW`, `es`, `pt-BR`, `fr`, `de`, `id`. Keep country/timezone precedence and padded KR/JP/CN/US formats, including EST/EDT. Date filtering and display use the same resolved timezone, but do not change schedule timezone settings. Do not silently depend on host-specific timezone rules: compare both adapters against the pinned Python timezone fixtures, including gaps and overlaps, before claiming parity.
10. Persist-before-send queues, exact unfinished message/target recovery, bounded Discord retries, bucket cooldowns, safe error codes, the existing narrow Google-link payload recovery, ambiguous-delivery reporting, and optional administrator alerts.

### State and recovery contract

The shared state model contains profile configuration versions, source scans and staged pages, handled/filtered item identities, ordered delivery items, ordered messages/targets, resolver cache, unknown publisher occurrences, run metrics, and schema/import versions. Stable keys include service, profile, source, item ID, and message/target position. Store webhook key names, not credential values, in queue records.

A run validates configuration before network requests, acquires its lock, repairs incomplete storage operations, resumes an unfinished source scan, commits complete source batches, and drains the oldest pending item. Newer messages may not overtake an unfinished older item. Other independent profiles may proceed after an individual profile failure; the run records partial failure rather than reporting blanket success.

API pages are staged durably with their continuation token and snapshot generation. Do not advance the successful search checkpoint or send a partially collected new batch before the scan completes. If a saved token expires, restart that source scan while retaining staged identities and reconciling duplicates. RSS snapshots are saved before processing; malformed items fail the affected scan instead of silently skipping to newer items. Items that disappear before any successful fetch cannot be recovered from RSS.

D1 commits queue publication and state changes atomically. Sheets is not SQLite: append item/message records with stable keys and a generation ID, flush them, then append a commit marker. Readers ignore an uncommitted generation. Recovery completes or discards only uncommitted records by deterministic identity; it never marks an unsent item as sent. A lock serializes all mutations from this script, and state-sheet edits by users are unsupported. Use text-safe cell writes so feed strings beginning with `=`, `+`, `-`, or `@` cannot become spreadsheet formulas. Chunk large snapshots rather than assuming one cell can hold an entire feed.

Before each external send, persist the attempt identity. Record a successful `wait=true` Discord message ID before proceeding. A crash or lost response between Discord acceptance and durable acknowledgement is inherently ambiguous: retain the existing at-least-once policy and surface possible duplicates. Do not promise exactly-once delivery, including after state-write failure. Never send newer positions first to bypass a failed message.

### Runtime budgets and schedules

Both distributions poll every 15 minutes by default. Cloudflare keeps service offsets where supported: Google News `7,22,37,52 * * * *`, YouTube `11,26,41,56 * * * *`. Apps Script uses one shared 15-minute trigger and round-robin profile processing; exact minute offsets are not promised. Examples for 30 minutes, one hour, six hours, daily, weekly, and monthly schedules must distinguish interval execution from calendar execution.

Apps Script has a six-minute execution limit and separate daily quotas. Use an explicit deadline with a safety margin and a conservative configurable daily work budget, counting throttling waits as runtime. Save unfinished scans, queue positions, and a profile rotation cursor. Cloudflare also uses explicit execution/request/DB budgets with a safety margin and saves deferred work before exhausting limits. Retry-After values beyond the remaining budget become durable retry times, not long blocking sleeps. Never suppress backlog or quota errors to claim success. Large backlogs can require multiple invocations and may outgrow a free/account quota; documentation must state this without reducing the feature scope.

### Migration and security

Provide a local Python export tool for existing SQLite state and a versioned import format accepted by both adapters. Preserve sent/baseline/filtered identities, filter fingerprints, unfinished messages and targets, cache entries, publisher observations, and source checkpoints. Private state exports can contain article URLs and message text: they are backups, not public diagnostics. They must contain no webhook URL, API key, or token, must never be committed, and must be imported only through authenticated/local setup.

For a destination already in use, stop its previous scheduler, wait for active sends to finish, export the final state, import and validate it, run a no-send check, then explicitly enable the selected new runtime. Keep the old state as rollback evidence. Independent installations cannot automatically deduplicate each other's writes: only one runtime owns a destination at a time. A rollback also needs the latest state from the new owner; re-enabling an old stale snapshot can duplicate messages.

Do not expose secrets in logs, reports, spreadsheet cells, example files, tests, or PR bodies. Restrict fetched service endpoints and accepted webhook hosts. Do not fetch arbitrary publisher pages merely to validate a resolved URL. Escape untrusted text for Discord and disable unintended mentions. Default setup validates without sending; real manual tests require an explicit send action.

### Implementation boundaries and acceptance evidence

Proposed layout: `runtimes/shared/` for pure logic and state contracts; `runtimes/cloudflare/` for Worker/D1 entry points, migrations and bindings; `runtimes/apps-script/` for the bundle, manifest, menus, storage and platform services; `runtimes/tests/` for parity and adapter fixtures; `tools/export-runtime-state.py` for SQLite migration. Keep maintained root README files focused on selecting an installation route; each runtime gets English and Korean setup guides.

Implement in independently reviewed stages, without dropping either platform from the full objective:

| Stage | Deliverable | Required evidence |
| --- | --- | --- |
| Shared behavior | Parsers, filters, formatting, identities, resolver and delivery state machine | Python-derived fixtures for both services; all related headlines; 10 languages; DST; UTF-16 message limits |
| Cloudflare | Runnable Worker plus D1, configuration and manual/no-send paths | Local Worker/D1 tests; competing leases; storage failures; quota/deadline continuation; denied manual authentication |
| Apps Script | Copy/install distribution, Sheets UI, properties and trigger | Built-bundle tests with service doubles; journal crash recovery; locking; formula injection; first test and recurring continuation |
| Migration and documentation | Versioned import/export and matching bilingual setup guides | Old SQLite fixture imports twice without duplicate rows or sends; pending position preserved; no credentials in exports |
| Deployment verification | Both independent installations verified after deployment authorization | Real RSS no-send check; platform authentication; real one-item test after sending authorization; stored message IDs and resumed positions |

For every stage, write failing tests first. Include three-page/100+ YouTube items, 50-item detail batches, filter changes, malformed feeds, long related lists, Google 429, Discord 429/4xx/5xx/network ambiguity, failures between send and acknowledgement, and manual/scheduled contention. Run the existing Python regression suite unchanged. A mock test is not proof of deployed Apps Script or Cloudflare behavior. No need to wait for weekly/monthly wall-clock schedules: use fixed clocks and manual no-send verification.

### Official constraints checked on September 9, 2026

- [Apps Script quotas](https://developers.google.com/apps-script/guides/services/quotas): six minutes per execution; consumer trigger runtime 90 minutes/day versus six hours/day for Workspace; quota exhaustion can interrupt a run.
- [Apps Script clock triggers](https://developers.google.com/apps-script/reference/script/clock-trigger-builder): `everyMinutes` accepts 1, 5, 10, 15, or 30. Do not promise a specific minute offset.
- [Workers limits](https://developers.cloudflare.com/workers/platform/limits/): scheduled execution has a 15-minute wall-clock ceiling; CPU and request limits also apply.
- [D1 limits](https://developers.cloudflare.com/d1/platform/limits/): plan-dependent query/storage limits require bounded operations; SQL batch statements retain per-statement limits.

## 한국어

### 결정 사항과 현재 상태

2026년 9월 9일 사용자가 독립된 두 버전을 선택했습니다. 어느 버전이든 다른 버전이나 GitHub Actions 없이 운영할 수 있어야 합니다. 개발 중에는 기존 Python/GitHub Actions 버전을 그대로 유지합니다. 이 문서는 상세 설계 검토본이며 구현·배포 완료를 뜻하지 않습니다.

기준은 `LYNGMN/DiscordActions`의 `main@26271a0570e4e1ec3a8a3eddafc8742c786acb9a`, 작업 브랜치는 `codex/feat/independent-runtimes`, 작성자는 Codex입니다. 기존 `.gstack/`과 이전 참고 작업 폴더 두 개는 건드리지 않습니다. 이 설계 저장 단계에는 인증정보 변경, 공개 게시, 클라우드 자원 생성, 요금제 변경, Discord 전송, 운영 전환이 포함되지 않습니다.

### 구성

공통 JavaScript 처리 코드와 Cloudflare·Apps Script 전용 연결 코드를 같은 저장소에 둡니다. 공통 코드는 각 배포본에 포함하며 두 서비스가 서로 호출하지 않습니다. Node.js는 개발·빌드에만 사용하고 Apps Script 사용자가 별도 서버를 운영할 필요는 없습니다. 플랫폼 API를 공통 코드와 분리하며 기존 Python 코드를 Apps Script에서 실행하려고 하지 않습니다.

| 항목 | Cloudflare 버전 | Apps Script 버전 |
| --- | --- | --- |
| 주기 실행 | Workers Cron Trigger, 기본 15분 | `everyMinutes(15)` 시간 기반 트리거 하나 |
| 설정 | 검증된 프로필 JSON과 Worker 설정 | 동일한 항목을 검증하는 Profiles 시트 |
| 인증정보 | Worker Secrets | Script Properties; 시트 셀·소스 코드에는 저장하지 않음 |
| 영구 상태 | D1 테이블과 트랜잭션 | 상태 시트와 추가 기록 방식의 작업 일지·저장 완료 표식 |
| 동시 실행 방지 | 소유 토큰과 갱신을 포함한 조건부 D1 잠금 | LockService의 스크립트 단위 잠금 |
| 수동 테스트 | 인증된 요청으로 테스트 작업을 먼저 저장 | 시트 메뉴로 테스트 작업을 저장·실행 |
| 언론사 검토 목록 | 인증 후 미등록 언론사 JSON 다운로드 | Unmapped Publishers 시트와 JSON 내보내기 |

수동·예약 실행은 같은 상태와 잠금을 사용합니다. 인증 없이 전송하는 공개 주소는 만들지 않습니다. Cloudflare 수동 요청은 작업을 저장한 뒤 예약 처리기가 완료하도록 하며, `waitUntil()`만으로 긴 전송을 끝낼 수 있다고 가정하지 않습니다. 스크립트 편집자는 Script Properties를 읽을 수 있으므로 신뢰하지 않는 사람에게 편집 권한을 주지 않도록 안내합니다. 숨긴 시트도 비밀정보 저장소가 아닙니다.

### 유지할 기능

1. Google News Top·Topic·Keyword 전체, 기존 11개 프로필, 각각의 웹훅, 표시 전용 키워드, 토픽 제외 설정을 유지합니다.
2. YouTube 채널·재생목록 RSS와 채널·재생목록·검색 API를 지원합니다. RSS/API 전환 시 같은 영상 ID를 사용합니다. API 채널은 업로드 재생목록, 일반 재생목록은 전체 페이지를 사용하며 검색은 성공 시점과 중첩 구간을 이용하는 최선 노력 방식입니다. 상세 정보는 50개씩 조회하고 재생목록 양식과 선택적 상세 웹훅도 유지합니다.
3. 경계일을 포함하는 날짜 필터, Boolean 키워드 식, 기본 메인 제목 검사, 별칭, 추가 필터, 설정 식별값을 유지합니다. Google News 설명 검사는 연관 기사 링크 제목만 추가하며 언론사명·URL·HTML 속성은 제외합니다. 기존 환경 설정도 설정 가져오기 기능으로 호환합니다.
4. 게시 시각이 아니라 응답 목록 위치로 전송합니다. 기본값은 최신 항목이 앞에 있는 응답을 뒤에서부터 처리하는 것입니다. 발견한 신규 일치 항목은 모두 대기열에 넣고 실행 한도에 도달하면 버리지 않고 다음 실행으로 넘깁니다.
5. YouTube 첫 예약 실행은 현재 항목을 초기 기준 상태로 저장합니다. 첫 수동 테스트는 최신 일치 항목 하나를 선택하고 나머지는 초기 기준 상태로 저장합니다. 이후 수동 테스트는 선택한 프로필당 최대 한 항목을 재개하되 그 항목의 모든 메시지·웹훅 대상을 처리합니다. 한 항목이 Discord 메시지 하나라는 뜻은 아닙니다.
6. 메인·모든 연관 기사의 원문 변환, 구형 링크 해독, 서명·타임스탬프 RPC, 성공 캐시, 실패 재시도 간격, 요청 한도, 429·접근 거부 시 추가 요청 중단을 유지합니다. URL 인코딩을 보존하고 실패 시 검증된 Google News 링크로 대체합니다. 비공식 RPC 변경이나 플랫폼별 접근 거부 가능성을 숨기지 않고 대체 건수를 표시합니다.
7. 모든 연관뉴스, 순서를 보존하는 메시지 분할, 언론사명 매핑, 미전송 메시지의 표시 보정, 안전한 미등록 언론사 수집을 유지합니다. 전송 완료 메시지는 바꾸지 않으며 수집 기록을 먼저 저장한 뒤 대기열을 확정합니다.
8. Discord 표시 이름은 `Google News`·`YouTube`, 아이콘은 프로젝트의 기존 URL로 유지합니다. 제목·백틱·빈 줄·썸네일·재생목록·상세 항목 양식을 유지합니다. RSS에 없는 재생시간·카테고리를 지어내거나 API 없이 표시하지 않습니다.
9. `ko`, `en`, `ja`, `zh-CN`, `zh-TW`, `es`, `pt-BR`, `fr`, `de`, `id`를 지원합니다. 국가·시간대 선택 우선순위와 한국·일본·중국·미국의 두 자리 날짜·시간 및 EST/EDT를 유지합니다. 필터와 표시는 같은 시간대를 사용하되 예약 시간대 설정을 바꾸지 않습니다. 실행 환경마다 다른 시간대 규칙을 그대로 믿지 않고 Python의 고정 시간대 데이터로 만든 경계·중복 시간 테스트와 두 버전을 비교합니다.
10. 전송 전 대기열 저장, 미전송 메시지·웹훅 위치 복구, 제한된 Discord 재시도, 버킷 소진 대기, 안전한 오류 코드, 기존의 좁은 Google 링크 오류 대응, 전송 결과를 확인할 수 없는 상태의 보고, 선택적 관리자 알림을 유지합니다.

### 저장과 재개 원칙

공통 상태에는 프로필 설정 버전, 수집 중인 페이지, 처리 완료·필터 제외 항목 식별값, 순서가 있는 전송 항목과 메시지·웹훅 대상, URL 캐시, 미등록 언론사 기록, 실행 통계, 스키마·가져오기 버전을 둡니다. 서비스·프로필·수집원·항목 ID·메시지 또는 대상 순번을 안정적인 키로 사용합니다. 대기열에는 웹훅 비밀값 대신 설정 이름을 저장합니다.

실행은 네트워크 요청 전 설정 검증 → 잠금 획득 → 중단된 저장 복구 → 미완료 수집 재개 → 완성된 수집 묶음 확정 → 가장 오래된 미전송 항목 처리 순서입니다. 새 항목이 미완료 이전 항목을 앞지를 수 없습니다. 다른 독립 프로필은 계속 처리할 수 있지만 일부 실패를 전체 성공으로 표시하지 않습니다.

API 페이지는 다음 페이지 토큰과 수집 회차 ID를 함께 저장합니다. 전체 수집이 끝나기 전에 성공 체크포인트를 옮기거나 불완전한 신규 묶음을 전송하지 않습니다. 저장한 토큰이 만료되면 이미 모은 식별값을 보존하고 중복을 대조하면서 다시 수집합니다. RSS도 처리 전에 응답 묶음을 저장합니다. 손상된 항목은 해당 수집을 실패시키며 더 최신 항목으로 건너뛰지 않습니다. 처음 가져오기 전에 RSS에서 사라진 항목은 복구할 수 없습니다.

D1은 대기열 확정과 상태 변경을 원자적으로 저장합니다. Sheets는 SQLite처럼 동작하지 않으므로 안정적인 키와 회차 ID가 있는 행을 추가하고 저장한 다음 완료 표식을 추가합니다. 읽는 쪽은 완료 표식이 없는 회차를 무시합니다. 복구 시 확정되지 않은 기록만 식별값으로 보충·정리하며 미전송 항목을 전송 완료로 바꾸지 않습니다. 같은 스크립트의 변경은 잠금으로 직렬화하고 상태 시트의 직접 편집은 지원하지 않습니다. `=`, `+`, `-`, `@`로 시작하는 외부 텍스트가 수식이 되지 않도록 문자로 저장합니다. 큰 응답은 여러 조각으로 저장하며 전체 피드가 한 셀에 들어간다고 가정하지 않습니다.

Discord 요청 전에 시도 식별값을 저장하고 `wait=true` 응답의 메시지 ID를 기록한 뒤 다음 순번으로 이동합니다. Discord가 받은 뒤 응답이나 저장이 실패하면 실제 전송 여부가 불명확할 수 있습니다. 이때 기존처럼 누락 방지를 우선해 재시도하고 중복 가능성을 보고합니다. 상태 저장 실패를 포함해 완전한 1회 전송을 보장한다고 표현하지 않습니다.

### 실행 한도와 예약

두 버전 모두 기본 확인 주기는 15분입니다. Cloudflare는 Google News `7,22,37,52 * * * *`, YouTube `11,26,41,56 * * * *` 분산 일정을 유지합니다. Apps Script는 공유 15분 트리거와 프로필 순환 처리를 사용하며 특정 분에 실행된다고 보장하지 않습니다. 30분·1시간·6시간·매일·매주·매월 예시에서 경과시간 간격과 달력 기준 실행을 구분합니다.

Apps Script는 실행당 6분 및 별도 일일 한도가 있습니다. 안전 여유를 둔 종료 시각과 조정 가능한 보수적 일일 작업 예산을 사용하고 대기시간도 실행시간으로 계산합니다. 미완료 페이지·전송 위치·다음 프로필 순서를 저장합니다. Cloudflare 역시 실행시간·요청·DB 사용량에 여유를 두고 한도 전에 남은 작업을 저장합니다. 남은 시간보다 긴 Retry-After는 오래 기다리지 않고 재시도 가능 시각으로 저장합니다. 밀린 작업과 할당량 오류를 숨기지 않습니다. 대량 작업은 여러 실행이 필요하거나 무료·계정 한도를 넘을 수 있음을 설명하되 기능 범위를 줄이지 않습니다.

### 이전과 보안

기존 SQLite 상태를 내보내는 로컬 Python 도구와 두 버전이 읽을 수 있는 버전형 가져오기 형식을 제공합니다. 전송 완료·초기 기준·필터 제외 식별값, 설정 식별값, 미완료 메시지·대상, 캐시, 언론사 수집 기록, 수집 체크포인트를 보존합니다. 상태 백업에는 기사 URL·메시지 내용이 들어갈 수 있으므로 공개 진단 자료와 구분합니다. 웹훅 URL·API 키·토큰은 넣지 않고 커밋하지 않으며 인증된 경로나 로컬 설치 과정으로만 가져옵니다.

기존 채널을 이전할 때는 이전 예약을 중지하고 실행 중 전송이 끝난 뒤 최종 상태를 내보냅니다. 새 버전에서 가져오기·검증·전송 없는 확인을 마친 다음 사용자가 선택한 실행기를 켭니다. 이전 상태는 복구용으로 보관합니다. 독립 설치끼리는 자동 중복 방지가 되지 않으므로 같은 채널은 한 실행기만 담당합니다. 되돌릴 때도 새 실행기의 최신 상태를 옮겨야 하며 예전 상태 그대로 다시 켜면 중복 전송될 수 있습니다.

로그·보고서·셀·예시·테스트·PR에 비밀값을 노출하지 않습니다. 서비스 요청 주소와 웹훅 호스트를 제한하고 원문 URL 검증만을 위해 임의의 언론사 페이지를 가져오지 않습니다. Discord 텍스트를 안전하게 처리하고 의도하지 않은 멘션을 막습니다. 기본 설치 검증은 전송하지 않으며 실제 수동 테스트는 명시적인 전송 동작으로 구분합니다.

### 구현 단위와 완료 증거

`runtimes/shared/`는 공통 처리와 상태 계약, `runtimes/cloudflare/`는 Worker·D1·설정, `runtimes/apps-script/`는 배포 묶음·manifest·메뉴·저장·서비스 연결, `runtimes/tests/`는 동작 비교와 플랫폼 테스트를 담당합니다. `tools/export-runtime-state.py`는 SQLite 이전 도구입니다. 루트 README 두 언어판은 설치 방식 선택을 안내하고 각 버전의 영어·한국어 설치 설명서로 연결합니다.

| 단계 | 결과물 | 필요한 검증 |
| --- | --- | --- |
| 공통 동작 | 파싱·필터·표시·식별값·URL 변환·전송 상태 처리 | Python 기준 양쪽 서비스 예시, 전체 연관뉴스, 10개 언어, DST, UTF-16 길이 제한 |
| Cloudflare | Worker·D1·설정·수동 및 전송 없는 실행 | 로컬 Worker/D1, 잠금 경쟁, 저장 실패, 한도·종료 후 재개, 인증 없는 수동 요청 거부 |
| Apps Script | 복사·설치 가능한 배포본·시트 메뉴·속성·트리거 | 빌드 결과와 서비스 모형 테스트, 저장 중단 복구, 잠금, 수식 주입 방지, 첫 테스트와 이후 주기 실행 |
| 이전·문서 | 버전형 내보내기·가져오기와 두 언어 설치 설명 | 기존 SQLite를 두 번 가져와도 행·전송 중복 없음, 미완료 위치 유지, 비밀값 미포함 |
| 운영 검증 | 별도 배포 승인 후 독립 설치 두 개 확인 | 실제 RSS 전송 없는 검사, 플랫폼 인증, 전송 승인 후 한 항목 실제 테스트, 메시지 ID·재개 위치 저장 |

각 단계는 실패 테스트부터 시작합니다. 3페이지·100개 이상 YouTube 영상, 50개 상세 조회, 필터 변경, 손상 피드, 긴 연관뉴스, Google 429, Discord 429·4xx·5xx·응답 불명, 전송 후 상태 기록 실패, 수동·예약 동시 실행을 포함합니다. 기존 Python 회귀 테스트도 그대로 실행합니다. 모형 테스트를 실제 배포 성공의 증거로 대신하지 않습니다. 주·월 시간을 기다리지 않고 고정 시계와 수동 비전송 검증을 사용합니다. 구현을 나눠 검토하더라도 전체 목표에서 어느 플랫폼도 제외하지 않습니다.

### 2026년 9월 9일 확인한 공식 제약

- [Apps Script 할당량](https://developers.google.com/apps-script/guides/services/quotas): 실행당 6분, 개인 계정 트리거 실행시간 하루 90분, Workspace 하루 6시간이며 한도 초과로 중단될 수 있습니다.
- [Apps Script 시간 트리거](https://developers.google.com/apps-script/reference/script/clock-trigger-builder): `everyMinutes`는 1·5·10·15·30을 받습니다. 정확한 분 위치는 보장하지 않습니다.
- [Workers 제한](https://developers.cloudflare.com/workers/platform/limits/): 예약 실행은 실제 경과시간 최대 15분이며 CPU·요청 제한도 적용됩니다.
- [D1 제한](https://developers.cloudflare.com/d1/platform/limits/): 요금제별 쿼리·저장 한도를 고려해 작업을 나눠야 하며 batch 안에서도 각 SQL 문의 한도가 적용됩니다.
