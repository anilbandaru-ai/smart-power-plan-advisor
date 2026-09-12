const form = document.querySelector('#compare-form');
const zipInput = document.querySelector('#zip-code');
let revision = 0;
let busy = false;

function updateButton() {
  button.disabled = busy || !/^[0-9]{5}$/.test(zipInput.value);
}

function invalidate() {
  revision++;
  busy = false;
  results.replaceChildren();
  status.textContent = '';
  history.replaceState(null, '', location.pathname);
  updateButton();
}

zipInput.addEventListener('input', invalidate);
document.querySelector('#plan-source').addEventListener('change', invalidate);
document.querySelector('#usage').addEventListener('input', invalidate);
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
  element('p', data.zip_code ? `ZIP ${data.zip_code}` : 'Legacy comparison (no ZIP saved)', results);
  for (const assumption of data.assumptions) element('p', assumption, results).className = 'note';
  data.recommendations.forEach((plan, index) => {
    const card = element('article', '', results);
    element('h3', `${index + 1}. ${plan.name}`, card);
    element('p', `${dollars(plan.annual_cost)} / 12 months`, card).className = 'price';
    if (index === 0) element('p', data.data_mode === 'pdf' ? 'Lowest estimated first-year cost among calculable PDF plans' : 'Lowest estimated cost among these demo plans', card);
    element('p', plan.explanation, card);
    element('p', `Source: ${plan.source}`, card).className = 'note';
    if (plan.source_url) {
      const source = element('a', 'Review source PDF', card);
      source.href = plan.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
    }
    if (plan.tdu_source) {
      const tdu = element('a', `TDU rates: ${plan.tdu_source.service_area} · published ${plan.tdu_source.published_on}`, card);
      tdu.href = plan.tdu_source.url; tdu.target = '_blank'; tdu.rel = 'noopener noreferrer';
    }
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
  if (data.excluded_plans?.length) {
    const excluded = element('details', '', results);
    element('summary', `Plans excluded from calculation (${data.excluded_plans.length})`, excluded);
    for (const plan of data.excluded_plans) element('p', `${plan.name}: ${plan.reasons.join('; ')}`, excluded);
  }
  const link = element('a', 'Link to this saved comparison', results);
  link.href = `/?comparison=${encodeURIComponent(data.id)}`;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  if (!/^[0-9]{5}$/.test(zipInput.value)) {
    status.textContent = 'Enter a five-digit ZIP code.';
    return;
  }
  const values = document.querySelector('#usage').value.split(',').map(value => value.trim());
  if (values.length !== 12 || values.some(value => !/^\d+(\.\d{1,4})?$/.test(value) || Number(value) > 99999999.9999)) {
    status.textContent = 'Enter 12 non-negative usage numbers with no more than four decimal places.';
    results.replaceChildren();
    return;
  }
  const version = ++revision;
  busy = true;
  updateButton();
  results.replaceChildren();
  status.textContent = 'Comparing plans…';
  try {
    const data = await request('/api/comparisons', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zip_code: zipInput.value, monthly_kwh: values, ...(document.querySelector('#plan-source').value === 'pdf' ? {data_source: 'pdf'} : {}) }),
    });
    if (version !== revision) return;
    render(data);
    history.replaceState(null, '', `/?comparison=${encodeURIComponent(data.id)}`);
    status.textContent = 'Comparison saved locally.';
  } catch (error) { if (version === revision) status.textContent = error.message; }
  finally { if (version === revision) { busy = false; updateButton(); } }
});

async function initialize() {
  const version = revision;
  const id = new URLSearchParams(location.search).get('comparison');
  if (!id) return;
  try {
    const data = await request(`/api/comparisons/${encodeURIComponent(id)}`);
    if (version !== revision) return;
    document.querySelector('.calculator-panel').open = true;
    render(data);
    zipInput.value = data.zip_code || '';
    document.querySelector('#plan-source').value = data.data_mode === 'pdf' ? 'pdf' : 'demo';
    document.querySelector('#usage').value = data.recommendations[0].monthly_costs.map(month => month.kwh).join(', ');
    status.textContent = data.zip_code
      ? 'Loaded saved comparison.'
      : 'Loaded saved comparison. Enter a ZIP before comparing again.';
    updateButton();
  } catch (error) { if (version === revision) status.textContent = error.message; }
}
initialize();
