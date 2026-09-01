# English

## Contribution workflow

Thank you for helping improve DiscordActions. Keep each change small enough to review, test, and merge independently.

### Issue and Pull Request responsibilities

An Issue records work to be done: the problem, desired outcome, impact, acceptance criteria, and any decisions still needed.

A Pull Request records the implemented change: the linked Issue, actual file changes, user impact, and fresh verification evidence. A Pull Request body is not a backlog. Put a future feature or unrelated improvement in a separate Issue instead of listing it in the current Pull Request.

Open an Issue before starting any non-trivial feature, behavior change, bug investigation, or multi-step task. A tiny self-contained correction, such as a typo or an uncontroversial documentation fix, may use a Pull Request without an Issue when it needs no discussion or tracking.

For a request with several independently reviewable outcomes, create an umbrella Issue and link smaller feature-sized Issues. Create a Branch only when implementation starts. An Issue by itself does not create a Branch.

### Required sequence

1. Search open and closed Issues for existing work.
2. Create or select one Issue with observable acceptance criteria.
3. Create one purpose-specific Branch for the implementation.
4. Save one-intention Commit checkpoints and run fresh tests.
5. Open a Draft Pull Request and link the Issue with `Closes #NUMBER`.
6. Keep the Pull Request Draft while code, tests, scope, and operational risk are reviewed.
7. After exact-state authorization and required checks, use Squash Merge.
8. Verify the default Branch and linked Issue before considering the work complete.
9. Remove the merged Branch and Worktree only after their recovery Commit is verified and cleanup is separately approved.

Never push directly to `main`. Never use Force Push.

### Language and writing

- Write the Pull Request title in English.
- Write the complete English Issue or Pull Request record first, then the complete Korean record below.
- Keep facts, commands, links, examples, and verification results equivalent in both languages.
- Use real Markdown line breaks. Do not paste escaped `\n` text.
- Do not include secrets, webhook URLs, tokens, cookies, private keys, or URL queries containing credentials.
- Re-open the published Issue or Pull Request and verify the rendered title and body.

### Issue content

A feature Issue must explain the request, current problem, expected result, user impact, and acceptance criteria. A bug Issue must also include reproducible conditions, actual behavior, and expected behavior. Use the repository Issue Forms so required information is not omitted.

### Pull Request content

Every Pull Request must contain:

- Purpose
- Related Issue, normally `Closes #NUMBER`
- Changes actually present in the diff
- User impact
- Fresh local, CI, and operational verification
- Operational notes only when reviewers or operators need them

Do not add a mandatory `Not included` list. If a scope boundary is essential to prevent a concrete misunderstanding, explain it briefly in Operational notes. Track separately planned work in its own Issue.

# 한국어

## 기여 절차

DiscordActions 개선에 참여해 주셔서 감사합니다. 각 변경은 독립적으로 검토하고 테스트하고 병합할 수 있는 크기로 유지합니다.

### Issue와 Pull Request의 역할

Issue는 앞으로 해야 할 일을 기록합니다. 문제, 원하는 결과, 사용자 영향, 완료 조건, 아직 결정해야 할 내용을 Issue에서 관리합니다.

Pull Request는 실제로 구현한 변경을 기록합니다. 연결된 Issue, 실제 파일 변경, 사용자 영향, 새로 확인한 검증 결과를 작성합니다. Pull Request 본문은 작업 목록이 아닙니다. 앞으로 구현할 기능이나 관계없는 개선 사항은 현재 Pull Request에 나열하지 않고 별도 Issue로 관리합니다.

작고 독립적인 수정이 아닌 기능 추가, 동작 변경, 원인 조사가 필요한 오류, 여러 단계의 작업은 구현 전에 Issue를 만듭니다. 오탈자나 논의가 필요 없는 간단한 문서 수정처럼 추적할 필요가 없는 변경은 Issue 없이 Pull Request를 만들 수 있습니다.

한 요청에 독립적으로 검토할 수 있는 결과가 여러 개라면 상위 Issue를 만들고 기능 단위의 작은 Issue를 연결합니다. 구현을 시작할 때만 Branch를 만듭니다. Issue만 만들어 둔다고 Branch가 생기지는 않습니다.

### 필수 진행 순서

1. 열린 Issue와 종료된 Issue에서 같은 작업이 있는지 검색합니다.
2. 관찰 가능한 완료 조건을 가진 Issue 하나를 만들거나 선택합니다.
3. 구현 목적 하나만 담는 Branch를 만듭니다.
4. 한 가지 의도의 Commit 체크포인트를 저장하고 새 테스트를 실행합니다.
5. Draft Pull Request를 만들고 `Closes #번호`로 Issue를 연결합니다.
6. 코드, 테스트, 범위, 운영 위험 검토가 끝날 때까지 Draft 상태를 유지합니다.
7. 정확한 상태에 대한 승인과 필수 검사가 끝나면 Squash Merge를 사용합니다.
8. 기본 Branch와 연결된 Issue를 확인한 뒤에만 작업 완료로 판단합니다.
9. 병합된 Branch와 Worktree는 복구할 Commit을 확인하고 별도 정리 승인을 받은 뒤 제거합니다.

`main`에 직접 Push하지 않습니다. Force Push는 사용하지 않습니다.

### 언어와 작성 방식

- Pull Request 제목은 영어로 작성합니다.
- Issue와 Pull Request는 영어 전체 기록을 먼저 작성하고 그 아래에 완전한 한국어 기록을 작성합니다.
- 사실, 명령어, 링크, 예시, 검증 결과는 두 언어에서 같은 의미로 유지합니다.
- 실제 Markdown 줄바꿈을 사용하고 이스케이프된 `\n` 문자를 붙여 넣지 않습니다.
- Secret, Webhook URL, Token, Cookie, Private Key, 인증정보가 포함된 URL Query를 기록하지 않습니다.
- 게시한 Issue나 Pull Request를 다시 열어 제목과 본문이 올바르게 표시되는지 확인합니다.

### Issue 작성 내용

기능 Issue에는 요청 내용, 현재 문제, 원하는 결과, 사용자 영향, 완료 조건을 작성합니다. 오류 Issue에는 재현 조건, 실제 동작, 기대 동작도 작성합니다. 필수 정보가 빠지지 않도록 저장소의 Issue Form을 사용합니다.

### Pull Request 작성 내용

모든 Pull Request에는 다음 내용을 작성합니다.

- 목적
- 관련 Issue, 일반적으로 `Closes #번호`
- 실제 Diff에 포함된 변경 내용
- 사용자 영향
- 새로 실행한 로컬 테스트, CI, 운영 검증
- 검토자나 운영자가 알아야 할 내용이 있을 때만 운영 참고사항

`포함하지 않은 내용`을 필수 목록으로 만들지 않습니다. 구체적인 오해를 막기 위해 범위를 설명해야 할 때만 운영 참고사항에 짧게 작성합니다. 별도로 계획한 작업은 별도 Issue에서 관리합니다.
