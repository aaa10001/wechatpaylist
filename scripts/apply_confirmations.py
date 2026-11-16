# -*- coding: utf-8 -*-
"""把 Web 界面导出的 moneylens-confirmations.json 回写到 data/ 下，并重建报告。

这就是「人在界面上确认 -> 机器重新计算」的闭环：
  web/app.js 导出 {overrides, manual, budgets}
  -> 本脚本合并进 data/overrides.json、data/manual.json、data/budgets.json
  -> python -m moneylens.build 重新生成图表数据与 reports/summary.md

用法：
    python scripts/apply_confirmations.py 下载目录/moneylens-confirmations.json
    python scripts/apply_confirmations.py xxx.json --no-build
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="回写 MoneyLens 人工确认结果")
    parser.add_argument("source", type=Path, help="web 界面导出的 json")
    parser.add_argument("--no-build", action="store_true", help="只回写，不重新构建")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"找不到文件：{args.source}", file=sys.stderr)
        return 1

    incoming = json.loads(args.source.read_text(encoding="utf-8"))
    overrides_path = ROOT / "data" / "overrides.json"
    manual_path = ROOT / "data" / "manual.json"
    budgets_path = ROOT / "data" / "budgets.json"

    overrides = read_json(overrides_path, {"by_id": {}, "by_counterparty": {}})
    by_id = overrides.setdefault("by_id", {})
    new_overrides = {k: v for k, v in (incoming.get("overrides") or {}).items() if v}
    by_id.update(new_overrides)
    write_json(overrides_path, overrides)

    manual = read_json(manual_path, [])
    known = {str(row.get("id")) for row in manual}
    added = 0
    for row in incoming.get("manual") or []:
        rid = str(row.get("id") or "")
        if not rid or rid in known:
            continue
        manual.append(
            {
                "id": rid,
                "date": str(row.get("date") or row.get("day") or "")[:10],
                "direction": row.get("direction", "expense"),
                "amount": row.get("amount", 0),
                "category": row.get("category", "其他"),
                "counterparty": row.get("counterparty", "手动记账"),
                "note": row.get("note", ""),
            }
        )
        known.add(rid)
        added += 1
    write_json(manual_path, manual)

    budgets = read_json(budgets_path, {"monthly": {}, "alert_ratio": 0.8})
    incoming_budgets = incoming.get("budgets") or {}
    if incoming_budgets:
        budgets.setdefault("monthly", {}).update({k: float(v) for k, v in incoming_budgets.items()})
        write_json(budgets_path, budgets)

    print(f"回写完成：分类确认 {len(new_overrides)} 条，新增手动记账 {added} 条。")
    if args.no_build:
        return 0

    sys.path.insert(0, str(ROOT))
    from moneylens.build import DEFAULT_SRC, build  # noqa: E402

    build(DEFAULT_SRC)
    print("已重新生成 web/data.js 与 reports/summary.md。")
    print("时间：", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())