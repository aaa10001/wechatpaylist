# -*- coding: utf-8 -*-
"""列出未匹配记录与现有分类明细，用于人工/AI 修正规则。"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
payload = json.loads((ROOT / "data/derived/moneylens.json").read_text(encoding="utf-8"))
txns = payload["transactions"]

print("== 未匹配（category_source=default 且支出）==")
groups = defaultdict(list)
for t in txns:
    if t["bucket"] == "consumption" and t["category_source"] == "default":
        groups[t["counterparty"]].append(t)
for name, items in sorted(groups.items(), key=lambda kv: -sum(i["amount"] for i in kv[1])):
    total = sum(i["amount"] for i in items)
    products = sorted({i["product"][:24] for i in items})
    dates = sorted(i["day"] for i in items)
    print(f'{total:>8.2f} x{len(items):<2} {name}  | {products[:3]} | {dates[0]}~{dates[-1]}')

print("\n== 各分类下的商户（消费净额）==")
cat = defaultdict(lambda: defaultdict(float))
for t in txns:
    if t["bucket"] == "consumption":
        cat[t["category"]][t["counterparty"]] += t["net"]
for c, merchants in sorted(cat.items(), key=lambda kv: -sum(kv[1].values())):
    top = sorted(merchants.items(), key=lambda kv: -kv[1])[:6]
    print(f'{c}  合计 {sum(merchants.values()):.2f}  ->  ' + ", ".join(f"{n}({v:.1f})" for n, v in top))