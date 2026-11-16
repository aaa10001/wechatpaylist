# -*- coding: utf-8 -*-
"""剖析微信账单：类型/状态/收支分布、月度分布、退款与重复、金额校验。"""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

SRC = Path(r"C:\Users\26852\Downloads\微信支付账单流水文件(20260721-20261021)_20261021100734.xlsx")
HEADER_ROW = 18

wb = load_workbook(SRC, read_only=True, data_only=True)
ws = wb["Sheet1"]
rows = list(ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True))
wb.close()

cols = ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额", "支付方式", "状态", "交易单号", "商户单号", "备注"]
recs = [dict(zip(cols, r)) for r in rows if r[0] is not None]
print(f"记录数: {len(recs)}")

print("\n== 列类型 ==")
for c in cols:
    types = Counter(type(r[c]).__name__ for r in recs)
    print(f"{c}: {dict(types)}")

print("\n== 时间范围 ==")
times = [r["交易时间"] for r in recs]
print(type(times[0]).__name__, min(times), "->", max(times))

print("\n== 收/支 ==")
for k, v in Counter(r["收/支"] for r in recs).most_common():
    s = sum(float(r["金额"]) for r in recs if r["收/支"] == k)
    print(f"{k!r}: {v} 笔, 合计 {s:.2f}")

print("\n== 交易类型（笔数, 合计）==")
by_type = defaultdict(lambda: [0, 0.0])
for r in recs:
    by_type[r["交易类型"]][0] += 1
    by_type[r["交易类型"]][1] += float(r["金额"])
for k, (n, s) in sorted(by_type.items(), key=lambda kv: -kv[1][1]):
    print(f"{k!r}: {n} 笔, {s:.2f}")

print("\n== 当前状态 ==")
for k, v in Counter(r["状态"] for r in recs).most_common():
    print(f"{k!r}: {v}")

print("\n== 月度（收/支/中性）==")
mon = defaultdict(lambda: defaultdict(float))
cnt = defaultdict(lambda: defaultdict(int))
for r in recs:
    m = r["交易时间"].strftime("%Y-%m")
    key = r["收/支"]
    mon[m][key] += float(r["金额"])
    cnt[m][key] += 1
for m in sorted(mon):
    print(m, {k: (cnt[m][k], round(v, 2)) for k, v in mon[m].items()})

print("\n== 交易单号重复 ==")
dup = [k for k, v in Counter(r["交易单号"] for r in recs).items() if v > 1]
print("重复单号数:", len(dup))

print("\n== 含'退款'的状态/类型 ==")
for r in recs:
    if "退款" in str(r["状态"]) or "退款" in str(r["交易类型"]):
        print(f'{r["交易时间"]:%m-%d %H:%M} | {r["交易类型"]} | {r["交易对方"]} | {r["收/支"]} | {r["金额"]} | {r["状态"]} | {str(r["商品"])[:20]}')

print("\n== 金额异常 ==")
bad = [r for r in recs if not isinstance(r["金额"], (int, float)) or float(r["金额"]) <= 0]
print("非正数/非数值:", len(bad))
for r in bad[:5]:
    print(r)

print("\n== 支付方式 ==")
for k, v in Counter(r["支付方式"] for r in recs).most_common():
    print(f"{k!r}: {v}")

print("\n== 商品字段样式（前 15 个去重）==")
for v in list(dict.fromkeys(str(r["商品"]) for r in recs))[:15]:
    print(repr(v))

print("\n== 收入 top10 ==")
for r in sorted((r for r in recs if r["收/支"] == "收入"), key=lambda r: -float(r["金额"]))[:10]:
    print(f'{r["交易时间"]:%m-%d} | {r["交易类型"]} | {r["交易对方"]} | {r["金额"]} | {r["状态"]}')

print("\n== 支出 top10 ==")
for r in sorted((r for r in recs if r["收/支"] == "支出"), key=lambda r: -float(r["金额"]))[:10]:
    print(f'{r["交易时间"]:%m-%d} | {r["交易类型"]} | {r["交易对方"]} | {r["金额"]} | {r["状态"]}')