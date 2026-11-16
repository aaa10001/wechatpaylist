# -*- coding: utf-8 -*-
"""MoneyLens —— 个人收支与预算分析。

模块划分：
  model       领域模型（Txn）与金额口径
  ingest      微信账单解析、退款识别、解析校验
  categorize  规则引擎 + 人工覆盖 + AI 建议
  analytics   月度趋势、分类、预算、异常、洞察、Markdown 报告
  build       命令行入口，产出 Web 数据与报告
"""
__version__ = "0.1.0"