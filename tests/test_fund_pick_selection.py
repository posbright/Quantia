#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P5 每日精选榜纯函数单元测试：AC 去重 + Top-N→去重→Top10 顺序。"""

import unittest

from quantia.core.fund import pick_selection as ps


class TestNormalizeFundName(unittest.TestCase):
    def test_strip_ac_suffix(self):
        self.assertEqual(ps.normalize_fund_name('华夏核心价值混合A'), '华夏核心价值混合')
        self.assertEqual(ps.normalize_fund_name('华夏核心价值混合C'), '华夏核心价值混合')

    def test_class_word_suffix(self):
        self.assertEqual(ps.normalize_fund_name('易方达蓝筹A类'), '易方达蓝筹')

    def test_paren_suffix(self):
        self.assertEqual(ps.normalize_fund_name('南方原油(A)'), '南方原油')

    def test_no_suffix_unchanged(self):
        self.assertEqual(ps.normalize_fund_name('易方达蓝筹精选混合'), '易方达蓝筹精选混合')

    def test_qdii_keeps_bracket(self):
        # 先剥尾部 A，QDII 括号保留
        self.assertEqual(ps.normalize_fund_name('南方原油(QDII)A'), '南方原油(QDII)')

    def test_empty(self):
        self.assertEqual(ps.normalize_fund_name(''), '')
        self.assertEqual(ps.normalize_fund_name(None), '')

    def test_all_stripped_fallback(self):
        # 单字母名被剥光 → 回退原名，避免空键归并
        self.assertEqual(ps.normalize_fund_name('A'), 'A')


class TestDedupAc(unittest.TestCase):
    def test_ac_pair_keeps_a(self):
        cands = [
            {'code': '000002', 'name': '华夏成长C', 'quality_score': 80},
            {'code': '000001', 'name': '华夏成长A', 'quality_score': 80},
        ]
        out = ps.dedup_ac(cands)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['name'], '华夏成长A')

    def test_keeps_larger_scale(self):
        cands = [
            {'code': '000001', 'name': '华夏成长A', 'quality_score': 80, 'scale': 1.0},
            {'code': '000002', 'name': '华夏成长C', 'quality_score': 80, 'scale': 9.0},
        ]
        out = ps.dedup_ac(cands)
        self.assertEqual(len(out), 1)
        # 规模优先于 A 类偏好
        self.assertEqual(out[0]['code'], '000002')

    def test_distinct_names_kept(self):
        cands = [
            {'code': '000001', 'name': '华夏成长A', 'quality_score': 80},
            {'code': '000003', 'name': '易方达蓝筹A', 'quality_score': 70},
        ]
        out = ps.dedup_ac(cands)
        self.assertEqual(len(out), 2)

    def test_empty_names_not_merged(self):
        cands = [
            {'code': '000001', 'name': '', 'quality_score': 80},
            {'code': '000002', 'name': None, 'quality_score': 70},
        ]
        out = ps.dedup_ac(cands)
        self.assertEqual(len(out), 2)

    def test_preserves_input_order(self):
        cands = [
            {'code': '000001', 'name': '甲基金A', 'quality_score': 90},
            {'code': '000002', 'name': '乙基金C', 'quality_score': 80},
            {'code': '000003', 'name': '甲基金C', 'quality_score': 90},
        ]
        out = ps.dedup_ac(cands)
        self.assertEqual([o['code'] for o in out], ['000001', '000002'])


class TestSelectBucketTop(unittest.TestCase):
    def _mk(self, n, base_q=100):
        return [{'code': f'{i:06d}', 'name': f'基金{i}混合A',
                 'quality_score': base_q - i} for i in range(n)]

    def test_top10_by_quality(self):
        out = ps.select_bucket_top(self._mk(30), top_k=10)
        self.assertEqual(len(out), 10)
        self.assertEqual([o['rank_in_type'] for o in out], list(range(1, 11)))
        # 质量降序
        qs = [o['quality_score'] for o in out]
        self.assertEqual(qs, sorted(qs, reverse=True))

    def test_topn_then_dedup_then_top10_order(self):
        # 构造：AC 双份额分布在 Top-N 边界，验证先取 N 再去重再截 10
        cands = []
        for i in range(20):
            cands.append({'code': f'A{i:05d}', 'name': f'基金{i}混合A',
                          'quality_score': 100 - i})
            cands.append({'code': f'C{i:05d}', 'name': f'基金{i}混合C',
                          'quality_score': 100 - i})
        out = ps.select_bucket_top(cands, top_k=10, pre_n=25)
        # 去重后每个底层只留 A，应正好 10 只不同底层
        names = [ps.normalize_fund_name(o['name']) for o in out]
        self.assertEqual(len(set(names)), 10)
        self.assertTrue(all(o['name'].endswith('A') for o in out))

    def test_fewer_than_topk(self):
        out = ps.select_bucket_top(self._mk(4), top_k=10)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[-1]['rank_in_type'], 4)

    def test_none_quality_sorts_last(self):
        cands = [
            {'code': '000001', 'name': '甲混合A', 'quality_score': None},
            {'code': '000002', 'name': '乙混合A', 'quality_score': 50},
        ]
        out = ps.select_bucket_top(cands, top_k=10)
        self.assertEqual(out[0]['code'], '000002')
        self.assertEqual(out[1]['code'], '000001')

    def test_reorder_after_dedup_keeps_quality_desc(self):
        # 同组保留 A 类但 C 类质量更高先出现 → 保留者按自身质量重排，名次不被位移
        cands = [
            {'code': '000001', 'name': '甲混合A', 'quality_score': 99},
            {'code': '000002', 'name': '乙混合C', 'quality_score': 95},   # 乙组先见（高质）
            {'code': '000003', 'name': '丙混合A', 'quality_score': 94},
            {'code': '000004', 'name': '乙混合A', 'quality_score': 90},   # 保留 A 类（低质）
        ]
        out = ps.select_bucket_top(cands, top_k=10)
        qs = [o['quality_score'] for o in out]
        self.assertEqual(qs, sorted(qs, reverse=True))
        codes = [o['code'] for o in out]
        self.assertEqual(codes, ['000001', '000003', '000004'])

    def test_dedup_backfills_to_ten(self):
        # 关键：先截 10 再去重会不足 10；正确顺序应回填到 10
        cands = []
        # 前 10 个里混入 5 对 AC（会被去重掉 5 只）
        for i in range(5):
            cands.append({'code': f'A{i}', 'name': f'热门{i}混合A', 'quality_score': 100 - i})
            cands.append({'code': f'C{i}', 'name': f'热门{i}混合C', 'quality_score': 100 - i - 0.5})
        # 再补 10 个独立基金
        for i in range(10):
            cands.append({'code': f'X{i}', 'name': f'独立{i}混合A', 'quality_score': 80 - i})
        out = ps.select_bucket_top(cands, top_k=10, pre_n=25)
        self.assertEqual(len(out), 10)
        names = [ps.normalize_fund_name(o['name']) for o in out]
        self.assertEqual(len(set(names)), 10)


if __name__ == '__main__':
    unittest.main()
