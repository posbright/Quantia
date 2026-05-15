#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


def get_pattern_recognitions(data, stock_column, end_date=None, threshold=120, calc_threshold=None):
    isCopy = False
    if end_date is not None:
        # 统一 date 类型：缓存数据的 date 列可能是 datetime64/Timestamp/datetime.date，
        # 而 end_date 来自 strftime 或 code_name[0]（字符串），
        # 混合类型无法直接比较，需统一为 pd.Timestamp。
        if not pd.api.types.is_datetime64_any_dtype(data['date']):
            data = data.copy()
            data['date'] = pd.to_datetime(data['date'])
            isCopy = True
        if not isinstance(end_date, pd.Timestamp):
            end_date = pd.Timestamp(end_date)
        mask = (data['date'] <= end_date)
        data = data.loc[mask]
        isCopy = True
    if calc_threshold is not None:
        data = data.tail(n=calc_threshold)
        isCopy = True
    if isCopy:
        data = data.copy()

    for k in stock_column:
        try:
            data.loc[:, k] = stock_column[k]['func'](data['open'].values, data['high'].values, data['low'].values, data['close'].values)
        except Exception as e:
            logging.debug(f"K线形态 {k} 计算跳过: {e}")

    if data is None or len(data.index) == 0:
        return None

    if threshold is not None:
        data = data.tail(n=threshold).copy()

    return data


def get_pattern_recognition(code_name, data, stock_column, date=None, calc_threshold=12):
    try:
        # 增加空判断，如果是空返回 0 数据。
        if date is None:
            end_date = code_name[0]
        else:
            end_date = date.strftime("%Y-%m-%d")

        code = code_name[1]
        # 设置返回数组。
        # 增加空判断，如果是空返回 0 数据。
        if len(data.index) <= 1:
            return None

        stockStat = get_pattern_recognitions(data, stock_column, end_date=end_date, threshold=1,
                                             calc_threshold=calc_threshold)

        if stockStat is None:
            return None

        isHas = False
        for k in stock_column:
            if stockStat.iloc[0][k] != 0:
                isHas = True
                break

        if isHas:
            stockStat.loc[:, 'code'] = code
            return stockStat.iloc[0, -(len(stock_column) + 1):]

    except Exception as e:
        logging.error(f"pattern_recognitions.get_pattern_recognition处理异常：{code}代码", exc_info=True)

    return None
