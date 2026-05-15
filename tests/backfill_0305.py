#!/usr/bin/env python3
"""Deploy and run March 5 backfill on server. Usage: python backfill_0305.py [check]"""
import paramiko
import time
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else 'start'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('115.29.213.22', username='root', password='Dzm@ming&662', timeout=15)

if MODE == 'check':
    cmds = [
        'free -m',
        'ps aux --sort=-%mem | head -8',
        'tail -30 /tmp/bf0305.log 2>/dev/null',
        'tail -10 /root/Quantia/quantia/log/stock_streaming_job.log 2>/dev/null',
    ]
    for c in cmds:
        _, o, e = ssh.exec_command(c, timeout=10)
        print(f"--- {c} ---")
        print(o.read().decode().strip())
    ssh.close()
    sys.exit(0)

# Write a shell script to server, then launch it with nohup
script = r"""#!/bin/bash
cd /root/Quantia/quantia/job
export QUANTIA_ANALYSIS_WORKERS=1
export QUANTIA_BATCH_SIZE=30
export QUANTIA_BACKTEST_OUTER_WORKERS=1
export QUANTIA_BACKTEST_INNER_WORKERS=1

echo "=== Starting March 5 backfill at $(date) ===" >> /tmp/bf0305.log

python3 streaming_analysis_job.py 2026-03-05 >> /tmp/bf0305.log 2>&1
echo "streaming_analysis done at $(date)" >> /tmp/bf0305.log

python3 backtest_data_daily_job.py 2026-03-05 >> /tmp/bf0305.log 2>&1
echo "backtest done at $(date)" >> /tmp/bf0305.log

echo "=== March 5 backfill completed at $(date) ===" >> /tmp/bf0305.log
"""

# Write script
write_cmd = f"cat > /tmp/bf0305.sh << 'ENDSCRIPT'\n{script}\nENDSCRIPT\nchmod +x /tmp/bf0305.sh && echo WRITTEN"
_, o, e = ssh.exec_command(write_cmd, timeout=10)
print("Write:", o.read().decode().strip())

# Launch with nohup
_, o, e = ssh.exec_command("nohup bash /tmp/bf0305.sh > /dev/null 2>&1 & echo PID=$!", timeout=10)
print("Launch:", o.read().decode().strip())

time.sleep(3)

# Quick process check
_, o, e = ssh.exec_command("ps aux | grep bf0305 | grep -v grep; echo '---'; cat /tmp/bf0305.log 2>/dev/null | tail -10", timeout=10)
print("Status:\n" + o.read().decode().strip())

ssh.close()
