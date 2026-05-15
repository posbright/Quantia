# bin 目录脚本使用文档

本目录包含项目运行所需的各类脚本，涵盖**服务管理、数据任务、交易服务、定时任务**等功能。

> **约定**：
> - 后端 Web 服务默认端口 **9988**
> - 前端 Vite 开发服务器默认端口 **3000**
> - 项目虚拟环境位于项目根目录 `.venv/`
> - 日志输出目录 `quantia/log/`

---

## 目录总览

| 脚本 | 平台 | 功能简述 |
|------|------|----------|
| `server.bat` | Windows | 一站式服务管理（启动/停止/重启/状态查询） |
| `server.sh` | Linux / macOS | 一站式服务管理（启动/停止/重启/状态查询） |
| `run_web.bat` | Windows | 前台启动后端 Web 服务 |
| `run_web.sh` | Linux / macOS | 前台启动后端 Web 服务 |
| `restart_web.sh` | Linux / macOS | 后台重启后端 Web 服务（nohup） |
| `run_job.bat` | Windows | 每日数据任务流水线 |
| `run_job.sh` | Linux / macOS | 每日数据任务流水线 |
| `run_local.bat` | Windows | 本地高并发数据处理（可配置环境变量） |
| `run_trade.bat` | Windows | 启动交易服务 |
| `run_cron.sh` | Linux (Docker) | Docker 容器内定时任务入口 |

---

## 1. server.bat（Windows 服务管理）

### 功能

统一管理后端 Python Web 服务和前端 Vite 开发服务器的启动、停止、重启及状态查询。使用 PowerShell `Get-NetTCPConnection` 检测端口占用，稳定可靠。

### 用法

```bat
server.bat <命令>
```

### 命令一览

| 命令 | 说明 |
|------|------|
| `start` | 启动后端 + 前端 |
| `stop` | 停止后端 + 前端 |
| `restart` | 重启全部服务 |
| `status` | 查看各服务运行状态 |
| `web` | 仅启动后端 Web 服务（端口 9988） |
| `front` | 仅启动前端 Vite 开发服务器（端口 3000） |

### 示例

```bat
REM 启动所有服务
server.bat start

REM 查看运行状态
server.bat status

REM 仅启动后端
server.bat web

REM 停止所有服务
server.bat stop

REM 重启
server.bat restart
```

### 输出示例

```
====== Service Status ======
[Backend]  RUNNING  PID=12345  http://localhost:9988/
[Frontend] RUNNING  PID=23456  http://localhost:3000/
=============================
```

### 注意事项

- 自动激活项目虚拟环境 `.venv\Scripts\activate.bat`
- 日志文件：`quantia/log/web_service.log`（后端）、`quantia/log/front_dev.log`（前端）
- 需要 PowerShell 5.0+ （Windows 10/11 默认自带）

---

## 2. server.sh（Linux/macOS 服务管理）

### 功能

与 `server.bat` 功能对等的 Linux/macOS 版本。使用 `lsof` 检测端口占用，`nohup` 后台运行服务。

### 用法

```bash
chmod +x server.sh
./server.sh <命令>
```

### 命令一览

与 `server.bat` 完全一致：`start` | `stop` | `restart` | `status` | `web` | `front`

### 示例

```bash
# 启动所有服务
./server.sh start

# 查看状态
./server.sh status

# 仅启动前端
./server.sh front

# 停止并重启
./server.sh restart
```

### 注意事项

- 自动 source `.venv/bin/activate`（若存在）
- PID 文件保存在 `quantia/log/web.pid` 和 `quantia/log/front.pid`
- 依赖 `lsof` 命令（大多数 Linux 发行版自带）

---

## 3. run_web.bat（Windows 前台启动后端）

### 功能

以前台模式启动后端 Python Web 服务，适合开发调试。脚本退出即服务停止。

### 用法

```bat
run_web.bat
```

### 工作流程

1. 激活虚拟环境 `.venv\Scripts\activate.bat`
2. 设置 `PYTHONPATH` 为项目根目录
3. 执行 `python quantia\web\web_service.py`

### 适用场景

- 开发调试时希望看到实时日志输出
- 不需要前端开发服务器时

---

## 4. run_web.sh（Linux/macOS 前台启动后端）

### 功能

`run_web.bat` 的 Linux/macOS 版本，前台运行后端服务。

### 用法

```bash
chmod +x run_web.sh
./run_web.sh
```

### 工作流程

1. 自动 source `.venv/bin/activate`（若存在）
2. 设置 `PYTHONPATH` 和 `LANG=zh_CN.UTF-8`
3. 执行 `python3 quantia/web/web_service.py`

---

## 5. restart_web.sh（Linux/macOS 后台重启后端）

### 功能

杀掉已运行的 `web_service.py` 进程，然后用 `nohup` 重新后台启动。适合生产环境的快速重启。

### 用法

```bash
chmod +x restart_web.sh
./restart_web.sh
```

### 工作流程

1. `kill` 所有 `web_service.py` 相关进程
2. 等待 1 秒
3. `nohup python3 web_service.py &` 在后台启动
4. 日志输出到同目录 `nohup.out`

### 注意事项

- 直接在 `quantia/web/` 目录下执行
- 使用 `ps -ef | grep web_service.py` 查找进程

---

## 6. run_job.bat（Windows 每日数据任务）

### 功能

执行每日数据采集与分析任务流水线。支持指定日期参数，默认当天。

### 用法

```bat
run_job.bat [日期参数]
```

### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| 无参数 | 执行当天日期的任务 | `run_job.bat` |
| 单个日期 | 执行指定日期的任务 | `run_job.bat 2024-01-15` |

### 工作流程

1. 激活虚拟环境
2. 设置 `PYTHONPATH`
3. 按顺序执行以下 Job：
   - `execute_daily_job.py` — 每日执行任务入口

### 示例

```bat
REM 默认当天
run_job.bat

REM 指定日期
run_job.bat 2024-01-15
```

---

## 7. run_job.sh（Linux/macOS 每日数据任务）

### 功能

`run_job.bat` 的 Linux/macOS 版本。

### 用法

```bash
chmod +x run_job.sh
./run_job.sh [日期参数]
```

### 示例

```bash
# 当天
./run_job.sh

# 指定日期
./run_job.sh 2024-01-15
```

---

## 8. run_local.bat（Windows 本地高并发数据处理）

### 功能

本地开发/测试专用脚本。相比 `run_job.bat`，提供了**丰富的环境变量配置**，适合在本地机器上对远程数据库进行高并发数据处理。

### 用法

```bat
run_local.bat [日期参数]
```

### 参数说明

| 参数格式 | 说明 | 示例 |
|----------|------|------|
| 无参数 | 当天日期 | `run_local.bat` |
| 单个日期 | 指定日期 | `run_local.bat 2024-07-15` |
| 逗号分隔 | 多个日期 | `run_local.bat 2024-07-15,2024-07-16` |
| 日期范围 | 起止区间 | `run_local.bat 2024-07-01~2024-07-31` |

### 可配置环境变量

脚本内置了完整的环境变量配置段，可直接修改：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `QUANTIA_DB_HOST` | 127.0.0.1 | 数据库地址 |
| `QUANTIA_DB_PORT` | 3306 | 数据库端口 |
| `QUANTIA_DB_USER` | root | 数据库用户名 |
| `QUANTIA_DB_PASSWORD` | 空 | 数据库密码 |
| `QUANTIA_DB_DATABASE` | quantiadb | 数据库名 |
| `QUANTIA_ANALYSIS_WORKERS` | 16 | 分析并发线程数 |
| `QUANTIA_BATCH_SIZE` | 3000 | 每批处理股票数 |
| `QUANTIA_DB_POOL_SIZE` | 8 | 数据库连接池大小 |
| `QUANTIA_DB_MAX_RETRIES` | 3 | 失败重试次数 |
| `QUANTIA_DB_RETRY_DELAY` | 10 | 重试间隔（秒） |

### 工作流程

1. 设置所有环境变量
2. 检查数据库连接（Python 脚本 `check_db`）
3. 激活虚拟环境
4. 执行 `execute_daily_job.py`

### 示例

```bat
REM 当天数据
run_local.bat

REM 补全历史某天
run_local.bat 2024-07-15

REM 批量补全
run_local.bat 2024-07-01~2024-07-31
```

### 注意事项

- 首次使用需确认脚本内的数据库连接信息
- 高并发配置适合本地宽带网络，远程服务器建议降低 `QUANTIA_ANALYSIS_WORKERS`

---

## 9. run_trade.bat（Windows 交易服务）

### 功能

启动自动化交易服务。

### 用法

```bat
run_trade.bat
```

### 工作流程

1. 激活虚拟环境
2. 设置 `PYTHONPATH`
3. 启动交易服务模块

### 注意事项

- 交易配置文件位于 `quantia/config/trade_client.json`
- **请确保交易配置正确后再运行**，避免误操作

---

## 10. run_cron.sh（Docker 容器定时任务）

### 功能

Docker 容器内的定时任务启动脚本。加载环境变量后启动 `cron` 守护进程。

### 用法

```bash
# 通常由 Docker 容器自动调用，不手动执行
./run_cron.sh
```

### 工作流程

1. 从 `/etc/environment` 加载环境变量
2. 导入当前环境变量到 cron 环境
3. 启动 `cron -f`（前台模式）

### 注意事项

- 仅在 Docker 容器中使用
- 配合 `cron/` 目录下的定时任务配置使用
- 定时任务模板参见 `cron/README.md`

---

## 常用运维场景

### 场景 1：开发调试（Windows）

```bat
REM 启动所有服务
server.bat start

REM 做完开发后停止
server.bat stop
```

### 场景 2：只启动后端 API（调试接口）

```bat
REM Windows
server.bat web

REM 或前台运行（ctrl+C 停止）
run_web.bat
```

### 场景 3：补全历史数据

```bat
REM 补全单日
run_local.bat 2024-07-15

REM 补全一整月
run_local.bat 2024-07-01~2024-07-31
```

### 场景 4：Linux 生产环境快速重启

```bash
./restart_web.sh
# 或
./server.sh restart
```

### 场景 5：Docker 部署

参见项目 `docker/` 目录下的 `DOCKER_DEPLOY.md`。
