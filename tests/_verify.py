#!/usr/bin/env python3
"""Validate strategy create + list flow"""
import urllib.request, json, sys

BASE = 'http://localhost:9988/quantia/api'

def get(path):
    return json.loads(urllib.request.urlopen(f'{BASE}{path}').read())

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f'{BASE}{path}', data=data, headers={'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req).read())

PASS = FAIL = 0
def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f'  PASS: {name}')
    else:
        FAIL += 1; print(f'  FAIL: {name} {detail}')

# 1. Create stock strategy (no prompt, auto-name)
print('=== 1. Create stock strategy ===')
r1 = post('/strategy/code', {
    'name': '一个简单的策略-99',
    'code': 'def initialize(c):\n    c.security="000001"\ndef handle_data(c,d):\n    pass',
    'category': 'stock'
})
check('create ok', r1['code'] == 0)
new_id = r1.get('data', {}).get('id', 0)
check('has id', new_id > 0, f'id={new_id}')

# 2. List shows new strategy with all fields
print('\n=== 2. List strategies ===')
r2 = get('/strategy/code/list')
check('list ok', r2['code'] == 0)
data = r2['data']
check('has strategies key', 'strategies' in data)
check('has folders key', 'folders' in data)
strategies = data['strategies']
check('strategies not empty', len(strategies) > 0)
# Find our new strategy
found = [s for s in strategies if s.get('id') == new_id]
check('new strategy in list', len(found) == 1)
if found:
    s = found[0]
    check('has name', s['name'] == '一个简单的策略-99')
    check('has category', s['category'] == 'stock')
    check('has updated_at', bool(s.get('updated_at')))
    check('has compile_count', 'compile_count' in s)
    check('has backtest_count', 'backtest_count' in s)
    check('has folder_id', 'folder_id' in s)
    check('type is strategy', s['type'] == 'strategy')

# 3. Create folder
print('\n=== 3. Create folder ===')
r3 = post('/strategy/folder/create', {'name': '测试文件夹'})
check('folder created', r3['code'] == 0)
folder_id = r3.get('data', {}).get('id', 0)
check('has folder id', folder_id > 0)

# 4. Move strategy to folder
print('\n=== 4. Move to folder ===')
r4 = post('/strategy/move', {'ids': [new_id], 'folder_id': folder_id})
check('move ok', r4['code'] == 0)

# 5. Rename strategy
print('\n=== 5. Rename strategy ===')
r5 = post('/strategy/rename', {'id': new_id, 'name': '重命名后的策略'})
check('rename ok', r5['code'] == 0)

# 6. Verify list shows updated info
print('\n=== 6. Verify updates ===')
r6 = get('/strategy/code/list')
strategies2 = r6['data']['strategies']
folders2 = r6['data']['folders']
found2 = [s for s in strategies2 if s.get('id') == new_id]
check('strategy still in list', len(found2) == 1)
if found2:
    check('name updated', found2[0]['name'] == '重命名后的策略')
    check('folder_id updated', found2[0]['folder_id'] == folder_id)
check('folder in list', any(f['id'] == folder_id for f in folders2))

# 7. Create another and batch delete
print('\n=== 7. Batch delete ===')
r7 = post('/strategy/code', {
    'name': '待删除策略',
    'code': 'def initialize(c): pass\ndef handle_data(c,d): pass',
    'category': 'blank'
})
del_id = r7.get('data', {}).get('id', 0)
r7d = post('/strategy/batch_delete', {'ids': [del_id]})
check('batch delete ok', r7d['code'] == 0)
# Verify deleted
r7v = get('/strategy/code/list')
check('deleted not in list', not any(s['id'] == del_id for s in r7v['data']['strategies']))

# 8. Strategy templates
print('\n=== 8. Templates ===')
r8 = get('/strategy/templates')
check('templates ok', r8['code'] == 0)
check('4 templates', len(r8['data']) == 4)

# 9. Run backtest
print('\n=== 9. Run backtest ===')
r9 = post('/backtest/portfolio/run', {
    'code': 'def initialize(c):\n    c.security="000001"\ndef handle_data(c,d):\n    if "000001" not in c.portfolio.positions:\n        order_value("000001", c.portfolio.available_cash*0.9)',
    'start_date': '2024-03-01',
    'end_date': '2024-12-01',
    'initial_cash': 100000
})
check('backtest ok', r9['code'] == 0)
bt = r9['data']
check('status completed', bt['status'] == 'completed')
check('has metrics', 'total_return' in bt.get('metrics', {}))
check('has nav', len(bt.get('nav', [])) > 0)
check('has trades', len(bt.get('trades', [])) > 0)
m = bt['metrics']
print(f'  Return: {m["total_return"]:.2f}%, Sharpe: {m["sharpe_ratio"]:.2f}, MaxDD: {m["max_drawdown"]:.2f}%')

# Cleanup
post('/strategy/batch_delete', {'ids': [new_id]})
post('/strategy/folder/delete', {'id': folder_id})

print(f'\n{"="*40}')
print(f'Results: {PASS} passed, {FAIL} failed')
if FAIL > 0:
    sys.exit(1)
