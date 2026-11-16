# -*- coding: utf-8 -*-
"""消费分类：规则引擎 + 人工覆盖 + AI 建议。

三层优先级（从高到低）：
  1. 人工覆盖  overrides.json      —— 人确认过的，永远最高
  2. 规则引擎  rules.json          —— 可解释、可测试、覆盖大多数商户
  3. AI 建议   ai_suggestions.json —— 只对规则兜不住的「其他」给候选，标记待确认
未被任何一层命中的记录进「其他」，并在报告里统计占比——这个数字就是分类质量的度量。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .model import Txn


def load_json(path: str | Path, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _blob(txn: Txn) -> str:
    return " | ".join([txn.type, txn.counterparty, txn.product, txn.note])


def _rule_hit(rule: dict[str, Any], txn: Txn, blob: str) -> bool:
    if "buckets" in rule and txn.bucket not in rule["buckets"]:
        return False
    if "types" in rule and txn.type not in rule["types"]:
        return False
    if "counterparties" in rule and txn.counterparty not in rule["counterparties"]:
        return False
    if "any" in rule and not any(word.lower() in blob.lower() for word in rule["any"]):
        return False
    if "all" in rule and not all(word.lower() in blob.lower() for word in rule["all"]):
        return False
    if "regex" in rule and not re.search(rule["regex"], blob):
        return False
    # 一个条件都没写的规则视为不匹配，避免误吞全部记录
    return any(key in rule for key in ("buckets", "types", "counterparties", "any", "all", "regex"))


def classify(
    txns: list[Txn],
    ruleset: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    ai_suggestions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = ruleset.get("rules", [])
    default = ruleset.get("default", "其他")
    overrides = overrides or {}
    by_id = overrides.get("by_id", {})
    by_party = overrides.get("by_counterparty", {})
    ai = (ai_suggestions or {}).get("suggestions", {})
    personal_qr = ruleset.get("fallbacks", {}).get("personal_qr")

    stats = {"override": 0, "rule": 0, "ai": 0, "review": 0, "default": 0}
    unmatched: dict[str, dict[str, Any]] = {}

    for txn in txns:
        if txn.id in by_id:
            txn.category, txn.category_source = by_id[txn.id], "override"
        elif txn.counterparty in by_party:
            txn.category, txn.category_source = by_party[txn.counterparty], "override"
        else:
            hit = next((r for r in rules if _rule_hit(r, txn, _blob(txn))), None)
            if hit:
                txn.category, txn.category_source = hit["category"], "rule"
            elif txn.counterparty in ai:
                txn.category, txn.category_source = ai[txn.counterparty]["category"], "ai"
            elif personal_qr and txn.type == "扫二维码付款":
                # 个人收款码：商户名是个人昵称，规则和 AI 都不可靠，交给人工确认
                txn.category, txn.category_source = personal_qr, "review"
            else:
                txn.category, txn.category_source = default, "default"
        stats[txn.category_source] += 1
        if txn.category_source == "default" and txn.direction == "expense":
            key = txn.counterparty or txn.type
            slot = unmatched.setdefault(key, {"counterparty": txn.counterparty, "count": 0, "amount": 0.0, "sample": txn.product})
            slot["count"] += 1
            slot["amount"] = round(slot["amount"] + float(txn.amount), 2)

    total = max(len(txns), 1)
    return {
        "stats": stats,
        "coverage": round((total - stats["default"] - stats["review"]) / total, 4),
        "review_ratio": round(stats["review"] / total, 4),
        "unmatched": sorted(unmatched.values(), key=lambda x: -x["amount"])[:30],
    }