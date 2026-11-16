# -*- coding: utf-8 -*-
"""MoneyLens 核心逻辑测试。

运行：python -m unittest discover -s tests -t .
覆盖三类最容易出错的地方：
  1. 退款：全额 / 部分 / 退款腿，三者净额算法必须一致且不重复
  2. 口径：中性交易、还款、转账不能混进消费
  3. 分析：不完整月份必须用日均，预算推算要按已过天数外推
"""
from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from moneylens.analytics import analyze
from moneylens.categorize import classify, load_json
from moneylens.ingest import parse_workbook, validate
from moneylens.model import Txn, money

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "wechat_20260721_20261021.xlsx"


def setUpModule() -> None:
    global TXNS, META, VALIDATION, RESULT, CLASSIFICATION
    TXNS, META = parse_workbook(SRC)
    VALIDATION = validate(TXNS, META)
    ruleset = load_json(ROOT / "data" / "rules.json", {"rules": [], "default": "其他"})
    overrides = load_json(ROOT / "data" / "overrides.json", {})
    ai = load_json(ROOT / "data" / "ai_suggestions.json", {})
    CLASSIFICATION = classify(TXNS, ruleset, overrides, ai)
    budgets = load_json(ROOT / "data" / "budgets.json", {"monthly": {}, "alert_ratio": 0.8})
    RESULT = analyze(TXNS, budgets)


def find(**kwargs) -> Txn:
    for txn in TXNS:
        if all(getattr(txn, key) == value for key, value in kwargs.items()):
            return txn
    raise AssertionError(f"找不到记录: {kwargs}")


class TestParse(unittest.TestCase):
    def test_record_count(self) -> None:
        self.assertEqual(len(TXNS), 323)

    def test_validation_matches_wechat_declared_totals(self) -> None:
        self.assertTrue(VALIDATION["all_ok"], VALIDATION)

    def test_all_amounts_positive(self) -> None:
        self.assertTrue(all(t.amount > 0 for t in TXNS))

    def test_transaction_ids_unique(self) -> None:
        self.assertEqual(len({t.id for t in TXNS}), len(TXNS))


class TestRefund(unittest.TestCase):
    def test_partial_refund_nets_out(self) -> None:
        txn = find(counterparty="智慧校园", amount=Decimal("2.00"), status="已退款(¥0.35)")
        self.assertEqual(txn.refund, Decimal("0.35"))
        self.assertEqual(txn.net, Decimal("1.65"))

    def test_full_refund_net_is_zero(self) -> None:
        txn = find(counterparty="抖音生活服务商家", amount=Decimal("794.00"))
        self.assertEqual(txn.refund, Decimal("794.00"))
        self.assertEqual(txn.net, Decimal("0.00"))

    def test_refund_leg_does_not_double_count_income(self) -> None:
        leg = find(type="杭州乐刻网络技术有限公司-退款")
        self.assertEqual(leg.bucket, "refund")
        self.assertEqual(leg.net, Decimal("0.00"))
        self.assertEqual(leg.signed, Decimal("0.00"))

    def test_transfer_returned_counts_as_full_refund(self) -> None:
        txn = find(counterparty="大美丽 (鱼哎呦)", amount=Decimal("1314.00"))
        self.assertEqual(txn.refund, Decimal("1314.00"))
        self.assertEqual(txn.net, Decimal("0.00"))


class TestBucket(unittest.TestCase):
    def test_neutral_transaction_excluded(self) -> None:
        txn = find(type="零钱提现")
        self.assertEqual(txn.bucket, "neutral")
        self.assertEqual(txn.signed, Decimal("0.00"))

    def test_settlement_excluded_from_consumption(self) -> None:
        txn = find(type="美团金融还款", amount=Decimal("785.44"))
        self.assertEqual(txn.bucket, "settlement")
        self.assertEqual(txn.signed, Decimal("0.00"))

    def test_transfer_not_in_consumption(self) -> None:
        txn = find(type="转账", amount=Decimal("1400.00"))
        self.assertEqual(txn.bucket, "transfer")

    def test_consumption_identity(self) -> None:
        """消费净额 = 支出净额 − 转账转出 − 还款，三条口径必须闭合。"""
        expense_net = sum((t.net for t in TXNS if t.direction == "expense"), Decimal("0"))
        transfer_out = sum((t.net for t in TXNS if t.bucket == "transfer" and t.direction == "expense"), Decimal("0"))
        settlement = sum((t.amount for t in TXNS if t.bucket == "settlement"), Decimal("0"))
        consumption = sum((t.net for t in TXNS if t.bucket == "consumption"), Decimal("0"))
        self.assertEqual(consumption, expense_net - transfer_out - settlement)


class TestAnalyze(unittest.TestCase):
    def test_monthly_partial_flags(self) -> None:
        by_month = {m["month"]: m for m in RESULT["monthly"]}
        self.assertFalse(by_month["2026-07"]["complete"])
        self.assertTrue(by_month["2026-08"]["complete"])
        self.assertFalse(by_month["2026-10"]["complete"])

    def test_partial_month_uses_covered_days(self) -> None:
        july = next(m for m in RESULT["monthly"] if m["month"] == "2026-07")
        self.assertEqual(july["covered_days"], 11)  # 7/21 - 7/31
        self.assertAlmostEqual(july["avg_daily"], july["consumption"] / 11, places=2)

    def test_monthly_sum_matches_total(self) -> None:
        total = sum(Decimal(str(m["consumption"])) for m in RESULT["monthly"])
        self.assertEqual(total, Decimal(str(RESULT["overview"]["consumption"])))

    def test_budget_projection_exceeds_spent_in_open_month(self) -> None:
        learning = next(b for b in RESULT["budgets"] if b["category"] == "学习")
        self.assertEqual(learning["status"], "over")
        self.assertGreater(learning["projected"], learning["spent"])

    def test_budget_thresholds(self) -> None:
        rows = {b["category"]: b for b in RESULT["budgets"]}
        self.assertEqual(rows["学习"]["status"], "over")
        self.assertIn(rows["购物"]["status"], {"ok", "warn", "over"})


class TestCategorize(unittest.TestCase):
    def test_school_charger_is_transport(self) -> None:
        txn = find(product="单次充电")
        self.assertEqual(txn.category, "交通")

    def test_campus_card_is_campus(self) -> None:
        txn = find(counterparty="山东大学", product="一卡通充值")
        self.assertEqual(txn.category, "校园")

    def test_ecommerce_is_shopping(self) -> None:
        txn = find(counterparty="拼多多平台商户")
        self.assertEqual(txn.category, "购物")

    def test_personal_qr_goes_to_review_not_guess(self) -> None:
        txn = find(counterparty="艾稀宇")
        self.assertEqual(txn.category, "待确认")
        self.assertEqual(txn.category_source, "review")

    def test_ai_suggestion_is_marked_as_ai(self) -> None:
        txn = find(counterparty="双星名人")
        self.assertEqual(txn.category, "购物")
        self.assertEqual(txn.category_source, "ai")

    def test_coverage_above_ninety_percent(self) -> None:
        self.assertGreater(CLASSIFICATION["coverage"], 0.90)


class TestModel(unittest.TestCase):
    def test_money_rounds_half_up(self) -> None:
        self.assertEqual(money("0.005"), Decimal("0.01"))
        self.assertEqual(money(2), Decimal("2.00"))

    def test_manual_txn_defaults(self) -> None:
        txn = Txn(
            id="manual-1",
            ts=datetime(2026, 10, 1, 12, 0, 0),
            type="手动记账",
            counterparty="测试",
            product="/",
            direction="expense",
            amount=Decimal("12.30"),
            status="手动",
            pay_method="手动",
            merchant_id="",
            note="",
        )
        self.assertEqual(txn.month, "2026-10")
        self.assertEqual(txn.net, Decimal("12.30"))
        self.assertEqual(txn.signed, Decimal("-12.30"))


if __name__ == "__main__":
    unittest.main(verbosity=2)