const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.children = []; this.listeners = {}; this.value = ''; this.textContent = ''; }
  append(node) { this.children.push(node); }
  replaceChildren() { this.children = []; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() { this.focusCount = (this.focusCount || 0) + 1; }
  fire(name) { return this.listeners[name]?.({ preventDefault() {} }); }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup(handler) {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  get('document').append(new Element());
  let id = 0;
  vm.runInNewContext(readFileSync('frontend/agent.js', 'utf8'), {
    document: { querySelector: selector => get(selector.replace('#agent-', '')), createElement: () => new Element(), querySelectorAll: () => [] },
    crypto: { randomUUID: () => `request-${++id}` },
    fetch: async (url, options) => {
      if (url === '/api/agent/status') return { ok: true, json: async () => ({ configured: true, indexed: true, dependencies_available: true, documents: [{id:'doc', filename:'Plan.pdf'}] }) };
      const result = await handler(url, options);
      return { ok: !result.error, status: result.error || 200, json: async () => result.body || result };
    },
  });
  return get;
}
test('chat creates thread, resumes clarification, renders safe citations and clears', async () => {
  const calls = [];
  const get = setup(async (url, options) => {
    calls.push({url, ...options});
    if (url.endsWith('/threads')) return { thread_id:'thread', token:'capability' };
    if (options.method === 'DELETE') return { cleared:true };
    assert.equal(options.headers.Authorization, 'Bearer capability');
    if (url.endsWith('/messages')) return {status:'needs_input', interrupt_id:'pause', question:'Which fee?', citations:[]};
    return {status:'answered', answer:'<script>plain text only</script>', citations:[{filename:'Plan.pdf',page:1,url:'/api/knowledge/documents/doc#page=1',excerpt:'Exact source excerpt'}],activity:['Searched documents']};
  });
  await flush();
  assert.equal(get('submit').disabled, false);
  get('question').value = 'What fee?';
  await get('form').fire('submit');
  assert.equal(get('submit').textContent, 'Send clarification');
  assert.equal(get('messages').children.length, 2);
  assert.equal(get('messages').children[0].className, 'chat-message user');
  assert.equal(get('empty').hidden, true);
  assert.equal(get('document').disabled, true);
  get('question').value = 'Termination';
  await get('form').fire('submit');
  assert.equal(JSON.parse(calls[2].body).interrupt_id, 'pause');
  assert.equal(get('messages').children.length, 4);
  const answer = get('messages').children.at(-1);
  assert.equal(answer.children[1].textContent, '<script>plain text only</script>');
  assert.equal(answer.children[2].children[1].href, '/api/knowledge/documents/doc#page=1');
  await get('reset').fire('click');
  assert.equal(get('messages').children.length, 0);
  assert.equal(calls.at(-1).method, 'DELETE');
});
test('expired conversation offers reset and disables further messages', async () => {
  const get = setup(async url => url.endsWith('/threads') ? {thread_id:'thread',token:'token'} : {error:404,body:{detail:'Conversation expired'}});
  await flush(); get('question').value = 'Term?'; await get('form').fire('submit');
  assert.equal(get('submit').disabled, true);
  assert.match(get('status').textContent, /New conversation/);
  await get('reset').fire('click');
  assert.equal(get('submit').disabled, false);
});
test('overlapping submits are blocked and a network retry reuses request ID', async () => {
  let attempts = 0; const ids = []; let release;
  const get = setup(async (url, options) => {
    if (url.endsWith('/threads')) return {thread_id:'thread',token:'token'};
    ids.push(JSON.parse(options.body).request_id);
    if (++attempts === 1) { await new Promise(resolve => {release = resolve;}); throw new Error('Network unavailable'); }
    return {status:'insufficient_evidence',answer:'No evidence',citations:[]};
  });
  await flush(); get('question').value = 'Term?'; const first = get('form').fire('submit'); await flush();
  await get('form').fire('submit'); assert.equal(attempts, 1);
  release(); await first; await get('form').fire('submit');
  assert.equal(ids[0], ids[1]);
});


test('Enter submits but Shift+Enter and composition preserve typing', async () => {
  const get = setup(async () => ({}));
  await flush();
  let submitted = 0, prevented = 0;
  get('form').requestSubmit = () => submitted++;
  get('question').value = 'Contract term?';
  const key = (shiftKey, isComposing = false) => get('question').listeners.keydown({key:'Enter', shiftKey, isComposing, preventDefault() { prevented++; }});
  key(true); key(false, true);
  assert.equal(submitted, 0);
  key(false);
  assert.equal(submitted, 1);
  assert.equal(prevented, 1);
});

test('page exposes one document composer and separate assistant and calculator tab panels', () => {
  const html = readFileSync('frontend/index.html', 'utf8');
  assert.equal((html.match(/id="agent-form"/g) || []).length, 1);
  assert.equal(html.includes('id="knowledge-form"'), false);
  assert.match(html, /id="compare-panel"[^>]*role="tabpanel"[^>]*hidden/);
});


test('chat completion retains its answer without focusing a hidden assistant', async () => {
  let finish;
  const response = new Promise(resolve => { finish = resolve; });
  const get = setup(async url => url.endsWith('/threads') ? {thread_id:'thread',token:'token'} : response);
  await flush();
  get('question').value = 'Term?';
  const pending = get('form').fire('submit');
  get('#assistant-panel').hidden = true;
  finish({status:'answered',answer:'12 months',citations:[]});
  await pending;
  assert.equal(get('question').focusCount || 0, 0);
  assert.equal(get('messages').children.at(-1).children[1].textContent, '12 months');
});
