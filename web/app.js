/* MoneyLens 前端：纯原生 JS + 手写 SVG 图表，无外部依赖，file:// 直接可开。
 * 所有派生指标都在浏览器里按「当前筛选 + 本地人工确认」实时重算，
 * 这样在界面上确认一条分类，图表会立刻变化——人机协作闭环在演示时看得见。 */
(function () {
  'use strict';

  var DATA = window.MONEYLENS;
  if (!DATA) {
    document.body.innerHTML = '<p style="padding:40px;font-family:sans-serif">缺少 data.js，请先运行 <code>python -m moneylens.build</code>。</p>';
    return;
  }

  var LS = { overrides: 'ml_overrides_v1', manual: 'ml_manual_v1', budget: 'ml_budget_v1' };
  var SYSTEM = ['待确认', '退款', '不计收支', '还款'];
  var ALL_CATEGORIES = ['餐饮', '交通', '购物', '校园', '生活缴费', '学习', '健身', '娱乐',
    '医疗', '居住', '通讯', '生活服务', '公益', '人情往来', '还款', '退款', '不计收支', '待确认', '其他'];
  var COLORS = {
    '购物': '#2f5d50', '待确认': '#c4bba9', '学习': '#8c5b3f', '交通': '#46697a',
    '校园': '#6d7f4e', '生活缴费': '#a8823c', '餐饮': '#b3612f', '娱乐': '#6b5b7a',
    '公益': '#5f7a5a', '其他': '#a89f92', '生活服务': '#9b6b5a', '医疗': '#a33b32',
    '健身': '#8a7b52', '人情往来': '#7d5a6b', '还款': '#8d8579', '退款': '#cfc7b9',
    '不计收支': '#ddd6c9', '居住': '#4d6b7f', '通讯': '#6f7f52'
  };
  var INK = { ink: '#1d1913', ink2: '#5b5346', ink3: '#7c7364', rule: '#dcd4c4', ruleSoft: '#eae4d8', green: '#1d5c4a', clay: '#a94f2c', ochre: '#96701f' };
  var BUCKET_LABEL = {
    consumption: '消费', income: '收入', transfer: '转账',
    refund: '退款', neutral: '中性', settlement: '还款'
  };
  var SOURCE_LABEL = { rule: '规则', ai: 'AI', override: '人工', review: '待确认', default: '未匹配', manual: '手动' };

  var $ = function (sel) { return document.querySelector(sel); };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v) { return Number(v || 0); }
  function amountText(v) {
    return num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function money(v) { return '¥' + amountText(v); }
  function money0(v) { return '¥' + Math.round(num(v)).toLocaleString('zh-CN'); }
  function pct(v) { return (num(v)).toFixed(1) + '%'; }
  function colorOf(cat) { return COLORS[cat] || '#8b93a3'; }
  function load(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 隐私模式忽略 */ }
  }

  var state = {
    base: DATA.transactions.map(function (t) { return Object.assign({}, t); }),
    manual: load(LS.manual, []),
    overrides: load(LS.overrides, {}),
    limits: load(LS.budget, null) || (function () {
      var m = {};
      DATA.budgets.forEach(function (b) { m[b.category] = b.limit; });
      return m;
    })(),
    month: 'all',
    category: 'all',
    source: 'all',
    query: ''
  };

  /* ---------- 数据合并与口径 ---------- */

  function allTxs() {
    var list = state.base.concat(state.manual);
    return list.map(function (t) {
      var cat = state.overrides[t.id];
      return cat ? Object.assign({}, t, { category: cat, category_source: 'override' }) : t;
    });
  }

  function scoped() {
    var list = allTxs();
    return state.month === 'all' ? list : list.filter(function (t) { return t.month === state.month; });
  }

  function daysFor(month) {
    if (month === 'all') return DATA.overview.days;
    var m = DATA.monthly.filter(function (x) { return x.month === month; })[0];
    return m ? m.covered_days : 30;
  }

  function summarize(txs) {
    var cons = [], inc = [], tra = [];
    txs.forEach(function (t) {
      if (t.bucket === 'consumption') cons.push(t);
      else if (t.bucket === 'income') inc.push(t);
      else if (t.bucket === 'transfer') tra.push(t);
    });
    var sum = function (arr) { return arr.reduce(function (a, t) { return a + num(t.net); }, 0); };
    var transferOut = sum(tra.filter(function (t) { return t.direction === 'expense'; }));
    var transferIn = sum(tra.filter(function (t) { return t.direction === 'income'; }));
    var consumption = sum(cons);
    var income = sum(inc);
    var biggest = cons.reduce(function (m, t) { return !m || num(t.net) > num(m.net) ? t : m; }, null);
    return {
      cons: cons, inc: inc, tra: tra,
      consumption: consumption, income: income,
      refund: txs.reduce(function (a, t) { return a + num(t.refund); }, 0),
      transferOut: transferOut, transferIn: transferIn,
      balance: income + transferIn - consumption - transferOut,
      count: cons.length, biggest: biggest
    };
  }

  function byCategory(cons) {
    var map = {};
    cons.forEach(function (t) {
      if (!map[t.category]) map[t.category] = { category: t.category, amount: 0, count: 0 };
      map[t.category].amount += num(t.net);
      map[t.category].count += 1;
    });
    var total = Object.keys(map).reduce(function (a, k) { return a + map[k].amount; }, 0);
    return Object.keys(map).map(function (k) {
      map[k].share = total ? map[k].amount / total * 100 : 0;
      return map[k];
    }).sort(function (a, b) { return b.amount - a.amount; });
  }

  function monthlySeries() {
    var map = {};
    allTxs().forEach(function (t) {
      if (!map[t.month]) map[t.month] = { month: t.month, consumption: 0, income: 0, count: 0, days: 30, complete: true };
      var row = map[t.month];
      if (t.bucket === 'consumption') { row.consumption += num(t.net); row.count += 1; }
      if (t.bucket === 'income') row.income += num(t.net);
    });
    return Object.keys(map).sort().map(function (m) {
      var row = map[m];
      var meta = DATA.monthly.filter(function (x) { return x.month === m; })[0];
      if (meta) { row.days = meta.covered_days; row.complete = meta.complete; }
      row.avg = row.consumption / (row.days || 1);
      return row;
    });
  }

  /* ---------- SVG 工具 ---------- */

  var NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }
  function makeSvg(w, h) {
    var root = svg('svg', { viewBox: '0 0 ' + w + ' ' + h, role: 'img' });
    return root;
  }
  function text(x, y, str, attrs) {
    var node = svg('text', Object.assign({ x: x, y: y }, attrs || {}));
    node.textContent = str;
    return node;
  }

  /* ---------- 月度趋势：柱=消费总额，线=日均（双刻度） ---------- */

  function drawMonthly() {
    var host = $('#monthlyChart');
    host.innerHTML = '';
    var data = monthlySeries();
    if (!data.length) return;

    var W = 660, H = 300, P = { l: 56, r: 46, t: 32, b: 42 };
    var iw = W - P.l - P.r, ih = H - P.t - P.b;
    var root = makeSvg(W, H);
    var maxTotal = Math.max.apply(null, data.map(function (d) { return d.consumption; })) * 1.25 || 1;
    var maxAvg = Math.max.apply(null, data.map(function (d) { return d.avg; })) * 1.4 || 1;
    var band = iw / data.length;
    var bw = Math.min(44, band * 0.42);
    var yT = function (v) { return P.t + ih - v / maxTotal * ih; };
    var yA = function (v) { return P.t + ih - v / maxAvg * ih; };
    var ticks = 4;

    for (var i = 0; i <= ticks; i++) {
      var gy = P.t + ih - ih * i / ticks;
      root.appendChild(svg('line', { x1: P.l, y1: gy, x2: W - P.r, y2: gy, stroke: INK.ruleSoft, 'stroke-width': 1 }));
      root.appendChild(text(P.l - 10, gy + 3.5, money0(maxTotal * i / ticks), { 'text-anchor': 'end', class: 'bar-label', fill: INK.ink3 }));
    }

    data.forEach(function (d, idx) {
      var cx = P.l + band * idx + band / 2;
      var selected = state.month === d.month;
      var h = Math.max(2, P.t + ih - yT(d.consumption));
      root.appendChild(svg('rect', {
        x: cx - bw / 2, y: yT(d.consumption), width: bw, height: h,
        rx: 2,
        fill: selected ? INK.green : '#cfc7b6',
        opacity: d.complete ? 1 : 0.42,
        stroke: d.complete ? 'none' : INK.ink3, 'stroke-width': d.complete ? 0 : 1,
        'stroke-dasharray': d.complete ? 'none' : '3 3'
      }));
      root.appendChild(text(cx, yT(d.consumption) - 9, money0(d.consumption), {
        'text-anchor': 'middle', class: 'bar-label', fill: selected ? INK.ink : INK.ink2
      }));
      var label = d.month.slice(2).replace('-', '/') + (d.complete ? '' : '*');
      root.appendChild(text(cx, H - P.b + 20, label, { 'text-anchor': 'middle', class: 'bar-label', fill: INK.ink3 }));
    });

    var path = data.map(function (d, idx) {
      var x = P.l + band * idx + band / 2;
      return (idx ? 'L' : 'M') + x + ',' + yA(d.avg);
    }).join(' ');
    root.appendChild(svg('path', { d: path, fill: 'none', stroke: INK.clay, 'stroke-width': 1.6, 'stroke-linejoin': 'round' }));
    data.forEach(function (d, idx) {
      var x = P.l + band * idx + band / 2;
      root.appendChild(svg('circle', { cx: x, cy: yA(d.avg), r: 3, fill: '#fbf9f4', stroke: INK.clay, 'stroke-width': 1.6 }));
      root.appendChild(text(x + 9, yA(d.avg) - 7, money0(d.avg), { class: 'bar-label', fill: INK.clay }));
    });

    root.appendChild(text(W - P.r + 10, P.t - 12, '日均', { class: 'bar-label', fill: INK.clay, 'text-anchor': 'end' }));
    host.appendChild(root);
  }

  /* ---------- 分类环图 ---------- */

  function drawDonut(cats, total) {
    var host = $('#donut');
    host.innerHTML = '';
    var legend = $('#legend');
    legend.innerHTML = '';

    var size = 200, r = 76, cx = size / 2, cy = size / 2, C = 2 * Math.PI * r;
    var root = makeSvg(size, size);
    root.appendChild(svg('circle', { cx: cx, cy: cy, r: r, fill: 'none', stroke: '#ece6d9', 'stroke-width': 16 }));

    var offset = 0;
    cats.forEach(function (c) {
      var len = Math.max(0, c.share / 100 * C);
      if (len <= 0) return;
      root.appendChild(svg('circle', {
        cx: cx, cy: cy, r: r, fill: 'none',
        stroke: colorOf(c.category), 'stroke-width': 16,
        'stroke-dasharray': Math.max(1, len - 2) + ' ' + (C - len + 2),
        'stroke-dashoffset': -offset,
        transform: 'rotate(-90 ' + cx + ' ' + cy + ')'
      }));
      offset += len;
    });

    root.appendChild(text(cx, cy + 2, money0(total), { 'text-anchor': 'middle', class: 'donut-total' }));
    root.appendChild(text(cx, cy + 24, '消费净额', { 'text-anchor': 'middle', class: 'donut-center' }));
    host.appendChild(root);

    cats.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'legend-row';
      row.innerHTML =
        '<span class="legend-dot" style="background:' + colorOf(c.category) + '"></span>' +
        '<span class="legend-name">' + esc(c.category) + '</span>' +
        '<span class="legend-val">' + money(c.amount) + '</span>' +
        '<span class="legend-share">' + pct(c.share) + '</span>';
      legend.appendChild(row);
    });
  }

  /* ---------- 日消费曲线 ---------- */

  function dayList(txs) {
    var map = {};
    txs.forEach(function (t) {
      if (t.bucket !== 'consumption') return;
      map[t.day] = (map[t.day] || 0) + num(t.net);
    });
    var days = Object.keys(map).sort();
    if (!days.length) return [];

    var start, end;
    if (state.month !== 'all') {
      var parts = state.month.split('-').map(Number);
      start = state.month + '-01';
      end = state.month + '-' + String(new Date(parts[0], parts[1], 0).getDate()).padStart(2, '0');
    } else {
      start = DATA.overview.period_start;
      end = DATA.overview.period_end;
    }
    var out = [];
    var cur = new Date(start + 'T00:00:00');
    var last = new Date(end + 'T00:00:00');
    var guard = 0;
    while (cur <= last && guard < 400) {
      var key = cur.getFullYear() + '-' + String(cur.getMonth() + 1).padStart(2, '0') + '-' + String(cur.getDate()).padStart(2, '0');
      out.push({ day: key, value: map[key] || 0 });
      cur.setDate(cur.getDate() + 1);
      guard++;
    }
    return out;
  }

  function drawDaily(txs) {
    var host = $('#dailyChart');
    host.innerHTML = '';
    var data = dayList(txs);
    if (!data.length) return;

    var W = 960, H = 230, P = { l: 46, r: 14, t: 16, b: 30 };
    var iw = W - P.l - P.r, ih = H - P.t - P.b;
    var max = Math.max.apply(null, data.map(function (d) { return d.value; })) * 1.15 || 1;
    var x = function (i) { return P.l + (data.length === 1 ? iw / 2 : i * iw / (data.length - 1)); };
    var y = function (v) { return P.t + ih - v / max * ih; };
    var root = makeSvg(W, H);

    for (var i = 0; i <= 3; i++) {
      var gy = P.t + ih - ih * i / 3;
      root.appendChild(svg('line', { x1: P.l, y1: gy, x2: W - P.r, y2: gy, stroke: INK.ruleSoft, 'stroke-width': 1 }));
      root.appendChild(text(P.l - 10, gy + 3.5, money0(max * i / 3), { 'text-anchor': 'end', class: 'bar-label', fill: INK.ink3 }));
    }

    var line = data.map(function (d, i) { return (i ? 'L' : 'M') + x(i) + ',' + y(d.value); }).join(' ');
    root.appendChild(svg('path', {
      d: line + ' L' + x(data.length - 1) + ',' + (P.t + ih) + ' L' + x(0) + ',' + (P.t + ih) + ' Z',
      fill: 'rgba(29,92,74,.07)', stroke: 'none'
    }));
    root.appendChild(svg('path', { d: line, fill: 'none', stroke: INK.green, 'stroke-width': 1.5, 'stroke-linejoin': 'round' }));

    var step = Math.max(1, Math.floor(data.length / 7));
    data.forEach(function (d, i) {
      if (i % step === 0 || i === data.length - 1) {
        root.appendChild(text(x(i), H - P.b + 20, d.day.slice(5), { 'text-anchor': 'middle', class: 'bar-label', fill: INK.ink3 }));
      }
    });
    host.appendChild(root);
  }

  /* ---------- KPI ---------- */

  function drawKpis(s) {
    var host = $('#kpis');
    var days = daysFor(state.month);
    var avg = days ? s.consumption / days : 0;
    var netTransfer = s.transferIn - s.transferOut;
    var rangeLabel = state.month === 'all' ? '全部账单期' : state.month;
    var facts = [
      { label: '日均消费', value: money(avg), sub: days + ' 天窗口' },
      { label: '收入净额', value: money(s.income), sub: '不含退款' },
      { label: '退款冲抵', value: money(s.refund), sub: '已从支出扣除' },
      { label: '转账净额', value: (netTransfer >= 0 ? '+' : '') + money(netTransfer), sub: '不计入消费', cls: netTransfer >= 0 ? 'pos' : 'neg' },
      { label: '净结余', value: (s.balance >= 0 ? '+' : '') + money(s.balance), sub: '现金净变化', cls: s.balance >= 0 ? 'pos' : 'neg' }
    ];
    host.innerHTML =
      '<div class="ledger-main">' +
        '<span class="eyebrow">本期消费净额 · ' + esc(rangeLabel) + '</span>' +
        '<div class="hero-number"><span class="unit">¥</span>' + esc(amountText(s.consumption)) + '</div>' +
        '<div class="hero-sub"><b>' + s.count + '</b> 笔消费 · <b>' + days + '</b> 天 · 已扣退款 ' + money(s.refund) + '</div>' +
      '</div>' +
      '<div class="ledger-facts">' +
        facts.map(function (f) {
          return '<div class="fact">' +
            '<span class="fact-label">' + esc(f.label) + '</span>' +
            '<div class="fact-value ' + (f.cls || '') + '">' + esc(f.value) + '</div>' +
            '<div class="fact-sub">' + esc(f.sub) + '</div>' +
            '</div>';
        }).join('') +
      '</div>';
  }

  /* ---------- 预算 ---------- */

  function drawBudgets() {
    var month = state.month === 'all' ? DATA.budget_month : state.month;
    var meta = DATA.monthly.filter(function (m) { return m.month === month; })[0];
    if (!meta) meta = DATA.monthly[DATA.monthly.length - 1];
    var days = Math.max(meta.covered_days, 1);
    var dim = meta.days_in_month || 30;
    var txs = allTxs().filter(function (t) { return t.month === month && t.bucket === 'consumption'; });
    var spentMap = {};
    txs.forEach(function (t) { spentMap[t.category] = (spentMap[t.category] || 0) + num(t.net); });

    $('#budgetHint').textContent = month + (meta.complete ? '（完整月）' : '（进行中，按日均推算月末）');

    var rows = Object.keys(state.limits).map(function (cat) {
      var limit = Number(state.limits[cat]) || 0;
      var spent = spentMap[cat] || 0;
      var p = limit ? spent / limit * 100 : 0;
      var projected = meta.complete ? spent : spent / days * dim;
      var status = p >= 100 ? 'over' : p >= 80 ? 'warn' : 'ok';
      return { cat: cat, limit: limit, spent: spent, pct: p, projected: projected, status: status };
    }).sort(function (a, b) { return b.pct - a.pct; });

    var host = $('#budgets');
    host.innerHTML = rows.map(function (r) {
      var pctText = r.pct.toFixed(1) + '%';
      var statusText = r.status === 'over' ? '已超支' : r.status === 'warn' ? '接近上限' : '正常';
      return '<div class="budget-row">' +
        '<span class="budget-name">' + esc(r.cat) + '<button class="budget-edit" data-cat="' + esc(r.cat) + '" title="调整预算">改</button></span>' +
        '<div class="budget-track"><div class="budget-fill ' + r.status + '" style="width:' + Math.min(100, r.pct) + '%"></div>' +
        '<div class="budget-mark" style="left:80%"></div></div>' +
        '<div class="budget-num"><b>' + money(r.spent) + '</b> / ' + money0(r.limit) + '</div>' +
        '<div class="budget-sub">' + pctText + ' · ' + statusText + ' · 月末预计 ' + money(r.projected) + '</div>' +
        '</div>';
    }).join('');
  }

  /* ---------- 待确认队列 ---------- */

  function drawReview() {
    var all = allTxs();
    var items = all.filter(function (t) {
      return t.bucket === 'consumption' && (t.category_source === 'review' || t.category_source === 'default');
    }).sort(function (a, b) { return num(b.amount) - num(a.amount); });

    $('#reviewBadge').textContent = items.length;
    var host = $('#review');
    if (!items.length) {
      host.innerHTML = '<div class="review-empty">全部确认完毕，图表已按你的判断重算。</div>';
      return;
    }

    var options = ALL_CATEGORIES.filter(function (c) { return SYSTEM.indexOf(c) < 0 && c !== '其他'; });
    host.innerHTML = items.slice(0, 40).map(function (t) {
      var opts = '<option value="">选择分类…</option>' + options.map(function (c) {
        return '<option value="' + esc(c) + '">' + esc(c) + '</option>';
      }).join('');
      return '<div class="review-row">' +
        '<div class="review-main">' +
        '<div class="review-party">' + esc(t.counterparty) + '</div>' +
        '<div class="review-meta">' + esc(t.day) + ' · ' + esc(t.product || t.type) + '</div>' +
        '</div>' +
        '<div class="review-amount">' + money(t.amount) + '</div>' +
        '<div class="review-controls">' +
        '<select data-id="' + esc(t.id) + '">' + opts + '</select>' +
        '<button class="btn small" data-confirm="' + esc(t.id) + '">确认</button>' +
        '</div>' +
        '</div>';
    }).join('') + (items.length > 40 ? '<div class="review-empty">还有 ' + (items.length - 40) + ' 条，先处理金额最大的。</div>' : '');
  }

  /* ---------- 洞察 ---------- */

  function drawInsights(s) {
    var cats = byCategory(s.cons);
    var lines = [];
    if (cats.length) {
      lines.push('最大支出分类是「' + cats[0].category + '」，' + money(cats[0].amount) + '，占消费 ' + pct(cats[0].share) + '。');
    }
    var days = daysFor(state.month);
    lines.push('消费合计 ' + money(s.consumption) + '，日均 ' + money(days ? s.consumption / days : 0) + '，共 ' + s.count + ' 笔。');
    if (s.refund > 0) {
      var n = allTxs().filter(function (t) { return num(t.refund) > 0; }).length;
      lines.push('退款 ' + n + ' 笔共 ' + money(s.refund) + '，已在支出中冲抵，未重复计入收入。');
    }
    if (s.transferIn || s.transferOut) {
      lines.push('转账往来净' + (s.transferIn - s.transferOut >= 0 ? '流入 ' : '流出 ') + money(Math.abs(s.transferIn - s.transferOut)) + '，不计入消费。');
    }
    if (s.biggest) {
      lines.push('最大单笔消费：' + s.biggest.day + '「' + s.biggest.counterparty + '」' + money(s.biggest.net) + '（' + s.biggest.category + '）。');
    }
    var review = allTxs().filter(function (t) {
      return t.bucket === 'consumption' && (t.category_source === 'review' || t.category_source === 'default');
    });
    if (review.length) {
      var sum = review.reduce(function (a, t) { return a + num(t.amount); }, 0);
      lines.push('还有 ' + review.length + ' 笔共 ' + money(sum) + ' 待确认分类，确认后会自动修正上面的占比。');
    } else {
      lines.push('分类已全部确认。');
    }
    $('#insights').innerHTML = lines.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('');
  }

  /* ---------- 明细表 ---------- */

  function fillFilters() {
    var used = {};
    allTxs().forEach(function (t) { if (t.bucket === 'consumption') used[t.category] = 1; });
    var cats = Object.keys(used).sort();
    $('#fCategory').innerHTML = '<option value="all">全部分类</option>' + cats.map(function (c) {
      return '<option value="' + esc(c) + '">' + esc(c) + '</option>';
    }).join('');

    $('#eCategory').innerHTML = ALL_CATEGORIES.filter(function (c) { return SYSTEM.indexOf(c) < 0; }).map(function (c) {
      return '<option value="' + esc(c) + '">' + esc(c) + '</option>';
    }).join('');
  }

  function drawRangeChips() {
    var host = $('#rangeChips');
    if (!host) return;
    var months = DATA.monthly.map(function (m) { return m.month; });
    var items = [{ v: 'all', label: '全部' }].concat(months.map(function (m) {
      return { v: m, label: Number(m.slice(5)) + '月' };
    }));
    host.innerHTML = items.map(function (it) {
      return '<button type="button" data-month="' + it.v + '" aria-pressed="' + (state.month === it.v) + '">' + it.label + '</button>';
    }).join('');

    var s = summarize(scoped());
    var note = $('#rangeNote');
    if (note) {
      note.textContent = (state.month === 'all' ? DATA.monthly.length + ' 个月合计' : state.month + ' 单月') + ' · ' + s.count + ' 笔消费';
    }
  }

  function drawTable() {
    var list = allTxs().filter(function (t) {
      if (state.month !== 'all' && t.month !== state.month) return false;
      if (state.category !== 'all' && t.category !== state.category) return false;
      if (state.source !== 'all' && t.category_source !== state.source) return false;
      if (state.query) {
        var q = state.query.toLowerCase();
        var blob = (t.counterparty + ' ' + t.product + ' ' + t.note + ' ' + t.type).toLowerCase();
        if (blob.indexOf(q) < 0) return false;
      }
      return true;
    }).sort(function (a, b) { return a.ts < b.ts ? 1 : -1; });

    $('#tableHint').textContent = '共 ' + list.length + ' 条';

    var rows = list.map(function (t) {
      var src = SOURCE_LABEL[t.category_source] || t.category_source;
      var srcCls = t.category_source === 'override' ? ' override'
        : (t.category_source === 'review' || t.category_source === 'default') ? ' review' : '';
      var refund = num(t.refund) > 0 ? money(t.refund) : '—';
      return '<tr>' +
        '<td class="mono">' + esc(t.ts.slice(0, 16)) + '</td>' +
        '<td class="merchant">' + esc(t.counterparty) + '</td>' +
        '<td class="product" title="' + esc(t.product) + '">' + esc(t.product) + '</td>' +
        '<td><span class="cat"><i style="background:' + colorOf(t.category) + '"></i>' + esc(t.category) + '</span></td>' +
        '<td><span class="src' + srcCls + '">' + esc(src) + '</span></td>' +
        '<td class="bucket">' + esc(BUCKET_LABEL[t.bucket] || t.bucket) + '</td>' +
        '<td class="num">' + (t.direction === 'income' ? '+' : '') + money(t.net) + '</td>' +
        '<td class="num">' + refund + '</td>' +
        '<td class="status" title="' + esc(t.status) + '">' + esc(t.status) + '</td>' +
        '</tr>';
    }).join('');

    $('#txTable tbody').innerHTML = rows || '<tr><td colspan="9" class="review-empty">没有匹配的记录</td></tr>';
  }

  /* ---------- 汇总渲染 ---------- */

  function renderAll() {
    var s = summarize(scoped());
    drawKpis(s);
    drawMonthly();
    drawDonut(byCategory(s.cons), s.consumption);
    drawDaily(scoped());
    drawBudgets();
    drawReview();
    drawInsights(s);
    drawRangeChips();
    drawTable();
  }

  /* ---------- 事件 ---------- */

  function bind() {
    var rangeHost = $('#rangeChips');
    if (rangeHost) {
      rangeHost.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-month]');
        if (!btn) return;
        state.month = btn.getAttribute('data-month');
        renderAll();
      });
    }
    $('#fCategory').addEventListener('change', function (e) { state.category = e.target.value; drawTable(); });
    $('#fSource').addEventListener('change', function (e) { state.source = e.target.value; drawTable(); });
    $('#fQuery').addEventListener('input', function (e) { state.query = e.target.value.trim(); drawTable(); });
    $('#btnReset').addEventListener('click', function () {
      state.category = 'all'; state.source = 'all'; state.query = '';
      $('#fCategory').value = 'all'; $('#fSource').value = 'all'; $('#fQuery').value = '';
      drawTable();
    });

    $('#review').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-confirm]');
      if (!btn) return;
      var id = btn.getAttribute('data-confirm');
      var sel = document.querySelector('select[data-id="' + CSS.escape(id) + '"]');
      if (!sel || !sel.value) { sel && sel.focus(); return; }
      state.overrides[id] = sel.value;
      save(LS.overrides, state.overrides);
      renderAll();
    });

    $('#budgets').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-cat]');
      if (!btn) return;
      var cat = btn.getAttribute('data-cat');
      var current = state.limits[cat] || 0;
      var next = window.prompt('设置「' + cat + '」的月度预算（元）', String(current));
      if (next === null) return;
      var value = Number(next);
      if (!isFinite(value) || value < 0) return;
      state.limits[cat] = value;
      save(LS.budget, state.limits);
      drawBudgets();
    });

    var dialog = $('#entryDialog');
    $('#btnAdd').addEventListener('click', function () {
      var now = new Date();
      $('#eDate').value = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
      dialog.showModal();
    });
    $('#eCancel').addEventListener('click', function () { dialog.close(); });
    $('#entryForm').addEventListener('submit', function (e) {
      if (e.submitter && e.submitter.value === 'cancel') return;
      e.preventDefault();
      var date = $('#eDate').value;
      var amount = Number($('#eAmount').value);
      if (!date || !(amount > 0)) return;
      var direction = $('#eDirection').value;
      var t = {
        id: 'manual-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7),
        ts: date + ' 12:00:00',
        month: date.slice(0, 7),
        day: date,
        type: '手动记账',
        counterparty: $('#eParty').value.trim() || '手动记账',
        product: $('#eNote').value.trim() || '/',
        direction: direction,
        amount: amount,
        refund: 0,
        net: amount,
        signed: direction === 'income' ? amount : -amount,
        status: '手动录入',
        pay_method: '手动',
        merchant_id: '',
        note: $('#eNote').value.trim(),
        bucket: direction === 'income' ? 'income' : 'consumption',
        exclude_reason: '',
        category: $('#eCategory').value,
        category_source: 'manual'
      };
      state.manual.push(t);
      save(LS.manual, state.manual);
      dialog.close();
      fillFilters();
      $('#fCategory').value = state.category;
      renderAll();
    });

    $('#btnExport').addEventListener('click', function () {
      var payload = { overrides: state.overrides, manual: state.manual, budgets: state.limits };
      var blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'moneylens-confirmations.json';
      a.click();
      URL.revokeObjectURL(a.href);
    });

    $('#btnClear').addEventListener('click', function () {
      if (!window.confirm('清除本地的人工确认、手动记账和预算调整？账单原始数据不受影响。')) return;
      Object.keys(LS).forEach(function (k) { localStorage.removeItem(LS[k]); });
      location.reload();
    });
  }

  /* ---------- 启动 ---------- */

  function boot() {
    $('#subtitle').textContent = DATA.overview.period_start + ' — ' + DATA.overview.period_end +
      ' · ' + DATA.overview.records + ' 笔记录';
    $('#footMeta').textContent = '数据源：' + DATA.meta.source + ' · 生成于 ' + DATA.meta.generated_at;
    fillFilters();
    bind();
    renderAll();
  }

  boot();
})();