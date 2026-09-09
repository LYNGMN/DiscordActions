import test from 'node:test';
import assert from 'node:assert/strict';
import {compileKeyword, matchItem} from '../shared/keyword.mjs';

test('main title is the default; related headlines are opt-in', () => {
  const compiled = compileKeyword('아이유 when:3d');
  const item = {title: '다른 연예인의 근황 - 신문', relatedTitles: ['아이유 공연 소식']};
  assert.equal(matchItem(item, compiled, {service: 'google-news'}), false);
  assert.equal(matchItem(item, compiled, {service: 'google-news', scope: 'title_or_description'}), true);
});

test('Google publisher suffix and raw description are not keyword inputs', () => {
  const item = {title: '일반 소식 - 아이유', description: '<a href="https://example.org/아이유">기사</a><font>아이유</font>', relatedTitles: ['일반 소식']};
  assert.equal(matchItem(item, compileKeyword('아이유'), {service: 'google-news', scope: 'title_or_description'}), false);
});

test('YouTube uses actual description and retains the complete title', () => {
  assert.equal(matchItem({title: '일반 영상', description: '아이유 공연 영상'}, compileKeyword('아이유'),
    {service: 'youtube', scope: 'title_or_description'}), true);
  assert.equal(matchItem({title: '공연 - IU'}, compileKeyword('IU'), {service: 'youtube'}), true);
});

test('aliases, normalized Asian substrings and ASCII boundaries', () => {
  const compiled = compileKeyword('아이유', 'IU | "Lee Ji-eun" | 이지은');
  for (const text of ['아이유의 공연', 'IU concert', 'ＩＵ concert', 'Lee Ji-eun performs', '이지은의 소식']) {
    assert.equal(compiled.matches(text), true, text);
  }
  for (const text of ['premium', 'IUsers', 'Lee Ji-eunice', '']) assert.equal(compiled.matches(text), false, text);
  assert.equal(compileKeyword('東京').matches('東京都のニュース'), true);
  assert.equal(compileKeyword('中国').matches('中国新闻'), true);
  assert.equal(compileKeyword('123').matches('1234'), false);
});

test('NOT, implicit AND and OR have explicit precedence', () => {
  const compiled = compileKeyword('AI OR robot AND NOT rumor');
  assert.equal(compiled.matches('AI rumor'), true);
  assert.equal(compiled.matches('robot news'), true);
  assert.equal(compiled.matches('robot rumor'), false);
  for (const expression of ['(AI | robot) !rumor', '(AI OR robot) -rumor', '(AI | robot) & NOT rumor']) {
    assert.equal(compileKeyword(expression).matches('AI rumor'), false);
    assert.equal(compileKeyword(expression).matches('robot news'), true);
  }
  assert.equal(compileKeyword('AI robot').matches('AI only'), false);
  assert.equal(compileKeyword('AI robot').matches('robot and AI'), true);
});

test('date operators are removed outside quotes only; hyphenated terms remain intact', () => {
  assert.equal(compileKeyword('no-code when:3d after:2026-01-01 before:2026-12-31').matches('no-code tools'), true);
  assert.equal(compileKeyword('"when:3d"').matches('when:3d'), true);
  assert.equal(compileKeyword('"Lee   Ji-eun"').matches('Lee Ji-eun'), true);
});

test('malformed expressions fail rather than broadening the match', () => {
  for (const expression of ['', 'when:3d', 'AI OR', 'AND AI', 'AI || robot', '()', '(AI', 'AI)', '"AI', '!', 'AI & & robot']) {
    assert.throws(() => compileKeyword(expression), {message: /invalid keyword/}, expression);
  }
  assert.throws(() => compileKeyword('AI', 'OR'), /invalid keyword/);
  assert.throws(() => compileKeyword('('.repeat(70) + 'AI' + ')'.repeat(70)), /invalid keyword/);
  assert.throws(() => compileKeyword('x'.repeat(5000)), /invalid keyword/);
});

test('unknown service and scope fail closed', () => {
  assert.throws(() => matchItem({title: 'AI'}, compileKeyword('AI'), {service: 'rss'}), /invalid service/);
  assert.throws(() => matchItem({title: 'AI'}, compileKeyword('AI'), {service: 'youtube', scope: 'all'}), /invalid scope/);
});
