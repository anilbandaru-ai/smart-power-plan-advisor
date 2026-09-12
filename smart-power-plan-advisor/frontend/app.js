const form = document.querySelector('#compare-form');
const area = document.querySelector('#tdu');
const button = document.querySelector('#submit');
const status = document.querySelector('#status');
const results = document.querySelector('#results');
const dollars = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));

function element(tag, text, parent) {
  const node = document.createElement(tag);
  node.textContent = text;
  parent.append(node);
  return node;
}

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}). Check your inputs and try again.`);
  }
  return response.json();
}

function render(data) {
  results.replaceChildren();
  element('h2', 'Your comparison', results);
  for (const assumption of data.assumptions) element('p', assumption, results).className = 'note';
  data.recommendations.forEach((plan, index) => {
    const card = element('article', '', results);
    element('h3', `${index + 1}. ${plan.name}`, card);
    element('p', `${dollars(plan.annual_cost)} / 12 months`, card).className = 'price';
    if (index === 0) element('p', 'Lowest estimated cost among these demo plans', card);
    element('p', plan.explanation, card);
    element('p', `Source: ${plan.source}`, card).className = 'note';
    const details = element('details', '', card);
    element('summary', 'Monthly cost breakdown', details);
    const wrapper = element('div', '', details);
    wrapper.className = 'table-scroll';
    const table = element('table', '', wrapper);
    element('caption', 'All charges in USD; credits are subtracted.', table);
    const head = element('tr', '', element('thead', '', table));
    for (const label of ['Month', 'kWh', 'Energy', 'Base fee', 'Delivery', 'Credit', 'Total']) element('th', label, head).scope = 'col';
    const body = element('tbody', '', table);
    for (const month of plan.monthly_costs) {
      const row = element('tr', '', body);
      for (const value of [month.month, month.kwh, ...['energy', 'base_fee', 'delivery', 'credit', 'total'].map(key => dollars(month[key]))]) element('td', String(value), row);
    }
  });
  const link = element('a', 'Link to this saved comparison', results);
  link.href = `/?comparison=${encodeURIComponent(data.id)}`;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const values = document.querySelector('#usage').value.split(',').map(value => value.trim());
  if (values.length !== 12 || values.some(value => !/^\d+(\.\d{1,4})?$/.test(value) || Number(value) > 99999999.9999)) {
    status.textContent = 'Enter 12 non-negative usage numbers with no more than four decimal places.';
    results.replaceChildren();
    return;
  }
  button.disabled = true;
  results.replaceChildren();
  status.textContent = 'Comparing plans…';
  try {
    const data = await request('/api/comparisons', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tdu: area.value, monthly_kwh: values }),
    });
    render(data);
    history.replaceState(null, '', `/?comparison=${encodeURIComponent(data.id)}`);
    status.textContent = 'Comparison saved locally.';
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});

async function initialize() {
  try {
    const catalog = await request('/api/plans');
    area.replaceChildren();
    for (const tdu of catalog.tdus) {
      const option = element('option', tdu, area);
      option.value = tdu;
    }
    if (!catalog.tdus.length) throw new Error('No demo delivery areas are available.');
    area.disabled = false;
    button.disabled = false;
    const id = new URLSearchParams(location.search).get('comparison');
    if (id) {
      const data = await request(`/api/comparisons/${encodeURIComponent(id)}`);
      render(data);
      area.value = data.tdu;
      document.querySelector('#usage').value = data.recommendations[0].monthly_costs.map(month => month.kwh).join(', ');
      status.textContent = 'Loaded saved comparison.';
    }
  } catch (error) { status.textContent = error.message; }
}
initialize();

const knowledgeForm = document.querySelector('#knowledge-form');
const knowledgeDocument = document.querySelector('#knowledge-document');
const knowledgeButton = document.querySelector('#knowledge-submit');
const knowledgeStatus = document.querySelector('#knowledge-status');
const knowledgeAnswer = document.querySelector('#knowledge-answer');

async function initializeKnowledge() {
  try {
    const data = await request('/api/knowledge/status');
    for (const document of data.documents) {
      const option = element('option', document.filename, knowledgeDocument);
      option.value = document.id;
    }
    if (!data.configured || !data.indexed) {
      knowledgeStatus.textContent = 'Document Q&A is not configured and indexed yet. You can still compare the demo plans above.';
      return;
    }
    knowledgeButton.disabled = false;
    knowledgeDocument.disabled = false;
    knowledgeStatus.textContent = `${data.documents.length} source document(s) indexed. Ask a question to retrieve supporting pages.`;
  } catch (error) { knowledgeStatus.textContent = error.message; }
}

knowledgeForm.addEventListener('submit', async event => {
  event.preventDefault();
  const question = document.querySelector('#knowledge-question').value.trim();
  if (!question) {
    knowledgeStatus.textContent = 'Enter a question about the plan documents.';
    return;
  }
  knowledgeButton.disabled = true;
  knowledgeAnswer.replaceChildren();
  knowledgeStatus.textContent = 'Finding supporting pages…';
  try {
    const data = await request('/api/knowledge/ask', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, document_id: knowledgeDocument.value || null }),
    });
    element('p', data.answer, knowledgeAnswer);
    for (const citation of data.citations) {
      const link = element('a', `${citation.source_id}: ${citation.filename}, page ${citation.page}`, knowledgeAnswer);
      link.href = citation.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      element('blockquote', citation.excerpt, knowledgeAnswer);
    }
    knowledgeStatus.textContent = data.abstained ? 'The documents do not support a complete answer to this question.' : 'Answer linked to supporting document excerpts. Review the source for full terms.';
  } catch (error) { knowledgeStatus.textContent = error.message; }
  finally { knowledgeButton.disabled = false; }
});
initializeKnowledge();
