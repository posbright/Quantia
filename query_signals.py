from quantia.lib.database import engine_to_db
from sqlalchemy import text
eng = engine_to_db('quantia')
tbls = ['cn_stock_strategy_enter','cn_stock_strategy_keep_increasing','cn_stock_strategy_low_backtrace_increase','cn_stock_strategy_climax_limitup','cn_stock_strategy_breakthrough_platform']
with eng.connect() as c:
    for t in tbls:
        try:
            r = c.execute(text(f'SELECT COUNT(*) as n, MIN(date) as mn, MAX(date) as mx FROM {t}')).fetchone()
            print(f'{t}: count={r[0]}, min={r[1]}, max={r[2]}')
        except Exception as e:
            print(f'{t}: ERR {e}')
