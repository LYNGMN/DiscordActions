# Independent Runtime Core Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` inline, followed by test-driven implementation. No subagent execution is requested. Steps use checkboxes for evidence tracking.

**Goal:** Implement the shared keyword and ordered delivery contracts used by both independent runtimes, without replacing the complete two-platform objective with this first checkpoint.

**Architecture:** Pure JavaScript modules isolate matching and queue transitions from platform storage and HTTP. Adapters persist snapshots under their platform lock, with compare-and-swap revisions; a delivery driver saves attempts before invoking Discord and saves acknowledgements before advancing.

**Tech Stack:** ES modules (`.mjs`), Node.js built-in `node:test` for development, existing Python 3.12 suite for regression. No new runtime package for this checkpoint.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-09-09-independent-runtimes-design.md`.
- Work only on `codex/feat/independent-runtimes`; preserve Python operating code and existing user files.
- Never log or persist webhook credentials in queue payloads; targets are secret names.
- Never sort by publication timestamp; default is reversed source-list position.
- No remote publication, cloud deployment, or Discord delivery during this checkpoint.
- Both Cloudflare and Apps Script remain required. A tested domain module is not a runnable platform.

## Full delivery map

1. Shared keyword matching and crash-recoverable ordered queue (this plan).
2. Feed parsers, source pagination/checkpoints, date filters/localization, URL resolver, publisher registry and complete message formatting, with Python parity fixtures.
3. Cloudflare entry points, D1 migration/storage/lease, authenticated manual jobs and deadline budgets, tested in the actual local Worker runtime.
4. Apps Script build, Sheets journal/locks, properties, menu and trigger, tested from the generated distribution with service doubles and then an authorized real installation.
5. SQLite export and bidirectional runtime state import/export, bilingual installation guides and CI for both distributions.
6. Full review, approved publication/deployment, no-send live verification, separately approved one-item Discord tests on each independent installation, final cleanup after merge verification.

Stages 2–6 get their own detailed plans using the interfaces established here. They are outstanding requirements, not optional enhancements.

## Task 1 — Keyword contract

**Files:** create `runtimes/shared/keyword.mjs`; test `runtimes/tests/keyword.test.mjs`.

**Interfaces:** `compileKeyword(query, aliases = '')` returns `{expression, terms, matches(text)}`. `matchItem({title, description, relatedTitles}, compiled, {service, scope})` returns a boolean. For Google News, strip only the final publisher suffix of the main title and inspect separate related headlines in description mode. For YouTube inspect the actual description. HTML parsing belongs to the source parser; `relatedTitles` contains parsed link text only.

- [x] Write executable fixtures for precedence, implicit AND, unary negatives, quoted phrases, Asian substrings, ASCII boundaries, full-width normalization, aliases, Google date operators, malformed syntax, publisher-only and URL-only matches, and YouTube descriptions.
- [x] Run `node --test runtimes/tests/keyword.test.mjs`; confirm missing implementation fails.
- [x] Implement recursive descent `OR -> AND -> NOT -> primary`, reject incomplete input and cap expression size/nesting. Normalize text with NFKC and lowercase. Match ASCII alphanumeric term edges with ASCII boundaries; preserve substrings for Asian text.
- [x] Re-run the same command and verify all assertions. Example contract:

```javascript
const keyword = compileKeyword('아이유 when:3d', 'IU | "Lee Ji-eun"');
assert.equal(keyword.matches('premium sound'), false);
assert.equal(keyword.matches('IU concert'), true);
assert.equal(matchItem({title: '다른 사람 소식 - 신문', relatedTitles: ['아이유 공연']}, keyword,
  {service: 'google-news', scope: 'title'}), false);
```

## Task 2 — Queue transitions

**Files:** create `runtimes/shared/delivery-state.mjs`; test `runtimes/tests/delivery-state.test.mjs`.

**Interfaces:** `createDeliveryState(profileId)`, `enqueueBatch(state, items, options)`, `nextMessage(state, now)`, `beginAttempt(state, messageKey, attemptId, now)`, `acknowledge(state, messageKey, attemptId, messageId)`, `failAttempt(state, messageKey, attemptId, failure)`, `recoverAttempts(state)`.

Each mutation returns a new JSON-serializable state with an incremented revision, leaving the input unchanged. IDs and positions are deterministic; messages contain only content and a target secret name. All messages of the oldest unfinished item precede later items. An item cannot be acknowledged without its current durable attempt identity. `recoverAttempts` marks an interrupted in-flight attempt ambiguous and pending; it cannot infer that Discord rejected it.

- [x] Write fixtures for reversed source order despite conflicting dates, all-or-nothing validation, duplicate discovery, whole-item manual limit, multi-target failure and resume, stale acknowledgements, invalid message IDs, attempt recovery, no mutation of saved inputs and UTF-16 length validation.
- [x] Run `node --test runtimes/tests/delivery-state.test.mjs`; confirm red.
- [x] Implement pure transitions, pending/in-flight/sent statuses, retry timestamps and numeric Discord message-ID validation. Reject empty/oversized payloads before a batch changes state. Keep duplicate IDs in an existing queue immutable.
- [x] Run the same tests; then run `node --test runtimes/tests/*.test.mjs`.

## Task 3 — Persist-before-send driver

**Files:** create `runtimes/shared/delivery-runner.mjs`; test `runtimes/tests/delivery-runner.test.mjs`.

**Interfaces:** `drainDelivery({store, send, now, deadline, maxItems, newAttemptId})`. `store.load()` returns state. `store.save(nextState, expectedRevision)` is durable compare-and-swap and throws on failure. `send({content,target,attemptId})` returns `{messageId}` or throws a sanitized failure with `code`, `retryAt`, and `ambiguous`. Platform adapters resolve secret names only at this boundary.

- [x] Write a test store in the test file that persists detached JSON snapshots and can reject a chosen save; this is the storage boundary, not a production in-memory adapter.
- [x] Test that no request occurs if attempt persistence fails, acknowledgements are durable before newer sends, lost acknowledgement is recovered as ambiguous, existing sent messages never repeat, deadline and manual limit preserve pending state, and storage conflicts stop without sending.
- [x] Run `node --test runtimes/tests/delivery-runner.test.mjs`; confirm red.
- [x] Implement load/recover/save, oldest pending selection, durable attempt, external send, durable acknowledgement/failure. Return `completedItems`, `pendingItems`, `ambiguousAttempts`, and a stop reason; do not swallow storage exceptions or expose exception text.
- [x] Re-run all Node tests and the unchanged Python suite.

## Checkpoint verification

- [x] `node --test runtimes/tests/*.test.mjs` — 28 passed on September 9, 2026.
- [x] `PYTHONPYCACHEPREFIX=/private/tmp/discordactions-independent-pycache /private/tmp/discordactions-independent-runtimes-venv/bin/python -m unittest discover -s .github/tests -q` — 313 passed on September 9, 2026.
- [x] `git diff --check` and staged new-file review; scan credentials without printing matches. The webhook-shaped string in the rejection test is an intentionally invalid fixture, not a credential.
- [x] Commit each independently verified responsibility. Keyword matching and ordered delivery are separate local commits. No publication or deployment occurred; runtime stages 2–6 remain outstanding.

## 한국어 진행 안내

첫 구현은 공통 키워드 판정과 전송 순서·재개 계약입니다. 테스트를 먼저 실패시킨 뒤 구현하고, 기존 Python 테스트도 다시 실행합니다. 실제 요청 전에 전송 시도를 저장하고 Discord 성공 응답을 기록한 다음에만 다음 메시지로 넘어갑니다. 상태 저장 실패·실행 중단·재시도에서도 순서를 유지하며, 성공 여부를 알 수 없는 경우는 중복 가능성을 숨기지 않습니다.

이 단계 다음에는 수집·필터·표시·원문 변환, Cloudflare 연결, Apps Script 연결, 상태 이전·문서, 승인된 배포·운영 검증이 남습니다. 공통 코드 테스트 통과는 두 플랫폼의 구현 완료나 실제 배포 성공을 뜻하지 않습니다.
