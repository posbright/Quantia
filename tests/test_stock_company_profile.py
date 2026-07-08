# -*- coding: utf-8 -*-
"""公司概况（F10 经营分析）抓取解析 + handler 解析单元测试。

覆盖：
- to_secid 交易所前缀路由
- stock_business_composition 解析 zyfw/zygcfx/jyps，最新报告期筛选、主营构成分组排序
- StockBusinessHandler._parse_mainop JSON 字符串解析容错

全部 mock，不打外部 API / 不连 DB。
"""
from unittest import mock

import pytest

import quantia.core.crawling.stock_business_em as sbe
import quantia.core.crawling.stock_business_ths as sbt
import quantia.job.fetch_company_profile_job as fcp
import quantia.web.stockProfileHandler as sph


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _sample_payload():
    return {
        'zyfw': [{'SECUCODE': '000651.SZ', 'BUSINESS_SCOPE': '制冷、空调设备制造;家用电器销售'}],
        'jyps': [{'SECUCODE': '000651.SZ', 'REPORT_DATE': '2025-12-31 00:00:00',
                  'BUSINESS_REVIEW': '公司是一家多元化科技型全球工业集团。'}],
        'zygcfx': [
            # 最新报告期
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '2', 'ITEM_NAME': '消费电器',
             'MAIN_BUSINESS_INCOME': 133055208627.13, 'MBI_RATIO': 0.780625,
             'GROSS_RPOFIT_RATIO': 0.352806, 'RANK': 1},
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '1', 'ITEM_NAME': '制造业',
             'MAIN_BUSINESS_INCOME': 153781972343.46, 'MBI_RATIO': 0.902227,
             'GROSS_RPOFIT_RATIO': 0.327466, 'RANK': 1},
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '3', 'ITEM_NAME': '内销',
             'MAIN_BUSINESS_INCOME': 126407077425.42, 'MBI_RATIO': 0.741621,
             'GROSS_RPOFIT_RATIO': 0.345242, 'RANK': 1},
            # 旧报告期（应被过滤）
            {'REPORT_DATE': '2016-12-31 00:00:00', 'MAINOP_TYPE': '1', 'ITEM_NAME': '空调',
             'MAIN_BUSINESS_INCOME': 88000000000.0, 'MBI_RATIO': 0.8,
             'GROSS_RPOFIT_RATIO': 0.3, 'RANK': 1},
        ],
    }


def test_to_secid_routing():
    assert sbe.to_secid('600519') == 'SH600519'
    assert sbe.to_secid('000651') == 'SZ000651'
    assert sbe.to_secid('300750') == 'SZ300750'
    assert sbe.to_secid('831832') == 'BJ831832'  # 北交所 8 开头
    assert sbe.to_secid('430047') == 'BJ430047'  # 北交所 4 开头
    assert sbe.to_secid('920819') == 'BJ920819'  # 北交所新代码段 920（须先于 9→SH 判断）
    assert sbe.to_secid('900957') == 'SH900957'  # 沪市 B 股 900
    assert sbe.to_secid('651') == 'SZ000651'     # 补零


def test_stock_business_composition_parsing():
    with mock.patch.object(sbe.fetcher, 'make_request', return_value=_FakeResp(_sample_payload())):
        out = sbe.stock_business_composition('000651')
    assert out is not None
    assert out['report_date'] == '2025-12-31'
    assert out['business_scope'].startswith('制冷')
    assert out['business_review'].startswith('公司是一家')
    # 只保留最新报告期（2016 的“空调”应被过滤）
    items = out['mainop']
    assert all(it['item'] != '空调' for it in items)
    assert len(items) == 3
    # 分组排序：行业 → 产品 → 地区
    types_in_order = [it['type'] for it in items]
    assert types_in_order == ['行业', '产品', '地区']
    manufacturing = next(it for it in items if it['item'] == '制造业')
    assert manufacturing['income'] == 153781972343.46
    assert abs(manufacturing['income_ratio'] - 0.902227) < 1e-6
    assert abs(manufacturing['gross_profit_ratio'] - 0.327466) < 1e-6
    # 每个明细项携带其维度自身报告期
    assert all(it['report_date'] == '2025-12-31' for it in items)


def _mixed_period_payload():
    """模拟真实场景：不同维度最新披露期不同。
    - 按行业(type1) 最新停在 2019-12-31（多年未再披露，应被剔除）
    - 按产品(type2) 最新为 2025-06-30（半年报，距全局最新 <450 天，应保留）
    - 按地区(type3) 最新为 2025-12-31（年报，全局最新）
    """
    return {
        'zyfw': [{'BUSINESS_SCOPE': '银行业务'}],
        'jyps': [{'REPORT_DATE': '2025-12-31 00:00:00', 'BUSINESS_REVIEW': '经营评述。'}],
        'zygcfx': [
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '3', 'ITEM_NAME': '华东地区',
             'MAIN_BUSINESS_INCOME': 5e10, 'MBI_RATIO': 0.5, 'GROSS_RPOFIT_RATIO': 0.4, 'RANK': 1},
            {'REPORT_DATE': '2025-06-30 00:00:00', 'MAINOP_TYPE': '2', 'ITEM_NAME': '对公业务',
             'MAIN_BUSINESS_INCOME': 6e10, 'MBI_RATIO': 0.6, 'GROSS_RPOFIT_RATIO': 0.45, 'RANK': 1},
            {'REPORT_DATE': '2025-06-30 00:00:00', 'MAINOP_TYPE': '2', 'ITEM_NAME': '零售业务',
             'MAIN_BUSINESS_INCOME': 4e10, 'MBI_RATIO': 0.4, 'GROSS_RPOFIT_RATIO': 0.35, 'RANK': 2},
            # 陈旧行业维度（2019），应被整体剔除
            {'REPORT_DATE': '2019-12-31 00:00:00', 'MAINOP_TYPE': '1', 'ITEM_NAME': '金融业',
             'MAIN_BUSINESS_INCOME': 3e10, 'MBI_RATIO': 1.0, 'GROSS_RPOFIT_RATIO': 0.3, 'RANK': 1},
        ],
    }


def test_stock_business_composition_per_dimension_latest_period():
    """回归：不同维度取各自最新期，保留近期错期维度、剔除多年僵尸维度。"""
    with mock.patch.object(sbe.fetcher, 'make_request',
                           return_value=_FakeResp(_mixed_period_payload())):
        out = sbe.stock_business_composition('600000')
    assert out is not None
    # 整表报告期 = 全局最新 2025-12-31
    assert out['report_date'] == '2025-12-31'
    items = out['mainop']
    types = {it['type'] for it in items}
    # 陈旧的“按行业”(2019) 被剔除
    assert '行业' not in types
    assert all(it['item'] != '金融业' for it in items)
    # “按产品”(2025-06-30, 半年报) 被保留，且携带其自身报告期
    product_items = [it for it in items if it['type'] == '产品']
    assert len(product_items) == 2
    assert all(it['report_date'] == '2025-06-30' for it in product_items)
    # “按地区”(2025-12-31) 保留
    region_items = [it for it in items if it['type'] == '地区']
    assert len(region_items) == 1
    assert region_items[0]['report_date'] == '2025-12-31'
    # 排序：产品在地区之前
    assert [it['type'] for it in items] == ['产品', '产品', '地区']


def test_stock_business_composition_empty_returns_none():
    empty = {'zyfw': [], 'jyps': [], 'zygcfx': []}
    with mock.patch.object(sbe.fetcher, 'make_request', return_value=_FakeResp(empty)):
        assert sbe.stock_business_composition('000651') is None


def test_stock_business_composition_request_failure_raises():
    # 传输层失败（尽管 make_request 已重试）应抛 BusinessFetchError，供上层 job 熔断区分。
    with mock.patch.object(sbe.fetcher, 'make_request', side_effect=RuntimeError('boom')):
        with pytest.raises(sbe.BusinessFetchError):
            sbe.stock_business_composition('000651')


def test_run_switches_to_ths_after_em_ban(monkeypatch):
    """EM 连续失败达阈值 ⇒ 确认被封 ⇒ 整体切换同花顺备用源续采（含失败流重排），
    不再调用 EM；同花顺正常则全部处理完，不中止。"""
    codes = [str(600000 + i) for i in range(200)]
    calls = {'em': 0, 'ths': 0}

    def _save(code, update_date, source='em'):
        calls[source] += 1
        if source == 'em':
            return (0, False)  # EM 始终传输失败
        return (1, True)       # 同花顺正常

    monkeypatch.setattr(fcp, 'save_company_profile', _save)
    monkeypatch.setattr(fcp, 'record_task_start', lambda *a, **k: 0)
    monkeypatch.setattr(fcp, 'record_task_end', lambda *a, **k: None)
    monkeypatch.setattr(fcp.time, 'sleep', lambda *a, **k: None)
    monkeypatch.setattr(fcp, '_MAX_CONSECUTIVE_FAILURES', 30)

    fcp.run(codes=codes, force=True)
    # EM 连续 30 失败即确认被封、停止调用 EM
    assert calls['em'] == 30
    # 切换后 THS 处理：重排队列 = 30 失败流 + 剩余 170 = 200 只
    assert calls['ths'] == 200


def test_run_aborts_when_both_sources_banned(monkeypatch):
    """EM 被封切换同花顺后，同花顺也连续失败达阈值 ⇒ 确认两源皆封 ⇒ 中止。"""
    codes = [str(600000 + i) for i in range(200)]
    calls = {'em': 0, 'ths': 0}

    def _save(code, update_date, source='em'):
        calls[source] += 1
        return (0, False)  # 两源都传输失败

    monkeypatch.setattr(fcp, 'save_company_profile', _save)
    monkeypatch.setattr(fcp, 'record_task_start', lambda *a, **k: 0)
    monkeypatch.setattr(fcp, 'record_task_end', lambda *a, **k: None)
    monkeypatch.setattr(fcp.time, 'sleep', lambda *a, **k: None)
    monkeypatch.setattr(fcp, '_MAX_CONSECUTIVE_FAILURES', 30)

    fcp.run(codes=codes, force=True)
    assert calls['em'] == 30   # EM 30 失败 → 切换同花顺
    assert calls['ths'] == 30  # 同花顺 30 失败 → 中止


def test_run_no_switch_when_em_healthy(monkeypatch):
    """EM 全程可达 ⇒ 全部走 EM，绝不切换同花顺。"""
    codes = [str(600000 + i) for i in range(80)]
    calls = {'em': 0, 'ths': 0}

    def _save(code, update_date, source='em'):
        calls[source] += 1
        return (1, True)

    monkeypatch.setattr(fcp, 'save_company_profile', _save)
    monkeypatch.setattr(fcp, 'record_task_start', lambda *a, **k: 0)
    monkeypatch.setattr(fcp, 'record_task_end', lambda *a, **k: None)
    monkeypatch.setattr(fcp.time, 'sleep', lambda *a, **k: None)
    monkeypatch.setattr(fcp, '_MAX_CONSECUTIVE_FAILURES', 30)

    fcp.run(codes=codes, force=True)
    assert calls['em'] == 80
    assert calls['ths'] == 0


def test_run_em_transient_failures_do_not_switch(monkeypatch):
    """EM 间歇失败（未连续达阈值）不触发切换，仍走 EM 跑完全部。"""
    codes = [str(600000 + i) for i in range(80)]
    calls = {'em': 0, 'ths': 0}

    def _save(code, update_date, source='em'):
        calls[source] += 1
        if source == 'em':
            # 每 10 只可达一只，最大连续失败 9 < 30，不切换
            return (1, True) if calls['em'] % 10 == 0 else (0, False)
        return (1, True)

    monkeypatch.setattr(fcp, 'save_company_profile', _save)
    monkeypatch.setattr(fcp, 'record_task_start', lambda *a, **k: 0)
    monkeypatch.setattr(fcp, 'record_task_end', lambda *a, **k: None)
    monkeypatch.setattr(fcp.time, 'sleep', lambda *a, **k: None)
    monkeypatch.setattr(fcp, '_MAX_CONSECUTIVE_FAILURES', 30)

    fcp.run(codes=codes, force=True)
    assert calls['em'] == 80
    assert calls['ths'] == 0  # 未切换


def test_handler_parse_mainop():
    assert sph._parse_mainop(None) == []
    assert sph._parse_mainop('') == []
    assert sph._parse_mainop('not-json') == []
    assert sph._parse_mainop('[{"item":"x"}]') == [{'item': 'x'}]
    # 已是 list 时原样返回
    assert sph._parse_mainop([{'item': 'y'}]) == [{'item': 'y'}]
    # JSON 对象（非 list）应归一为空 list
    assert sph._parse_mainop('{"a":1}') == []


# ---------------------------------------------------------------------------
# 同花顺备用源（stock_business_ths）
# ---------------------------------------------------------------------------
class _FakeThsDF:
    """极简 DataFrame 替身：iloc[0].to_dict() 返回首行 dict。"""
    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    class _ILoc:
        def __init__(self, rows):
            self._rows = rows

        def __getitem__(self, idx):
            class _Row:
                def __init__(self, d):
                    self._d = d

                def to_dict(self):
                    return self._d
            return _Row(self._rows[idx])

    @property
    def iloc(self):
        return self._ILoc(self._rows)


def test_ths_composition_success():
    """同花顺返回定性主营 → 经营范围/主营评述解析成功，mainop 恒空（不编造占比）。"""
    df = _FakeThsDF([{
        '股票代码': '000651', '主营业务': '空调、生活电器、工业制品',
        '产品类型': '家用空调、冰箱', '产品名称': '格力空调', '经营范围': '制冷设备制造；家电销售',
    }])
    fake_ak = mock.MagicMock()
    fake_ak.stock_zyjs_ths.return_value = df
    with mock.patch.dict('sys.modules', {'akshare': fake_ak}):
        out = sbt.stock_business_composition_ths('651')
    assert out is not None
    assert out['source'] == 'ths'
    assert out['report_date'] is None
    assert out['business_scope'].startswith('制冷设备')
    assert '空调、生活电器' in out['business_review']
    assert '主要产品：家用空调、冰箱' in out['business_review']
    # 关键：同花顺无定量占比，mainop 必须为空，绝不编造
    assert out['mainop'] == []
    fake_ak.stock_zyjs_ths.assert_called_once_with(symbol='000651')


def test_ths_composition_empty_returns_none():
    fake_ak = mock.MagicMock()
    fake_ak.stock_zyjs_ths.return_value = _FakeThsDF([])
    with mock.patch.dict('sys.modules', {'akshare': fake_ak}):
        assert sbt.stock_business_composition_ths('000651') is None


def test_ths_composition_failure_raises():
    """akshare 抛错（网络/反爬）应转成 BusinessFetchError，供上层熔断。"""
    fake_ak = mock.MagicMock()
    fake_ak.stock_zyjs_ths.side_effect = RuntimeError('ths blocked')
    with mock.patch.dict('sys.modules', {'akshare': fake_ak}):
        with pytest.raises(sbe.BusinessFetchError):
            sbt.stock_business_composition_ths('000651')


def test_save_em_source_success(monkeypatch):
    """source='em' 且 EM 返回数据 → 落库，返回 (1, True)。"""
    monkeypatch.setattr(fcp.sbe, 'stock_business_composition',
                        mock.Mock(return_value={
                            'report_date': '2025-12-31', 'business_scope': '制冷设备',
                            'business_review': '经营评述', 'mainop': [{'type': '行业', 'item': '空调'}]}))
    monkeypatch.setattr(fcp.mdb, 'checkTableIsExist', lambda *a, **k: True)
    captured = {}
    monkeypatch.setattr(fcp.mdb, 'insert_db_from_df',
                        lambda df, *a, **k: captured.__setitem__('df', df))

    rows, src_ok = fcp.save_company_profile('000651', '2026-07-08', source='em')
    assert (rows, src_ok) == (1, True)
    assert captured['df'].iloc[0]['mainop'] is not None


def test_save_em_source_transport_fail(monkeypatch):
    """source='em' 且 EM 传输失败 → 返回 (0, False)，不落库。"""
    monkeypatch.setattr(fcp.sbe, 'stock_business_composition',
                        mock.Mock(side_effect=sbe.BusinessFetchError('EM banned')))
    called = {'n': 0}
    monkeypatch.setattr(fcp.mdb, 'insert_db_from_df',
                        lambda *a, **k: called.__setitem__('n', called['n'] + 1))
    assert fcp.save_company_profile('000651', '2026-07-08', source='em') == (0, False)
    assert called['n'] == 0


def test_save_em_source_no_data(monkeypatch):
    """source='em' 且 EM 返回 None（源可达但无数据）→ 返回 (0, True)。"""
    monkeypatch.setattr(fcp.sbe, 'stock_business_composition', mock.Mock(return_value=None))
    assert fcp.save_company_profile('000651', '2026-07-08', source='em') == (0, True)


def test_save_ths_source_new_stock(monkeypatch):
    """source='ths' 且库中无既有记录 → 写入同花顺定性数据，返回 (1, True)；mainop 恒空。"""
    monkeypatch.setattr(fcp.sbt, 'stock_business_composition_ths',
                        mock.Mock(return_value={
                            'report_date': None, 'business_scope': '制冷设备制造',
                            'business_review': '空调业务', 'mainop': [], 'source': 'ths'}))
    monkeypatch.setattr(fcp.mdb, 'checkTableIsExist', lambda *a, **k: True)
    monkeypatch.setattr(fcp.mdb, 'executeSqlFetch', lambda *a, **k: [])  # 无既有记录
    captured = {}
    monkeypatch.setattr(fcp.mdb, 'insert_db_from_df',
                        lambda df, *a, **k: captured.__setitem__('df', df))

    rows, src_ok = fcp.save_company_profile('999998', '2026-07-08', source='ths')
    assert (rows, src_ok) == (1, True)
    row = captured['df'].iloc[0]
    assert row['business_scope'] == '制冷设备制造'
    import pandas as _pd
    assert row['mainop'] is None or _pd.isna(row['mainop'])


def test_save_ths_source_preserves_existing(monkeypatch):
    """source='ths' 但库中已有完整东财定量记录（含 mainop）→ 不覆盖，返回 (0, True)。"""
    monkeypatch.setattr(fcp.sbt, 'stock_business_composition_ths',
                        mock.Mock(return_value={
                            'report_date': None, 'business_scope': '制冷设备制造',
                            'business_review': '空调业务', 'mainop': [], 'source': 'ths'}))
    monkeypatch.setattr(fcp.mdb, 'checkTableIsExist', lambda *a, **k: True)
    monkeypatch.setattr(fcp.mdb, 'executeSqlFetch',
                        lambda *a, **k: [('2025-12-31', '[{"type":"行业"}]')])
    insert_called = {'n': 0}
    monkeypatch.setattr(fcp.mdb, 'insert_db_from_df',
                        lambda *a, **k: insert_called.__setitem__('n', insert_called['n'] + 1))

    rows, src_ok = fcp.save_company_profile('000651', '2026-07-08', source='ths')
    assert (rows, src_ok) == (0, True)      # 未覆盖、源可达
    assert insert_called['n'] == 0          # 绝不写库覆盖


def test_save_ths_source_transport_fail(monkeypatch):
    """source='ths' 且同花顺传输失败 → 返回 (0, False)，供 run() 熔断计数。"""
    monkeypatch.setattr(fcp.sbt, 'stock_business_composition_ths',
                        mock.Mock(side_effect=sbe.BusinessFetchError('THS blocked')))
    assert fcp.save_company_profile('000651', '2026-07-08', source='ths') == (0, False)


def test_save_ths_source_no_data(monkeypatch):
    """source='ths' 且同花顺无数据（None）→ 返回 (0, True)。"""
    monkeypatch.setattr(fcp.sbt, 'stock_business_composition_ths', mock.Mock(return_value=None))
    assert fcp.save_company_profile('000651', '2026-07-08', source='ths') == (0, True)


# ---------------------------------------------------------------------------
# AI 工具 stock_profile._query_company_profile
# ---------------------------------------------------------------------------
def test_stock_profile_query_company_profile_parses_mainop(monkeypatch):
    import quantia.lib.ai.tools.stock_profile as spt
    import json as _json
    mainop = [{'type': '产品', 'item': '消费电器', 'income': 1.3e11,
               'income_ratio': 0.78, 'gross_profit_ratio': 0.35,
               'rank': 1, 'report_date': '2025-12-31'}]
    rows = [('2025-12-31', '制冷设备制造；家电销售', _json.dumps(mainop))]
    monkeypatch.setattr('quantia.lib.database.executeSqlFetch',
                        lambda *a, **k: rows)
    out = spt._query_company_profile('000651')
    assert out['report_date'] == '2025-12-31'
    assert out['business_scope'].startswith('制冷设备')
    assert len(out['mainop']) == 1
    item = out['mainop'][0]
    assert item['维度'] == '产品'
    assert item['项目'] == '消费电器'
    assert abs(item['收入占比'] - 0.78) < 1e-9
    assert item['报告期'] == '2025-12-31'


def test_stock_profile_query_company_profile_table_missing(monkeypatch):
    """表未部署 / SQL 异常 → 返回 {}，安全跳过。"""
    import quantia.lib.ai.tools.stock_profile as spt
    monkeypatch.setattr('quantia.lib.database.executeSqlFetch',
                        mock.Mock(side_effect=Exception('no such table')))
    assert spt._query_company_profile('000651') == {}


def test_stock_profile_query_company_profile_no_row(monkeypatch):
    import quantia.lib.ai.tools.stock_profile as spt
    monkeypatch.setattr('quantia.lib.database.executeSqlFetch',
                        lambda *a, **k: [])
    assert spt._query_company_profile('000651') == {}

