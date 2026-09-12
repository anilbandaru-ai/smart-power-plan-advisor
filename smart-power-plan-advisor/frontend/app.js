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

zipInput.addEventListener('input', () => { clearBaseline(); invalidate(); });
document.querySelector('#plan-source').addEventListener('change', () => { clearBaseline(); invalidate(); });
for (const id of ['usage-provenance', 'baseline-plan']) document.querySelector(`#${id}`).addEventListener('change', invalidate);
for (const id of ['max-contract', 'switching-cost']) document.querySelector(`#${id}`).addEventListener('input', invalidate);
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

function clearBaseline() {
  const select = document.querySelector('#baseline-plan');
  select.replaceChildren();
  element('option', 'No baseline selected', select).value = '';
}

function populateBaseline(data) {
  clearBaseline();
  const select = document.querySelector('#baseline-plan');
  for (const plan of data.recommendations) element('option', `${plan.name} (${plan.term_months} months)`, select).value = plan.plan_id;
  select.value = data.recommendation_result?.options.baseline_plan_id || '';
}

function recommendationOptions() {
  const options = {};
  const provenance = document.querySelector('#usage-provenance').value;
  if (provenance && provenance !== 'unknown') options.usage_provenance = provenance;
  const contract = document.querySelector('#max-contract').value;
  if (contract) {
    if (!/^\d+$/.test(contract) || Number(contract) < 12 || Number(contract) > 120) throw new Error('Maximum contract length must be a whole number from 12 to 120 months.');
    options.max_contract_months = Number(contract);
  }
  const baseline = document.querySelector('#baseline-plan').value;
  if (baseline) options.baseline_plan_id = baseline;
  const cost = document.querySelector('#switching-cost').value;
  if (cost !== '') {
    if (!/^\d+(\.\d{1,2})?$/.test(cost) || Number(cost) > 9999999999.99) throw new Error('Enter a non-negative switching cost with at most two decimal places, or leave it blank.');
    options.switching_cost = cost;
  }
  return options;
}

function renderRecommendation(data) {
  const rec = data.recommendation_result;
  if (!rec) return;
  const panel = element('section', '', results);
  panel.className = 'recommendation-summary';
  element('h2', 'Your recommendation', panel);
  if (!rec.best_overall) {
    element('p', 'No plan meets your recommendation preferences. Adjust the maximum contract length.', panel);
    for (const warning of rec.warnings) element('p', warning, panel);
    return;
  }
  const best = rec.best_overall;
  element('h3', best.name, panel).className = 'recommended-name';
  const metrics = element('div', '', panel);
  metrics.className = 'cost-metrics';
  const annual = element('div', '', metrics);
  element('span', 'Estimated annual cost', annual).className = 'note';
  element('p', `${dollars(best.estimated_annual_cost)}`, annual).className = 'price';
  const monthly = element('div', '', metrics);
  element('span', 'Average per month', monthly).className = 'note';
  element('p', dollars(Number(best.estimated_annual_cost) / 12), monthly).className = 'price';
  element('p', 'Annual estimate / 12; actual monthly bills vary.', monthly).className = 'note';
  element('p', 'Lowest estimated cost among plans meeting your preferences.', panel).className = 'note';
  element('p', `Recommendation confidence: ${rec.confidence}`, panel);
  const confidence = element('details', '', panel);
  element('summary', 'Why this confidence level?', confidence);
  for (const reason of rec.confidence_reasons) element('p', reason, confidence).className = 'note';
  const alternative = rec.plan_analyses.find(plan => plan.plan_id === rec.category_winners.lowest_scenario_regret);
  const tradeoffs = element('details', '', panel);
  element('summary', 'Cost vs. usage uncertainty', tradeoffs);
  for (const tradeoff of rec.key_tradeoffs) element('p', tradeoff, tradeoffs);
  if (alternative?.plan_id === best.plan_id) element('p', 'The primary plan also has the lowest maximum regret across tested scenarios.', tradeoffs);
  element('h3', `Top ${rec.top_3.length} qualifying plan${rec.top_3.length === 1 ? '' : 's'}`, panel);
  const shortlist = element('div', '', panel);
  shortlist.className = 'shortlist';
  for (const [index, plan] of rec.top_3.entries()) {
    const card = element('div', '', shortlist);
    card.className = 'shortlist-card';
    element('h4', `${index + 1}. ${plan.name}`, card);
    element('p', dollars(plan.estimated_annual_cost), card).className = 'shortlist-price';
    element('p', `${plan.term_months} months / annual estimate`, card).className = 'note';
    element('p', `Maximum tested regret: ${dollars(plan.max_scenario_regret)}`, card).className = 'note';
  }
  element('p', 'Regret is the extra cost versus the cheapest plan in a tested usage scenario.', panel).className = 'note';
  if (rec.baseline) {
    element('h3', 'Savings against your selected current plan', panel);
    element('p', `${rec.baseline.name}: ${dollars(rec.baseline.annual_cost)} under the same usage.`, panel);
    const savings = rec.expected_savings;
    element('p', `Estimated gross savings: ${dollars(savings.gross_annual_savings)}. Net after switching costs: ${savings.net_annual_savings === null ? 'unknown' : dollars(savings.net_annual_savings)}.`, panel);
    element('p', savings.sustained_payback_month === null ? 'No switching payback month established.' : `Switching costs recovered from month ${savings.sustained_payback_month} through month 12.`, panel);
  } else element('p', 'Savings unavailable until a current-plan baseline is selected.', panel);
  const analysis = element('details', '', panel);
  element('summary', 'Explore usage scenarios & bill credits', analysis);
  const scenarioDetails = element('details', '', analysis);
  element('summary', 'Scenario costs and regret for all qualifying plans', scenarioDetails);
  const tableWrapper = element('div', '', scenarioDetails);
  tableWrapper.className = 'table-scroll';
  const table = element('table', '', tableWrapper);
  element('caption', 'Regret is the additional cost versus the cheapest eligible plan in that scenario. No scenario probabilities are assumed.', table);
  const head = element('tr', '', element('thead', '', table));
  for (const title of ['Plan', 'Usage multiplier', 'Annual cost', 'Rank', 'Regret']) element('th', title, head).scope = 'col';
  const body = element('tbody', '', table);
  for (const plan of rec.plan_analyses) {
    for (const value of plan.scenario_results) {
      const row = element('tr', '', body);
      const scenario = rec.scenarios.find(s => s.id === value.scenario_id);
      for (const text of [plan.name, `${Number(scenario.multiplier) * 100}%`, dollars(value.annual_cost), value.rank, dollars(value.regret)]) element('td', String(text), row);
    }
    const credit = plan.bill_credit_analysis;
    const details = element('details', '', analysis);
    element('summary', `${plan.name}: bill-credit sensitivity`, details);
    element('p', `${dollars(credit.annual_credits)} in credits across ${credit.qualifying_months.length} months at supplied usage.`, details);
    for (const change of credit.credit_loss_scenarios) element('p', `${change.scenario_id}: ${dollars(change.lost_credit_value)} of credits lost in months ${change.months.join(', ')}.`, details);
    for (const threshold of credit.threshold_exposure) {
      element('p', `Boundary: ${threshold.boundary_kwh} kWh. Nearby months: ${threshold.nearby_months.join(', ') || 'none'}.`, details);
      for (const probe of threshold.probes) element('p', `${probe.kwh} kWh: bill ${dollars(probe.bill)}, credit ${dollars(probe.credit)}.`, details).className = 'note';
    }
    if (!credit.threshold_exposure.length) element('p', 'No usage-dependent credit boundaries.', details);
  }
  const conditions = element('details', '', panel);
  element('summary', 'Break-even conditions', conditions);
  if (!rec.break_even_conditions.length) element('p', 'No cost-preference changes detected between the tested usage scenarios; this does not rule out crossings between samples.', conditions);
  for (const condition of rec.break_even_conditions) {
    const name = condition.plan_ids ? rec.plan_analyses.find(p => p.plan_id === condition.plan_ids[1])?.name : '';
    element('p', condition.kind === 'sampled_usage_bracket'
      ? `Compared with ${name}, cost preference changes between ${Number(condition.lower_multiplier) * 100}% and ${Number(condition.upper_multiplier) * 100}% usage. ${condition.description}`
      : `Switching payback month: ${condition.month ?? 'not established'}. ${condition.description}`, conditions);
  }
  if (rec.warnings.length) element('p', rec.warnings[0], panel).className = 'result-warning';
  const limits = element('details', '', panel);
  element('summary', `Warnings & assumptions (${rec.warnings.length + rec.assumptions.length})`, limits);
  for (const warning of [...rec.warnings, ...rec.assumptions]) element('p', warning, limits).className = 'note';
  const evidence = element('details', '', panel);
  element('summary', 'Recommendation evidence', evidence);
  for (const ref of rec.evidence_refs) {
    const line = element('p', `${ref.quote || ref.description || ref.date_label || ref.kind}`, evidence);
    if (ref.url && (ref.url.startsWith('/api/') || ref.url.startsWith('https://'))) {
      const link = element('a', ' Source', line);
      link.href = ref.url + (ref.page ? `#page=${ref.page}` : ''); link.target = '_blank'; link.rel = 'noopener noreferrer';
    }
  }
  element('p', `Policy: ${rec.policy_version}. Comparison horizon: ${rec.comparison_horizon} months.`, evidence).className = 'note';
}

function render(data) {
  results.replaceChildren();
  populateBaseline(data);
  renderRecommendation(data);
  element('h2', `All compared plans (${data.recommendations.length})`, results);
  element('p', data.zip_code ? `ZIP ${data.zip_code}` : 'Legacy comparison (no ZIP saved)', results);
  const assumptions = element('details', '', results);
  element('summary', 'Calculation assumptions', assumptions);
  for (const assumption of data.assumptions) element('p', assumption, assumptions).className = 'note';
  data.recommendations.forEach((plan, index) => {
    const card = element('details', '', results);
    card.className = 'plan-row';
    const rowSummary = element('summary', '', card);
    element('span', `${index + 1}. ${plan.name}`, rowSummary).className = 'plan-name';
    element('span', plan.term_months ? `${plan.term_months} months` : 'Contract not recorded', rowSummary).className = 'plan-term';
    element('span', `${dollars(plan.annual_cost)} / year`, rowSummary).className = 'plan-cost';
    const content = element('div', '', card);
    content.className = 'plan-content';
    if (index === 0) element('p', data.data_mode === 'pdf' ? 'Lowest estimated first-year cost among calculable PDF plans' : 'Lowest estimated cost among these demo plans', content);
    element('p', plan.explanation, content);
    element('p', `Source: ${plan.source}`, content).className = 'note';
    if (plan.source_url) {
      const source = element('a', 'Review source PDF', content);
      source.href = plan.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
    }
    if (plan.tdu_source) {
      const tdu = element('a', `TDU rates: ${plan.tdu_source.service_area} · published ${plan.tdu_source.published_on}`, content);
      tdu.href = plan.tdu_source.url; tdu.target = '_blank'; tdu.rel = 'noopener noreferrer';
    }
    const details = element('details', '', content);
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
  let options;
  try { options = recommendationOptions(); } catch (error) { status.textContent = error.message; return; }
  const version = ++revision;
  busy = true;
  updateButton();
  results.replaceChildren();
  status.textContent = 'Comparing plans…';
  try {
    const data = await request('/api/comparisons', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zip_code: zipInput.value, monthly_kwh: values, ...(Object.keys(options).length ? { recommendation_options: options } : {}), ...(document.querySelector('#plan-source').value === 'pdf' ? {data_source: 'pdf'} : {}) }),
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
    render(data);
    zipInput.value = data.zip_code || '';
    document.querySelector('#plan-source').value = data.data_mode === 'pdf' ? 'pdf' : 'demo';
    document.querySelector('#usage').value = data.recommendations[0].monthly_costs.map(month => month.kwh).join(', ');
    status.textContent = data.zip_code
      ? 'Loaded saved comparison.'
      : 'Loaded saved comparison. Enter a ZIP before comparing again.';
    const options = data.recommendation_result?.options;
    document.querySelector('#usage-provenance').value = options?.usage_provenance || 'unknown';
    document.querySelector('#max-contract').value = options?.max_contract_months?.toString() || '';
    document.querySelector('#switching-cost').value = options?.switching_cost ?? '';
    updateButton();
  } catch (error) { if (version === revision) status.textContent = error.message; }
}
initialize();
