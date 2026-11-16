# -*- coding: utf-8 -*-
"""微信支付账单 xlsx 解析。

微信导出的表不是「干净的表」：前面有 17 行说明，表头在第 18 行附近，
金额是数值但状态字段里嵌着退款金额，收/支里还有 "/" 这种中性标记。
解析器的职责就是把这些坑一次性处理掉，产出规范化的 Txn 列表。
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .model import Txn, money

HEADER_FIRST_CELL = "交易时间"

# 交易类型 -> 口径
SETTLEMENT_TYPES = {"美团金融还款", "信用卡还款", "花呗还款"}
TRANSFER_TYPES = {"转账", "微信红包", "群收款", "二维码收款"}

# "已退款(¥0.35)" / "已退款¥0.35" / "已退款（￥0.35）"
REFUND_AMOUNT_RE = re.compile(r"已退款\s*[（(]?\s*[¥￥]?\s*([0-9]+(?:\.[0-9]+)?)")
FULL_REFUND_HINTS = ("全额退款", "已退还")

_DIRECTION = {"收入": "income", "支出": "expense"}

_META_TOTAL_RE = r"(收入|支出|中性交易)\s*[：:]\s*(\d+)\s*笔\s*([\d.]+)\s*元"


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_header(ws) -> tuple[int, list[str]]:
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row and _cell_text(row[0]) == HEADER_FIRST_CELL:
            return idx, [_cell_text(c) for c in row]
    raise ValueError("没有找到表头行（第一列应为「交易时间」），可能不是微信支付账单")


def _parse_meta(ws, header_row: int) -> dict[str, Any]:
    """读取表头之前的说明区，抽取账单周期与微信自报的合计，供校验。"""
    lines = []
    for row in ws.iter_rows(min_row=1, max_row=header_row - 1, values_only=True):
        text = " ".join(_cell_text(c) for c in row if _cell_text(c))
        if text:
            lines.append(text)
    blob = "\n".join(lines)

    meta: dict[str, Any] = {"raw_lines": lines, "declared": {}}
    period = re.search(r"起始时间：\[([^\]]+)\]\s*终止时间：\[([^\]]+)\]", blob)
    if period:
        meta["start"] = period.group(1)
        meta["end"] = period.group(2)
    for name, count, total in re.findall(_META_TOTAL_RE, blob):
        meta["declared"][name] = {"count": int(count), "total": Decimal(total)}
    return meta


def _refund_amount(status: str, amount: Decimal, direction: str) -> Decimal:
    """从状态文本推断这笔支出退回了多少钱。

    三种写法：
      已退款(¥0.35)  -> 部分退款，金额在括号里
      已全额退款      -> 全额
      对方已退还      -> 全额（转账被退回）
    """
    if direction != "expense":
        return Decimal("0.00")
    status = status or ""
    if any(hint in status for hint in FULL_REFUND_HINTS):
        return amount
    found = REFUND_AMOUNT_RE.search(status)
    if found:
        refund = money(found.group(1))
        return min(refund, amount)
    return Decimal("0.00")


def _bucket(direction: str, type_: str) -> tuple[str, str]:
    """返回 (bucket, 排除原因)。"""
    if direction == "neutral":
        return "neutral", "中性交易（充值/提现/内部划转）"
    if direction == "income" and "退款" in type_:
        return "refund", "退款到账，已冲抵原支出"
    if type_ in SETTLEMENT_TYPES:
        return "settlement", "还款，非新增消费"
    if type_ in TRANSFER_TYPES:
        return "transfer", "转账/红包，非消费"
    if direction == "expense":
        return "consumption", ""
    return "income", ""


def parse_workbook(path: str | Path) -> tuple[list[Txn], dict[str, Any]]:
    path = Path(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        header_row, headers = _find_header(ws)
        meta = _parse_meta(ws, header_row)
        col = {name: i for i, name in enumerate(headers) if name}

        required = ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "当前状态"]
        missing = [name for name in required if name not in col]
        if missing:
            raise ValueError(f"账单缺少必要列：{missing}")

        txns: list[Txn] = []
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            ts = row[col["交易时间"]]
            if not isinstance(ts, datetime):
                continue  # 跳过空行与页脚
            direction = _DIRECTION.get(_cell_text(row[col["收/支"]]), "neutral")
            amount = money(row[col["金额(元)"]])
            type_ = _cell_text(row[col["交易类型"]])
            status = _cell_text(row[col["当前状态"]])
            bucket, reason = _bucket(direction, type_)
            txns.append(
                Txn(
                    id=_cell_text(row[col["交易单号"]]) or f"row-{len(txns) + 1}",
                    ts=ts,
                    type=type_,
                    counterparty=_cell_text(row[col["交易对方"]]),
                    product=_cell_text(row[col["商品"]]),
                    direction=direction,
                    amount=amount,
                    status=status,
                    pay_method=_cell_text(row[col["支付方式"]]),
                    merchant_id=_cell_text(row[col["商户单号"]]) if "商户单号" in col else "",
                    note=_cell_text(row[col["备注"]]) if "备注" in col else "",
                    refund=_refund_amount(status, amount, direction),
                    bucket=bucket,
                    exclude_reason=reason,
                )
            )
        return txns, meta
    finally:
        wb.close()


def validate(txns: list[Txn], meta: dict[str, Any]) -> dict[str, Any]:
    """拿微信自报的合计校验解析结果，避免静默错行。"""
    declared = meta.get("declared", {})
    computed = {
        "收入": sum((t.amount for t in txns if t.direction == "income"), Decimal("0")),
        "支出": sum((t.amount for t in txns if t.direction == "expense"), Decimal("0")),
        "中性交易": sum((t.amount for t in txns if t.direction == "neutral"), Decimal("0")),
    }
    counts = {
        "收入": sum(1 for t in txns if t.direction == "income"),
        "支出": sum(1 for t in txns if t.direction == "expense"),
        "中性交易": sum(1 for t in txns if t.direction == "neutral"),
    }
    checks = []
    for key, got_total in computed.items():
        want = declared.get(key)
        checks.append(
            {
                "item": key,
                "expected_count": want["count"] if want else None,
                "actual_count": counts[key],
                "expected_total": float(want["total"]) if want else None,
                "actual_total": float(got_total),
                "ok": bool(want) and want["count"] == counts[key] and want["total"] == got_total,
            }
        )
    return {"all_ok": all(c["ok"] for c in checks), "checks": checks}