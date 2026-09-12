const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
function setup(search = '') {
  const panels = [{ hidden: false, content: { draft: 'My question' } }, { hidden: true, content: { zip: '75201', results: ['saved'] } }];
  const tabs = panels.map((panel, index) => ({
    attributes: { 'aria-controls': String(index) }, listeners: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    getAttribute(key) { return this.attributes[key]; },
    addEventListener(key, fn) { this.listeners[key] = fn; },
    focus() { this.focused = true; },
  }));
  vm.runInNewContext(readFileSync('frontend/tabs.js', 'utf8'), {
    document: { querySelectorAll: () => tabs, getElementById: id => panels[Number(id)] },
    URLSearchParams, location: { search },
  });
  return { tabs, panels };
}
test('tabs default to assistant and preserve both workspaces on repeated switches', () => {
  const { tabs, panels } = setup();
  const content = panels.map(panel => panel.content);
  assert.equal(panels[0].hidden, false);
  assert.equal(panels[1].hidden, true);
  for (const index of [1, 0, 1]) {
    tabs[index].listeners.click();
    assert.equal(panels[index].hidden, false);
    assert.equal(panels[1-index].hidden, true);
    assert.equal(tabs[index].attributes['aria-selected'], 'true');
    assert.equal(tabs[index].tabIndex, 0);
    assert.equal(tabs[1-index].tabIndex, -1);
  }
  panels.forEach((panel, index) => assert.equal(panel.content, content[index]));
});
test('saved links select comparison immediately; empty query still opens assistant', () => {
  assert.equal(setup('?comparison=saved').panels[1].hidden, false);
  assert.equal(setup('?comparison=').panels[0].hidden, false);
});
test('arrow keys wrap; Home and End activate and focus the selected tab', () => {
  const { tabs, panels } = setup();
  for (const [from, key, target] of [[0,'ArrowLeft',1],[1,'ArrowRight',0],[0,'End',1],[1,'Home',0]]) {
    let prevented = false;
    tabs[from].listeners.keydown({key, preventDefault() { prevented = true; }});
    assert.ok(prevented);
    assert.ok(tabs[target].focused);
    assert.equal(panels[target].hidden, false);
  }
});
