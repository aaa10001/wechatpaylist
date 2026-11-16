# -*- coding: utf-8 -*-
"""命令行入口：解析账单 -> 分类 -> 分析 -> 产出 Web 数据与 Markdown 报告。

用法：
    python -m moneylens.build
    python -m moneylens.build --src data/raw/xxx.xlsx
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .analytics import analyze, render_markdown
from .categorize import classify, load_json
from .ingest import parse_workbook, validate
from .model import Txn, money

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "data" / "raw" / "wechat_20260721_20261021.xlsx"


def load_manual(path: Path) -> list[Txn]:
    """把手动记账（来自 Web 界面导出并回写的 manual.json）并入数据集。"""
    rows = load_json(path, [])
    txns: list[Txn] = []
    for i, row in enumerate(rows):
        direction = row.get("direction", "expense")
        amount = money(row.get("amount", 0))
        if amount <= 0:
            continue
        date_text = str(row.get("date", ""))[:10]
        try:
            ts = datetime.fromisoformat(date_text + "T12:00:00")
        except ValueError:
            continue
        note = str(row.get("note", "") or "")
        txns.append(
            Txn(
                id=str(row.get("id") or f"manual-{i + 1}"),
                ts=ts,
                type="手动记账",
                counterparty=str(row.get("counterparty") or "手动记账"),
                product=note or "/",
                direction=direction,
                amount=amount,
                status="手动录入",
                pay_method="手动",
                merchant_id="",
                note=note,
                bucket="consumption" if direction == "expense" else "income",
                category=str(row.get("category") or "其他"),
                category_source="manual",
            )
        )
    return txns


def _json_default(obj: Any):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"无法序列化 {type(obj)}")


def build(src: Path) -> dict[str, Any]:
    parsed, meta = parse_workbook(src)
    validation = validate(parsed, meta)

    ruleset = load_json(ROOT / "data" / "rules.json", {"rules": [], "default": "其他"})
    overrides = load_json(ROOT / "data" / "overrides.json", {})
    ai = load_json(ROOT / "data" / "ai_suggestions.json", {})
    budgets = load_json(ROOT / "data" / "budgets.json", {"monthly": {}, "alert_ratio": 0.8})

    classification = classify(parsed, ruleset, overrides, ai)
    manual = load_manual(ROOT / "data" / "manual.json")
    txns = parsed + manual
    result = analyze(txns, budgets)

    payload = {
        "meta": {
            "source": src.name,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "period_start": meta.get("start"),
            "period_end": meta.get("end"),
            "records": len(txns),
        },
        "validation": validation,
        "classification": classification,
        "transactions": [t.to_dict() for t in txns],
        **result,
    }

    web_dir = ROOT / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    derived = ROOT / "data" / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    (derived / "moneylens.json").write_text(text, encoding="utf-8")
    (web_dir / "data.js").write_text("window.MONEYLENS = " + text + ";\n", encoding="utf-8")
    (reports / "summary.md").write_text(
        render_markdown(result, meta, validation, classification), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="MoneyLens 构建")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="微信账单 xlsx 路径")
    args = parser.parse_args()

    payload = build(args.src)
    ov = payload["overview"]
    val = payload["validation"]

    print("== 解析校验 ==")
    for check in val["checks"]:
        flag = "OK " if check["ok"] else "BAD"
        print(f"  [{flag}] {check['item']}: {check['actual_count']} 笔 / {check['actual_total']:.2f} 元"
              f"（微信自报 {check['expected_count']} 笔 / {check['expected_total']} 元）")
    print(f"  总体: {'通过' if val['all_ok'] else '未通过'}")

    print("\n== 口径汇总 ==")
    print(f"  消费净额: {ov['consumption']:.2f}  收入净额: {ov['income']:.2f}  退款冲抵: {ov['refund']:.2f}")
    print(f"  转账: 转出 {ov['transfer_out']:.2f} / 转入 {ov['transfer_in']:.2f}  净结余: {ov['balance']:.2f}")
    print(f"  天数 {ov['days']}  日均消费 {ov['avg_daily']:.2f}")

    print("\n== 分类覆盖率 ==")
    stats = payload["classification"]["stats"]
    print(f"  {payload['classification']['coverage'] * 100:.1f}%  "
          f"规则 {stats['rule']} / AI {stats['ai']} / 人工 {stats['override']} / 待确认 {stats['review']} / 未匹配 {stats['default']}")
    print("  未匹配金额 Top:")
    for row in payload["classification"]["unmatched"][:12]:
        print(f"    {row['amount']:>9.2f}  x{row['count']:<2}  {row['counterparty']}  (商品: {row['sample'][:20]})")

    print("\n== 月度 ==")
    for m in payload["monthly"]:
        print(f"  {m['month']}  消费 {m['consumption']:>9.2f}  日均 {m['avg_daily']:>7.2f}  "
              f"收入 {m['income']:>8.2f}  {'完整' if m['complete'] else '不完整'}  {m['count']} 笔")

    print("\n== 分类 ==")
    for c in payload["categories"]:
        print(f"  {c['category']:<6} {c['amount']:>9.2f}  {c['share']:>5.1f}%  {c['count']} 笔")

    print("\n== 预算（%s）==" % payload["budget_month"])
    for b in payload["budgets"]:
        print(f"  {b['category']:<6} {b['spent']:>7.2f}/{b['limit']:<6.0f} {b['pct']:>5.1f}%  "
              f"预计 {b['projected']:>7.2f}  {b['status']}")

    print("\n== 洞察 ==")
    for line in payload["insights"]:
        print("  -", line)

    print("\n已生成: web/data.js, reports/summary.md, data/derived/moneylens.json")


if __name__ == "__main__":
    main()