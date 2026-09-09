import {nextMessage, beginAttempt, acknowledge, failAttempt, recoverAttempts} from './delivery-state.mjs';

const pendingCount = state => state.items.filter(item => item.messages.some(message => message.status !== 'sent')).length;
const ambiguousCount = state => state.items.reduce((total, item) => total +
  item.messages.reduce((count, message) => count + message.ambiguousAttempts, 0), 0);

/**
 * The caller must hold its platform's exclusive profile lock for the entire call.
 * save(next, expectedRevision) must durably compare-and-swap before resolving.
 * send resolves secret names at the HTTP boundary, never in persisted state.
 */
export async function drainDelivery({store, send, now, deadline, maxItems = Infinity, newAttemptId}) {
  if (!(maxItems === Infinity || (Number.isSafeInteger(maxItems) && maxItems > 0)) || !Number.isFinite(deadline)) {
    throw new Error('invalid delivery budget');
  }
  let state = await store.load();
  async function persist(next) {
    if (next === state) return;
    await store.save(next, state.revision);
    state = next;
  }
  // An in-flight attempt from an earlier exclusive run has an unknown result.
  await persist(recoverAttempts(state));
  const initialPending = pendingCount(state);
  const visited = new Set();
  function result(reason) {
    const pendingItems = pendingCount(state);
    return {reason, completedItems: initialPending - pendingItems, pendingItems,
      ambiguousAttempts: ambiguousCount(state)};
  }
  while (pendingCount(state)) {
    const timestamp = now();
    if (!Number.isFinite(timestamp)) throw new Error('invalid clock');
    if (timestamp >= deadline) return result('deadline');
    const message = nextMessage(state, timestamp);
    if (!message) return result('retry_wait');
    if (!visited.has(message.itemId) && visited.size >= maxItems) return result('item_limit');
    visited.add(message.itemId);
    const attemptId = newAttemptId();
    await persist(beginAttempt(state, message.key, attemptId, timestamp));
    let response;
    try {
      response = await send({content: message.content, target: message.target, attemptId});
    } catch (error) {
      await persist(failAttempt(state, message.key, attemptId, {
        code: error?.code,
        retryAt: Number.isFinite(error?.retryAt) && error.retryAt >= 0 ? error.retryAt : timestamp,
        ambiguous: error?.ambiguous !== false,
      }));
      return result('delivery_failed');
    }
    if (typeof response?.messageId !== 'string' || !/^[0-9]+$/.test(response.messageId)) {
      await persist(failAttempt(state, message.key, attemptId,
        {code: 'invalid_discord_response', ambiguous: true, retryAt: timestamp}));
      return result('delivery_failed');
    }
    // Keep this outside the network catch. A failed acknowledgement write must
    // leave the durable attempt in flight; it does not mean Discord rejected it.
    await persist(acknowledge(state, message.key, attemptId, response.messageId));
  }
  return result('complete');
}
