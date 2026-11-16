# -*- coding: utf-8 -*-
"""统计分析：月度趋势、分类构成、预算预警、异常检测、洞察与报告。

所有金额在内部用 Decimal 聚合，只在输出时转 float。
口径说明（会在报告里写清楚）：
  consumption 消费 = 支出的净额（扣退款），不含转账、还款、中性交易
  income      收入 = 收入的净额，不含退款腿（避免与原支出重复计算）
  transfer    转账 = 单列，不计入消费
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .model import Txn, f


def _d(value: float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(x) for x in month.split("-"))
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


def _covered_days(month: str, start: date, end: date) -> int:
    first, last = _month_bounds(month)
    lo, hi = max(first, start), min(last, end)
    if hi < lo:
        return 0
    return (hi - lo).days + 1


def _group(txns: list[Txn], key) -> dict[Any, list[Txn]]:
    out: dict[Any, list[Txn]] = defaultdict(list)
    for txn in txns:
        out[key(txn)].append(txn)
    return out


def _sum(items: list[Txn]) -> Decimal:
    return sum((t.net for t in items), Decimal("0.00"))


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def analyze(txns: list[Txn], budgets: dict[str, Any]) -> dict[str, Any]:
    if not txns:
        raise ValueError("没有可分析的记录")

    start = min(t.ts for t in txns).date()
    end = max(t.ts for t in txns).date()
    total_days = (end - start).days + 1

    consumption = [t for t in txns if t.bucket == "consumption"]
    incomes = [t for t in txns if t.bucket == "income"]
    transfers = [t for t in txns if t.bucket == "transfer"]

    # ---------- 月度 ----------
    months = sorted({t.month for t in txns})
    by_month = _group(txns, lambda t: t.month)
    monthly: list[dict[str, Any]] = []
    for month in months:
        items = by_month[month]
        cons = [t for t in items if t.bucket == "consumption"]
        inc = [t for t in items if t.bucket == "income"]
        tra = [t for t in items if t.bucket == "transfer"]
        transfer_out = sum((t.net for t in tra if t.direction == "expense"), Decimal("0"))
        transfer_in = sum((t.net for t in tra if t.direction == "income"), Decimal("0"))
        first, last = _month_bounds(month)
        days = _covered_days(month, start, end)
        complete = first >= start and last <= end
        spent = _sum(cons)
        monthly.append(
            {
                "month": month,
                "complete": complete,
                "covered_days": days,
                "days_in_month": calendar.monthrange(first.year, first.month)[1],
                "consumption": f(spent),
                "income": f(_sum(inc)),
                "transfer_out": f(transfer_out),
                "transfer_in": f(transfer_in),
                "count": len(cons),
                "avg_daily": f(spent / days) if days else 0.0,
            }
        )

    # ---------- 总览 ----------
    total_cons = _sum(consumption)
    total_income = _sum(incomes)
    total_refund = sum((t.refund for t in txns), Decimal("0"))
    transfer_out = sum((t.net for t in transfers if t.direction == "expense"), Decimal("0"))
    transfer_in = sum((t.net for t in transfers if t.direction == "income"), Decimal("0"))
    cash_in = total_income + transfer_in
    cash_out = total_cons + transfer_out

    overview = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "days": total_days,
        "records": len(txns),
        "income": f(total_income),
        "consumption": f(total_cons),
        "refund": f(total_refund),
        "transfer_out": f(transfer_out),
        "transfer_in": f(transfer_in),
        "transfer_net": f(transfer_in - transfer_out),
        "cash_in": f(cash_in),
        "cash_out": f(cash_out),
        "balance": f(cash_in - cash_out),
        "avg_daily": f(total_cons / total_days) if total_days else 0.0,
        "expense_count": len(consumption),
    }

    # ---------- 分类 ----------
    by_cat = _group(consumption, lambda t: t.category)
    categories = []
    for name, items in by_cat.items():
        amount = _sum(items)
        categories.append(
            {
                "category": name,
                "amount": f(amount),
                "count": len(items),
                "share": round(float(amount / total_cons) * 100, 1) if total_cons else 0.0,
            }
        )
    categories.sort(key=lambda x: -x["amount"])

    monthly_categories: dict[str, list[dict[str, Any]]] = {}
    for month in months:
        cons = [t for t in by_month[month] if t.bucket == "consumption"]
        rows = [
            {"category": name, "amount": f(_sum(items)), "count": len(items)}
            for name, items in _group(cons, lambda t: t.category).items()
        ]
        monthly_categories[month] = sorted(rows, key=lambda x: -x["amount"])

    # ---------- 日序列 ----------
    per_day_expense: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    per_day_income: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for t in consumption:
        per_day_expense[t.day] += t.net
    for t in incomes:
        per_day_income[t.day] += t.net
    daily = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        daily.append({"date": key, "expense": f(per_day_expense[key]), "income": f(per_day_income[key])})
        cursor = date.fromordinal(cursor.toordinal() + 1)

    # ---------- 商户榜 ----------
    merchants = [
        {"name": name, "amount": f(_sum(items)), "count": len(items)}
        for name, items in _group(consumption, lambda t: t.counterparty).items()
    ]
    merchants.sort(key=lambda x: -x["amount"])

    # ---------- 预算 ----------
    current_month = months[-1]
    current = next(m for m in monthly if m["month"] == current_month)
    elapsed = current["covered_days"]
    days_in_month = current["days_in_month"]
    budget_rows = []
    limits = budgets.get("monthly", {})
    alert_ratio = float(budgets.get("alert_ratio", 0.8))
    for category, limit in limits.items():
        spent = _sum([t for t in consumption if t.month == current_month and t.category == category])
        projected = spent / elapsed * days_in_month if elapsed else spent
        pct = float(spent / Decimal(str(limit))) * 100 if limit else 0.0
        status = "over" if pct >= 100 else "warn" if pct >= alert_ratio * 100 else "ok"
        budget_rows.append(
            {
                "category": category,
                "limit": float(limit),
                "spent": f(spent),
                "pct": round(pct, 1),
                "remaining": f(Decimal(str(limit)) - spent),
                "projected": f(projected),
                "projected_pct": round(float(projected / Decimal(str(limit))) * 100, 1) if limit else 0.0,
                "status": status,
                "month": current_month,
            }
        )
    budget_rows.sort(key=lambda x: -x["pct"])

    # ---------- 异常支出（大额偏离）----------
    anomalies = []
    for category, items in by_cat.items():
        mean = float(_sum(items)) / len(items)
        for txn in items:
            amount = float(txn.amount)
            if amount < 200 or not mean:
                continue
            anomalies.append(
                {
                    "id": txn.id,
                    "date": txn.day,
                    "counterparty": txn.counterparty,
                    "product": txn.product,
                    "category": category,
                    "amount": f(txn.amount),
                    "ratio": round(amount / mean, 1),
                }
            )
    anomalies.sort(key=lambda x: -x["amount"])
    anomalies = anomalies[:8]

    # ---------- 洞察 ----------
    insights = []
    if categories:
        top = categories[0]
        insights.append(f"最大支出分类是「{top['category']}」，¥{top['amount']:.2f}，占消费 {top['share']}%。")
    insights.append(f"覆盖 {total_days} 天，消费合计 ¥{f(total_cons):.2f}，日均 ¥{f(total_cons / total_days):.2f}。")
    if total_refund > 0:
        refund_count = sum(1 for t in txns if t.refund > 0)
        insights.append(f"退款 {refund_count} 笔，合计 ¥{f(total_refund):.2f}，已在支出中冲抵，未重复计入收入。")
    if transfer_out > 0:
        insights.append(f"转账往来净流入 ¥{f(transfer_in - transfer_out):+.2f}（转入 ¥{f(transfer_in):.2f}，转出 ¥{f(transfer_out):.2f}），不计入消费。")
    if anomalies:
        top_anom = anomalies[0]
        insights.append(f"最大单笔支出是 {top_anom['date']} 的「{top_anom['counterparty']}」¥{top_anom['amount']:.2f}（{top_anom['category']}，为分类均值的 {top_anom['ratio']} 倍）。")
    weekend = [t for t in consumption if t.ts.weekday() >= 5]
    weekday = [t for t in consumption if t.ts.weekday() < 5]
    weekend_days = sum(1 for i in range(total_days) if date.fromordinal(start.toordinal() + i).weekday() >= 5)
    weekday_days = total_days - weekend_days
    if weekend_days and weekday_days:
        w_end = float(_sum(weekend)) / weekend_days
        w_day = float(_sum(weekday)) / weekday_days
        if w_day:
            insights.append(f"周末日均 ¥{w_end:.2f}，工作日日均 ¥{w_day:.2f}，相差 {round((w_end - w_day) / w_day * 100)}%。")
    risky = [b for b in budget_rows if b["status"] != "ok"]
    if risky:
        names = "、".join(f"{b['category']}({b['pct']}%)" for b in risky[:3])
        insights.append(f"预算预警：{names}，按当前速度月末预计超支。")

    return {
        "overview": overview,
        "monthly": monthly,
        "categories": categories,
        "monthly_categories": monthly_categories,
        "daily": daily,
        "merchants": merchants[:15],
        "budgets": budget_rows,
        "anomalies": anomalies[:10],
        "insights": insights,
        "budget_month": current_month,
    }


def render_markdown(result: dict[str, Any], meta: dict[str, Any], validation: dict[str, Any], classification: dict[str, Any]) -> str:
    def signed(value: float) -> str:
        return ("+" if value >= 0 else "-") + f"¥{abs(value):.2f}"

    ov = result["overview"]
    lines = [
        "# MoneyLens 消费分析报告",
        "",
        f"账单周期：{ov['period_start']} ~ {ov['period_end']}（{ov['days']} 天，{ov['records']} 条记录）",
        "",
        "## 一、总览",
        "",
        "| 指标 | 金额 |",
        "| --- | ---: |",
        f"| 消费（净额） | ¥{ov['consumption']:.2f} |",
        f"| 收入（净额） | ¥{ov['income']:.2f} |",
        f"| 退款冲抵 | ¥{ov['refund']:.2f} |",
        f"| 转账净额 | {signed(ov['transfer_net'])} |",
        f"| 净结余 | {signed(ov['balance'])} |",
        f"| 日均消费 | ¥{ov['avg_daily']:.2f} |",
        "",
        "## 二、月度趋势",
        "",
        "| 月份 | 消费 | 日均 | 收入 | 完整月 | 笔数 |",
        "| --- | ---: | ---: | ---: | :---: | ---: |",
    ]
    for m in result["monthly"]:
        lines.append(
            f"| {m['month']} | ¥{m['consumption']:.2f} | ¥{m['avg_daily']:.2f} | ¥{m['income']:.2f} | {'是' if m['complete'] else '否'} | {m['count']} |"
        )
    lines += ["", "## 三、分类构成", "", "| 分类 | 金额 | 占比 | 笔数 |", "| --- | ---: | ---: | ---: |"]
    for c in result["categories"]:
        lines.append(f"| {c['category']} | ¥{c['amount']:.2f} | {c['share']}% | {c['count']} |")
    lines += ["", f"## 四、预算执行（{result['budget_month']}，进行中）", "", "| 分类 | 预算 | 已用 | 已用% | 月末预计 | 状态 |", "| --- | ---: | ---: | ---: | ---: | :---: |"]
    for b in result["budgets"]:
        label = {"ok": "正常", "warn": "接近上限", "over": "超支"}[b["status"]]
        lines.append(f"| {b['category']} | ¥{b['limit']:.0f} | ¥{b['spent']:.2f} | {b['pct']}% | ¥{b['projected']:.2f} | {label} |")
    lines += ["", "## 五、大额与异常支出", ""]
    if result["anomalies"]:
        lines += ["| 日期 | 商户 | 分类 | 金额 | 相对分类均值 |", "| --- | --- | --- | ---: | ---: |"]
        for a in result["anomalies"]:
            lines.append(f"| {a['date']} | {a['counterparty']} | {a['category']} | ¥{a['amount']:.2f} | ×{a['ratio']} |")
    else:
        lines.append("未发现显著偏离记录。")
    lines += ["", "## 六、洞察", ""]
    lines += [f"- {x}" for x in result["insights"]]
    lines += [
        "",
        "## 七、数据质量",
        "",
        f"- 解析校验：{'通过' if validation['all_ok'] else '未通过'}（与微信自报合计逐项比对）",
        f"- 自动分类覆盖率：{classification['coverage'] * 100:.1f}%（规则 {classification['stats']['rule']} 条 / AI {classification['stats']['ai']} 条 / 人工 {classification['stats']['override']} 条 / 待确认 {classification['stats']['review']} 条 / 未匹配 {classification['stats']['default']} 条）",
        "",
        "### 口径说明",
        "",
        "1. 消费 = 支出净额（原始金额 − 退款），不含转账、还款与中性交易。",
        "2. 退款在微信账单里表现为两条记录：原支出状态标注退款金额，另加一条退款收入。本报告只认可原支出的退款金额，退款收入不重复计入。",
        "3. 首尾月份不完整，跨月比较一律使用日均而非总额。",
    ]
    if meta.get("start"):
        lines.append(f"4. 账单时间均为 UTC+8，导出区间 {meta['start']} ~ {meta['end']}。")
    return "\n".join(lines) + "\n"