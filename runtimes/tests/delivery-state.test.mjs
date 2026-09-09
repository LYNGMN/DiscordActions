import test from 'node:test';
import assert from 'node:assert/strict';
import {createDeliveryState, enqueueBatch, nextMessage, beginAttempt, acknowledge, failAttempt, recoverAttempts} from '../shared/delivery-state.mjs';

const item = (id, targets = ['DISCORD_WEBHOOK']) => ({id, pubDate: id === 'old' ? '2030-01-01' : '2020-01-01',
  messages: targets.map(target => ({target, content: `${id} content`}))});
const queued = () => enqueueBatch(createDeliveryState('top_kr'), [item('new'), item('old')]);

test('queue order follows source position, ignores dates, and leaves input unchanged', () => {
  const state = createDeliveryState('top_kr');
  const items = [item('new'), item('old')];
  const result = enqueueBatch(state, items);
  assert.deepEqual(result.items.map(i => i.id), ['old', 'new']);
  assert.equal(nextMessage(result, 0).itemId, 'old');
  assert.equal(state.items.length, 0);
  assert.equal(result.revision, state.revision + 1);
  assert.deepEqual(items.map(i => i.id), ['new', 'old']);
  const newest = enqueueBatch(state, items, {order: 'feed_newest_first'});
  assert.equal(nextMessage(newest, 0).itemId, 'new');
});

test('all malformed batch input is rejected before any mutation', () => {
  const state = createDeliveryState('profile');
  for (const broken of [{id: '', messages: []}, item('x', ['https://discord.com/api/webhooks/1/private']),
    {id: 'x', messages: [{target: 'SECRET', content: '😀'.repeat(1001)}]}, {id: 'x', messages: []}]) {
    assert.throws(() => enqueueBatch(state, [item('valid'), broken]), /invalid/);
    assert.equal(state.items.length, 0);
  }
  assert.throws(() => enqueueBatch(state, [item('x')], {order: 'pubDate'}), /invalid/);
  assert.throws(() => createDeliveryState(''), /invalid/);
});

test('rediscovery does not overwrite pending or sent content', () => {
  let state = queued();
  const first = nextMessage(state, 0);
  state = beginAttempt(state, first.key, 'attempt-1', 0);
  state = acknowledge(state, first.key, 'attempt-1', '123456');
  const result = enqueueBatch(state, [item('old', ['CHANGED']), item('new', ['CHANGED']), item('later')]);
  assert.equal(result.items.length, 3);
  assert.equal(result.items[0].messages[0].target, 'DISCORD_WEBHOOK');
  assert.equal(result.items[1].messages[0].target, 'DISCORD_WEBHOOK');
  assert.equal(result.items[0].messages[0].messageId, '123456');
  assert.equal(nextMessage(result, 0).itemId, 'new');
});

test('all messages and targets of one item precede later items', () => {
  let state = enqueueBatch(createDeliveryState('youtube'), [item('new'), item('old', ['BASIC', 'DETAIL'])]);
  const first = nextMessage(state, 0);
  state = beginAttempt(state, first.key, 'a1', 0);
  assert.equal(nextMessage(state, 0), null, 'in-flight is not bypassed');
  state = acknowledge(state, first.key, 'a1', '1');
  assert.equal(nextMessage(state, 0).target, 'DETAIL');
  const detail = nextMessage(state, 0);
  state = beginAttempt(state, detail.key, 'a2', 0);
  state = failAttempt(state, detail.key, 'a2', {code: 'rate_limited', retryAt: 1000, ambiguous: false});
  assert.equal(nextMessage(state, 999), null, 'a delayed old item blocks newer ones');
  assert.equal(nextMessage(state, 1000).target, 'DETAIL');
  state = beginAttempt(state, detail.key, 'a3', 1000);
  state = acknowledge(state, detail.key, 'a3', '2');
  assert.equal(nextMessage(state, 1000).itemId, 'new');
});

test('stale acknowledgements and out-of-order attempts fail', () => {
  const original = queued();
  const first = nextMessage(original, 0);
  let state = beginAttempt(original, first.key, 'current', 0);
  assert.throws(() => acknowledge(state, first.key, 'stale', '1'), /attempt/);
  assert.throws(() => acknowledge(state, first.key, 'current', 'not-an-id'), /message id/);
  assert.throws(() => beginAttempt(state, first.key, 'second', 0), /order/);
  assert.throws(() => beginAttempt(original, JSON.stringify(['top_kr', 'new', 0]), 'a2', 0), /order/);
  assert.equal(original.items[0].messages[0].status, 'pending');
});

test('crashed attempts become ambiguous pending work without resending completed messages', () => {
  let state = queued();
  const first = nextMessage(state, 0);
  state = beginAttempt(state, first.key, 'crash', 0);
  const recovered = recoverAttempts(JSON.parse(JSON.stringify(state)));
  assert.equal(recovered.items[0].messages[0].status, 'pending');
  assert.equal(recovered.items[0].messages[0].ambiguousAttempts, 1);
  assert.equal(nextMessage(recovered, 0).key, first.key);
  assert.deepEqual(recoverAttempts(recovered), recovered, 'repeated recovery does not recount');
});

test('unsafe error text is not persisted', () => {
  let state = queued();
  const first = nextMessage(state, 0);
  state = beginAttempt(state, first.key, 'a1', 0);
  state = failAttempt(state, first.key, 'a1', {code: 'https://secret.example/token', retryAt: 0, ambiguous: true});
  assert.equal(state.items[0].messages[0].lastError, 'delivery_failed');
  assert.equal(JSON.stringify(state).includes('secret.example'), false);
  assert.equal(state.items[0].messages[0].ambiguousAttempts, 1);
});

test('a retry must not reuse an attempt identity that can accept a stale acknowledgement', () => {
  let state = queued();
  const first = nextMessage(state, 0);
  state = beginAttempt(state, first.key, 'old-attempt', 0);
  state = recoverAttempts(state);
  assert.throws(() => beginAttempt(state, first.key, 'old-attempt', 0), /attempt/);
  assert.throws(() => beginAttempt(state, first.key, 'https://secret.example/token', 0), /attempt/);
});
