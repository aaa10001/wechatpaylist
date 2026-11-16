# -*- coding: utf-8 -*-
"""领域模型：一条账单记录及其派生属性（退款、口径、分类）。

设计要点
--------
1. 金额一律用 Decimal，避免 0.1 + 0.2 的浮点误差。
2. 一条记录同时保存「原始金额 gross」和「退款金额 refund」，净额 net 由两者推出。
   这样全额退款、部分退款、对方退还三种情况用同一套公式，不需要事后配对。
3. bucket 决定这条记录参与哪个口径的统计：
   consumption 消费 / income 收入 / transfer 转账 / refund 退款腿 / neutral 中性 / settlement 还款。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    """把任意数值安全地转成两位小数 Decimal。"""
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def f(value: Decimal | float | int) -> float:
    """Decimal -> float，供 JSON 输出。"""
    return float(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


@dataclass
class Txn:
    id: str                      # 交易单号（唯一）
    ts: datetime                 # UTC+8
    type: str                    # 交易类型
    counterparty: str            # 交易对方
    product: str                 # 商品
    direction: str               # income / expense / neutral
    amount: Decimal              # 原始金额
    status: str                  # 当前状态原文
    pay_method: str
    merchant_id: str
    note: str

    refund: Decimal = Decimal("0.00")
    bucket: str = "consumption"
    exclude_reason: str = ""
    category: str = "其他"
    category_source: str = "default"   # rule / override / ai / default

    # ---- 派生金额 ----
    @property
    def month(self) -> str:
        return self.ts.strftime("%Y-%m")

    @property
    def day(self) -> str:
        return self.ts.strftime("%Y-%m-%d")

    @property
    def net(self) -> Decimal:
        """净额：支出扣掉退款；退款腿为 0；其余为原额。"""
        if self.bucket == "refund":
            return Decimal("0.00")
        if self.direction == "expense":
            return max(self.amount - self.refund, Decimal("0.00"))
        return self.amount

    @property
    def signed(self) -> Decimal:
        """带符号净额，用于现金流。"""
        if self.bucket in {"neutral", "refund", "settlement"}:
            return Decimal("0.00")
        return self.net if self.direction == "income" else -self.net

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.strftime("%Y-%m-%d %H:%M:%S"),
            "month": self.month,
            "day": self.day,
            "type": self.type,
            "counterparty": self.counterparty,
            "product": self.product,
            "direction": self.direction,
            "amount": f(self.amount),
            "refund": f(self.refund),
            "net": f(self.net),
            "signed": f(self.signed),
            "status": self.status,
            "pay_method": self.pay_method,
            "merchant_id": self.merchant_id,
            "note": self.note,
            "bucket": self.bucket,
            "exclude_reason": self.exclude_reason,
            "category": self.category,
            "category_source": self.category_source,
        }