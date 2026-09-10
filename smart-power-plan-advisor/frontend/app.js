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
