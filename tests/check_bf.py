#!/usr/bin/env python3
"""Quick check backfill status"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('115.29.213.22', username='root', password='Dzm@ming&662', timeout=15)

cmds = [
    ('Memory', 'free -m | head -2'),
    ('Processes', 'ps aux --sort=-%mem | head -8'),
    ('bf0305.log', 'tail -5 /tmp/bf0305.log'),
    ('Recent logs', 'find /root/Quantia/quantia/log/ -name "*.log" -mmin -5 -ls'),
    ('streaming log', 'tail -15 /root/Quantia/quantia/log/stock_streaming_job.log 2>/dev/null'),
    ('streaming2 log', 'tail -15 /root/Quantia/quantia/log/stock_streaming.log 2>/dev/null'),
    ('backfill log', 'tail -15 /root/Quantia/quantia/log/stock_backfill_0305.log 2>/dev/null'),
]

for label, cmd in cmds:
    _, o, e = ssh.exec_command(cmd, timeout=10)
    out = o.read().decode().strip()
    if out:
        print(f"--- {label} ---")
        print(out)

ssh.close()
