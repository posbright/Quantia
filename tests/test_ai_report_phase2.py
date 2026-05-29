#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from unittest.mock import patch


SAMPLE_REPORT = """
#### 一、行情概览
当前走势震荡。

#### 二、技术面
指标偏强。

#### 三、基本面
研发投入稳定。

#### 四、资金面
主力资金小幅流入。

#### 四.五、竞争壁垒（护城河）
- 核心专利较多，IPC 主要集中在通信领域，研发团队稳定。
- 品牌和规模优势一般。

#### 五、多空对比
| 看多因素 | 看空因素 |
| --- | --- |
| 资金改善 | 估值不低 |

#### 六、综合判断与操作建议
##### 评级: 🟢买入（综合评分 82 分）

##### 短期（1-4周）
- 操作建议: 回踩承接后分批介入，止损价 14.5 元。
- 关键催化: 资金继续流入。

##### 中期（1-6个月）
- 趋势判断: 目标区间 18-22 元，关注订单兑现。

##### 长期（1年以上）
- 护城河强度评分: 强。
- 适合长持，但需跟踪研发转化。

#### 七、风险提示
股市有风险。
"""


def test_extract_structured_fields_from_phase2_report():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(SAMPLE_REPORT)

    assert fields['rating'] == 'buy'
    assert fields['rating_score'] == 82
    assert fields['short_term_advice'].startswith('操作建议')
    assert '目标区间' in fields['mid_term_advice']
    assert fields['long_term_advice'].startswith('护城河强度评分')
    assert fields['target_price_low'] == 18.0
    assert fields['target_price_high'] == 22.0
    assert fields['stop_loss_price'] == 14.5
    assert fields['moat_score'] == 5
    assert fields['moat_factors']['patents'] is True
    assert fields['moat_factors']['tech'] is True


def test_rating_option_line_is_not_parsed_as_avoid():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '#### 六、综合判断与操作建议\n'
        '##### 评级: 🟢买入 / 🟡观望 / 🔴回避（一句话理由）\n'
    )

    assert fields['rating'] is None
    assert fields['rating_score'] is None


def test_single_rating_line_is_parsed():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '#### 六、综合判断与操作建议\n'
        '##### 评级: 🟡观望（等待趋势确认）\n'
    )

    assert fields['rating'] == 'hold'
    assert fields['rating_score'] == 50


def test_moat_option_line_is_not_parsed_as_strong():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '#### 四.五、竞争壁垒（护城河）\n'
        '- **护城河强度**: 强 / 中 / 弱 / 无（一句话理由）\n'
    )

    assert fields['moat_score'] is None


def test_stop_loss_does_not_match_risk_reward_ratio():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '##### 短期（1-4周）\n'
        '- 止损-止盈策略 风险报酬比 1:3。\n'
    )

    assert fields['stop_loss_price'] is None


def test_mid_term_advice_stops_at_next_heading():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '##### 中期（1-6个月）\n'
        '- 目标价区间 22-26 元。\n'
        '#### 四.五、竞争壁垒（护城河）\n'
        '- **护城河强度**: 中。\n'
    )

    assert fields['mid_term_advice'] is not None
    assert '护城河' not in fields['mid_term_advice']
    assert '四.五' not in fields['mid_term_advice']


def test_moat_score_with_markdown_bold():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '#### 四.五、竞争壁垒（护城河）\n'
        '- **护城河强度**：**中**（规模+技术双驱动）\n'
    )
    assert fields['moat_score'] == 3


def test_target_price_with_en_dash():
    from quantia.lib.ai.report_parser import extract_structured_fields

    fields = extract_structured_fields(
        '##### 中期（1-6个月）\n'
        '- 目标价区间：4.10\u20134.70元（对应PB 1.35\u20131.55倍）\n'
    )
    assert fields['target_price_low'] == 4.1
    assert fields['target_price_high'] == 4.7


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self.lastrowid = 99

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def fetchone(self):
        return (7, 2)


class _FakeConnection:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.autocommit_values = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def cursor(self):
        return self.cursor_obj

    def autocommit(self, value):
        self.autocommit_values.append(value)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True



def test_save_report_persists_structured_fields_and_version():
    from quantia.web import stockReportHandler as handler

    fake_conn = _FakeConnection()
    with patch.object(handler, '_lazy_ensure_table'), \
         patch.object(handler.mdb, 'get_connection', return_value=fake_conn):
        report_id = handler._save_report(
            code='300560',
            name='中富通',
            report_md=SAMPLE_REPORT,
            model='test-model',
            provider='test-provider',
            tools_used=['stock_profile'],
            tokens_used=123,
            latency_ms=456,
        )

    assert report_id == 99
    assert fake_conn.committed is True
    assert fake_conn.rolled_back is False
    assert fake_conn.autocommit_values == [False, True]
    assert len(fake_conn.cursor_obj.calls) == 2

    insert_sql, params = fake_conn.cursor_obj.calls[1]
    assert 'rating, rating_score, short_term_advice' in insert_sql
    assert params[9] == 'buy'
    assert params[10] == 82
    assert params[14] == 18.0
    assert params[15] == 22.0
    assert params[16] == 14.5
    assert params[17] == 5
    assert json.loads(params[18])['patents'] is True
    assert params[19] == 3
    assert params[20] == 7


def test_phase2_columns_are_in_lazy_migration_source():
    from quantia.web import stockReportHandler as handler

    source = handler._ensure_missing_columns.__code__.co_consts
    joined = '\n'.join(str(item) for item in source)

    assert 'ADD COLUMN rating ENUM' in joined
    assert 'ADD COLUMN short_term_advice' in joined
    assert 'ADD COLUMN moat_factors JSON' in joined
    assert 'ADD COLUMN report_version INT' in joined
    assert 'ADD INDEX idx_rating' in joined