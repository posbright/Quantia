#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2024/5/10 00:00
Desc: 新浪财经-龙虎榜
https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/lhb/index.phtml
"""

from io import StringIO
import logging
import pandas as pd
import requests
from bs4 import BeautifulSoup
import sys
from tqdm import tqdm

# tqdm 在 stderr 不可用时（Windows 服务/后台进程）会抛 OSError，禁用进度条
_tqdm_disabled = not hasattr(sys.stderr, 'fileno')
try:
    if not _tqdm_disabled:
        sys.stderr.fileno()
except (OSError, AttributeError):
    _tqdm_disabled = True
from quantia.core.singleton_proxy import proxys


def _sina_request(url, params=None, timeout=30):
    """新浪财经通用请求（带代理反馈、超时、错误处理）"""
    proxy_pool = proxys()
    current_proxy = proxy_pool.get_proxies()
    proxy_url = current_proxy.get("http") if current_proxy else None
    try:
        r = requests.get(url, proxies=current_proxy, params=params, timeout=timeout)
        proxy_pool.report_success(proxy_url)
        return r
    except Exception as e:
        proxy_pool.report_failure(proxy_url)
        logging.debug(f"新浪龙虎榜请求失败: {url} - {e}")
        raise


def stock_lhb_detail_daily_sina(date: str = "20240222") -> pd.DataFrame:
    """
    龙虎榜-每日详情
    https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/lhb/index.phtml
    :param date: 交易日
    :type date: str
    :return: 龙虎榜-每日详情
    :rtype: pandas.DataFrame
    """
    date = "-".join([date[:4], date[4:6], date[6:]])
    url = "https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/lhb/index.phtml"
    params = {"tradedate": date}
    try:
        r = _sina_request(url, params=params)
    except Exception:
        return pd.DataFrame()
    soup = BeautifulSoup(r.text, features="lxml")
    list_div = soup.find(name="div", attrs={"class": "list"})
    if list_div is None:
        return pd.DataFrame()
    selected_html = list_div.find_all(name="table", attrs={"class": "list_table"})
    if not selected_html:
        return pd.DataFrame()
    big_df = pd.DataFrame()
    for table in selected_html:
        temp_df = pd.read_html(StringIO(table.prettify()), header=0, skiprows=1)[0]
        temp_symbol = pd.read_html(StringIO(table.prettify()))[0].iat[0, 0]
        temp_df["指标"] = temp_symbol
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    if big_df.empty or "股票代码" not in big_df.columns:
        return pd.DataFrame()
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    if "查看详情" in big_df.columns:
        del big_df["查看详情"]
    big_df.columns = [
        "序号",
        "股票代码",
        "股票名称",
        "收盘价",
        "对应值",
        "成交量",
        "成交额",
        "指标",
    ]
    big_df["收盘价"] = pd.to_numeric(big_df["收盘价"], errors="coerce")
    big_df["对应值"] = pd.to_numeric(big_df["对应值"], errors="coerce")
    big_df["成交量"] = pd.to_numeric(big_df["成交量"], errors="coerce")
    big_df["成交额"] = pd.to_numeric(big_df["成交额"], errors="coerce")
    return big_df


def _find_last_page(
    url: str = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml",
    recent_day: str = "60",
):
    params = {
        "last": recent_day,
        "p": "1",
    }
    try:
        r = _sina_request(url, params=params)
    except Exception:
        return 1
    soup = BeautifulSoup(r.text, "lxml")
    try:
        previous_page = int(soup.find_all(attrs={"class": "page"})[-2].text)
    except (IndexError, ValueError):
        previous_page = 1
    if previous_page != 1:
        while True:
            params = {
                "last": recent_day,
                "p": previous_page,
            }
            try:
                r = _sina_request(url, params=params)
            except Exception:
                break
            soup = BeautifulSoup(r.text, features="lxml")
            last_page = int(soup.find_all(attrs={"class": "page"})[-2].text)
            if last_page != previous_page:
                previous_page = last_page
                continue
            else:
                break
    return previous_page


def stock_lhb_ggtj_sina(symbol: str = "5") -> pd.DataFrame:
    """
    龙虎榜-个股上榜统计
    https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml
    :param symbol: choice of {"5": 最近 5 天; "10": 最近 10 天; "30": 最近 30 天; "60": 最近 60 天;}
    :type symbol: str
    :return: 龙虎榜-个股上榜统计
    :rtype: pandas.DataFrame
    """
    url = (
        "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml"
    )
    last_page_num = _find_last_page(url, symbol)
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False, disable=_tqdm_disabled):
        params = {
            "last": symbol,
            "p": page,
        }
        try:
            r = _sina_request(url, params=params)
        except Exception:
            continue
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    if big_df.empty:
        return big_df
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    big_df.columns = [
        "股票代码",
        "股票名称",
        "上榜次数",
        "累积购买额",
        "累积卖出额",
        "净额",
        "买入席位数",
        "卖出席位数",
    ]
    return big_df


def stock_lhb_yytj_sina(symbol: str = "5") -> pd.DataFrame:
    """
    龙虎榜-营业部上榜统计
    https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/yytj/index.phtml
    :param symbol: choice of {"5": 最近 5 天; "10": 最近 10 天; "30": 最近 30 天; "60": 最近 60 天;}
    :type symbol: str
    :return: 龙虎榜-营业部上榜统计
    :rtype: pandas.DataFrame
    """
    url = (
        "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/yytj/index.phtml"
    )
    last_page_num = _find_last_page(url, symbol)
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False, disable=_tqdm_disabled):
        params = {
            "last": "5",
            "p": page,
        }
        try:
            r = _sina_request(url, params=params)
        except Exception:
            continue
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        big_df = pd.concat([big_df, temp_df], ignore_index=True)
    if big_df.empty:
        return big_df
    big_df.columns = [
        "营业部名称",
        "上榜次数",
        "累积购买额",
        "买入席位数",
        "累积卖出额",
        "卖出席位数",
        "买入前三股票",
    ]
    big_df["上榜次数"] = pd.to_numeric(big_df["上榜次数"], errors="coerce")
    big_df["买入席位数"] = pd.to_numeric(big_df["买入席位数"], errors="coerce")
    big_df["卖出席位数"] = pd.to_numeric(big_df["卖出席位数"], errors="coerce")
    return big_df


def stock_lhb_jgzz_sina(symbol: str = "5") -> pd.DataFrame:
    """
    龙虎榜-机构席位追踪
    https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/jgzz/index.phtml
    :param symbol: choice of {"5": 最近 5 天; "10": 最近 10 天; "30": 最近 30 天; "60": 最近 60 天;}
    :type symbol: str
    :return: 龙虎榜-机构席位追踪
    :rtype: pandas.DataFrame
    """
    url = (
        "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/jgzz/index.phtml"
    )
    last_page_num = _find_last_page(url, symbol)
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False, disable=_tqdm_disabled):
        params = {
            "last": symbol,
            "p": page,
        }
        try:
            r = _sina_request(url, params=params)
        except Exception:
            continue
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        if temp_df.empty:
            continue
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    if big_df.empty:
        return big_df
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    del big_df["当前价"]
    del big_df["涨跌幅"]
    big_df.columns = [
        "股票代码",
        "股票名称",
        "累积买入额",
        "买入次数",
        "累积卖出额",
        "卖出次数",
        "净额",
    ]
    big_df["买入次数"] = pd.to_numeric(big_df["买入次数"], errors="coerce")
    big_df["卖出次数"] = pd.to_numeric(big_df["卖出次数"], errors="coerce")
    return big_df


def stock_lhb_jgmx_sina() -> pd.DataFrame:
    """
    龙虎榜-机构席位成交明细
    https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/jgmx/index.phtml
    :return: 龙虎榜-机构席位成交明细
    :rtype: pandas.DataFrame
    """
    url = (
        "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/jgmx/index.phtml"
    )
    params = {
        "p": "1",
    }
    try:
        r = _sina_request(url, params=params)
    except Exception:
        return pd.DataFrame()
    soup = BeautifulSoup(r.text, features="lxml")
    try:
        last_page_num = int(soup.find_all(attrs={"class": "page"})[-2].text)
    except (IndexError, ValueError):
        last_page_num = 1
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False, disable=_tqdm_disabled):
        params = {
            "p": page,
        }
        try:
            r = _sina_request(url, params=params)
        except Exception:
            continue
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    big_df["交易日期"] = pd.to_datetime(big_df["交易日期"], errors="coerce").dt.date
    big_df.rename(
        columns={
            "机构席位买入额(万)": "机构席位买入额",
            "机构席位卖出额(万)": "机构席位卖出额",
        },
        inplace=True,
    )
    big_df["机构席位买入额"] = pd.to_numeric(big_df["机构席位买入额"], errors="coerce")
    big_df["机构席位卖出额"] = pd.to_numeric(big_df["机构席位卖出额"], errors="coerce")
    return big_df


if __name__ == "__main__":
    stock_lhb_detail_daily_sina_df = stock_lhb_detail_daily_sina(date="20240222")
    print(stock_lhb_detail_daily_sina_df)

    stock_lhb_ggtj_sina_df = stock_lhb_ggtj_sina(symbol="5")
    print(stock_lhb_ggtj_sina_df)

    stock_lhb_yytj_sina_df = stock_lhb_yytj_sina(symbol="5")
    print(stock_lhb_yytj_sina_df)

    stock_lhb_jgzz_sina_df = stock_lhb_jgzz_sina(symbol="5")
    print(stock_lhb_jgzz_sina_df)

    stock_lhb_jgmx_sina_df = stock_lhb_jgmx_sina()
    print(stock_lhb_jgmx_sina_df)
