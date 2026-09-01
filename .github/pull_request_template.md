<!--
The Pull Request title must be written in English.
Write the complete English record first, then the complete Korean record below.
Use real Markdown line breaks, not escaped newline text.
The Pull Request body records this change; future work belongs in a separate Issue.
Re-open the published Pull Request and verify the remote title and rendered body.
-->

# English

## Purpose

<!-- Explain the user-facing problem and intended outcome. -->

## Related issue

<!-- Use `Closes #123`. For a tiny self-contained correction that needs no tracking, explain why an Issue is not required. -->

## Changes

<!-- List only changes that are present in this Pull Request's diff. -->

## User impact

<!-- Explain what users or operators will notice after Merge. -->

## Verification

<!-- Record fresh tests, CI, and operational checks. State clearly when a live test was not run. Never include secrets. -->

## Operational notes

<!-- Optional. Remove this section when no reviewer or operator action is needed. Track future work in a separate Issue. -->

<details>
<summary>Review and Merge checklists</summary>

### Review Checklist

- [ ] The Pull Request remains Draft until exact-state final authorization.
- [ ] Requirements, Acceptance Criteria, and scope were reviewed on this exact Head SHA.
- [ ] Quality, security, tests, and operational risk were reviewed.
- [ ] The exact Pull Request, Base Branch, Head Branch, Head SHA, current checks, unresolved reviews, required reviews, mergeability, method, and expected Squash title were shown before final authorization.
- [ ] After final authorization, the Pull Request was first changed from Draft to Ready for review.
- [ ] After Ready for review, required Code Owner reviews and checks passed, and the unchanged Head, base, title, method, conflicts, mergeability, and enabled Squash Merge were re-checked immediately before Merge.
- [ ] New changes received new tests and Review; an earlier final authorization was not reused.

### Merge Checklist

- [ ] One exact-state final authorization first permits Ready for review and, only after required reviews and checks pass, permits Squash Merge.
- [ ] A new Commit, base/title/method change, failing check, conflict, or blocking review stops Merge and invalidates the existing final authorization; corrective development returns the Pull Request to Draft before retest and re-review.
- [ ] The expected Squash Commit title matches the approved Pull Request title, and Squash Merge is the enabled method.
- [ ] After Merge, the default-Branch Squash SHA, Pull Request merged state, and linked Issue closure were verified.

</details>

---

# 한국어

## 목적

<!-- 사용자가 겪는 문제와 의도한 결과를 한국어로 적으세요. -->

## 관련 Issue

<!-- `Closes #123`을 사용하세요. 추적할 필요가 없는 작고 독립적인 수정이라면 Issue가 필요하지 않은 이유를 설명하세요. -->

## 변경 내용

<!-- 이 Pull Request의 Diff에 실제로 포함된 변경만 나열하세요. -->

## 사용자 영향

<!-- Merge 후 사용자나 운영자가 무엇을 체감하는지 설명하세요. -->

## 검증

<!-- 새로 실행한 테스트, CI, 운영 확인을 작성하세요. 실제 운영 테스트를 하지 않았다면 명확히 밝히세요. 민감정보는 적지 마세요. -->

## 운영 참고사항

<!-- 선택 항목입니다. 검토자나 운영자의 조치가 필요하지 않으면 이 항목을 삭제하세요. 후속 작업은 별도 Issue로 관리합니다. -->

<details>
<summary>리뷰와 병합 체크리스트</summary>

### 리뷰 체크리스트

- [ ] Pull Request는 정확한 상태에 대한 최종 승인 전까지 Draft를 유지합니다.
- [ ] 요구사항, Acceptance Criteria, 범위를 이 정확한 Head SHA에서 Review했습니다.
- [ ] 품질, 보안, 테스트, 운영 위험을 Review했습니다.
- [ ] 최종 승인 전에 정확한 Pull Request, Base Branch, Head Branch, Head SHA, 현재 checks, 미해결 reviews, 필수 reviews, 병합 가능 여부, 병합 방식, 예상 Squash title을 보여 주었습니다.
- [ ] 최종 승인 뒤 Pull Request를 먼저 Draft에서 Ready for review로 전환했습니다.
- [ ] Ready for review 전환 뒤 필수 Code Owner reviews와 checks가 통과했으며, Merge 직전에 Head, base, title, method가 그대로인지, conflict, 병합 가능 여부, Squash Merge 허용 상태를 다시 확인했습니다.
- [ ] 새 변경에는 새 테스트와 Review를 수행했으며 이전 최종 승인을 재사용하지 않았습니다.

### 병합 체크리스트

- [ ] 정확한 상태에 대한 최종 승인 한 번은 먼저 Ready for review를 허가하고, 필수 reviews와 checks가 통과한 뒤에만 Squash Merge를 허가합니다.
- [ ] 새 Commit, base/title/method 변경, 실패한 check, conflict, blocking review가 생기면 Merge를 중단하고 기존 최종 승인을 무효화하며, 수정 개발은 retest와 re-review 전에 Pull Request를 Draft로 되돌립니다.
- [ ] 예상 Squash Commit 제목은 승인된 Pull Request 제목과 일치하며 Squash Merge가 허용된 병합 방식입니다.
- [ ] Merge 뒤 기본 Branch의 Squash SHA, Pull Request merged 상태, 연결된 Issue 종료 여부를 확인했습니다.

</details>
