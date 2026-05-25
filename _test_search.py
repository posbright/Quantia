"""Quick search validation."""
import quantia.lib.database as mdb

# Test basic search
rows = mdb.executeSqlFetch(
    "SELECT code, name FROM cn_stock_spot WHERE code LIKE %s LIMIT 3",
    ('%0001%',)
)
print("Search by code '0001':", rows)

# Test with special characters (LIKE escape)
escaped_q = '100%'.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
pattern = f'%{escaped_q}%'
rows2 = mdb.executeSqlFetch(
    "SELECT code, name FROM cn_stock_spot WHERE (code LIKE %s OR name LIKE %s) LIMIT 3",
    (pattern, pattern)
)
print(f"Search by '100%' (escaped): {rows2}")

# Test fund_flow query (from stock_profile)
from quantia.lib.ai.tools.stock_profile import _query_fund_flow
flow = _query_fund_flow('000001', 5)
print(f"Fund flow 000001 (5d): {len(flow)} records")
if flow:
    print(f"  Keys: {list(flow[0].keys())}")

# Test indicators
from quantia.lib.ai.tools.stock_profile import _query_indicators
ind = _query_indicators('000001')
print(f"Indicators 000001: {ind}")

# Test patterns
from quantia.lib.ai.tools.stock_profile import _query_patterns
pat = _query_patterns('000001')
print(f"Patterns 000001: {pat}")
