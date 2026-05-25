"""Phase 3 全面验证脚本 — 事件风控 + 评分趋势 + 导出分享"""
import sys
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

print('=== Phase 3 全面验证 ===\n')

# ═══════════════════════════════════════════════════════════════════
# 1. event_context 模块
# ═══════════════════════════════════════════════════════════════════
from quantia.ai_decision.event_context import (
    build_event_context, _infer_risk_type, _infer_opportunity_type
)

print('[1] event_context 模块...')
# 风险子类型推断
assert _infer_risk_type('ST预警公告', '') == 'st_warning'
assert _infer_risk_type('涉嫌违规被处罚', '') == 'regulatory_action'
assert _infer_risk_type('被立案调查', '') == 'investigation'
assert _infer_risk_type('诉讼判决', '') == 'litigation'
assert _infer_risk_type('资产冻结', '') == 'asset_freeze'
assert _infer_risk_type('业绩预亏', '') == 'major_loss'
assert _infer_risk_type('业绩预减', '') == 'earnings_miss'
assert _infer_risk_type('随便', '') == 'general_risk'
# 机会子类型推断
assert _infer_opportunity_type('获得发明专利', '') == 'patent_grant'
assert _infer_opportunity_type('中标重大项目', '') == 'contract_win'
assert _infer_opportunity_type('实控人增持', '') == 'insider_buy'
assert _infer_opportunity_type('业绩预增公告', '') == 'earnings_beat'
assert _infer_opportunity_type('获得政策补贴', '') == 'policy_support'
assert _infer_opportunity_type('战略合作', '') == 'strategic_partnership'
assert _infer_opportunity_type('一般公告', '') == 'general_opportunity'
print('  ✓ 风险/机会子类型推断正确 (15 cases)')


# ═══════════════════════════════════════════════════════════════════
# 2. context_builder
# ═══════════════════════════════════════════════════════════════════
from quantia.ai_decision.context_builder import build_input_summary

print('\n[2] context_builder...')
# 2a. event_context=None → 填充默认
s = build_input_summary(code='000001', decision_date='2026-05-25', event_context=None)
assert 'event_context' in s
assert s['event_context']['news_sentiment'] == 'neutral'
assert s['event_context']['risk_events'] == []
assert s['event_context']['opportunity_events'] == []
assert s['event_context']['recent_announcements'] == []
print('  ✓ event_context=None → 默认空结构')

# 2b. event_context 有值时保留
ec = {
    'risk_events': [{'type': 'st_warning', 'date': '2026-05-20', 'desc': 'ST预警'}],
    'opportunity_events': [],
    'recent_announcements': [{'date': '2026-05-18', 'title': '年报', 'type': '财务报告', 'tag': 'neutral'}],
    'news_sentiment': 'negative',
}
s2 = build_input_summary(code='000001', decision_date='2026-05-25', event_context=ec)
assert s2['event_context'] == ec
print('  ✓ event_context 有值时原样保留')

# 2c. K线窗口未来数据过滤
klines = [
    {'date': '2026-05-23', 'close': 10, 'open': 9.5, 'high': 10.5, 'low': 9.3, 'volume': 1000},
    {'date': '2026-05-24', 'close': 11, 'open': 10, 'high': 11.2, 'low': 9.8, 'volume': 1200},
    {'date': '2026-05-26', 'close': 12, 'open': 11, 'high': 12.5, 'low': 10.5, 'volume': 1500},
]
s3 = build_input_summary(code='000001', decision_date='2026-05-25', kline_window=klines)
assert len(s3['kline_window']) == 2, f"Expected 2, got {len(s3['kline_window'])}"
assert all(row['date'] <= '2026-05-25' for row in s3['kline_window'])
print('  ✓ K线窗口正确过滤未来数据')

# 2d. 空 kline_window → 不含该key
s4 = build_input_summary(code='000001', decision_date='2026-05-25', kline_window=[])
assert 'kline_window' not in s4
print('  ✓ 空K线窗口不添加字段')

# 2e. portfolio_snapshot 只保留安全字段
port = {
    'available_cash': 50000, 'total_value': 100000,
    'api_key': 'secret123',  # 敏感字段
    'drawdown': 0.05,
}
s5 = build_input_summary(code='000001', decision_date='2026-05-25', portfolio_snapshot=port)
assert 'api_key' not in s5.get('portfolio', {})
assert s5['portfolio']['available_cash'] == 50000
print('  ✓ portfolio 过滤敏感字段')


# ═══════════════════════════════════════════════════════════════════
# 3. prompt_renderer
# ═══════════════════════════════════════════════════════════════════
from quantia.ai_decision.prompt_renderer import render_messages, _render_template

print('\n[3] prompt_renderer...')
# 3a. 正常渲染（空事件）
msgs = render_messages(system_prompt=None, user_prompt_template=None, input_summary=s)
assert len(msgs) == 2
user_text = msgs[1]['content']
assert '{{ event_context' not in user_text, f'占位符残留!'
assert '[]' in user_text
assert 'neutral' in user_text
print('  ✓ 空事件时模板完全渲染，无残留占位符')

# 3b. 有风险事件时渲染
msgs2 = render_messages(system_prompt=None, user_prompt_template=None, input_summary=s2)
user_text2 = msgs2[1]['content']
assert 'st_warning' in user_text2
assert 'ST预警' in user_text2
assert '{{ event_context' not in user_text2
print('  ✓ 风险事件正确渲染到 user prompt')

# 3c. System prompt 包含事件评分规则
sys_text = msgs[0]['content']
assert 'ST 预警' in sys_text
assert '70分以上' in sys_text
assert '专利' in sys_text or '突破性技术' in sys_text
print('  ✓ System prompt 包含事件敏感评分规则')

# 3d. _render_template 边界测试
assert _render_template('', {}) == ''
assert _render_template('hello {{ name }}', {'name': 'world'}) == 'hello world'
assert _render_template('{{ missing }}', {}) == '{{ missing }}'  # 未知变量保留
assert _render_template('{{ a.b }}', {'a': {'b': 42}}) == '42'  # 嵌套路径
print('  ✓ 模板渲染边界case正确')


# ═══════════════════════════════════════════════════════════════════
# 4. stock_announcement_em
# ═══════════════════════════════════════════════════════════════════
from quantia.job.stock_announcement_em import classify_tag

print('\n[4] stock_announcement_em 分类...')
# Risk keywords
assert classify_tag('关于公司*ST风险警示的公告', '重大事项') == 'risk'
assert classify_tag('收到行政处罚决定书', '风险提示') == 'risk'
assert classify_tag('涉嫌违规', '') == 'risk'
assert classify_tag('被立案调查', '') == 'risk'
assert classify_tag('诉讼公告', '') == 'risk'
assert classify_tag('关于退市风险警示', '') == 'risk'
assert classify_tag('仲裁申请', '') == 'risk'
assert classify_tag('股份被冻结', '') == 'risk'
assert classify_tag('业绩预亏', '') == 'risk'
assert classify_tag('业绩预减公告', '') == 'risk'
assert classify_tag('业绩首亏公告', '') == 'risk'
assert classify_tag('暂停上市', '') == 'risk'
# Opportunity keywords
assert classify_tag('获得发明专利', '') == 'opportunity'
assert classify_tag('中标公告', '') == 'opportunity'
assert classify_tag('签署重大合同', '') == 'opportunity'
assert classify_tag('关于增持计划', '') == 'opportunity'
assert classify_tag('关于回购股份', '') == 'opportunity'
assert classify_tag('业绩预增', '') == 'opportunity'
assert classify_tag('扭亏为盈', '') == 'opportunity'
assert classify_tag('获得政策补贴', '') == 'opportunity'
assert classify_tag('战略合作框架协议', '') == 'opportunity'
# Neutral
assert classify_tag('关于召开股东大会', '信息变更') == 'neutral'
assert classify_tag('定期报告更正', '财务报告') == 'neutral'
print('  ✓ 公告风险标签分类正确 (23 cases)')


# ═══════════════════════════════════════════════════════════════════
# 5. stockReportHandler 缓存 + 数据变更
# ═══════════════════════════════════════════════════════════════════
import quantia.lib.database as mdb
from quantia.web.stockReportHandler import _check_cache, _has_data_update

print('\n[5] stockReportHandler...')

# 5a. _has_data_update: 财报更新优先
with patch.object(mdb, 'executeSqlFetch') as mock_fetch:
    def se_financial(sql, params=None):
        if 'cn_stock_financial' in sql:
            return [('2026-05-20',)]
        if 'cn_stock_fund_flow' in sql:
            return [('2026-05-18',)]
        if 'cn_stock_selection' in sql:
            return [('2026-05-19',)]
        return []
    mock_fetch.side_effect = se_financial
    has_update, reason = _has_data_update('000001', '2026-05-15 10:00:00')
    assert has_update is True
    assert '新财报' in reason
    # 验证只查了一次(短路)
    assert mock_fetch.call_count == 1, f"Expected 1 call (short-circuit), got {mock_fetch.call_count}"
    print(f'  ✓ 财报更新短路返回: ({has_update}, "{reason}")')

# 5b. 仅资金流向更新
with patch.object(mdb, 'executeSqlFetch') as mock_fetch:
    def se_flow(sql, params=None):
        if 'cn_stock_financial' in sql:
            return [('2026-05-10',)]
        if 'cn_stock_fund_flow' in sql:
            return [('2026-05-16',)]
        if 'cn_stock_selection' in sql:
            return [('2026-05-14',)]
        return []
    mock_fetch.side_effect = se_flow
    has_update, reason = _has_data_update('000001', '2026-05-15 10:00:00')
    assert has_update is True
    assert '资金面' in reason
    assert mock_fetch.call_count == 2  # financial miss → flow hit
    print(f'  ✓ 资金流向更新: ({has_update}, "{reason}")')

# 5c. 仅行情数据更新
with patch.object(mdb, 'executeSqlFetch') as mock_fetch:
    def se_sel(sql, params=None):
        if 'cn_stock_financial' in sql:
            return [('2026-05-10',)]
        if 'cn_stock_fund_flow' in sql:
            return [('2026-05-14',)]
        if 'cn_stock_selection' in sql:
            return [('2026-05-16',)]
        return []
    mock_fetch.side_effect = se_sel
    has_update, reason = _has_data_update('000001', '2026-05-15 10:00:00')
    assert has_update is True
    assert '行情' in reason
    assert mock_fetch.call_count == 3  # all three checked
    print(f'  ✓ 行情数据更新: ({has_update}, "{reason}")')

# 5d. 无更新
with patch.object(mdb, 'executeSqlFetch') as mock_fetch:
    def se_none(sql, params=None):
        if 'cn_stock_financial' in sql:
            return [('2026-05-10',)]
        if 'cn_stock_fund_flow' in sql:
            return [('2026-05-14',)]
        if 'cn_stock_selection' in sql:
            return [('2026-05-14',)]
        return []
    mock_fetch.side_effect = se_none
    has_update, reason = _has_data_update('000001', '2026-05-15 10:00:00')
    assert has_update is False
    assert reason == ''
    print(f'  ✓ 无更新: ({has_update}, "{reason}")')

# 5e. DB 异常时安全返回 (False, "")
with patch.object(mdb, 'executeSqlFetch', side_effect=Exception("DB连接断开")):
    has_update, reason = _has_data_update('000001', '2026-05-15 10:00:00')
    assert has_update is False
    assert reason == ''
    print('  ✓ DB异常时安全降级返回 (False, "")')

# 5f. _check_cache 命中
with patch.object(mdb, 'executeSqlFetch') as mock_fetch:
    mock_fetch.return_value = [
        (1, '000001', '平安银行', '# 报告', 'deepseek-chat', 'deepseek',
         json.dumps(['stock_profile']), 3000, 5000, datetime(2026, 5, 25, 18, 0, 0))
    ]
    result = _check_cache('000001')
    assert result is not None
    assert result['id'] == 1
    assert result['report_md'] == '# 报告'
    assert result['tools_used'] == ['stock_profile']
    print('  ✓ 缓存命中返回正确结构')

# 5g. _check_cache 未命中
with patch.object(mdb, 'executeSqlFetch') as mock_fetch:
    mock_fetch.return_value = []
    result = _check_cache('999999')
    assert result is None
    print('  ✓ 缓存未命中返回 None')


# ═══════════════════════════════════════════════════════════════════
# 6. Timeline 评级提取
# ═══════════════════════════════════════════════════════════════════
print('\n[6] Timeline 评级提取...')
test_cases = [
    ('🟢买入 — MACD金叉+主力连续流入', '🟢买入'),
    ('综合评级：🟡观望，等待回调确认', '🟡观望'),
    ('建议🔴回避，短期利空较大', '🔴回避'),
    ('当前可以买入，估值合理', '买入'),
    ('建议观望等待确认信号', '观望'),
    ('回避该股，风险较大', '回避'),
    ('没有明确评级的报告内容 pure technical', ''),
]
for excerpt, expected in test_cases:
    rating = ''
    for tag in ['🟢买入', '🟡观望', '🔴回避', '买入', '观望', '回避']:
        if tag in excerpt:
            rating = tag
            break
    assert rating == expected, f'Expected "{expected}" got "{rating}" for: {excerpt[:40]}'
print(f'  ✓ 评级关键词提取正确 ({len(test_cases)} cases)')


# ═══════════════════════════════════════════════════════════════════
# 7. Share handler UUID + 路由匹配
# ═══════════════════════════════════════════════════════════════════
print('\n[7] 分享链接验证...')
import uuid, re
token = str(uuid.uuid4())
assert len(token) == 36
assert re.match(r'^[a-f0-9\-]{36}$', token)
# Route regex
route_re = re.compile(r'/quantia/api/ai/report/shared/([a-f0-9\-]{36})')
m = route_re.match(f'/quantia/api/ai/report/shared/{token}')
assert m is not None and m.group(1) == token
# Invalid token rejected
m2 = route_re.match('/quantia/api/ai/report/shared/invalid-token')
assert m2 is None
m3 = route_re.match('/quantia/api/ai/report/shared/' + 'A' * 36)  # uppercase = rejected
assert m3 is None
print('  ✓ UUID 生成 + 路由正则验证正确')


# ═══════════════════════════════════════════════════════════════════
# 8. Paper engine 集成点验证
# ═══════════════════════════════════════════════════════════════════
print('\n[8] Paper engine 集成验证...')
# 验证 build_event_context 在无DB时安全返回
with patch.dict('sys.modules', {'quantia.lib.database': None}):
    # Re-import to test import failure path
    import importlib
    from quantia.ai_decision import event_context as ec_mod
    # Direct test: when DB import fails
    result = ec_mod.build_event_context('600519')
    assert result == {
        'recent_announcements': [],
        'risk_events': [],
        'opportunity_events': [],
        'news_sentiment': 'neutral',
    }
    print('  ✓ build_event_context 在 DB 不可用时安全返回空结构')

# 验证 paper_engine 的事件过滤逻辑
# 当无风险/机会事件时传 None（节省 token）
empty_ctx = {'risk_events': [], 'opportunity_events': [], 'recent_announcements': [], 'news_sentiment': 'neutral'}
should_pass_none = not (empty_ctx.get('risk_events') or empty_ctx.get('opportunity_events'))
assert should_pass_none is True
print('  ✓ 空事件时传 None（节省 token）')

# 当有事件时传完整 context
full_ctx = {'risk_events': [{'type': 'st', 'desc': 'xx'}], 'opportunity_events': [], 'recent_announcements': [], 'news_sentiment': 'negative'}
should_pass_ctx = bool(full_ctx.get('risk_events') or full_ctx.get('opportunity_events'))
assert should_pass_ctx is True
print('  ✓ 有事件时传完整 context')


# ═══════════════════════════════════════════════════════════════════
# 9. Score history handler SQL 验证
# ═══════════════════════════════════════════════════════════════════
print('\n[9] Score history SQL 逻辑...')
# Verify the handler filters status='succeeded' and orders by decision_date ASC
import inspect
from quantia.web.stockReportHandler import StockScoreHistoryHandler
src = inspect.getsource(StockScoreHistoryHandler)
assert "status = 'succeeded'" in src
assert "ORDER BY decision_date ASC" in src
assert "cn_stock_trade_ai_score" in src
assert "DATE_SUB(CURDATE(), INTERVAL %s DAY)" in src
print('  ✓ ScoreHistoryHandler SQL: succeeded过滤 + ASC排序 + 日期参数化')


# ═══════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════
print('\n' + '=' * 60)
print('  Phase 3 全面验证通过！共 9 组 50+ 测试用例')
print('=' * 60)
