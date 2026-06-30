# MySQL 主从复制部署与备份运维手册（Quantia）

> 适用对象：Quantia 量化选股系统的生产 MySQL（库名 `instockdb`）。
> 目标：在 **主库 `115.29.213.22`** 与 **从库 `36.137.20.40`** 之间建立实时主从复制（Replication），
> 实现热备份、读扩展与灾备切换（DR Failover）。
>
> 本手册同时说明 **Quantia 项目本身需不需要改配置、改哪些**（见 [§7](#7-quantia-项目配置需要改吗改哪些)）。

---

## 0. 角色与拓扑

| 角色 | IP | server-id | 职责 | 运行的 Quantia 组件 |
| --- | --- | --- | --- | --- |
| **主库 Master / Source** | `115.29.213.22` | `1` | 唯一可写库，承接 web 写入 + cron 抓取/分析作业 | web_service + cron 全量作业（fetch/analysis） |
| **从库 Slave / Replica** | `36.137.20.40` | `2` | 实时复制主库、只读热备，灾备时可提升为主 | **仅备机**：web 可只读运行，**cron 写入作业必须停用** |

```
     写 + 读                          异步复制 (binlog → relay log)
 ┌──────────────┐   3306/tcp   ┌──────────────────────────────────┐
 │  Quantia App │ ───────────► │  Master MySQL  115.29.213.22     │
 │ (web + cron) │              │  server-id=1  log-bin=ON  RW     │
 └──────────────┘              └──────────────┬───────────────────┘
                                              │  binlog 实时推送
                                              ▼
                               ┌──────────────────────────────────┐
   只读/灾备                    │  Slave MySQL   36.137.20.40      │
 ┌──────────────┐   只读        │  server-id=2  read_only=ON       │
 │ Quantia(备机)│ ◄─────────── │  super_read_only=ON  relay-log   │
 └──────────────┘              └──────────────────────────────────┘
```

> **重要前提（与代码事实一致）**：Quantia 已内置**可选**的应用层读写分离（默认**关闭**）。关闭时
> `quantia/lib/database.py` 只用单一 `QUANTIA_DB_HOST` 建一个连接池（`engine()`），应用统一连向主库，
> 从库价值是「热备 + 灾备切换 + 离线只读分析」。**开启后**（`QUANTIA_RW_SPLIT=1` + `QUANTIA_DB_READ_HOST`）
> 仅 **Web 层读**经 `engine_ro()` 分流到从库，写入与抓取/分析作业仍走主库，详见 [§7.3](#73-让从库分担读流量已内置实现默认关闭)。

---

## 1. 前置准备（两台都做）

### 1.1 确认版本（命令在不同大版本里有差异）

```bash
mysql --version
mysql -uroot -p -e "SELECT VERSION();"
```

- **MySQL 8.0.22+**：推荐用新术语 `CHANGE REPLICATION SOURCE TO` / `START REPLICA` / `SHOW REPLICA STATUS`。
- **MySQL 5.7 / 8.0.21-**：用旧术语 `CHANGE MASTER TO` / `START SLAVE` / `SHOW SLAVE STATUS`。

> 本手册**两套命令都给**。请按你的版本选用对应一套；功能完全等价。

### 1.2 网络与防火墙

主库必须放行从库来源 IP 访问 3306：

```bash
# 阿里云/腾讯云：在「安全组」放行 源IP=36.137.20.40 → 端口 3306/tcp
# 主机本地防火墙（firewalld 示例，主库 115.29.213.22 上执行）：
sudo firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=36.137.20.40/32 port port=3306 protocol=tcp accept"
sudo firewall-cmd --reload

# 从库侧验证能连通主库
mysql -h115.29.213.22 -P3306 -urepl -p -e "SELECT 1;"
```

> 安全建议：复制账号 `repl` 只授权给从库 IP（`repl@'36.137.20.40'`），不要用 `%`。
> 主库 `bind-address` 若为 `127.0.0.1` 需改为 `0.0.0.0` 或内网/公网 IP，否则从库连不上。

### 1.3 时间同步（强烈建议）

```bash
sudo timedatectl set-ntp true   # 或部署 chrony / ntpd
timedatectl                     # 确认两台时区/时间一致
```

---

## 2. 配置主库（`115.29.213.22`）

### 2.1 修改 my.cnf

编辑 `/etc/my.cnf` 或 `/etc/mysql/mysql.conf.d/mysqld.cnf` 的 `[mysqld]` 段：

```ini
[mysqld]
# === 复制基础 ===
server-id                = 1
log-bin                  = /var/lib/mysql/mysql-bin     # 开启二进制日志（主库必须）
binlog_format            = ROW                          # ROW 最安全（避免非确定性语句不一致）
binlog_row_image         = FULL

# === 只复制业务库（按需）===
binlog-do-db             = instockdb                    # 只记录 instockdb 的变更
# 注意：用了 binlog-do-db 后，跨库语句可能不被复制；如不确定就删掉这行复制全部库

# === GTID（推荐，便于灾备切换/换主）===
gtid_mode                = ON
enforce_gtid_consistency = ON

# === binlog 保留与可靠性 ===
expire_logs_days         = 7                            # MySQL 8.0.3+ 用 binlog_expire_logs_seconds=604800
sync_binlog              = 1                            # 每次提交刷盘，最安全（性能换可靠）
innodb_flush_log_at_trx_commit = 1

# === 字符集（与 Quantia 一致）===
character-set-server     = utf8mb4
collation-server         = utf8mb4_general_ci

# 1.6GB 内存小机注意：不要把 binlog 与 sync_binlog 设得过激进影响写入吞吐，
# 已知主库 OOM 敏感，开 binlog 后观察内存与磁盘（binlog 会额外占盘）。
```

> MySQL 8.0.3+ 把 `expire_logs_days` 改为 `binlog_expire_logs_seconds`：
> `binlog_expire_logs_seconds = 604800`（7 天）。两者别同时写。

重启主库使配置生效：

```bash
sudo systemctl restart mysqld     # 或 mysql / mariadb，按发行版
mysql -uroot -p -e "SHOW VARIABLES LIKE 'server_id'; SHOW VARIABLES LIKE 'log_bin';"
# log_bin 应为 ON
```

### 2.2 创建复制专用账号（主库上执行）

```sql
-- 仅授权从库 IP，最小权限
CREATE USER 'repl'@'36.137.20.40' IDENTIFIED BY '强随机密码_请替换';
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'36.137.20.40';

-- MySQL 8.0 默认 caching_sha2_password，如从库握手报认证插件问题可改用：
-- ALTER USER 'repl'@'36.137.20.40' IDENTIFIED WITH mysql_native_password BY '强随机密码_请替换';

FLUSH PRIVILEGES;
SELECT user, host FROM mysql.user WHERE user='repl';
```

> 复制账号密码与 Quantia 的 `QUANTIA_DB_PASSWORD` **无关**，是独立的 MySQL 账号，不要混用业务账号。

---

## 3. 全量初始化从库（导出主库 → 导入从库）

复制只同步「建立复制点之后」的增量，必须先把存量数据搬到从库，且导出与复制点要**一致**。
`mysqldump` 的 `--master-data` / `--source-data` 会在备份里写入精确复制坐标。

### 3.1 在主库导出（推荐 GTID + 单事务一致性快照）

```bash
# MySQL 8.0（--source-data=2 把 CHANGE SOURCE 坐标写成注释）
mysqldump -uroot -p \
  --single-transaction \
  --quick \
  --source-data=2 \
  --set-gtid-purged=ON \
  --routines --triggers --events \
  --default-character-set=utf8mb4 \
  --databases instockdb \
  | gzip > /tmp/instockdb_full_$(date +%Y%m%d_%H%M%S).sql.gz

# MySQL 5.7 等价写法：把 --source-data=2 换成 --master-data=2
# mysqldump -uroot -p --single-transaction --quick --master-data=2 \
#   --routines --triggers --events --default-character-set=utf8mb4 \
#   --databases instockdb | gzip > /tmp/instockdb_full_$(date +%Y%m%d_%H%M%S).sql.gz
```

> `--single-transaction` 对 InnoDB 做一致性快照，**不锁表**，适合线上导出（Quantia 全为 InnoDB）。
> 若有 MyISAM 表才需要 `--lock-all-tables`（会锁库，谨慎）。

把备份传到从库：

```bash
scp /tmp/instockdb_full_*.sql.gz root@36.137.20.40:/tmp/
```

### 3.2 在从库导入

```bash
# 从库 36.137.20.40 上执行
gunzip -c /tmp/instockdb_full_YYYYMMDD_HHMMSS.sql.gz | mysql -uroot -p
# 若 dump 用了 --databases 则已含 CREATE DATABASE；否则先手动建库：
# mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS instockdb CHARACTER SET utf8mb4;"
```

> 记下 dump 文件头部注释里的复制坐标（position 法需要）：
> `grep -m1 -E "CHANGE (MASTER|REPLICATION SOURCE) TO" <(gunzip -c xxx.sql.gz)`

---

## 4. 配置从库（`36.137.20.40`）并启动复制

### 4.1 修改 my.cnf

```ini
[mysqld]
server-id                = 2
relay-log                = /var/lib/mysql/relay-bin
read_only                = ON          # 从库只读，防止误写破坏复制
super_read_only          = ON          # 连 SUPER 账号也禁止写（更安全）
log-bin                  = /var/lib/mysql/mysql-bin   # 可选：开启便于「级联复制」或将来提升为主
log_slave_updates        = ON          # 8.0 为 log_replica_updates；级联/换主时需要

# GTID（与主库一致）
gtid_mode                = ON
enforce_gtid_consistency = ON

character-set-server     = utf8mb4
collation-server         = utf8mb4_general_ci
```

重启从库：

```bash
sudo systemctl restart mysqld
mysql -uroot -p -e "SHOW VARIABLES LIKE 'read_only'; SHOW VARIABLES LIKE 'server_id';"
```

### 4.2 建立复制关系并启动

**方式 A：GTID（推荐，换主免找 position）**

```sql
-- MySQL 8.0.22+
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST     = '115.29.213.22',
  SOURCE_PORT     = 3306,
  SOURCE_USER     = 'repl',
  SOURCE_PASSWORD = '强随机密码_请替换',
  SOURCE_AUTO_POSITION = 1,
  GET_SOURCE_PUBLIC_KEY = 1;        -- 8.0 caching_sha2 首连取公钥；用 SSL 时可省
START REPLICA;

-- MySQL 5.7 / 8.0.21-
-- CHANGE MASTER TO
--   MASTER_HOST='115.29.213.22', MASTER_PORT=3306,
--   MASTER_USER='repl', MASTER_PASSWORD='强随机密码_请替换',
--   MASTER_AUTO_POSITION=1;
-- START SLAVE;
```

**方式 B：binlog 位点（dump 用 --source-data=2 时坐标在备份注释里）**

```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='115.29.213.22', SOURCE_PORT=3306,
  SOURCE_USER='repl', SOURCE_PASSWORD='强随机密码_请替换',
  SOURCE_LOG_FILE='mysql-bin.000123',   -- 取自 dump 注释
  SOURCE_LOG_POS=456789;                -- 取自 dump 注释
START REPLICA;
```

### 4.3 校验复制状态（关键）

```sql
SHOW REPLICA STATUS\G          -- 5.7 用 SHOW SLAVE STATUS\G
```

必须确认这几项：

| 字段 | 期望值 | 含义 |
| --- | --- | --- |
| `Replica_IO_Running` | `Yes` | IO 线程正常拉取主库 binlog |
| `Replica_SQL_Running` | `Yes` | SQL 线程正常回放 relay log |
| `Seconds_Behind_Source` | `0` 或很小 | 复制延迟（秒）|
| `Last_IO_Error` / `Last_SQL_Error` | 空 | 无错误 |
| `Retrieved_Gtid_Set` / `Executed_Gtid_Set` | 持续增长且接近一致 | GTID 推进正常 |

> 5.7 对应字段：`Slave_IO_Running` / `Slave_SQL_Running` / `Seconds_Behind_Master`。

### 4.4 端到端验证

```sql
-- 主库写一条
mysql -h115.29.213.22 -uroot -p -e \
 "CREATE TABLE IF NOT EXISTS instockdb._repl_check(id INT PRIMARY KEY, t DATETIME); \
  REPLACE INTO instockdb._repl_check VALUES (1, NOW());"

-- 从库几秒内应能查到同一行
mysql -h36.137.20.40 -uroot -p -e "SELECT * FROM instockdb._repl_check;"

-- 验证完清理（主库执行，会同步删除从库）
mysql -h115.29.213.22 -uroot -p -e "DROP TABLE instockdb._repl_check;"
```

---

## 5. 灾备切换（Failover：把从库提升为主库）

当主库 `115.29.213.22` 宕机，需把从库 `36.137.20.40` 提升为新主：

```sql
-- 1) 从库确认已追平（Executed_Gtid_Set 与主库最后一致；或等待 Seconds_Behind 归零）
SHOW REPLICA STATUS\G

-- 2) 停止并清除复制关系
STOP REPLICA;
RESET REPLICA ALL;          -- 5.7: STOP SLAVE; RESET SLAVE ALL;

-- 3) 解除只读，允许写入
SET GLOBAL super_read_only = OFF;
SET GLOBAL read_only       = OFF;
```

应用切换：把 Quantia 的 `QUANTIA_DB_HOST` 指向 `36.137.20.40`（见 §7），重启 web 与 cron。

> **原主库恢复后**要作为新从库重新挂回（反向复制），否则会出现「双主写入」数据分叉。
> 步骤同 §3+§4，只是主从角色对调（新主 = 36.137.20.40）。生产建议引入
> MHA / Orchestrator / MySQL Group Replication 做自动故障转移，手册此处为手动流程。

---

## 6. 日常运维与监控

### 6.1 复制健康巡检脚本

```bash
#!/bin/bash
# /root/check_replica.sh —— 放从库 36.137.20.40，cron 每 5 分钟
OUT=$(mysql -uroot -p"$MYSQL_ROOT_PW" -e "SHOW REPLICA STATUS\G" 2>/dev/null)
IO=$(echo "$OUT"  | awk -F: '/Replica_IO_Running/{gsub(/ /,"",$2);print $2}')
SQL=$(echo "$OUT" | awk -F: '/Replica_SQL_Running/{gsub(/ /,"",$2);print $2}')
LAG=$(echo "$OUT" | awk -F: '/Seconds_Behind_Source/{gsub(/ /,"",$2);print $2}')
if [ "$IO" != "Yes" ] || [ "$SQL" != "Yes" ]; then
  echo "[ALERT] 复制中断 IO=$IO SQL=$SQL" | logger -t repl_check
  # 这里可接 Quantia 的钉钉/IM 通知
fi
if [ -n "$LAG" ] && [ "$LAG" != "NULL" ] && [ "$LAG" -gt 300 ]; then
  echo "[WARN] 复制延迟 ${LAG}s" | logger -t repl_check
fi
```

```cron
*/5 * * * * MYSQL_ROOT_PW='xxx' /root/check_replica.sh
```

### 6.2 主库定期逻辑备份（从库上备份，零影响主库）

在从库执行 mysqldump 做每日冷备，既得到可恢复快照又不打扰主库：

```bash
# /root/backup_instockdb.sh —— 从库 36.137.20.40，cron 每天凌晨
set -e
DEST=/data/backup; mkdir -p "$DEST"
STAMP=$(date +%Y%m%d)
# 备份期间临时停 SQL 线程拿一致点（可选；--single-transaction 已足够 InnoDB）
mysqldump -uroot -p"$MYSQL_ROOT_PW" --single-transaction --quick \
  --routines --triggers --events --default-character-set=utf8mb4 \
  --databases instockdb | gzip > "$DEST/instockdb_$STAMP.sql.gz"
# 保留最近 14 天
find "$DEST" -name 'instockdb_*.sql.gz' -mtime +14 -delete
```

> 这条 `mysqldump` 写的是本地文件、**不是** `df.to_sql`，与 AGENTS.md 的 `chunksize=500` 规则无关。

### 6.3 binlog 磁盘管理（主库）

```sql
-- 查看 binlog 占用
SHOW BINARY LOGS;
-- 手动清理（确保从库已消费完该坐标后再清，否则复制断裂）
PURGE BINARY LOGS BEFORE NOW() - INTERVAL 7 DAY;
```

### 6.4 常见故障速查

| 现象 | 排查/处理 |
| --- | --- |
| `Replica_IO_Running: Connecting` | 防火墙/安全组未放行、`repl` 账号 host 不匹配、密码错、`bind-address` 未放开 |
| 8.0 认证报 `Authentication requires secure connection` | 复制账号改 `mysql_native_password`，或 `GET_SOURCE_PUBLIC_KEY=1`，或配 SSL |
| `Seconds_Behind_Source` 持续增大 | 从库单线程回放跟不上；开并行复制 `replica_parallel_workers=4` + `replica_parallel_type=LOGICAL_CLOCK` |
| `Last_SQL_Error: duplicate entry / table doesn't exist` | 数据漂移；GTID 下可 `SET GTID_NEXT` 跳过坏事务（谨慎），或重做全量初始化 |
| 从库被误写导致复制断 | 因没开 `super_read_only`；改回只读并重做初始化 |
| 主库换了 binlog 文件后位点法断裂 | 改用 GTID（`SOURCE_AUTO_POSITION=1`）从根本避免 |

---

## 7. Quantia 项目配置需要改吗？改哪些？

**结论：Quantia 应用代码无需改动**（除非要做读写分离，见 §7.3）。只改两台服务器的 **`.env`** 与 **作业开关**。

配置真相源：`quantia/lib/database.py` 读取 `QUANTIA_DB_HOST / QUANTIA_DB_PORT / QUANTIA_DB_USER / QUANTIA_DB_PASSWORD / QUANTIA_DB_DATABASE / QUANTIA_DB_CHARSET`（来自 `.env`），只建一个连接池。

### 7.1 主库服务器（`115.29.213.22`）——正常运行写库

`.env`（业务账号，**不是** repl 复制账号）：

```dotenv
QUANTIA_DB_HOST=127.0.0.1          # MySQL 与 web 同机时用本地回环最快；跨机则填 115.29.213.22
QUANTIA_DB_PORT=3306
QUANTIA_DB_USER=<业务账号>
QUANTIA_DB_PASSWORD=<业务密码>
QUANTIA_DB_DATABASE=instockdb
QUANTIA_DB_CHARSET=utf8mb4
```

- web_service 与全部 cron 抓取/分析作业**照常**跑在主库（写入端）。
- 改完重启 web（`/root/Quantia/quantia/bin/restart_web.sh`）。**注意**：`.env` 改动属环境变更，
  web 进程缓存连接信息，必须重启才生效。

### 7.2 从库服务器（`36.137.20.40`）——备机，关键是别往只读库写

从库 MySQL 是 `read_only=ON`。Quantia 的 **cron 抓取/分析作业会写库**，若指向从库会**全部报错**
（`The MySQL server is running with the --read-only option`），且即使能写也会破坏复制一致性。因此：

1. **必须停用从库服务器上的写入作业**（cron fetch/analysis 全关）：

   ```bash
   # 从库 36.137.20.40：注释掉所有写库的 cron（fetch_*/analysis/execute_daily_job 等）
   crontab -e
   # 或停用 cron 投放目录（按你的部署方式）：
   #   cron/cron.hourly  cron/cron.workdayly  cron/cron.monthly 内的抓取/分析脚本
   ```

2. **备机 web 若要常驻（用于灾备快速接管或只读查看）**，让它连本地从库、并接受只读：

   ```dotenv
   # 从库服务器 .env
   QUANTIA_DB_HOST=127.0.0.1     # = 本地从库 36.137.20.40
   QUANTIA_DB_PORT=3306
   QUANTIA_DB_USER=<只读或业务账号>
   QUANTIA_DB_PASSWORD=<密码>
   QUANTIA_DB_DATABASE=instockdb
   QUANTIA_DB_CHARSET=utf8mb4
   ```

   - 备机 web 上任何「触发抓取/写库」的操作都会因从库只读而失败 —— 这是**预期**行为，备机就该只读。
   - 建议给备机建一个**只读 MySQL 账号**（`GRANT SELECT ON instockdb.*`），从库 `.env` 用它，
     从账号层面再加一道防误写保险。

3. **灾备切换发生时**（§5 把从库提升为主）：

   - 把（原从库）`.env` 的 `QUANTIA_DB_HOST` 确认指向新主（本地），解除只读后；
   - 打开原先停用的 cron 作业（fetch/analysis），重启 web。
   - 同时把仍存活的旧主或其它机器上的应用 `QUANTIA_DB_HOST` 指到 `36.137.20.40`。

### 7.3 让从库分担读流量（已内置实现，默认关闭）

`database.py` 已内置**应用层读写分离**，默认关闭，开启后**仅 Web 层读**走从库、主库承接所有写
与作业的「写后立即读」，无需改业务代码。

**启用方式**（在跑 Web 的服务器 `.env` 配置后重启 web）：

```dotenv
QUANTIA_RW_SPLIT=1                 # 总开关；缺省/0 时一切走主库（零行为变化）
QUANTIA_DB_READ_HOST=36.137.20.40  # 从库地址；为空则即使开关打开也不分流
QUANTIA_DB_READ_PORT=3306          # 缺省同 QUANTIA_DB_PORT
QUANTIA_DB_READ_USER=ro_user       # 建议建只读账号 GRANT SELECT ON instockdb.*
QUANTIA_DB_READ_PASSWORD=xxx
QUANTIA_RW_SPLIT_COOLDOWN=30        # 从库故障熔断冷却秒数（期间只读走主库），缺省 30
# 主库写入仍用 QUANTIA_DB_HOST/USER/PASSWORD（保持指向主库 115.29.213.22）
```

**实现要点**（`quantia/lib/database.py`）：

- `RW_SPLIT_ENABLED = QUANTIA_RW_SPLIT 且 QUANTIA_DB_READ_HOST 非空`。两者缺一即全程主库。
- `engine_ro()`：只读引擎。未启用 / 在 `use_master()` 上下文内 → 返回主库 `engine()`（同一对象）；
  启用 → 返回指向从库的独立只读连接池单例。
- 写入（`engine()` / `insert_*` / `update_*` / `executeSql`）与共享只读助手
  （`executeSqlFetch` / `executeSqlCount` / `checkTableIsExist`）**始终走主库**——因为这些被
  抓取/分析作业复用，作业普遍「写后立即读」，走从库会撞复制延迟读到旧数据。
- **只有 Web handler 的 `pd.read_sql` 改用了 `read_sql_ro()`**（读的是早先落库的结算数据，秒级延迟
  可忽略）。jobs 的 `pd.read_sql` 仍用 `engine()`（主库），保证写后读一致。
- **故障自动降级（熔断）**：Web 只读统一入口 `read_sql_ro(sql, params=...)` 优先走从库；当从库抛
  **连接级异常**（`OperationalError` / `InterfaceError`，如 `[Errno 111] Connection refused`、从库
  重启/复制中断）时，**当次请求内自动改走主库**并打开熔断——`QUANTIA_RW_SPLIT_COOLDOWN` 秒（缺省
  30）内所有只读查询直接走主库、跳过已死的从库，冷却到期后自动重新探测从库。故核心页面（综合
  选股评分、基金分析、回测看板等）**不会因从库宕机而 500**。
  - 仅连接级异常降级；**查询级错误**（如 `ProgrammingError` 1054 未知列）**不**降级，照常抛出——
    那是真实 SQL/schema 问题，应当暴露而非被静默掩盖。
- **逃生口**：若某段 Web 代码确有「写后立即读」，包一层 `with mdb.use_master(): ...`，其内
  `engine_ro()` / `read_sql_ro()` 强制回主库。

> 复制延迟提醒：从库 `Seconds_Behind_Source` 升高时，Web 上可能短暂看到「数据比主库旧几秒」，
> 这是异步复制的固有特性；对强一致读用 `use_master()`。
>
> 排障提醒：开启读写分离前请先确认从库 `QUANTIA_DB_READ_HOST:PORT` 可达（`mysql -h<从库> -P<端口>`
> 能连上）。若从库不可达，页面虽因熔断降级仍可用，但每隔冷却周期会有一次失败重试日志
> （`从库只读连接失败…降级走主库`）——应尽快修复从库连通性，或临时 `QUANTIA_RW_SPLIT=0` 回退。

**替代方案（无代码、要额外组件）**：两台之间放 **ProxySQL / MaxScale** 做读写分离 + 故障转移，
应用连代理 VIP。本仓库已内置应用层方案，通常无需再引入代理。

### 7.4 配置改动清单速查

| 位置 | 改什么 | 是否重启 |
| --- | --- | --- |
| 主库 `my.cnf` | `server-id=1` + `log-bin` + `binlog_format=ROW` + GTID | 重启 mysqld |
| 主库 SQL | 建 `repl@'36.137.20.40'` 复制账号 | 否 |
| 从库 `my.cnf` | `server-id=2` + `read_only`/`super_read_only` + relay-log + GTID | 重启 mysqld |
| 从库 SQL | `CHANGE REPLICATION SOURCE TO ... ; START REPLICA;` | 否 |
| **主库服务器 `.env`** | 维持指向主库（127.0.0.1 / 115.29.213.22），cron 照常 | 重启 web |
| **从库服务器 `.env`** | 指向本地从库 + 用只读账号；**停用 cron 写入作业** | 重启 web |
| Quantia 应用代码 | **无需改**（除非做 §7.3 读写分离） | — |

---

## 8. 安全与合规要点

- 复制账号 `repl` 仅授权从库 IP，权限仅 `REPLICATION SLAVE`，密码用强随机串，**勿**复用业务账号/密码。
- 跨公网复制（两台不在同内网）务必启用 **SSL 复制**（`SOURCE_SSL=1` + CA 证书）或走 VPN/专线，
  否则 binlog（含全部数据变更）在公网明文传输有泄露风险。
- 云安全组按**最小源 IP**放行 3306，不要对 `0.0.0.0/0` 开放。
- 备份文件（`*.sql.gz`）含全量业务数据，存储与传输需加密、限权限、定期清理。
- `.env`（含 `QUANTIA_DB_PASSWORD`）与复制密码不入库、不进 git；仅本机维护。

---

## 9. 一页速查（Cheat Sheet）

```text
主库 115.29.213.22:  my.cnf{server-id=1, log-bin, binlog_format=ROW, gtid_mode=ON}
                     → 重启 → CREATE USER repl@'36.137.20.40' + GRANT REPLICATION SLAVE
                     → mysqldump --single-transaction --source-data=2 --set-gtid-purged=ON

从库 36.137.20.40:   导入 dump → my.cnf{server-id=2, read_only, super_read_only, gtid_mode=ON}
                     → 重启 → CHANGE REPLICATION SOURCE TO(... SOURCE_AUTO_POSITION=1) → START REPLICA
                     → SHOW REPLICA STATUS\G  (IO=Yes, SQL=Yes, Behind≈0)

项目配置:            主库server .env→指主库, cron 全开;  从库server .env→指本地从库+只读账号, cron 写入作业关闭
                     应用代码无需改动 (读写分离才需改, 见 §7.3)

灾备:                STOP REPLICA; RESET REPLICA ALL; SET GLOBAL super_read_only=OFF; read_only=OFF
                     → 应用 QUANTIA_DB_HOST 指向 36.137.20.40 → 重启 web + 开 cron
```
