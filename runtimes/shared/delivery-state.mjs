// Pure queue transitions. The adapter must persist each transition while holding its lock.
const clone = state => JSON.parse(JSON.stringify(state));
const validString = value => typeof value === 'string' && value.trim().length > 0;
const changed = state => ({...clone(state), revision: state.revision + 1});

export function createDeliveryState(profileId) {
  if (!/^[a-z][a-z0-9_]{0,127}$/.test(profileId ?? '')) throw new Error('invalid profile id');
  return {schemaVersion: 1, profileId, revision: 0, items: []};
}

function validateItem(item) {
  if (!item || !validString(item.id) || item.id.length > 4096 || !Array.isArray(item.messages) || !item.messages.length) {
    throw new Error('invalid delivery item');
  }
  for (const message of item.messages) {
    // JS string length counts UTF-16 code units, matching Discord's content limit.
    if (!message || !validString(message.content) || message.content.length > 2000 ||
        !/^[A-Z][A-Z0-9_]{0,127}$/.test(message.target ?? '')) throw new Error('invalid delivery message');
  }
}

export function enqueueBatch(state, items, {order = 'feed_oldest_first'} = {}) {
  if (!['feed_oldest_first', 'feed_newest_first'].includes(order) || !Array.isArray(items)) {
    throw new Error('invalid delivery order or batch');
  }
  items.forEach(validateItem);
  const seen = new Set(state.items.map(item => item.id));
  const additions = items.filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
  if (!additions.length) return state;
  if (order === 'feed_oldest_first') additions.reverse();
  const result = changed(state);
  for (const item of additions) {
    result.items.push({id: item.id, messages: item.messages.map((message, position) => ({
      key: JSON.stringify([state.profileId, item.id, position]),
      target: message.target, content: message.content,
      status: 'pending', attemptId: null, attempts: 0, ambiguousAttempts: 0,
      messageId: null, retryAt: 0, lastError: null,
    }))});
  }
  return result;
}

function firstUnsent(state) {
  for (const item of state.items) {
    for (const message of item.messages) {
      if (message.status !== 'sent') return {itemId: item.id, ...message};
    }
  }
  return null;
}

export function nextMessage(state, now) {
  if (!Number.isFinite(now)) throw new Error('invalid clock');
  const first = firstUnsent(state);
  return first && first.status === 'pending' && first.retryAt <= now ? first : null;
}

function getMessage(state, key) {
  for (const item of state.items) {
    const message = item.messages.find(message => message.key === key);
    if (message) return message;
  }
  throw new Error('invalid message key');
}

export function beginAttempt(state, key, attemptId, now) {
  if (nextMessage(state, now)?.key !== key) throw new Error('invalid delivery order');
  if (typeof attemptId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(attemptId) ||
      getMessage(state, key).attemptId === attemptId) throw new Error('invalid or reused attempt id');
  const result = changed(state);
  const message = getMessage(result, key);
  message.status = 'in_flight';
  message.attemptId = attemptId;
  message.attempts++;
  return result;
}

function currentAttempt(state, key, attemptId) {
  const first = firstUnsent(state);
  if (!first || first.key !== key || first.status !== 'in_flight' || first.attemptId !== attemptId) {
    throw new Error('invalid or stale attempt');
  }
}

export function acknowledge(state, key, attemptId, messageId) {
  currentAttempt(state, key, attemptId);
  if (typeof messageId !== 'string' || !/^[0-9]+$/.test(messageId)) throw new Error('invalid Discord message id');
  const result = changed(state);
  const message = getMessage(result, key);
  message.status = 'sent';
  message.messageId = messageId;
  message.lastError = null;
  message.retryAt = 0;
  return result;
}

export function failAttempt(state, key, attemptId, {code, retryAt = 0, ambiguous = false}) {
  currentAttempt(state, key, attemptId);
  if (!Number.isFinite(retryAt) || retryAt < 0) throw new Error('invalid retry time');
  const result = changed(state);
  const message = getMessage(result, key);
  message.status = 'pending';
  message.retryAt = retryAt;
  message.lastError = typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : 'delivery_failed';
  if (ambiguous) message.ambiguousAttempts++;
  return result;
}

export function recoverAttempts(state) {
  if (!state.items.some(item => item.messages.some(message => message.status === 'in_flight'))) return state;
  const result = changed(state);
  for (const item of result.items) {
    for (const message of item.messages) {
      if (message.status !== 'in_flight') continue;
      message.status = 'pending';
      message.lastError = 'ambiguous_delivery';
      message.ambiguousAttempts++;
    }
  }
  return result;
}
