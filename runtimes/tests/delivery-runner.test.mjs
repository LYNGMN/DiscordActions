import test from 'node:test';
import assert from 'node:assert/strict';
import {createDeliveryState, enqueueBatch} from '../shared/delivery-state.mjs';
import {drainDelivery} from '../shared/delivery-runner.mjs';

const copy = value => JSON.parse(JSON.stringify(value));
const queue = () => enqueueBatch(createDeliveryState('profile'), [
  {id: 'new', messages: [{target: 'BASIC', content: 'new'}]},
  {id: 'old', messages: [{target: 'BASIC', content: 'old basic'}, {target: 'DETAIL', content: 'old detail'}]},
]);

// Storage-boundary double: writes are atomic and detached, and revisions are enforced.
function fixture() {
  let saved = queue();
  let saves = 0;
  let sequence = 0;
  const calls = [];
  const store = {
    failSave: 0,
    load: async () => copy(saved),
    save: async (state, revision) => {
      saves++;
      if (saves === store.failSave) throw new Error('storage unavailable');
      assert.equal(saved.revision, revision, 'compare-and-swap');
      saved = copy(state);
    },
  };
  const options = {store, now: () => 0, deadline: 1000, newAttemptId: () => `attempt-${++sequence}`,
    send: async message => {
      const durable = saved.items.flatMap(i => i.messages).find(m => m.attemptId === message.attemptId);
      assert.equal(durable?.status, 'in_flight', 'attempt is persisted before HTTP');
      calls.push(message.content);
      return {messageId: String(calls.length)};
    }};
  return {store, options, calls};
}

test('persist-before-send and acknowledgement-before-advance; second run sends nothing', async () => {
  const f = fixture();
  const result = await drainDelivery(f.options);
  assert.deepEqual(f.calls, ['old basic', 'old detail', 'new']);
  assert.equal(result.completedItems, 2);
  assert.equal(result.pendingItems, 0);
  assert.equal(result.reason, 'complete');
  assert.equal((await drainDelivery(f.options)).completedItems, 0);
  assert.equal(f.calls.length, 3);
});

test('manual item limit includes all messages of the oldest item', async () => {
  const f = fixture();
  const result = await drainDelivery({...f.options, maxItems: 1});
  assert.deepEqual(f.calls, ['old basic', 'old detail']);
  assert.equal(result.completedItems, 1);
  assert.equal(result.pendingItems, 1);
  assert.equal(result.reason, 'item_limit');
});

test('failed attempt save prevents any external send', async () => {
  const f = fixture();
  f.store.failSave = 1;
  await assert.rejects(drainDelivery(f.options), /storage unavailable/);
  assert.deepEqual(f.calls, []);
});

test('lost acknowledgement leaves in-flight state, stops newer messages, and reports ambiguity on recovery', async () => {
  const f = fixture();
  f.store.failSave = 2;
  await assert.rejects(drainDelivery(f.options), /storage unavailable/);
  assert.deepEqual(f.calls, ['old basic']);
  assert.equal((await f.store.load()).items[0].messages[0].status, 'in_flight');
  const result = await drainDelivery(f.options);
  assert.equal(result.ambiguousAttempts, 1);
  assert.deepEqual(f.calls, ['old basic', 'old basic', 'old detail', 'new']);
});

test('detail failure resumes at detail after retry time, never repeats primary', async () => {
  const f = fixture();
  let fail = true;
  const send = async message => {
    if (message.target === 'DETAIL' && fail) {
      fail = false;
      throw {code: 'rate_limited', retryAt: 50, ambiguous: false};
    }
    return f.options.send(message);
  };
  const first = await drainDelivery({...f.options, send});
  assert.equal(first.reason, 'delivery_failed');
  assert.deepEqual(f.calls, ['old basic']);
  assert.equal((await drainDelivery({...f.options, send, now: () => 49})).reason, 'retry_wait');
  await drainDelivery({...f.options, send, now: () => 50});
  assert.deepEqual(f.calls, ['old basic', 'old detail', 'new']);
});

test('deadline defers work without deleting the queue', async () => {
  const f = fixture();
  const result = await drainDelivery({...f.options, deadline: 0});
  assert.equal(result.reason, 'deadline');
  assert.equal(result.pendingItems, 2);
  assert.deepEqual(f.calls, []);
  assert.equal((await f.store.load()).revision, queue().revision);
});

test('invalid success response is ambiguous and cannot advance the queue', async () => {
  const f = fixture();
  const result = await drainDelivery({...f.options, send: async () => ({})});
  assert.equal(result.reason, 'delivery_failed');
  assert.equal(result.ambiguousAttempts, 1);
  assert.equal(result.pendingItems, 2);
});

test('unknown thrown exceptions persist only safe codes and never exception text', async () => {
  const f = fixture();
  const result = await drainDelivery({...f.options, send: async () => { throw new Error('webhook-secret-value'); }});
  assert.equal(result.ambiguousAttempts, 1);
  assert.equal(JSON.stringify(await f.store.load()).includes('webhook-secret-value'), false);
});

test('invalid limits fail before loading or sending', async () => {
  const f = fixture();
  for (const maxItems of [0, -1, 1.5, '1']) {
    await assert.rejects(drainDelivery({...f.options, maxItems}), /invalid/);
  }
  assert.deepEqual(f.calls, []);
});

test('a compare-and-swap conflict prevents sending from a stale snapshot', async () => {
  const f = fixture();
  f.store.save = async () => { throw new Error('revision conflict'); };
  await assert.rejects(drainDelivery(f.options), /revision conflict/);
  assert.equal(f.calls.length, 0);
});

test('deadline reached mid-item resumes only the remaining messages', async () => {
  const f = fixture();
  let clock = 0;
  const send = async message => {
    const response = await f.options.send(message);
    clock = 1000;
    return response;
  };
  const first = await drainDelivery({...f.options, send, now: () => clock});
  assert.equal(first.reason, 'deadline');
  assert.deepEqual(f.calls, ['old basic']);
  await drainDelivery(f.options);
  assert.deepEqual(f.calls, ['old basic', 'old detail', 'new']);
});

test('all 125 discovered items are delivered in source order without a hidden result cap', async () => {
  let saved = enqueueBatch(createDeliveryState('large'), Array.from({length: 125}, (_, i) =>
    ({id: `video-${i}`, messages: [{target: 'WEBHOOK', content: `video-${i}`}]})));
  const sent = [];
  const result = await drainDelivery({
    store: {load: async () => copy(saved), save: async (next, revision) => {
      assert.equal(saved.revision, revision); saved = copy(next);
    }},
    send: async message => { sent.push(message.content); return {messageId: String(sent.length)}; },
    now: () => 0, deadline: 1000, newAttemptId: () => `attempt-${sent.length}`,
  });
  assert.equal(result.completedItems, 125);
  assert.equal(result.pendingItems, 0);
  assert.deepEqual(sent, Array.from({length: 125}, (_, i) => `video-${124 - i}`));
});
