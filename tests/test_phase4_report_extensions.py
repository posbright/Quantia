#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4 功能验证测试。

覆盖:
1. AI 评分预警推送逻辑
2. 定时分析 cron 逻辑
3. 报告对比 handler
4. 钉钉报告推送
5. 专利数据爬虫数据模型
6. 机构评级数据模型
7. 多语言翻译 handler
8. 语音播报文本提取
9. 自定义报告偏好 handler
"""
import json
import sys
import os
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════
# 1. 定时分析 + 评分预警
# ═══════════════════════════════════════════════════════════════════

class TestStockReportScheduled:
    """stock_report_scheduled.py 单元测试。"""

    def test_module_import(self):
        import quantia.job.stock_report_scheduled as srs
        assert hasattr(srs, 'scheduled_report_analysis')
        assert hasattr(srs, 'score_alert_check')
        assert hasattr(srs, 'push_report_summary_to_dingtalk')
        assert hasattr(srs, 'run_all')

    @patch('quantia.job.stock_report_scheduled.mdb')
    def test_get_attention_codes_empty(self, mock_mdb):
        from quantia.job.stock_report_scheduled import _get_attention_codes
        mock_mdb.executeSqlFetch.return_value = []
        codes = _get_attention_codes()
        assert codes == []

    @patch('quantia.job.stock_report_scheduled.mdb')
    def test_get_attention_codes_returns_valid(self, mock_mdb):
        from quantia.job.stock_report_scheduled import _get_attention_codes
        mock_mdb.executeSqlFetch.return_value = [('000001',), ('600036',), ('invalid',)]
        codes = _get_attention_codes()
        assert codes == ['000001', '600036']

    @patch('quantia.job.stock_report_scheduled.mdb')
    def test_get_score_threshold_default(self, mock_mdb):
        from quantia.job.stock_report_scheduled import _get_score_threshold
        mock_mdb.executeSqlFetch.return_value = []
        threshold = _get_score_threshold()
        assert threshold == 50

    @patch('quantia.job.stock_report_scheduled.mdb')
    def test_get_score_threshold_custom(self, mock_mdb):
        from quantia.job.stock_report_scheduled import _get_score_threshold
        mock_mdb.executeSqlFetch.return_value = [(json.dumps({'threshold': 40}),)]
        threshold = _get_score_threshold()
        assert threshold == 40

    def test_build_alert_dedupe_key(self):
        from quantia.job.stock_report_scheduled import _build_alert_dedupe_key
        key1 = _build_alert_dedupe_key('000001', 'score_drop', '2026-01-01')
        key2 = _build_alert_dedupe_key('000001', 'score_drop', '2026-01-01')
        key3 = _build_alert_dedupe_key('000001', 'score_drop', '2026-01-02')
        assert key1 == key2  # 同参数相同
        assert key1 != key3  # 不同日期不同
        assert len(key1) == 64

    @patch('quantia.job.stock_report_scheduled.mdb')
    def test_is_alert_cooled_down_false(self, mock_mdb):
        from quantia.job.stock_report_scheduled import _is_alert_cooled_down
        mock_mdb.executeSqlFetch.return_value = [(0,)]
        assert not _is_alert_cooled_down('000001', 'score_drop')

    @patch('quantia.job.stock_report_scheduled.mdb')
    def test_is_alert_cooled_down_true(self, mock_mdb):
        from quantia.job.stock_report_scheduled import _is_alert_cooled_down
        mock_mdb.executeSqlFetch.return_value = [(1,)]
        assert _is_alert_cooled_down('000001', 'score_drop')

    def test_build_score_alert_message(self):
        from quantia.job.stock_report_scheduled import _build_score_alert_message
        msg = _build_score_alert_message(
            '000001', '平安银行', 35.5, 50, 'reject', '技术面弱势', '2026-01-01 10:00'
        )
        assert '⚠️' in msg['title']
        assert '000001' in msg['title']
        assert '35.5' in msg['markdown']
        assert '50' in msg['markdown']
        assert '拒绝交易' in msg['markdown']

    @patch('quantia.job.stock_report_scheduled._get_attention_codes')
    def test_scheduled_report_analysis_empty(self, mock_codes):
        from quantia.job.stock_report_scheduled import scheduled_report_analysis
        mock_codes.return_value = []
        result = scheduled_report_analysis()
        assert result['generated'] == 0
        assert result['total'] == 0

    @patch('quantia.job.stock_report_scheduled._get_attention_codes')
    def test_score_alert_check_empty(self, mock_codes):
        from quantia.job.stock_report_scheduled import score_alert_check
        mock_codes.return_value = []
        result = score_alert_check()
        assert result['checked'] == 0
        assert result['alerted'] == 0


# ═══════════════════════════════════════════════════════════════════
# 2. 专利数据爬虫
# ═══════════════════════════════════════════════════════════════════

class TestPatentCrawler:
    """stock_patent_crawler.py 单元测试。"""

    def test_module_import(self):
        import quantia.job.stock_patent_crawler as spc
        assert hasattr(spc, 'fetch_patent_announcements')
        assert hasattr(spc, 'save_patent_data')
        assert hasattr(spc, 'run_patent_crawler')

    def test_classify_patent_type(self):
        from quantia.job.stock_patent_crawler import _classify_patent_type
        assert _classify_patent_type('关于获得发明专利的公告') == 'invention'
        assert _classify_patent_type('实用新型专利授权') == 'utility'
        assert _classify_patent_type('外观设计专利') == 'design'
        assert _classify_patent_type('知识产权转让') == 'ip_transfer'
        assert _classify_patent_type('获得XX项专利') == 'general'

    def test_extract_patent_count(self):
        from quantia.job.stock_patent_crawler import _extract_patent_count
        assert _extract_patent_count('获得15项发明专利') == 15
        assert _extract_patent_count('3件实用新型') == 3
        assert _extract_patent_count('某公告标题') is None

    @patch('quantia.job.stock_patent_crawler.mdb')
    def test_save_empty_records(self, mock_mdb):
        from quantia.job.stock_patent_crawler import save_patent_data
        result = save_patent_data([])
        assert result == 0


# ═══════════════════════════════════════════════════════════════════
# 3. 机构评级数据爬虫
# ═══════════════════════════════════════════════════════════════════

class TestRatingCrawler:
    """stock_rating_crawler.py 单元测试。"""

    def test_module_import(self):
        import quantia.job.stock_rating_crawler as src
        assert hasattr(src, 'fetch_institutional_ratings')
        assert hasattr(src, 'save_rating_data')
        assert hasattr(src, 'get_stock_ratings')
        assert hasattr(src, 'get_rating_consensus')

    def test_normalize_rating(self):
        from quantia.job.stock_rating_crawler import _normalize_rating
        assert _normalize_rating('买入') == '买入'
        assert _normalize_rating('强烈推荐') == '买入'
        assert _normalize_rating('增持') == '增持'
        assert _normalize_rating('持有') == '中性'
        assert _normalize_rating('减持') == '减持'
        assert _normalize_rating('弱于大市') == '减持'

    def test_normalize_rating_change(self):
        from quantia.job.stock_rating_crawler import _normalize_rating_change
        assert _normalize_rating_change('上调') == '上调'
        assert _normalize_rating_change('调高') == '上调'
        assert _normalize_rating_change('维持') == '维持'
        assert _normalize_rating_change('下调') == '下调'
        assert _normalize_rating_change('首次覆盖') == '首次'

    @patch('quantia.job.stock_rating_crawler.mdb')
    def test_save_empty_records(self, mock_mdb):
        from quantia.job.stock_rating_crawler import save_rating_data
        result = save_rating_data([])
        assert result == 0


# ═══════════════════════════════════════════════════════════════════
# 4. Handler 注册验证
# ═══════════════════════════════════════════════════════════════════

class TestHandlerRegistration:
    """验证 Phase 4 handlers 正确注册。"""

    def test_compare_handler_exists(self):
        from quantia.web.stockReportHandler import StockReportCompareHandler
        assert StockReportCompareHandler is not None

    def test_preference_handler_exists(self):
        from quantia.web.stockReportHandler import StockReportPreferenceHandler
        assert StockReportPreferenceHandler is not None

    def test_translate_handler_exists(self):
        from quantia.web.stockReportHandler import StockReportTranslateHandler
        assert StockReportTranslateHandler is not None

    def test_speech_text_handler_exists(self):
        from quantia.web.stockReportHandler import StockReportSpeechTextHandler
        assert StockReportSpeechTextHandler is not None

    def test_routes_registered(self):
        """验证 web_service 中新路由存在。"""
        import quantia.web.web_service as ws
        import inspect
        source = inspect.getsource(ws)
        assert '/quantia/api/ai/report/compare' in source
        assert '/quantia/api/ai/report/preference' in source
        assert '/quantia/api/ai/report/translate' in source
        assert '/quantia/api/ai/report/speech_text' in source


# ═══════════════════════════════════════════════════════════════════
# 5. 语音文本提取逻辑
# ═══════════════════════════════════════════════════════════════════

class TestSpeechTextExtraction:
    """验证 Markdown → 纯文本转换逻辑。"""

    def test_markdown_strip_basic(self):
        """模拟 speech_text handler 的文本清洗逻辑。"""
        import re
        text = "## 标题\n\n**加粗文字** 和 *斜体*\n\n```python\ncode\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |"

        # 去除代码块
        text = re.sub(r'```[\s\S]*?```', '', text)
        # 去除标题符号
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # 去除加粗/斜体
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        # 去除表格分隔线
        text = re.sub(r'\|?[-:]+\|[-:|]+\|?', '', text)
        text = re.sub(r'\|', '，', text)
        text = text.strip()

        assert '##' not in text
        assert '**' not in text
        assert '```' not in text
        assert '标题' in text
        assert '加粗文字' in text


# ═══════════════════════════════════════════════════════════════════
# 6. 钉钉报告推送
# ═══════════════════════════════════════════════════════════════════

class TestDingTalkReportPush:
    """验证钉钉报告推送逻辑。"""

    @patch('quantia.job.stock_report_scheduled._get_user_preference')
    @patch('quantia.notification.service._load_config')
    def test_push_disabled(self, mock_config, mock_pref):
        from quantia.job.stock_report_scheduled import push_report_summary_to_dingtalk
        mock_pref.return_value = {'push_enabled': True}
        mock_config.return_value = {'enabled': False, 'webhook': ''}
        result = push_report_summary_to_dingtalk('000001', '平安银行', '测试摘要', 'bullish')
        assert result is False

    @patch('quantia.notification.channels.dingtalk.DingTalkChannel')
    @patch('quantia.notification.service._load_config')
    @patch('quantia.job.stock_report_scheduled._get_user_preference')
    def test_push_enabled(self, mock_pref, mock_config, mock_channel_cls):
        from quantia.job.stock_report_scheduled import push_report_summary_to_dingtalk
        mock_pref.return_value = {'push_enabled': True}
        mock_config.return_value = {'enabled': True, 'webhook': 'http://test', 'secret': ''}

        mock_result = MagicMock()
        mock_result.ok = True
        mock_channel_cls.return_value.send.return_value = mock_result

        result = push_report_summary_to_dingtalk('000001', '平安银行', '看多摘要', 'bullish')
        assert result is True


# ═══════════════════════════════════════════════════════════════════
# 7. Cron 脚本存在性验证
# ═══════════════════════════════════════════════════════════════════

class TestCronIntegration:
    """验证 cron 配置完整性。"""

    def test_cron_script_exists(self):
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cron', 'cron.workdayly', 'run_report_alert'
        )
        assert os.path.exists(script_path), f'Missing: {script_path}'

    def test_cron_script_content(self):
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cron', 'cron.workdayly', 'run_report_alert'
        )
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'stock_report_scheduled' in content
        assert '--mode all' in content

    def test_workdayly_calls_report_alert(self):
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cron', 'cron.workdayly', 'run_workdayly'
        )
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'run_report_alert' in content
        assert 'Phase 5: AI报告+评分预警' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
