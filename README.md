# 玄枢 Quantia 智能量化投资中枢

玄枢 Quantia 是面向 A 股与 ETF 的智能量化投资工作台，覆盖多源行情采集、历史 K 线缓存、技术指标计算、K 线形态识别、筹码分布、综合选股、策略回测、模拟交易、通知与 AI 策略助手。它的目标不是做一个单点脚本，而是把数据获取、信号生成、策略验证和交易前评估串成一条可重复运行的研究流程。

当前仓库已完成 Quantia 化收尾：Python 包目录为 `quantia/`，前端默认请求 `/quantia` API 前缀，运行环境变量主前缀统一为 `QUANTIA_*`，数据库默认名为 `quantiadb`。

## 核心能力

- 多源行情数据：支持 A 股、ETF、指数、资金流、龙虎榜、大宗交易、公告、行业与概念等数据采集。
- 历史 K 线缓存：按股票和指数维护本地增量缓存，减少重复请求并支持大批量回测。
- 技术指标计算：内置 MACD、KDJ、BOLL、RSI、CCI、DMI、ATR、OBV、SAR、Supertrend 等常用指标。
- K 线形态识别：覆盖 60 多种经典形态，可用于选股、回测和信号解释。
- 综合选股：支持基本面、技术面、资金流、人气、行业、概念、指数成份等多维条件组合。
- 策略回测：提供单策略、组合策略、批量回测、收益分布、时间序列和买卖配对分析。
- 模拟交易：支持纸面账户、持仓、净值曲线、执行日志和每日调度。
- 通知与 IM：提供通知配置、事件追踪、重试机制和钉钉 IM 指令确认能力。
- AI 策略助手：支持策略生成、优化、修复、会话记忆、检索增强和工具调用。
- 前端工作台：Vue + Vite + Element Plus，包含选股验证、回测看板、策略管理、模拟交易、AI 助手等页面。

## 架构概览

```text
Quantia
├── quantia/                 # Python 包与服务代码
│   ├── core/                # 数据获取、指标、策略、回测等核心逻辑
│   ├── job/                 # 数据采集、缓存更新、分析与调度任务
│   ├── web/                 # Tornado 后端服务与生产静态资源
│   ├── fontWeb/             # Vue 前端源码，Vite 开发服务
│   ├── lib/                 # 数据库、配置、日志、AI 基础库
│   ├── paper_trading/       # 模拟交易引擎与调度器
│   ├── notification/        # 通知服务与渠道实现
│   └── trade/               # 交易相关扩展
├── cron/                    # Linux 定时任务脚本
├── document/                # 设计文档、开发计划、专题说明
├── docker/                  # Docker 部署相关文件
├── tests/                   # 后端和集成测试
├── QUICKSTART.md            # 快速启动说明
└── PROJECT_DOCUMENTATION.md # 更完整的项目说明
```

## 快速开始

### 1. 准备 Python 环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置数据库

复制 `.env.example` 为 `.env`，按实际环境修改数据库配置：

```env
QUANTIA_DB_HOST=127.0.0.1
QUANTIA_DB_USER=root
QUANTIA_DB_PASSWORD=your_password_here
QUANTIA_DB_DATABASE=quantiadb
QUANTIA_DB_PORT=3306
```

说明：新项目默认使用 `quantiadb`。已有部署需要保留原有库时，可显式设置 `QUANTIA_DB_DATABASE` 指向实际数据库名。

### 3. 启动后端服务

Windows:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python quantia\web\web_service.py
```

或使用脚本：

```powershell
cd quantia\bin
.\run_web.bat
```

默认访问地址：

```text
http://localhost:9988/
```

### 4. 启动前端开发服务

```powershell
cd quantia\fontWeb
npm install
npx vite --host=127.0.0.1
```

当前 Vite 配置默认端口为 `3000`，并代理后端接口到 `http://localhost:9988`：

```text
http://127.0.0.1:3000/
```

### 5. 验证服务

```powershell
Invoke-WebRequest http://127.0.0.1:9988/robots.txt
Invoke-WebRequest http://127.0.0.1:9988/quantia/api/auth/me
Invoke-WebRequest http://127.0.0.1:3000/
Invoke-WebRequest http://127.0.0.1:3000/quantia/api/auth/me
```

`/quantia/api/auth/me` 在未开启鉴权时会返回类似：

```json
{"ok": true, "data": {"enabled": false, "username": null, "role": null}}
```

## 常用任务

### 数据获取

```powershell
cd quantia\job
python fetch_data_job.py
```

指定日期：

```powershell
python fetch_data_job.py 2024-06-15
```

### 整体日任务

```powershell
cd quantia\job
python execute_daily_job.py
```

日期范围：

```powershell
python execute_daily_job.py 2024-01-01 2024-01-31
```

### K 线缓存增量更新

```powershell
cd quantia\job
python kline_cache_daily_job.py
```

### 本地分析任务

```powershell
cd quantia\job
python analysis_daily_job.py
```

### 运行测试

```powershell
pytest tests
```

前端测试：

```powershell
cd quantia\fontWeb
npm test
```

## Web 功能入口

- 回测看板：跨策略总览、单策略明细、收益分布、时间序列、买入卖出配对。
- 策略管理：内置策略模板、自定义策略代码、组合回测和任务结果查看。
- 综合选股：按基本面、技术面、资金流、人气、行情字段组合筛选。
- 模拟交易：纸面账户创建、运行、持仓、执行日志和净值对比。
- 自定义指标：综合指标 CRUD、回测、关注榜和 K 线叠加序列。
- AI 策略助手：策略生成、会话、修复、智能体配置和检索工具。
- 通知与 IM：通知配置、事件追踪、钉钉回调和指令确认。

## 配置说明

Quantia 通过 `.env`、系统环境变量和代码默认值读取配置。常用变量包括：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `QUANTIA_DB_HOST` | `127.0.0.1` | MySQL 主机 |
| `QUANTIA_DB_USER` | `root` | MySQL 用户 |
| `QUANTIA_DB_PASSWORD` | 空 | MySQL 密码 |
| `QUANTIA_DB_DATABASE` | `quantiadb` | 数据库名 |
| `QUANTIA_WEB_PORT` | `9988` | 后端服务端口 |
| `HIST_DATA_DEFAULT_YEARS` | `10` | 默认历史数据年数 |
| `QUANTIA_FORCE_FETCH` | `0` | 强制执行数据获取 |
| `QUANTIA_FORCE_KLINE_CACHE` | `0` | 强制执行 K 线缓存更新 |
| `QUANTIA_FORCE_ANALYSIS` | `0` | 强制执行分析任务 |
| `QUANTIA_AUTH_ENABLED` | `false` | 是否启用鉴权 |

数据库配置变量为 `QUANTIA_DB_*`，默认库名为 `quantiadb`。

## 开发约定

- 当前代码包名为 `quantia`。
- 当前后端 API 主前缀为 `/quantia`。
- `quantia/fontWeb/dist/` 与 `quantia/web/static/` 是生产静态资源相关目录，修改前端源码后需要按部署方式同步构建。
- `cache/`、`quantia/log/`、`__pycache__/`、`node_modules/`、`.pytest_cache/` 等生成物不应提交。
- 涉及数据库、任务调度、交易和通知的改动应优先补充测试或至少做启动验证。

## 当前状态

- 品牌名称：玄枢 Quantia
- 后端框架：Tornado
- 前端框架：Vue 3 + Vite + Element Plus
- 数据库：MySQL / MariaDB
- 主要语言：Python、TypeScript、Vue
- 默认后端端口：`9988`
- 默认前端开发端口：`3000`

## 文档索引

- [快速入门](QUICKSTART.md)
- [完整项目文档](PROJECT_DOCUMENTATION.md)
- [API 接口文档](document/API_REFERENCE.md)
- [数据库设计文档](document/database_schema.md)
- [历史 K 线缓存说明](document/hist_cache_incremental.md)
- [回测看板计划](document/backtest_dashboard_plan.md)
- [定时任务说明](cron/README.md)

## 迁移说明

本仓库已作为 Quantia 新项目重新整理提交历史，并完成代码包、API 主前缀、运行环境变量和默认数据库命名迁移。后续如果需要，可以继续推进：

1. 更新 Docker 镜像、服务名和生产部署路径中的剩余兼容命名。
