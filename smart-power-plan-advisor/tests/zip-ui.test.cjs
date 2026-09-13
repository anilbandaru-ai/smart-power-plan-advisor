const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync('frontend/app.js', 'utf8');

class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.listeners = {}; this.disabled = false; this.textContent = ''; }
  get value() { return this.selected ?? (this.tag === 'select' ? this.children[0]?.value ?? '' : ''); }
  set value(value) { this.selected = value; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; this.selected = undefined; }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  fire(event) { return this.listeners[event]?.({ preventDefault() {} }); }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const saved = zip => ({
  id: 'saved', zip_code: zip, assumptions: [],
  recommendations: [{ name: 'Demo', annual_cost: '1800', explanation: 'Demo', source: 'Fixture',
    monthly_costs: Array.from({ length: 12 }, (_, i) => ({ month: i + 1, kwh: '1000', energy: '130', base_fee: '5', delivery: '55', credit: '40', total: '150' })) }],
});
function setup(handler, search = '') {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, new Element(id === 'knowledge-document' ? 'select' : 'div'));
    return nodes.get(id);
  };
  get('submit').disabled = true;
  get('usage').value = Array(12).fill('1000').join(',');
  let url = '/' + search;
  vm.runInNewContext(source, {
    document: { querySelector: selector => get(selector.slice(1)), createElement: tag => new Element(tag) },
    location: { search, pathname: '/' }, history: { replaceState: (_, __, value) => { url = value; } },
    URLSearchParams, Intl,
    fetch: async (path, options) => ({ ok: true, json: async () => path === '/api/knowledge/status'
      ? { documents: [], configured: false, indexed: false } : await handler(path, options) }),
  });
  return { get, url: () => url };
}
function enterZip(app, zip) {
  app.get('zip-code').value = zip;
  app.get('zip-code').fire('input');
}

test('ZIP-only submission needs no lookup and clears results on edits', async () => {
  let payload;
  const app = setup(async (url, options) => {
    assert.equal(url, '/api/comparisons');
    payload = JSON.parse(options.body);
    return saved('75201');
  });
  enterZip(app, '75201');
  assert.equal(app.get('submit').disabled, false);
  await app.get('compare-form').fire('submit');
  assert.deepEqual(Object.keys(payload).sort(), ['monthly_kwh', 'zip_code']);
  assert.equal(payload.zip_code, '75201');
  assert.ok(app.get('results').children.length);
  enterZip(app, '77002');
  assert.equal(app.get('results').children.length, 0);
  assert.equal(app.url(), '/');
});

test('invalid ZIP cannot submit; server coverage errors are displayed', async () => {
  const app = setup(async () => { throw new Error('This ZIP code is not covered by the demo lookup.'); });
  enterZip(app, '123');
  assert.equal(app.get('submit').disabled, true);
  await app.get('compare-form').fire('submit');
  assert.match(app.get('status').textContent, /five-digit/);
  enterZip(app, '99999');
  await app.get('compare-form').fire('submit');
  assert.match(app.get('status').textContent, /not covered/);
  assert.equal(app.get('submit').disabled, false);
});

test('stale comparison response cannot replace edited ZIP', async () => {
  const old = deferred();
  const app = setup(() => old.promise);
  enterZip(app, '75201');
  const pending = app.get('compare-form').fire('submit');
  enterZip(app, '77002');
  old.resolve(saved('75201'));
  await pending;
  assert.equal(app.get('results').children.length, 0);
  assert.equal(app.get('zip-code').value, '77002');
  assert.equal(app.url(), '/');
});

test('saved and legacy comparisons load without a coverage request', async () => {
  for (const zip of ['75201', null]) {
    const app = setup(async url => {
      assert.equal(url, '/api/comparisons/saved');
      return saved(zip);
    }, '?comparison=saved');
    await flush();
    assert.ok(app.get('results').children.length);
    assert.equal(app.get('zip-code').value, zip || '');
    assert.equal(app.get('submit').disabled, !zip);
  }
});

test('editing ZIP while a saved comparison loads ignores the old response', async () => {
  const old = deferred();
  const app = setup(() => old.promise, '?comparison=saved');
  enterZip(app, '77002');
  old.resolve(saved('75201'));
  await flush();
  assert.equal(app.get('zip-code').value, '77002');
  assert.equal(app.get('results').children.length, 0);
});

test('PDF mode is explicit, renders exclusions and changing mode invalidates results', async () => {
  let payload;
  const app = setup(async (_, options) => {
    payload = JSON.parse(options.body);
    return { ...saved('75201'), data_mode:'pdf', excluded_plans:[{name:'Missing rates',reasons:['TDU rates absent']}],
      recommendations:[{...saved('75201').recommendations[0],source_url:'/api/catalog/plans/id/document'}] };
  });
  enterZip(app, '75201');
  app.get('plan-source').value = 'pdf';
  await app.get('compare-form').fire('submit');
  assert.equal(payload.data_source, 'pdf');
  assert.ok(app.get('results').children.some(node => node.tag === 'details'));
  app.get('plan-source').value = 'demo';
  app.get('plan-source').fire('change');
  assert.equal(app.get('results').children.length, 0);
});


function recommendedSnapshot() {
  const plan = { plan_id:'demo', name:'Credit plan', term_months:12, estimated_annual_cost:'1800.00',
    max_scenario_regret:'330.00', additional_cost_at_supplied_usage:'0', recommendation_reasons:[],
    scenario_results:[{scenario_id:'supplied',annual_cost:'1800',rank:1,regret:'0'}],
    bill_credit_analysis:{annual_credits:'480',qualifying_months:[1],credit_loss_scenarios:[],
      threshold_exposure:[{boundary_kwh:'1000',nearby_months:[1],probes:[{kwh:'999.9999',bill:'190',credit:'0'}]}]}, evidence_refs:[] };
  return { ...saved('75201'), recommendations:[{...saved('75201').recommendations[0],plan_id:'demo',term_months:12}],
    recommendation_result:{status:'recommended',best_overall:plan,top_3:[plan],plan_analyses:[plan],
      category_winners:{lowest_estimated_cost:'demo',lowest_scenario_regret:'demo'},
      confidence:'low',confidence_reasons:['Usage is estimated.'],key_tradeoffs:['Credits depend on usage.'],
      baseline:{name:'Current plan',annual_cost:'1920'},expected_savings:{gross_annual_savings:'120',net_annual_savings:null,sustained_payback_month:null},
      warnings:['Live availability unverified.'],assumptions:[],break_even_conditions:[],evidence_refs:[],
      scenarios:[{id:'supplied',multiplier:'1'}],policy_version:'v1',comparison_horizon:12,
      options:{usage_provenance:'bills',baseline_plan_id:'demo',max_contract_months:24,switching_cost:'0'}} };
}
function allText(node) { return [node.textContent, ...node.children.map(allText)].join(' '); }

test('recommendation controls submit options and render regret, confidence, credits and unknown net savings', async () => {
  let body;
  const app = setup(async (_, options) => { body=JSON.parse(options.body); return recommendedSnapshot(); });
  enterZip(app,'75201');
  app.get('usage-provenance').value='bills'; app.get('max-contract').value='24';
  app.get('baseline-plan').value='demo'; app.get('switching-cost').value='0';
  await app.get('compare-form').fire('submit');
  assert.deepEqual(body.recommendation_options,{usage_provenance:'bills',max_contract_months:24,baseline_plan_id:'demo',switching_cost:'0'});
  const text=allText(app.get('results'));
  for (const phrase of ['Your recommendation','330.00','confidence: low','480.00','999.9999','Net after switching costs: unknown']) assert.ok(text.includes(phrase),phrase);
  app.get('switching-cost').value='50'; app.get('switching-cost').fire('input');
  assert.equal(app.get('results').children.length,0);
});

test('recommendation options restore and ZIP edits clear the baseline', async () => {
  const app=setup(async () => recommendedSnapshot(),'?comparison=saved');
  await flush();
  assert.equal(app.get('baseline-plan').value,'demo');
  assert.equal(app.get('max-contract').value,'24');
  assert.equal(app.get('switching-cost').value,'0');
  assert.equal(app.get('usage-provenance').value,'bills');
  enterZip(app,'77002');
  assert.equal(app.get('baseline-plan').value,'');
});

test('no qualifying recommendation does not claim a winner, and invalid costs never submit', async () => {
  let calls=0;
  const app=setup(async () => {
    calls++;
    return {...saved('75201'),recommendation_result:{status:'no_eligible_plans',best_overall:null,warnings:[],options:{}}};
  });
  enterZip(app,'75201');
  app.get('switching-cost').value='-1';
  await app.get('compare-form').fire('submit');
  assert.equal(calls,0);
  app.get('switching-cost').value='';
  await app.get('compare-form').fire('submit');
  assert.match(allText(app.get('results')),/No plan meets/);
});


test('saved contract preference separates longer plans while retaining baseline choices and bills', async () => {
  const snapshot = recommendedSnapshot();
  snapshot.recommendation_result.options.max_contract_months = 12;
  snapshot.recommendations.push({...snapshot.recommendations[0], plan_id:'long', name:'Long contract', term_months:24});
  const app = setup(async () => snapshot, '?comparison=saved');
  await flush();
  const results = app.get('results');
  const rows = results.children.filter(n => n.className === 'plan-row');
  assert.equal(rows.length, 1);
  assert.ok(!allText(rows[0]).includes('Long contract'));
  const outside = results.children.find(n => n.className === 'longer-contracts');
  assert.ok(outside && !outside.open);
  assert.match(allText(outside), /Long contract/);
  assert.match(allText(outside), /Monthly cost breakdown/);
  assert.match(allText(results), /Maximum contract: 12 months/);
  assert.equal(app.get('baseline-plan').children.length, 3);
  snapshot.recommendation_result.options.max_contract_months = null;
  const unrestricted = setup(async () => snapshot, '?comparison=saved');
  await flush();
  assert.equal(unrestricted.get('results').children.filter(n => n.className === 'plan-row').length, 2);
  assert.ok(!unrestricted.get('results').children.some(n => n.className === 'longer-contracts'));
});
const assertPreferences = text => {
  for (const phrase of ['Applied preferences', 'up to 24 months', 'Electricity bills', 'Current plan: Current plan', 'Entered switching costs: $0.00']) assert.ok(text.includes(phrase), phrase);
};
test('all saved preferences are visible and negative savings are prominent', async () => {
  const data = recommendedSnapshot();
  data.recommendation_result.expected_savings.net_annual_savings = '-80';
  data.recommendation_result.expected_savings.switching_cost = '200';
  const app = setup(async () => data, '?comparison=saved');
  await flush();
  assertPreferences(allText(app.get('results')));
  const panel = app.get('results').children.find(n => n.className === 'recommendation-summary');
  assert.ok(panel.children.some(n => n.className === 'result-warning' && n.textContent.includes('Switching costs exceed')));
});
test('switching costs without a baseline are explicitly unapplied and unknown differs from zero', async () => {
  for (const cost of [null, '0', '50']) {
    const data = recommendedSnapshot();
    data.recommendation_result.baseline = null;
    data.recommendation_result.expected_savings = null;
    data.recommendation_result.options.baseline_plan_id = null;
    data.recommendation_result.options.switching_cost = cost;
    const app = setup(async () => data, '?comparison=saved');
    await flush();
    const text = allText(app.get('results'));
    assert.ok(text.includes(`Entered switching costs: ${cost === null ? 'Unknown' : cost === '0' ? '$0.00' : '$50.00'}`));
    assert.equal(text.includes('apply these switching costs to savings'), cost !== null);
  }
});
test('no eligible recommendation still displays all applied preferences', async () => {
  const data = recommendedSnapshot();
  data.recommendation_result.best_overall = null;
  const app = setup(async () => data, '?comparison=saved');
  await flush();
  assertPreferences(allText(app.get('results')));
});

test('renewal options submit and restore and horizon totals drive visible costs', async () => {
  const data = recommendedSnapshot();
  const rec = data.recommendation_result;
  rec.comparison_horizon = 24; rec.policy_version = 'horizon-renewal-v2';
  rec.options.renewal_escalation_pct = '8'; rec.options.renewal_credit_policy = 'drop';
  rec.best_overall.horizon_cost = '4000';
  rec.expected_savings.gross_horizon_savings = '400'; rec.expected_savings.net_horizon_savings = '250';
  let payload;
  const app = setup(async (_, options) => { payload = JSON.parse(options.body); return data; });
  enterZip(app, '75201'); app.get('max-contract').value = '24';
  app.get('renewal-escalation').value = '8'; app.get('renewal-credits').value = 'drop';
  await app.get('compare-form').fire('submit');
  assert.equal(payload.recommendation_options.renewal_escalation_pct, '8');
  assert.equal(payload.recommendation_options.renewal_credit_policy, 'drop');
  const text = allText(app.get('results'));
  for (const phrase of ['Estimated 24-month cost', '$4,000.00', '$166.67', 'Net after switching costs: $250.00']) assert.ok(text.includes(phrase), phrase);
  app.get('renewal-escalation').fire('input');
  assert.equal(app.get('results').children.length, 0);
  const restored = setup(async () => data, '?comparison=saved');
  await flush();
  assert.equal(restored.get('renewal-escalation').value, '8');
  assert.equal(restored.get('renewal-credits').value, 'drop');
});

test('average price maps EFL reference ranges including fractional boundaries without changing bills', async () => {
  const data = saved('75201');
  const plan = data.recommendations[0];
  plan.efl_price_examples = [
    {kwh:'500',cents_per_kwh:'19.7',page:1,quote:'500 kWh | 19.7 cents'},
    {kwh:'1000',cents_per_kwh:'6.8',page:1,quote:'1000 kWh | 6.8 cents'},
    {kwh:'2000',cents_per_kwh:'12.8',page:1,quote:'2000 kWh | 12.8 cents'}];
  plan.efl_price_examples.reverse();
  plan.horizon_monthly_costs = ['500','1000','2000','999.9','0','1000','500.1','1000.1','2000.1'].map((kwh,i) => ({
    ...plan.monthly_costs[0],month:i+1,kwh,basis:i===5?'modeled_renewal':'document_terms'}));
  const app=setup(async () => data,'?comparison=saved');
  await flush();
  const flatten = n => [n,...n.children.flatMap(flatten)];
  const nodes = flatten(app.get('results'));
  const header = nodes.find(n => n.tag==='thead').children[0].children.map(n => n.textContent);
  assert.deepEqual(header.slice(2,5), ['Energy','Average Price / EFL reference (\u00a2/kWh)','Base fee']);
  const rows = nodes.find(n => n.tag==='tbody').children;
  assert.deepEqual(rows.map(row => row.children[3].textContent), ['19.7','19.7','6.8','19.7','19.7','Not available (renewal)','19.7','6.8','12.8']);
  delete plan.efl_price_examples;
  const legacy=setup(async () => data,'?comparison=saved');
  await flush();
  assert.equal(flatten(legacy.get('results')).find(n => n.tag==='tbody').children[0].children[3].textContent,'Not listed');
});


test('inclusive EFL estimates show their actual rate, included charges and unchanged total', async () => {
  const data=recommendedSnapshot();
  data.recommendation_result.policy_version='efl-average-v3';
  for (const p of data.recommendation_result.plan_analyses) p.bill_credit_analysis={status:'included_in_average'};
  const plan=data.recommendations[0];
  plan.pricing_basis='efl_average';
  plan.horizon_monthly_costs=[
    {month:1,kwh:'1800',energy:'122.40',average_price_cents:'6.8',base_fee:'0',delivery:'0',credit:'0',total:'122.40',basis:'document_terms'},
    {month:13,kwh:'1800',energy:'128.52',average_price_cents:'7.14',base_fee:'0',delivery:'0',credit:'0',total:'128.52',basis:'modeled_renewal'}];
  const app=setup(async()=>data,'?comparison=saved');
  await flush();
  const flatten=n=>[n,...n.children.flatMap(flatten)];
  const nodes=flatten(app.get('results'));
  const rows=flatten(nodes.find(n=>n.className==='plan-row')).find(n=>n.tag==='tbody').children;
  assert.deepEqual(rows[0].children.map(n=>n.textContent),['1','1800','$122.40','6.8','Included','Included','Included','$122.40','Document terms']);
  assert.deepEqual(rows[1].children.map(n=>n.textContent),['13','1800','$128.52','7.14','Included','Included','Included','$128.52','Modeled renewal']);
  const text=allText(app.get('results'));
  assert.ok(text.includes('Estimated charge (all-in)'));
  assert.ok(text.includes('Separate renewal credit settings do not apply'));
  assert.ok(text.includes('Separate credit amounts and eligibility are not calculated'));
  assert.ok(!text.includes('No usage-dependent credit boundaries.'));
});


test('custom EFL energy shows numeric fees and credits and identifies the custom total', async () => {
  const data=recommendedSnapshot();
  data.recommendation_result.policy_version='custom-efl-v4';
  const plan=data.recommendations[0];
  plan.pricing_basis='custom_efl';
  plan.horizon_monthly_costs=[{month:1,kwh:'1800',energy:'122.40',average_price_cents:'6.8',base_fee:'0',delivery:'112.59',credit:'125',total:'109.99',basis:'document_terms'}];
  const app=setup(async()=>data,'?comparison=saved');await flush();
  const flatten=n=>[n,...n.children.flatMap(flatten)];
  const nodes=flatten(app.get('results'));
  const card=nodes.find(n=>n.className==='plan-row');
  const row=flatten(card).find(n=>n.tag==='tbody').children[0];
  assert.deepEqual(row.children.map(n=>n.textContent),['1','1800','$122.40','6.8','$0.00','$112.59','$125.00','$109.99','Custom estimate']);
  assert.ok(allText(card).includes('Total (custom)'));
  assert.ok(allText(app.get('results')).includes('not an actual tariff bill'));
});


test('plan details disclose only actual modeled renewal using saved percentage', async () => {
  const data=recommendedSnapshot();
  const plan=data.recommendations[0];
  plan.horizon_monthly_costs=[{month:1,basis:'document_terms'}, {month:14,basis:'modeled_renewal'}, {month:13,basis:'modeled_renewal'}];
  const flatten=n=>[n,...n.children.flatMap(flatten)];
  for (const rate of ['8','0',null]) {
    data.recommendation_result.options.renewal_escalation_pct=rate;
    const app=setup(async()=>data,'?comparison=saved');await flush();
    const notes=flatten(app.get('results')).filter(n=>n.className==='renewal-note note');
    assert.equal(notes.length,1);
    assert.ok(notes[0].textContent.includes(rate==null ? 'percentage not recorded' : `assumption: ${rate}%`));
    assert.ok(notes[0].textContent.includes('from month 13 for 2 modeled month(s)'));
    assert.ok(notes[0].textContent.includes('not a confirmed renewal offer'));
  }
  plan.horizon_monthly_costs=[{month:1,basis:'document_terms'}];
  let app=setup(async()=>data,'?comparison=saved');await flush();
  assert.equal(flatten(app.get('results')).filter(n=>n.className==='renewal-note note').length,0);
  delete plan.horizon_monthly_costs;
  app=setup(async()=>data,'?comparison=saved');await flush();
  assert.equal(flatten(app.get('results')).filter(n=>n.className==='renewal-note note').length,0);
});
