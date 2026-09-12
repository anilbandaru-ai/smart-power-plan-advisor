/* Unified document conversation; calculator stays independent. */
(() => {
  const get = id => document.querySelector(`#agent-${id}`);
  const form = get('form'), submit = get('submit'), reset = get('reset');
  const scope = get('document'), question = get('question'), status = get('status'), messages = get('messages');
  let thread = null, pending = null, busy = false, ready = false, retry = null;
  function add(tag, text, parent) {
    const node = document.createElement(tag);
    node.textContent = text;
    parent.append(node);
    return node;
  }
  function scrollToLatest() {
    const viewport = get('scroll');
    viewport.scrollTop = viewport.scrollHeight;
  }
  function bubble(role, text) {
    get('empty').hidden = true;
    const card = add('article', '', messages);
    card.className = `chat-message ${role}`;
    add('h3', role === 'user' ? 'You' : role === 'error' ? 'Connection update' : 'Plan assistant', card);
    add('p', text, card);
    scrollToLatest();
    return card;
  }
  function controls() {
    submit.disabled = busy || !ready;
    reset.disabled = busy;
    scope.disabled = busy || !ready || Boolean(pending);
    question.disabled = busy;
    get('thinking').hidden = !busy;
    if (busy) scrollToLatest();
    get('question-label').textContent = pending ? 'Your clarification' : 'Your message';
    submit.textContent = pending ? 'Send clarification' : 'Send message';
  }
  async function api(path, method = 'GET', body) {
    const response = await fetch(`/api/agent${path}`, { method,
      headers: { 'Content-Type': 'application/json', ...(thread ? { Authorization: `Bearer ${thread.token}` } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'Check your message and try again.');
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function display(data) {
    const card = bubble('assistant', data.question || data.answer);
    if (data.citations?.length) {
      const sources = add('details', '', card);
      sources.className = 'source-details';
      add('summary', `View sources (${data.citations.length})`, sources);
      for (const citation of data.citations) {
        const link = add('a', `${citation.filename}, page ${citation.page}`, sources);
        link.href = citation.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        add('blockquote', citation.excerpt, sources);
      }
    }
    if (data.activity?.length) add('p', data.activity.join(' · '), card).className = 'note';
    scrollToLatest();
  }
  question.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!busy && ready && question.value.trim()) form.requestSubmit();
    }
  });
  document.querySelectorAll('[data-prompt]').forEach(chip => {
    chip.addEventListener('click', () => {
      if (busy) return;
      question.value = chip.dataset.prompt;
      question.focus();
    });
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = question.value.trim();
    if (busy || !ready || !text) return;
    busy = true; controls();
    status.textContent = 'Searching and checking supporting pages…';
    try {
      const signature = JSON.stringify([text, scope.value, pending]);
      if (!retry || retry.signature !== signature) {
        retry = { signature, id: crypto.randomUUID() };
        bubble('user', text);
      }
      if (!thread) thread = await api('/threads', 'POST');
      const body = { request_id: retry.id, message: text,
        ...(pending ? { interrupt_id: pending } : { document_id: scope.value || null }) };
      const data = await api(`/threads/${thread.thread_id}/${pending ? 'resume' : 'messages'}`, 'POST', body);
      display(data);
      pending = data.status === 'needs_input' ? data.interrupt_id : null;
      retry = null; question.value = '';
      status.textContent = data.status === 'needs_input' ? 'Answer the clarification to continue.'
        : data.status === 'answered' ? 'Answer linked to source excerpts. Review the PDF for full terms.'
        : data.status === 'limit_reached' ? 'Processing limit reached. Select New conversation.'
        : 'The indexed evidence does not support a complete answer.';
      if (data.status === 'limit_reached') ready = false;
    } catch (error) {
      bubble('error', error.message);
      status.textContent = error.message;
      if ([404, 409, 502].includes(error.status)) { ready = false; status.textContent += ' Select New conversation to continue.'; }
    } finally { busy = false; controls(); if (!document.querySelector('#assistant-panel').hidden) question.focus(); }
  });
  reset.addEventListener('click', async () => {
    if (busy) return;
    busy = true; controls();
    try {
      if (thread) await api(`/threads/${thread.thread_id}`, 'DELETE');
    } catch (error) {
      if (error.status !== 404) { status.textContent = error.message; busy = false; controls(); return; }
    }
    thread = pending = retry = null;
    messages.replaceChildren(); get('empty').hidden = false; question.value = '';
    busy = false;
    await initialize();
    if (!document.querySelector('#assistant-panel').hidden) question.focus();
  });
  async function initialize() {
    try {
      const data = await api('/status');
      ready = data.configured && data.indexed && data.dependencies_available;
      if (scope.children.length === 1) {
        for (const doc of data.documents) add('option', doc.filename, scope).value = doc.id;
      }
      status.textContent = ready ? 'Ready. Ask about an indexed document.' : 'The document agent needs configured keys, dependencies and indexed documents.';
    } catch (error) { status.textContent = error.message; ready = false; }
    controls();
  }
  initialize();
})();
