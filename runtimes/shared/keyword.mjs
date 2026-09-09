// Platform-independent keyword expressions. HTML extraction belongs to feed parsers.
const normalize = value => String(value ?? '').normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim();
const invalid = () => { throw new Error('invalid keyword expression'); };

function tokenize(expression, stripDates) {
  if (typeof expression !== 'string' || expression.length > 4096) invalid();
  const tokens = [];
  let index = 0;
  while (index < expression.length) {
    const char = expression[index];
    if (/\s/u.test(char)) { index++; continue; }
    const operator = {'(': '(', ')': ')', '|': 'OR', '&': 'AND', '!': 'NOT', '-': 'NOT'}[char];
    if (operator) { tokens.push({type: operator}); index++; continue; }
    if (char === '"') {
      const end = expression.indexOf('"', index + 1);
      if (end < 0) invalid();
      const value = normalize(expression.slice(index + 1, end));
      if (!value) invalid();
      tokens.push({type: 'TERM', value});
      index = end + 1;
      continue;
    }
    const start = index;
    while (index < expression.length && !/[\s()|&!"]/u.test(expression[index])) index++;
    const word = expression.slice(start, index);
    if (stripDates && /^(when|after|before):\S+$/i.test(word)) continue;
    tokens.push(/^(AND|OR|NOT)$/i.test(word)
      ? {type: word.toUpperCase()} : {type: 'TERM', value: normalize(word)});
  }
  return tokens;
}

function parse(tokens) {
  let index = 0;
  const peek = () => tokens[index]?.type;
  function unary(depth) {
    if (depth > 64) invalid();
    if (peek() === 'NOT') { index++; return {type: 'NOT', child: unary(depth + 1)}; }
    if (peek() === '(') {
      index++;
      const node = disjunction(depth + 1);
      if (peek() !== ')') invalid();
      index++;
      return node;
    }
    if (peek() !== 'TERM') invalid();
    return tokens[index++];
  }
  function conjunction(depth) {
    let node = unary(depth);
    while (['AND', 'TERM', 'NOT', '('].includes(peek())) {
      if (peek() === 'AND') index++;
      node = {type: 'AND', left: node, right: unary(depth)};
    }
    return node;
  }
  function disjunction(depth) {
    let node = conjunction(depth);
    while (peek() === 'OR') {
      index++;
      node = {type: 'OR', left: node, right: conjunction(depth)};
    }
    return node;
  }
  const ast = disjunction(0);
  if (index !== tokens.length) invalid();
  return ast;
}

function termMatches(term, text) {
  let start = 0;
  while ((start = text.indexOf(term, start)) >= 0) {
    const end = start + term.length;
    const left = !/^[a-z0-9]/.test(term) || start === 0 || !/[a-z0-9]/.test(text[start - 1]);
    const right = !/[a-z0-9]$/.test(term) || end === text.length || !/[a-z0-9]/.test(text[end]);
    if (left && right) return true;
    start++;
  }
  return false;
}

function evaluate(node, text) {
  if (node.type === 'TERM') return termMatches(node.value, text);
  if (node.type === 'NOT') return !evaluate(node.child, text);
  if (node.type === 'AND') return evaluate(node.left, text) && evaluate(node.right, text);
  return evaluate(node.left, text) || evaluate(node.right, text);
}

export function compileKeyword(query, aliases = '') {
  const baseTokens = tokenize(query, true);
  const base = parse(baseTokens);
  if (typeof aliases !== 'string') invalid();
  const extraTokens = aliases.trim() ? tokenize(aliases, false) : [];
  const ast = extraTokens.length ? {type: 'OR', left: base, right: parse(extraTokens)} : base;
  const terms = [...new Set([...baseTokens, ...extraTokens].filter(t => t.type === 'TERM').map(t => t.value))];
  return {
    expression: JSON.stringify(ast),
    terms,
    matches(text) {
      const normalized = normalize(text);
      return normalized !== '' && evaluate(ast, normalized);
    },
  };
}

export function matchItem(item, compiled, {service, scope = 'title'} = {}) {
  if (!['google-news', 'youtube'].includes(service)) throw new Error('invalid service');
  if (!['title', 'title_or_description'].includes(scope)) throw new Error('invalid scope');
  let title = String(item.title ?? '');
  if (service === 'google-news' && title.includes(' - ')) title = title.slice(0, title.lastIndexOf(' - '));
  if (compiled.matches(title)) return true;
  if (scope === 'title') return false;
  return service === 'google-news'
    ? (item.relatedTitles ?? []).some(text => compiled.matches(text))
    : compiled.matches(item.description ?? '');
}
