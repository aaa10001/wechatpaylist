/* 无头冒烟测试：用假 DOM 跑一遍 app.js 的启动与渲染，捕获运行期异常。
 * 目的不是像素级验证，而是确保「数据 -> 聚合 -> 图表/表格」整条链路不抛错。 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function makeEl(tag) {
  const el = {
    tagName: tag || 'div',
    children: [],
    attrs: {},
    style: {},
    dataset: {},
    innerHTML: '',
    textContent: '',
    value: '',
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener() {},
    removeEventListener() {},
    closest() { return null; },
    focus() {},
    showModal() {},
    close() {},
    click() {},
    querySelector() { return makeEl('div'); }
  };
  return el;
}

const registry = new Map();

const documentStub = {
  body: makeEl('body'),
  createElement: (tag) => makeEl(tag),
  createElementNS: (_ns, tag) => makeEl(tag),
  querySelector(sel) {
    if (!registry.has(sel)) registry.set(sel, makeEl('div'));
    return registry.get(sel);
  },
  querySelectorAll() { return []; }
};

const windowStub = {
  MONEYLENS: null,
  confirm: () => false,
  prompt: () => null,
  localStorage: {
    _m: new Map(),
    getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
    setItem(k, v) { this._m.set(k, String(v)); },
    removeItem(k) { this._m.delete(k); }
  }
};

const sandbox = {
  window: windowStub,
  document: documentStub,
  localStorage: windowStub.localStorage,
  console,
  Date,
  Math,
  JSON,
  Number,
  String,
  Object,
  Array,
  Map,
  Set,
  Blob: class {},
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  CSS: { escape: (s) => s },
  isFinite,
  setTimeout,
  clearTimeout
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const root = path.resolve(__dirname, '..', 'web');
for (const file of ['data.js', 'app.js']) {
  const code = fs.readFileSync(path.join(root, file), 'utf8');
  vm.runInContext(code, sandbox, { filename: file });
}

const data = windowStub.MONEYLENS;
const checks = [];
const assert = (ok, label) => checks.push({ ok: Boolean(ok), label });

assert(data, 'data.js 注入 window.MONEYLENS');
assert(data && Array.isArray(data.transactions) && data.transactions.length > 0, 'transactions 非空: ' + (data ? data.transactions.length : 0));
assert(data && data.overview && typeof data.overview.consumption === 'number', 'overview.consumption 为数值');
assert(data && Array.isArray(data.monthly) && data.monthly.length > 0, 'monthly 非空');
assert(data && Array.isArray(data.budgets) && data.budgets.length > 0, 'budgets 非空');

const kpiHtml = registry.get('#kpis').innerHTML;
assert(kpiHtml.includes('消费净额'), 'KPI 卡片已渲染');
assert(kpiHtml.includes('日均消费'), 'KPI 含日均消费');

const monthly = registry.get('#monthlyChart');
assert(monthly.children.length > 0, '月度图 SVG 已创建节点: ' + monthly.children.length + ' 个');
const daily = registry.get('#dailyChart');
assert(daily.children.length > 0, '日曲线 SVG 已创建节点: ' + daily.children.length + ' 个');
const donut = registry.get('#donut');
assert(donut.children.length > 0, '环图 SVG 已创建节点: ' + donut.children.length + ' 个');

const review = registry.get('#review').innerHTML;
assert(review.includes('review-row') || review.includes('review-empty'), '待确认队列已渲染');
const table = registry.get('#txTable tbody').innerHTML;
assert(table.includes('<tr>'), '明细表已渲染行');

let failed = 0;
for (const c of checks) {
  if (!c.ok) failed++;
  console.log((c.ok ? 'PASS ' : 'FAIL ') + c.label);
}
console.log(`\n${checks.length - failed}/${checks.length} 通过`);
process.exit(failed ? 1 : 0);