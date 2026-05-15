# -*- coding: utf-8 -*-
"""Phase 6: IM 指令确认模块。

模块边界：
- ``schema``：建表 / 表名常量。
- ``signature``：钉钉回调 HMAC-SHA256 签名校验。
- ``service``：指令解析 / 风控 / 持久化（不直接调券商，落 ``cn_stock_trade_command``）。

设计要点：
- ``QUANTIA_IM_COMMAND_ENABLED`` 默认关闭，回调直接 503，仅在测试或开通后启用。
- 所有指令落库（含拒绝原因）；通过 ``UNIQUE(source_channel, source_message_id)`` 防重放。
- 风控字段（最大单笔金额、最大单日金额、白名单）在 service 内集中校验，便于审计。
"""
