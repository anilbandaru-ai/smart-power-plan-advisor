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
for (const id of ['usage-provenance', 'baseline-plan', 'renewal-credits']) document.querySelector(`#${id}`).addEventListener('change', invalidate);
for (const id of ['max-contract', 'switching-cost', 'renewal-escalation']) document.querySelector(`#${id}`).addEventListener('input', invalidate);
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
  const escalation = document.querySelector('#renewal-escalation').value;
  if (escalation !== '') {
    if (!/^\d+(\.\d{1,2})?$/.test(escalation) || Number(escalation) > 30) throw new Error('Enter renewal escalation from 0 to 30 percent with at most two decimal places.');
    if (Number(escalation) !== 5) options.renewal_escalation_pct = escalation;
  }
  if (document.querySelector('#renewal-credits').value === 'drop') options.renewal_credit_policy = 'drop';
  return options;
}

function renderAppliedPreferences(data, parent) {
  const options = data.recommendation_result?.options;
  if (!options) return;
  const summary = element('div', '', parent);
  summary.className = 'applied-preferences';
  element('h3', 'Applied preferences', summary);
  element('p', data.recommendation_result.policy_version === 'efl-average-v3'
    ? `Comparison period: ${data.recommendation_result.comparison_horizon || 12} months. Renewal escalation: ${options.renewal_escalation_pct ?? 5}% annually on the inclusive average. Separate renewal credit settings do not apply.`
    : ['horizon-renewal-v2', 'custom-efl-v4'].includes(data.recommendation_result.policy_version)
    ? `Comparison period: ${data.recommendation_result.comparison_horizon || 12} months. Renewal escalation: ${options.renewal_escalation_pct ?? 5}% annually; renewal credits: ${options.renewal_credit_policy || 'retain'}. Future terms are assumed.`
    : `Saved comparison period: ${data.recommendation_result.comparison_horizon || 12} months. Compare again to apply the updated renewal policy.`, summary);
  const usageLabels = { unknown: 'Not specified', estimated: 'Estimates', bills: 'Electricity bills', meter: 'Meter records' };
  const baseline = data.recommendation_result.baseline?.name || data.recommendations.find(p => p.plan_id === options.baseline_plan_id)?.name;
  element('p', `Contract: ${options.max_contract_months ? `up to ${options.max_contract_months} months` : 'No maximum'}. Usage source: ${usageLabels[options.usage_provenance] || 'Not specified'}.`, summary);
  element('p', `Current plan: ${baseline || 'Not selected'}. Entered switching costs: ${options.switching_cost == null ? 'Unknown' : dollars(options.switching_cost)}.`, summary);
  element('p', 'Contract length filters plans. Usage source informs confidence; it does not change prices. Current plan and switching costs determine savings, not the total-cost ranking.', summary).className = 'note';
  if (!options.baseline_plan_id && options.switching_cost != null) element('p', 'Select your current plan and compare again to apply these switching costs to savings.', summary).className = 'result-warning';
}

function renderRecommendation(data) {
  const rec = data.recommendation_result;
  if (!rec) return;
  const panel = element('section', '', results);
  panel.className = 'recommendation-summary';
  element('h2', 'Your recommendation', panel);
  renderAppliedPreferences(data, panel);
  if (!rec.best_overall) {
    element('p', 'No plan meets your recommendation preferences. Adjust the maximum contract length.', panel);
    for (const warning of rec.warnings) element('p', warning, panel);
    return;
  }
  if (rec.policy_version === 'efl-average-v3') element('p', 'Costs use your mapped EFL average prices, including fees and credits. These are range-based approximations, not tariff-derived bills.', panel).className = 'note';
  if (rec.policy_version === 'custom-efl-v4') element('p', 'Custom estimate: Energy uses your mapped EFL average; PDF fees and delivery are added and eligible credits subtracted. This repeats effects embedded in that average and is not an actual tariff bill.', panel).className = 'result-warning';
  const best = rec.best_overall;
  const horizon = rec.comparison_horizon || 12;
  const total = plan => plan.horizon_cost ?? plan.estimated_annual_cost;
  element('h3', best.name, panel).className = 'recommended-name';
  const metrics = element('div', '', panel);
  metrics.className = 'cost-metrics';
  const annual = element('div', '', metrics);
  element('span', `Estimated ${horizon}-month cost`, annual).className = 'note';
  element('p', `${dollars(total(best))}`, annual).className = 'price';
  const monthly = element('div', '', metrics);
  element('span', 'Average per month', monthly).className = 'note';
  element('p', dollars(Number(total(best)) / horizon), monthly).className = 'price';
  element('p', `Period total / ${horizon}; monthly bills vary.`, monthly).className = 'note';
  element('p', 'Lowest estimated total cost among plans meeting your preferences.', panel).className = 'note';
  if (best.annualized_cost != null) element('p', `Annualized average: ${dollars(best.annualized_cost)}. This is not a year-by-year forecast.`, panel).className = 'note';
  if (best.initial_term_cost != null) {
    element('p', `Initial contract: ${dollars(best.initial_term_cost)}. Modeled renewal: ${dollars(best.modeled_renewal_cost)}.`, panel).className = 'note';
    const years = element('details', '', panel);
    element('summary', 'Cost by year', years);
    for (const year of best.yearly_costs || []) element('p', `Year ${year.year} (${year.months} months): ${dollars(year.cost)}`, years);
  }
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
    element('p', dollars(total(plan)), card).className = 'shortlist-price';
    element('p', `${plan.term_months}-month contract / ${horizon}-month estimate`, card).className = 'note';
    element('p', `Maximum tested regret: ${dollars(plan.max_scenario_regret)}`, card).className = 'note';
  }
  element('p', 'Regret is the extra cost versus the cheapest plan in a tested usage scenario.', panel).className = 'note';
  if (rec.baseline) {
    element('h3', 'Savings against your selected current plan', panel);
    element('p', `${rec.baseline.name}: ${dollars(rec.baseline.horizon_cost ?? rec.baseline.annual_cost)} under the same usage.`, panel);
    const savings = rec.expected_savings;
    const gross = savings.gross_horizon_savings ?? savings.gross_annual_savings;
    const net = 'net_horizon_savings' in savings ? savings.net_horizon_savings : savings.net_annual_savings;
    element('p', `Switching costs applied: ${savings.switching_cost == null ? 'Unknown' : dollars(savings.switching_cost)}.`, panel).className = 'note';
    if (rec.baseline.plan_id === best.plan_id) element('p', 'Your current plan is the lowest-cost qualifying plan. Staying applies no switching cost.', panel).className = 'note';
    if (net != null && Number(net) < 0) element('p', 'Switching costs exceed comparison-period savings. Staying on your current plan may cost less.', panel).className = 'result-warning';
    element('p', `Estimated gross savings: ${dollars(gross)}. Net after switching costs: ${net == null ? 'unknown' : dollars(net)}.`, panel);
    element('p', savings.sustained_payback_month === null ? 'No switching payback month established.' : `Switching costs recovered from month ${savings.sustained_payback_month} through month ${horizon}.`, panel);
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
  for (const title of ['Plan', 'Usage / renewal assumption', `${horizon}-month cost`, 'Rank', 'Regret']) element('th', title, head).scope = 'col';
  const body = element('tbody', '', table);
  for (const plan of rec.plan_analyses) {
    for (const value of plan.scenario_results) {
      const row = element('tr', '', body);
      const scenario = rec.scenarios.find(s => s.id === value.scenario_id);
      for (const text of [plan.name, `${Number(scenario.multiplier) * 100}% / ${scenario.renewal_case || "base"} (${scenario.renewal_escalation_pct ?? "n/a"}%)`, dollars(value.horizon_cost ?? value.annual_cost), value.rank, dollars(value.regret)]) element('td', String(text), row);
    }
    const credit = plan.bill_credit_analysis;
    const details = element('details', '', analysis);
    element('summary', `${plan.name}: bill-credit sensitivity`, details);
    if (credit.status === 'included_in_average') {
      element('p', 'Credits are already included in the average price. Separate credit amounts and eligibility are not calculated by this estimate.', details);
      continue;
    }
    element('p', `${dollars(credit.horizon_credits ?? credit.annual_credits)} in credits across ${credit.qualifying_months.length} months over the ${horizon}-month period.`, details);
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
  const maxContract = data.recommendation_result?.options?.max_contract_months;
  const matching = data.recommendations.filter(plan => !maxContract || plan.term_months <= maxContract);
  const longer = data.recommendations.filter(plan => maxContract && plan.term_months > maxContract);
  element('h2', maxContract ? `Plans matching your contract preference (${matching.length})` : `All compared plans (${matching.length})`, results);
  if (maxContract) element('p', `Maximum contract: ${maxContract} months. Longer contracts are listed separately below.`, results).className = 'note';
  if (!matching.length) element('p', 'No compared plans meet your maximum contract length.', results);
  const longerPlans = document.createElement('details');
  longerPlans.className = 'longer-contracts';
  element('summary', `Longer contracts (${longer.length}) - outside your preference`, longerPlans);
  element('p', data.zip_code ? `ZIP ${data.zip_code}` : 'Legacy comparison (no ZIP saved)', results);
  const assumptions = element('details', '', results);
  element('summary', 'Calculation assumptions', assumptions);
  for (const assumption of data.assumptions) element('p', assumption, assumptions).className = 'note';
  [...matching, ...longer].forEach((plan, index) => {
    const outsidePreference = index >= matching.length;
    const card = element('details', '', outsidePreference ? longerPlans : results);
    const horizon = plan.comparison_horizon || 12;
    card.className = 'plan-row';
    const rowSummary = element('summary', '', card);
    element('span', `${outsidePreference ? index - matching.length + 1 : index + 1}. ${plan.name}`, rowSummary).className = 'plan-name';
    element('span', plan.term_months ? `${plan.term_months} months` : 'Contract not recorded', rowSummary).className = 'plan-term';
    element('span', `${dollars(plan.horizon_cost ?? plan.annual_cost)} / ${horizon} months`, rowSummary).className = 'plan-cost';
    const content = element('div', '', card);
    content.className = 'plan-content';
    if (outsidePreference) element('p', `Exceeds your maximum contract length of ${maxContract} months; excluded from recommendations.`, content).className = 'note';
    if (index === 0 && !outsidePreference && maxContract) element('p', 'Lowest estimated cost among plans matching your contract preference.', content);
    else if (index === 0 && !outsidePreference) element('p', data.data_mode === 'pdf' ? 'Lowest estimated comparison-period cost among calculable PDF plans' : 'Lowest estimated cost among these demo plans', content);
    element('p', plan.explanation, content);
    const renewalMonths = (plan.horizon_monthly_costs || []).filter(month => month.basis === 'modeled_renewal');
    if (renewalMonths.length) {
      const rate = data.recommendation_result?.options?.renewal_escalation_pct;
      const rateLabel = rate == null ? 'Annual renewal percentage not recorded in this saved result' : `Annual renewal assumption: ${rate}%`;
      const firstMonth = Math.min(...renewalMonths.map(month => Number(month.month)));
      element('p', `${rateLabel}. Applied from month ${firstMonth} for ${renewalMonths.length} modeled month(s). Compounds by whole elapsed years from the comparison start, after the initial contract ends. This is a hypothetical assumption, not a confirmed renewal offer.`, content).className = 'renewal-note note';
    }
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
    const examples = [...(plan.efl_price_examples || [])].sort((a, b) => Number(a.kwh) - Number(b.kwh));
    if (examples.length) {
      const published = element('details', '', details);
      element('summary', 'Published EFL average prices', published);
      for (const example of examples) {
        element('p', `${example.kwh} kWh: ${example.cents_per_kwh} \u00a2/kWh${example.page ? ` (page ${example.page})` : ''}`, published);
        element('p', example.quote, published).className = 'note';
      }
    }
    const custom = plan.pricing_basis === 'custom_efl';
    const inclusive = plan.pricing_basis === 'efl_average';
    const projected = plan.horizon_monthly_costs?.length > 0;
    if (projected) element('p', 'Document terms are held constant during the initial contract. Later months use hypothetical renewal assumptions.', details).className = 'note';
    const wrapper = element('div', '', details);
    wrapper.className = 'table-scroll';
    const table = element('table', '', wrapper);
    element('caption', custom ? 'Custom estimate: Energy = kWh times displayed EFL reference / 100; Total = Energy + base/usage fees + delivery - eligible credits. This repeats fee/credit effects embedded in the published average, not an actual tariff bill. Renewal rates are hypothetical.' : inclusive ? 'Estimated charge and Total both equal kWh times the displayed average price / 100, rounded to cents. Base fees, delivery and credits are embedded in that price and are not applied again. These user-defined EFL ranges approximate costs; renewal rows use a hypothetical escalated average.' : 'Charges in USD; credits are subtracted. Average Price is an EFL reference mapped to your requested usage ranges: use the first price through the second usage threshold, then the preceding example at each exact threshold; above the highest threshold use its price. These ranges are not published tariff rules or calculated effective prices. Renewal prices are not documented.', table);
    const head = element('tr', '', element('thead', '', table));
    for (const label of ['Month', 'kWh', inclusive ? 'Estimated charge (all-in)' : custom ? 'Energy (custom)' : 'Energy', inclusive ? 'Average Price used (\u00a2/kWh)' : 'Average Price / EFL reference (\u00a2/kWh)', custom ? 'Base / usage fee' : 'Base fee', 'Delivery', 'Credit', custom ? 'Total (custom)' : 'Total', ...(projected ? ['Basis'] : [])]) element('th', label, head).scope = 'col';
    const body = element('tbody', '', table);
    for (const month of (projected ? plan.horizon_monthly_costs : plan.monthly_costs)) {
      const row = element('tr', '', body);
      const example = examples.reduce((selected, example) => Number(month.kwh) > Number(example.kwh) ? example : selected, examples[0]);
      const averagePrice = (inclusive || custom) && month.average_price_cents != null ? String(month.average_price_cents) : month.basis === 'modeled_renewal' ? 'Not available (renewal)' : example ? String(example.cents_per_kwh) : 'Not listed';
      for (const value of [month.month, month.kwh, dollars(month.energy), averagePrice, ...['base_fee', 'delivery', 'credit', 'total'].map(key => inclusive && key !== 'total' ? 'Included' : dollars(month[key])), ...(projected ? [month.basis === 'modeled_renewal' ? 'Modeled renewal' : custom ? 'Custom estimate' : 'Document terms'] : [])]) element('td', String(value), row);
    }
  });
  if (longer.length) results.append(longerPlans);
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
    document.querySelector('#renewal-escalation').value = options?.renewal_escalation_pct ?? '5';
    document.querySelector('#renewal-credits').value = options?.renewal_credit_policy || 'retain';
    document.querySelector('#usage-provenance').value = options?.usage_provenance || 'unknown';
    document.querySelector('#max-contract').value = options?.max_contract_months?.toString() || '';
    document.querySelector('#switching-cost').value = options?.switching_cost ?? '';
    updateButton();
  } catch (error) { if (version === revision) status.textContent = error.message; }
}
initialize();
