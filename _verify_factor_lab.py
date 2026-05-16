"""Quick verification script for Factor Lab API."""
import json, urllib.request

# Test 1: Factor catalog
req1 = urllib.request.Request('http://localhost:9988/quantia/api/factor_lab/factors')
resp1 = json.loads(urllib.request.urlopen(req1).read())
cats = resp1['categories']
print(f"[OK] Factor catalog: {len(cats)} categories")
for c in cats:
    print(f"     {c['name']}: {len(c['factors'])} factors")

# Test 2: Presets
req2 = urllib.request.Request('http://localhost:9988/quantia/api/factor_lab/presets')
resp2 = json.loads(urllib.request.urlopen(req2).read())
print(f"\n[OK] Presets: {len(resp2['presets'])} templates")
for p in resp2['presets']:
    print(f"     {p['name']} ({len(p['factors'])} factors, {p['fusion_mode']})")

# Test 3: Run backtest - 2 strategy signals
body3 = json.dumps({
    'factors': [
        {'id': 'keep_increasing', 'weight': 50, 'enabled': True},
        {'id': 'breakout_confirm', 'weight': 50, 'enabled': True},
    ],
    'fusion_mode': 'score',
    'holding_days': 10,
    'start_date': '2026-02-24',
    'end_date': '2026-04-27',
}).encode()
req3 = urllib.request.Request(
    'http://localhost:9988/quantia/api/factor_lab/run',
    data=body3, headers={'Content-Type': 'application/json'})
resp3 = json.loads(urllib.request.urlopen(req3).read())
k = resp3['kpi']
b = resp3['baseline']
print(f"\n[OK] Run (2 signals, score mode):")
print(f"     sharpe={k['sharpe']}  win_rate={k['win_rate']}%  avg_return={k['avg_return']}%")
print(f"     signals={k['signal_count']}  daily_avg={k['daily_signal_avg']}")
print(f"     max_drawdown={k['max_drawdown']}%  calmar={k['calmar']}")
print(f"     baseline_sharpe={b['sharpe']}  baseline_signals={b['signal_count']}")
print(f"     daily_series: {len(resp3['daily_series'])} points")
print(f"     contributions: {len(resp3['factor_contributions'])} factors")
for c in resp3['factor_contributions']:
    print(f"       {c['name']}: impact={c['impact']}")
print(f"     sparse_warning={resp3['signal_sparse_warning']}")

# Test 4: Run with indicator filter
body4 = json.dumps({
    'factors': [
        {'id': 'keep_increasing', 'weight': 60, 'enabled': True},
        {'id': 'rsi_6', 'weight': 40, 'enabled': True, 'operator': '<', 'value': 70},
    ],
    'fusion_mode': 'and',
    'holding_days': 10,
    'start_date': '2026-02-24',
    'end_date': '2026-04-27',
}).encode()
req4 = urllib.request.Request(
    'http://localhost:9988/quantia/api/factor_lab/run',
    data=body4, headers={'Content-Type': 'application/json'})
resp4 = json.loads(urllib.request.urlopen(req4).read())
k4 = resp4['kpi']
b4 = resp4['baseline']
print(f"\n[OK] Run (signal + RSI<70 filter):")
print(f"     sharpe={k4['sharpe']}  win_rate={k4['win_rate']}%  signals={k4['signal_count']}")
print(f"     baseline_signals={b4['signal_count']}  filter_rate={k4['filter_rate']}%")

print("\n=== All API tests passed! ===")
