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
