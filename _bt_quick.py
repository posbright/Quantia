import sys, os
sys.path.insert(0, '.')
print('1. importing...')
from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine
print('2. reading code...')
with open('quantia/core/strategy/templates/fundamental_bottom_breakout.py', 'r', encoding='utf-8') as f:
    code = f.read()
print(f'3. code length: {len(code)}')
print('4. creating engine...')
engine = PortfolioBacktestEngine()
print('5. running backtest (2025-01 to 2026-03, ~15 months)...')
result = engine.run(
    strategy_code=code,
    start_date='2025-01-01',
    end_date='2026-03-31',
    initial_cash=1000000,
    benchmark='000300',
)
status = result.get('status')
print(f'6. result status: {status}')
if status == 'error':
    err = result.get('error', '')
    tb = result.get('traceback', '')
    print(f'   error: {err[:800]}')
    if tb:
        print(f'   traceback: {tb[:1000]}')
else:
    m = result.get('metrics', {})
    print(f'   total_return: {m.get("total_return",0)*100:.2f}%')
    print(f'   annual_return: {m.get("annual_return",0)*100:.2f}%')
    print(f'   max_drawdown: {m.get("max_drawdown",0)*100:.2f}%')
    print(f'   sharpe: {m.get("sharpe_ratio",0):.3f}')
    print(f'   win_rate: {m.get("win_rate",0)*100:.1f}%')
    print(f'   trade_count: {m.get("trade_count",0)}')
    trades = result.get('trades', [])
    print(f'   trades list len: {len(trades)}')
    logs = result.get('logs', [])
    print(f'   log messages: {len(logs)}')
    if logs:
        for msg in logs[-15:]:
            print(f'     {msg}')
    if trades:
        print('   Last 5 trades:')
        for t in trades[-5:]:
            d = t.get('direction', 'buy' if t.get('amount',0)>0 else 'sell')
            print(f'     {t.get("date","")} {d} {t.get("code","")} px={t.get("price",0):.2f} amt={t.get("amount",0)}')
print('DONE')
