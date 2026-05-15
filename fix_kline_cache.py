#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线缓存数据清理脚本

修复已知的缓存污染问题：
- 日线缓存中混入了月度聚合数据行（特征：月末日期、价格偏离、成交量异常大）
- 受影响股票: 15只以上（详见 KNOWN_AFFECTED）
- 检测使用三重算法与 stockfetch.py 中的 _filter_ohlc_outliers() 保持一致

使用方法:
    python fix_kline_cache.py           # 扫描并修复所有缓存
    python fix_kline_cache.py --scan    # 仅扫描，不修复
    python fix_kline_cache.py --delete  # 删除受影响的缓存文件（下次获取时重建）
"""
import os
import sys
import glob
import argparse
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 缓存目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, 'quantia', 'cache', 'hist')

# 已知受影响的股票（扫描发现15只，272行污染）
KNOWN_AFFECTED = [
    '600660', '002557', '600276', '002049', '601601',
    '002024', '600809', '000002', '002371', '000858',
    '002916', '300760', '600309', '600438', '600519',
]


def filter_ohlc_outliers(data, code=''):
    """
    过滤OHLC异常行。直接复用 stockfetch.py 中的向量化实现。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from quantia.core.stockfetch import _filter_ohlc_outliers
        return _filter_ohlc_outliers(data, code)
    except ImportError:
        logger.warning("无法导入 stockfetch._filter_ohlc_outliers，使用内置简化版")
        # 简化版回退：仅检测 close<=0（邻居正常时）和极端偏离
        if data is None or data.empty or len(data) < 10:
            return data, 0
        close = pd.to_numeric(data['close'], errors='coerce')
        if close.isna().all():
            return data, 0
        c_m2 = close.shift(2)
        c_m1 = close.shift(1)
        c_p1 = close.shift(-1)
        c_p2 = close.shift(-2)
        nb = pd.DataFrame({'a': c_m2, 'b': c_m1, 'c': c_p1, 'd': c_p2})
        nb_med = nb.median(axis=1, skipna=True)
        nb_cnt = nb.notna().sum(axis=1)
        has_nb = nb_cnt >= 2
        safe_med = nb_med.where(nb_med > 0, np.nan)
        pr = close / safe_med
        invalid = (close <= 0) & has_nb & (nb_med > 0)
        extreme = has_nb & ((pr < 0.4) | (pr > 2.5))
        mask = (invalid | extreme).fillna(False)
        n_out = int(mask.sum())
        if n_out > 0 and n_out < len(data) * 0.15:
            data = data.loc[~mask].reset_index(drop=True)
            return data, n_out
        return data, 0


def scan_cache_files(cache_dir):
    """扫描所有缓存文件，返回受影响的文件列表"""
    affected = []
    total = 0

    if not os.path.exists(cache_dir):
        logger.error(f"缓存目录不存在: {cache_dir}")
        return affected

    pattern = os.path.join(cache_dir, '**', '*qfq.gzip.pickle')
    files = glob.glob(pattern, recursive=True)
    logger.info(f"找到 {len(files)} 个缓存文件")

    for filepath in sorted(files):
        filename = os.path.basename(filepath)
        code = filename.replace('qfq.gzip.pickle', '')
        total += 1

        try:
            data = pd.read_pickle(filepath, compression='gzip')
            if data is None or data.empty or len(data) < 10:
                continue

            _, outlier_count = filter_ohlc_outliers(data.copy(), code)
            if outlier_count > 0:
                affected.append({
                    'code': code,
                    'path': filepath,
                    'rows': len(data),
                    'outliers': outlier_count,
                })
        except Exception as e:
            logger.warning(f"  读取缓存失败 [{code}]: {e}")

    logger.info(f"\n扫描完成: 共 {total} 个文件，{len(affected)} 个受影响")
    return affected


def fix_cache_files(affected_list):
    """修复受影响的缓存文件（删除异常行后重新保存）"""
    fixed = 0
    for item in affected_list:
        code = item['code']
        filepath = item['path']
        logger.info(f"修复 [{code}] ...")

        try:
            data = pd.read_pickle(filepath, compression='gzip')
            cleaned, removed = filter_ohlc_outliers(data, code)

            if removed > 0:
                # 备份原文件
                backup_path = filepath + '.bak'
                if not os.path.exists(backup_path):
                    os.rename(filepath, backup_path)
                    logger.info(f"  已备份到 {backup_path}")
                else:
                    os.remove(filepath)

                # 保存清理后的数据
                cleaned.to_pickle(filepath, compression='gzip')
                logger.info(f"  已修复: {len(data)} -> {len(cleaned)} 行 (删除 {removed} 行)")
                fixed += 1
            else:
                logger.info(f"  无需修复")
        except Exception as e:
            logger.error(f"  修复失败 [{code}]: {e}")

    logger.info(f"\n修复完成: {fixed}/{len(affected_list)} 个文件已修复")
    return fixed


def delete_cache_files(codes, cache_dir):
    """删除指定股票的缓存文件（下次数据获取时会自动重建）"""
    deleted = 0
    for code in codes:
        cache_path = os.path.join(cache_dir, code[:3], f"{code}qfq.gzip.pickle")
        meta_path = os.path.join(cache_dir, code[:3], f"{code}qfq.meta")

        for path in [cache_path, meta_path]:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"  已删除: {path}")
                deleted += 1
            else:
                logger.info(f"  文件不存在: {path}")

    logger.info(f"\n删除完成: {deleted} 个文件")
    return deleted


def main():
    parser = argparse.ArgumentParser(description='K线缓存数据清理脚本')
    parser.add_argument('--scan', action='store_true', help='仅扫描，不修复')
    parser.add_argument('--delete', action='store_true', help='删除受影响的缓存文件')
    parser.add_argument('--cache-dir', default=CACHE_DIR, help=f'缓存目录 (默认: {CACHE_DIR})')
    parser.add_argument('--codes', nargs='*', help='指定股票代码 (默认: 扫描全部)')
    args = parser.parse_args()

    cache_dir = args.cache_dir
    logger.info(f"缓存目录: {cache_dir}")

    if args.delete:
        codes = args.codes or KNOWN_AFFECTED
        logger.info(f"删除模式: 将删除 {codes} 的缓存文件")
        delete_cache_files(codes, cache_dir)
        return

    # 扫描
    logger.info("开始扫描缓存文件...")
    affected = scan_cache_files(cache_dir)

    if not affected:
        logger.info("未发现异常数据，所有缓存正常。")
        return

    for item in affected:
        logger.info(f"  {item['code']}: {item['outliers']} 行异常 / {item['rows']} 行总计")

    if args.scan:
        logger.info("扫描模式，不执行修复。使用不带 --scan 参数运行以执行修复。")
        return

    # 修复
    logger.info("\n开始修复...")
    fix_cache_files(affected)


if __name__ == '__main__':
    main()
