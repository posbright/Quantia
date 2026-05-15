#!/usr/bin/env python3
"""测试板块资金流向数据源可用性"""
import requests
import time
import json

s = requests.Session()
s.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Referer': 'https://data.eastmoney.com/bkzj/hy.html',
    'Accept': 'application/json, text/plain, */*',
})

# 测试1: datacenter-web API（行业）
print("=== 测试 datacenter-web.eastmoney.com API ===")
url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
params = {
    'sortColumns': 'MAIN_NET_INFLOW',
    'sortTypes': '-1',
    'pageSize': '500',
    'pageNumber': '1',
    'reportName': 'RPT_INDUSTRY_BOARD_MONEY_FLOW',
    'columns': 'ALL',
    'source': 'WEB',
    'client': 'WEB',
}
try:
    r = s.get(url, params=params, timeout=15)
    d = r.json()
    result = d.get('result')
    if result and result.get('data'):
        data = result['data']
        print(f"行业: 成功! count={result.get('count')}, got={len(data)} 条")
        # 打印第一条的字段名
        print(f"字段: {list(data[0].keys())[:15]}")
        print(f"示例: {data[0].get('INDUSTRY_BOARD', '?')} 主力净流入={data[0].get('MAIN_NET_INFLOW', '?')}")
    else:
        print(f"行业: 无数据 msg={d.get('message', '')}")
except Exception as e:
    print(f"行业: 失败 {e}")

time.sleep(1)

# 测试2: datacenter-web API（概念）
params2 = dict(params)
params2['reportName'] = 'RPT_CONCEPT_BOARD_MONEY_FLOW'
try:
    r = s.get(url, params=params2, timeout=15)
    d = r.json()
    result = d.get('result')
    if result and result.get('data'):
        data = result['data']
        print(f"概念: 成功! count={result.get('count')}, got={len(data)} 条")
        print(f"示例: {data[0].get('CONCEPT_BOARD', '?')} 主力净流入={data[0].get('MAIN_NET_INFLOW', '?')}")
    else:
        print(f"概念: 无数据 msg={d.get('message', '')}")
except Exception as e:
    print(f"概念: 失败 {e}")

time.sleep(2)

# 测试3: push2 HTTPS（原始API，小page_size）
print("\n=== 测试 push2.eastmoney.com HTTPS ===")
url3 = 'https://push2.eastmoney.com/api/qt/clist/get'
params3 = {
    'pn': 1, 'pz': 50, 'po': '1', 'np': '1',
    'ut': 'b2884a393a59ad64002292a3e90d46a5',
    'fltt': '2', 'invt': '2',
    'fid0': 'f62',
    'fs': 'm:90 t:2',
    'stat': '1',
    'fields': 'f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124',
}
try:
    r = s.get(url3, params=params3, timeout=15)
    d = r.json()
    total = d.get('data', {}).get('total', 0)
    diff = d.get('data', {}).get('diff', [])
    print(f"push2 HTTPS(行业): 成功! total={total}, got={len(diff)} 条")
except Exception as e:
    print(f"push2 HTTPS(行业): 失败 {e}")

time.sleep(1)

# 测试4: push2 HTTPS（概念）
params4 = dict(params3)
params4['fs'] = 'm:90 t:3'
try:
    r = s.get(url3, params=params4, timeout=15)
    d = r.json()
    total = d.get('data', {}).get('total', 0)
    diff = d.get('data', {}).get('diff', [])
    print(f"push2 HTTPS(概念): 成功! total={total}, got={len(diff)} 条")
except Exception as e:
    print(f"push2 HTTPS(概念): 失败 {e}")

# 测试5: 个股资金流（东方财富HTTPS）
print("\n=== 测试 个股资金流 HTTPS ===")
time.sleep(2)
url5 = 'https://push2.eastmoney.com/api/qt/clist/get'
params5 = {
    'fid': 'f62', 'po': '1', 'pz': 50, 'pn': 1,
    'np': '1', 'fltt': '2', 'invt': '2',
    'ut': 'b2884a393a59ad64002292a3e90d46a5',
    'fs': 'm:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2',
    'fields': 'f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124',
}
try:
    r = s.get(url5, params=params5, timeout=15)
    d = r.json()
    total = d.get('data', {}).get('total', 0)
    diff = d.get('data', {}).get('diff', [])
    print(f"个股资金流: 成功! total={total}, got={len(diff)} 条")
except Exception as e:
    print(f"个股资金流: 失败 {e}")

# 测试6: stock_zh_a_spot_em（实时行情HTTPS）
print("\n=== 测试 实时行情 HTTPS ===")
time.sleep(2)
url6 = 'https://push2.eastmoney.com/api/qt/clist/get'
params6 = {
    'pn': 1, 'pz': 50, 'po': '1', 'np': '1',
    'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
    'fltt': '2', 'invt': '2', 'fid': 'f12',
    'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
    'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f14',
}
try:
    r = s.get(url6, params=params6, timeout=15)
    d = r.json()
    total = d.get('data', {}).get('total', 0)
    diff = d.get('data', {}).get('diff', [])
    print(f"实时行情: 成功! total={total}, got={len(diff)} 条")
except Exception as e:
    print(f"实时行情: 失败 {e}")
