# 玄枢 Quantia 快速入门指南

本文档帮助您快速上手玄枢 Quantia 智能量化投资中枢。

---

## 🚀 五分钟快速开始

### 1. 安装依赖

```bash
# 克隆项目
git clone https://github.com/posbright/Quantia.git
cd Quantia

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置数据库

复制 `.env.example` 为 `.env`，并填写数据库连接：

```env
QUANTIA_DB_HOST=localhost
QUANTIA_DB_USER=root
QUANTIA_DB_PASSWORD=your_password
QUANTIA_DB_DATABASE=quantiadb
QUANTIA_DB_PORT=3306
```

### 3. 运行数据作业

```bash
cd quantia/job
python execute_daily_job.py
```

### 4. 启动 Web 服务

```bash
cd quantia/bin
# Windows:
run_web.bat
# Linux/Mac:
./run_web.sh
```

### 5. 启动前端开发服务（可选）

```bash
cd quantia/fontWeb
npm install
npm run dev
```

### 6. 访问系统

| 入口 | 地址 | 说明 |
|------|------|------|
| 后端直连 | http://localhost:9988 | Tornado 服务（生产环境） |
| 前端开发 | http://localhost:3000 | Vite dev server（开发时用） |

前端开发模式通过 `.env.development` 中 `VITE_API_TARGET` 配置 API 代理目标。

---

## 📊 常用操作

### 回测看板（Vue前端）

启动 Web 服务后，在页面左侧菜单进入：**选股验证 → 回测看板**。

- 支持跨策略总览、时间序列、单策略明细、收益分布、买入-卖出配对
- 支持两种区间方式：最近 N 个交易日（days）或显式日期区间（start_date/end_date）

### 选股验证中心（因子实验）

默认因子验证模板用 `m1_auto_ic_m12`，`m1_auto_ic_m15` / `m1_auto_ic_m16` 只作约束实验对照；做模板比较时建议固定样本、窗口和披露滞后，再看 Top−Bottom 与单调性。

### 手动拉取历史数据

```bash
cd quantia/job

# 拉取当前交易日的最新数据（实时行情 + 历史K线 + 指数K线，增量更新）
python fetch_data_job.py

# 指定日期拉取
python fetch_data_job.py 2024-06-15
```

> 首次运行需从API获取全量历史数据（耗时较长），后续运行只需补缺新增交易日数据（快速完成）。
> 数据源优先级：东方财富 → 腾讯财经 → 新浪财经，自动容错切换。

### 获取今日股票数据

```bash
cd quantia/job
python basic_data_daily_job.py
```

### 计算技术指标

```bash
python indicators_data_daily_job.py
```

### 运行策略选股

```bash
python strategy_data_daily_job.py
```

### 批量处理历史数据

```bash
# 指定日期
python execute_daily_job.py 2024-01-15

# 日期范围
python execute_daily_job.py 2024-01-01 2024-01-31
```

### 调整历史数据获取年数

```bash
# 默认10年，Docker默认3年，可通过环境变量调整
# Windows:
set HIST_DATA_DEFAULT_YEARS=10
python fetch_data_job.py

# Linux/Mac:
export HIST_DATA_DEFAULT_YEARS=10
python fetch_data_job.py
```

### 强制重建缓存

```bash
# 清空缓存目录后重新获取（耗时较长）
# Windows:
rd /s /q quantia\cache\hist
# Linux/Mac:
rm -rf quantia/cache/hist

python fetch_data_job.py
```

---

## 🐳 Docker 快速部署

```bash
cd docker

# 完整部署（包含MySQL）
docker-compose up -d

# 仅应用（使用外部MySQL）
docker-compose -f docker-compose.remote-db.yml up -d
```

---

## 📁 核心目录说明

| 目录 | 说明 |
|-----|------|
| `quantia/job/` | 数据作业脚本 |
| `quantia/core/` | 核心业务逻辑 |
| `quantia/web/` | Web服务 |
| `quantia/config/` | 配置文件 |
| `quantia/log/` | 日志文件 |

---

## 🔧 常见问题

### Q: 数据获取失败？

A: 系统已配置多数据源（东方财富→腾讯财经→新浪财经），会自动切换。如果仍失败：
1. 检查网络连接
2. 配置代理：编辑 `quantia/config/proxy.txt`

### Q: 数据库连接失败？

A: 检查数据库配置和MySQL服务是否运行：
```bash
mysql -u root -p -e "SELECT 1"
```

### Q: 如何更新历史数据？

A: 历史数据采用增量更新机制，只需运行：
```bash
cd quantia/job
python fetch_data_job.py
```
或使用整体作业：
```bash
python execute_daily_job.py
```

---

## 📖 更多文档

- [完整项目文档](PROJECT_DOCUMENTATION.md)
- [API接口文档](document/API_REFERENCE.md)
- [数据库设计文档](document/database_schema.md)
- Docker 部署文件：当前仓库保留在 `docker/` 目录，详细部署文档待补充。
- [定时任务说明](cron/README.md)
- [历史数据缓存说明](document/hist_cache_incremental.md)
- [回测看板计划（对齐当前实现）](document/backtest_dashboard_plan.md)
