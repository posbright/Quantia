#!/usr/bin/env python3
"""Check server data status for March 5+"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('115.29.213.22', username='root', password='Dzm@ming&662', timeout=15)

sql = (
    "SELECT 'spot' as t, date, count(*) as c FROM cn_stock_spot WHERE date >= '2025-03-05' GROUP BY date ORDER BY date;"
    " SELECT 'indicators' as t, date, count(*) as c FROM cn_stock_indicators WHERE date >= '2025-03-05' GROUP BY date ORDER BY date;"
    " SELECT 'kline' as t, date, count(*) as c FROM cn_stock_kline_pattern WHERE date >= '2025-03-05' GROUP BY date ORDER BY date;"
    " SELECT 'strategy' as t, date, count(*) as c FROM cn_stock_strategy_enter WHERE date >= '2025-03-05' GROUP BY date ORDER BY date;"
)

cmd = f"date; echo '---'; mysql -u root -p'Dzm@ming&662' quantiadb -e \"{sql}\" 2>&1"
_, o, e = ssh.exec_command(cmd, timeout=30)
print(o.read().decode())
ssh.close()
