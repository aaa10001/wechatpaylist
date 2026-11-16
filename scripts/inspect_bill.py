# -*- coding: utf-8 -*-
"""检查微信支付账单 xlsx 的结构：sheet、前导说明行、表头、列类型。"""
import sys
from pathlib import Path

from openpyxl import load_workbook

SRC = Path(r"C:\Users\26852\Downloads\微信支付账单流水文件(20260721-20261021)_20261021100734.xlsx")

wb = load_workbook(SRC, read_only=True, data_only=True)
print("sheets:", wb.sheetnames)
for name in wb.sheetnames:
    ws = wb[name]
    print(f"--- sheet={name!r} dims={ws.max_row} x {ws.max_column} ---")
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        cells = ["" if v is None else str(v) for v in row]
        line = " | ".join(cells)
        if len(line) > 300:
            line = line[:300] + "..."
        print(f"{i:>3}: {line}")
        if i >= 40:
            print("... (stopped at 40)")
            break
wb.close()