# Google News Country-Specific Date and Time Format Design

## Goal

Display every Google News publication time on one Discord line in the date and
time convention selected by the Google News country profile. The date line does
not repeat a country name or flag because that context already appears in the
message header.

## Required Formats

The formatter uses the profile country and its configured IANA time zone.
Month, day, hour, minute, and second values that are numeric are always padded to
two digits.

```text
Korea (Asia/Seoul)
📅 2026년 08월 31일 오후 05:41:00 (KST)

Japan (Asia/Tokyo)
📅 2026年09月01日 13:51:11 (JST)

China (Asia/Shanghai)
📅 2026年09月01日 09:50:00 (CST)

United States (America/New_York)
📅 August 31, 2026, 05:41:00 PM (EDT)
```

- Korea uses a 12-hour clock with `오전` or `오후`.
- Japan and China use a 24-hour clock.
- The United States uses a full English month name and a 12-hour clock with
  `AM` or `PM`.
- `America/New_York` determines `EST` or `EDT` from the actual US daylight
  saving boundary. No fixed-offset or manually maintained transition table is
  used.
- Seconds and the active time-zone abbreviation are always shown.
- The output contains no newline.

## Chosen Implementation

Add one Google-News-specific formatter to the shared feed localization module.
The three Google News scripts—Top, Keyword, and Topic—will call it with the
profile country and time zone. The existing general formatter remains unchanged
so YouTube output does not change.

The country selects the display convention, while the IANA time zone performs
the actual time conversion. Explicit string assembly is used for these four
formats because locale-dependent long formats do not guarantee the requested
zero padding, punctuation, or 12/24-hour rules.

Profiles for other countries keep the existing localized date-time output. This
preserves current behavior outside the four explicitly specified countries.

## Error Handling and Compatibility

- Invalid or unknown time zones continue to fail before Discord delivery.
- Existing aware and naive input handling in the localization module is reused.
- Google News message headers, source links, related-news handling, delivery
  queues, schedules, database data, and webhook branding are unchanged.
- YouTube date and time formatting is explicitly outside this change.

## Verification

- Start with failing unit tests for all four exact output formats.
- Test one-digit month, day, and hour values to prove zero padding.
- Test Korean morning, afternoon, midnight, and noon behavior.
- Test a US winter instant that renders `EST` and a summer instant that renders
  `EDT`.
- Test that every result is exactly one line and does not add a country name or
  flag.
- Test that Top, Keyword, and Topic use the shared Google News formatter.
- Test that the existing YouTube localized date output is unchanged.
- Run the complete Python unit suite, `py_compile`, structured-file checks,
  `git diff --check`, and the changed-file credential scan before publication.
- Do not send live Discord messages as part of implementation verification.

---

# Google 뉴스 국가별 날짜·시간 표시 설계

## 목표

Google 뉴스의 게시 시각을 해당 프로필에서 선택한 국가의 표기 방식에
맞춰 Discord 한 줄에 표시합니다. 국가와 국기는 메시지 제목에 이미
나오므로 날짜 줄에는 다시 넣지 않습니다.

## 표시 형식

프로필의 국가가 표시 방식을 정하고, 프로필에 설정된 IANA 시간대가 실제
시각 변환을 담당합니다. 숫자로 표시하는 월, 일, 시, 분, 초는 항상 두
자리로 맞춥니다.

```text
한국 (Asia/Seoul)
📅 2026년 08월 31일 오후 05:41:00 (KST)

일본 (Asia/Tokyo)
📅 2026年09月01日 13:51:11 (JST)

중국 (Asia/Shanghai)
📅 2026年09月01日 09:50:00 (CST)

미국 (America/New_York)
📅 August 31, 2026, 05:41:00 PM (EDT)
```

- 한국은 `오전`·`오후`가 있는 12시간제를 사용합니다.
- 일본과 중국은 24시간제를 사용합니다.
- 미국은 영어 월 전체 이름과 `AM`·`PM`이 있는 12시간제를 사용합니다.
- 미국은 `America/New_York` 시간대를 사용해 실제 서머타임 전환일에 따라
  `EST`와 `EDT`를 자동으로 선택합니다. 고정 UTC 오프셋이나 수동 전환일
  표는 사용하지 않습니다.
- 초와 현재 시간대 약자는 항상 표시합니다.
- 출력 문자열에는 줄바꿈을 넣지 않습니다.

## 구현 방식

공통 피드 현지화 모듈에 Google 뉴스 전용 날짜·시간 함수 하나를
추가합니다. Google 뉴스 Top, Keyword, Topic 스크립트가 이 함수를 함께
사용하며 프로필 국가와 시간대를 전달합니다. 기존 공통 날짜 함수는
그대로 유지하여 YouTube 표시에는 영향을 주지 않습니다.

국가는 표시 규칙을 선택하고 IANA 시간대는 실제 시각을 변환합니다. 기존
긴 날짜 현지화 형식은 요청한 앞자리 0, 쉼표, 12·24시간제 규칙을 정확히
보장하지 못하므로 네 국가 형식은 명시적으로 조합합니다.

이번에 형식을 지정하지 않은 다른 국가는 기존 현지화 날짜·시간 표시를
유지합니다. 따라서 네 국가 밖의 기존 동작은 바뀌지 않습니다.

## 오류 처리와 호환성

- 잘못되거나 알 수 없는 시간대는 기존과 같이 Discord 전송 전에
  실행을 중단합니다.
- 현지화 모듈의 기존 입력 시각 처리 방식을 재사용합니다.
- Google 뉴스 제목, 원문 링크, 연관뉴스, 전송 대기열, 일정, 데이터베이스,
  웹훅 이름과 아이콘은 변경하지 않습니다.
- YouTube 날짜·시간 표시는 이번 변경 범위에 포함하지 않습니다.

## 검증

- 네 국가의 정확한 출력 문자열을 먼저 실패 테스트로 작성합니다.
- 한 자리 월·일·시를 사용해 앞자리 0이 붙는지 확인합니다.
- 한국의 오전·오후·자정·정오를 확인합니다.
- 미국 겨울 시각은 `EST`, 여름 시각은 `EDT`로 표시되는지 확인합니다.
- 모든 결과가 한 줄이며 국가명이나 국기가 추가되지 않는지 확인합니다.
- Top, Keyword, Topic이 공통 Google 뉴스 전용 함수를 사용하는지
  확인합니다.
- 기존 YouTube 현지화 날짜 출력이 바뀌지 않는지 확인합니다.
- 전체 Python 단위 테스트, `py_compile`, 구조화 파일 검사,
  `git diff --check`, 변경 파일의 민감정보 검사를 게시 전에 실행합니다.
- 구현 검증 과정에서는 실제 Discord 메시지를 보내지 않습니다.
