# -*- coding:utf-8 -*-
# !/usr/bin/env python

import logging
import math
import random
import time
import pandas as pd
import quantia.core.tablestructure as tbs
from quantia.core.eastmoney_fetcher import eastmoney_fetcher

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 创建全局实例，供所有函数使用
fetcher = eastmoney_fetcher()

def stock_selection() -> pd.DataFrame:
    """
    东方财富网-个股-选股器
    https://data.eastmoney.com/xuangu/
    :return: 选股器
    :rtype: pandas.DataFrame

    API 支持的最大 page_size 约为 2000~3000；
    使用 500 每页 → ≈10 页即可获取全部 A 股，
    比原来 50 每页 × 92 页减少 90% 请求量，大幅降低因代理不稳定导致的整体失败概率。
    每页独立 try/except + 重试，部分失败仍返回已获取的数据。
    """
    cols = tbs.TABLE_CN_STOCK_SELECTION['columns']
    page_size = 500
    sty = ""  # 初始值 "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE"
    for k in cols:
        if 'map' in cols[k]:
            sty = f"{sty},{cols[k]['map']}"
    url = "https://data.eastmoney.com/dataapi/xuangu/list"
    params = {
        "sty": sty[1:],
        "filter": "(MARKET+in+(\"上交所主板\",\"深交所主板\",\"深交所创业板\"))(NEW_PRICE>0)",
        "p": 1,
        "ps": page_size,
        "source": "SELECT_SECURITIES",
        "client": "WEB"
    }

    # 首页请求加重试保护（首页失败则整个函数失败）
    data = None
    data_count = 0
    for first_attempt in range(3):
        try:
            r = fetcher.make_request(url, params=params)
            data_json = r.json()
            data = data_json["result"]["data"]
            data_count = data_json["result"]["count"]
            break
        except Exception as e:
            logging.warning(f"选股器首页获取失败(第{first_attempt+1}次): {e}")
            if first_attempt < 2:
                time.sleep(random.uniform(2, 5))

    if not data:
        return pd.DataFrame()
    total_pages = math.ceil(data_count / page_size)
    failed_pages = []

    for page in range(2, total_pages + 1):
        # 随机延迟，降低被限流的风险
        time.sleep(random.uniform(0.5, 1.5))
        params["p"] = page
        page_ok = False
        for attempt in range(3):  # 每页最多重试 3 次
            try:
                r = fetcher.make_request(url, params=params)
                page_json = r.json()
                page_data = page_json["result"]["data"]
                if page_data:
                    data.extend(page_data)
                page_ok = True
                break
            except Exception as e:
                logging.warning(f"选股器第 {page}/{total_pages} 页获取失败(第{attempt+1}次): {e}")
                if attempt < 2:
                    time.sleep(random.uniform(2, 4))
        if not page_ok:
            failed_pages.append(page)

    if failed_pages:
        logging.warning(f"选股器有 {len(failed_pages)} 页获取失败: {failed_pages}，"
                        f"已获取 {len(data)}/{data_count} 条数据")

    temp_df = pd.DataFrame(data)

    mask = ~temp_df['CONCEPT'].isna()
    temp_df.loc[mask, 'CONCEPT'] = temp_df.loc[mask, 'CONCEPT'].apply(lambda x: ', '.join(x))
    mask = ~temp_df['STYLE'].isna()
    temp_df.loc[mask, 'STYLE'] = temp_df.loc[mask, 'STYLE'].apply(lambda x: ', '.join(x))

    for k in cols:
        if 'map' not in cols[k]:
            continue
        map_name = cols[k]["map"]
        if map_name not in temp_df.columns:
            continue
        t = tbs.get_field_type_name(cols[k]["type"])
        if t == 'numeric':
            temp_df[map_name] = pd.to_numeric(temp_df[map_name], errors="coerce")
        elif t == 'datetime':
            temp_df[map_name] = pd.to_datetime(temp_df[map_name], errors="coerce").dt.date

    return temp_df


def stock_industry_supplement() -> pd.DataFrame:
    """东方财富选股器-科创板/北交所行业补全（主选股器 stock_selection 的 MARKET 过滤
    只含「上交所主板/深交所主板/深交所创业板」，故 688 科创板与北交所 8xx/4xx 全库无行业）。

    本函数用同一 xuangu 接口、只取 (代码,名称,行业) 三列，过滤到科创板+北交所，作为
    「补充映射」供基金持仓行业回填等场景填补空缺——**不写 cn_stock_selection、不改动
    全库选股口径**，仅按需读取补齐 688/北交所行业。taxonomy 与主选股器同源（东财行业）。

    抓取失败（代理不稳/限流）时返回已获取的部分或空 DataFrame，调用方须容忍降级。
    :return: DataFrame[code, name, industry]
    """
    sty = "SECURITY_CODE,SECURITY_NAME_ABBR,INDUSTRY"
    page_size = 500
    url = "https://data.eastmoney.com/dataapi/xuangu/list"
    params = {
        "sty": sty,
        "filter": "(MARKET+in+(\"上交所科创板\",\"北京证券交易所\"))(NEW_PRICE>0)",
        "p": 1,
        "ps": page_size,
        "source": "SELECT_SECURITIES",
        "client": "WEB",
    }
    data = None
    data_count = 0
    for first_attempt in range(3):
        try:
            r = fetcher.make_request(url, params=params)
            data_json = r.json()
            data = data_json["result"]["data"]
            data_count = data_json["result"]["count"]
            break
        except Exception as e:
            logging.warning(f"科创板/北交所行业补全首页获取失败(第{first_attempt+1}次): {e}")
            if first_attempt < 2:
                time.sleep(random.uniform(2, 5))
    if not data:
        return pd.DataFrame(columns=['code', 'name', 'industry'])
    total_pages = math.ceil(data_count / page_size)
    for page in range(2, total_pages + 1):
        time.sleep(random.uniform(0.5, 1.5))
        params["p"] = page
        for attempt in range(3):
            try:
                r = fetcher.make_request(url, params=params)
                page_data = r.json()["result"]["data"]
                if page_data:
                    data.extend(page_data)
                break
            except Exception as e:
                logging.warning(f"科创板/北交所行业补全第 {page}/{total_pages} 页失败(第{attempt+1}次): {e}")
                if attempt < 2:
                    time.sleep(random.uniform(2, 4))
    temp_df = pd.DataFrame(data)
    if temp_df.empty:
        return pd.DataFrame(columns=['code', 'name', 'industry'])
    out = pd.DataFrame({
        'code': temp_df.get('SECURITY_CODE'),
        'name': temp_df.get('SECURITY_NAME_ABBR'),
        'industry': temp_df.get('INDUSTRY'),
    })
    out = out[out['code'].notna()]
    return out.reset_index(drop=True)


def stock_selection_params():
    """
    东方财富网-个股-选股器-选股指标
    https://data.eastmoney.com/xuangu/
    :return: 选股器-选股指标
    :rtype: pandas.DataFrame
    """
    params = {
        "type": "RPTA_PCNEW_WHOLE",
        "sty": "ALL",
        "p": 1,
        "ps": 1000,
        "source": "SELECT_SECURITIES",
        "client": "WEB"
    }

    r = fetcher.make_request(url, params=params)
    data_json = r.json()
    zxzb = data_json["result"]["data"]  # 指标
    print(zxzb)


if __name__ == "__main__":
    stock_selection_df = stock_selection()
    print(stock_selection)
    # stock_selection_params()
