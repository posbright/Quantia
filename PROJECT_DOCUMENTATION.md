# 玄枢 Quantia 智能量化投资中枢

> 洞察市场玄机的智能量化投资中枢，支持A股股票和ETF数据抓取、技术指标计算、K线形态识别、策略选股、回测验证、模拟交易和自动交易。

---

## 📑 目录

- [功能概述](#功能概述)
- [系统架构](#系统架构)
- [目录结构](#目录结构)
- [模块详解](#模块详解)
- [安装部署](#安装部署)
- [使用指南](#使用指南)
- [配置说明](#配置说明)
- [API接口](#api接口)
- [扩展开发](#扩展开发)

---

## 功能概述

### 核心功能

| 功能模块 | 描述 |
|---------|------|
| **综合选股** | 支持200+信息栏目自由组合选股，包括股票范围、基本面、技术面、消息面等 |
| **每日数据** | 自动抓取股票/ETF日数据、资金流向、龙虎榜、大宗交易、分红配送等 |
| **指标计算** | 基于TA-Lib计算32种技术指标（MACD、KDJ、BOLL、RSI等） |
| **K线形态** | 精准识别61种K线形态（锤头、十字星、吞噬模式等） |
| **策略选股** | 内置14种选股策略（放量上涨、停机坪、突破平台、GPT综合选股等） |
| **回测验证** | 对选股策略进行历史回测，验证成功率；提供回测看板（总览/时间序列/分布/配对），支持自定义收益周期与日期区间 |
| **自动交易** | 支持自动交易，内置打新策略，可扩展交易策略 |
| **筹码分布** | 计算并可视化股票筹码分布图 |

### 技术特点

- **多数据源支持**：东方财富 → 腾讯财经 → 新浪财经（22 个爬虫模块），自动容错切换
- **AKShare财务数据**：通过AKShare获取东方财富个股财务分析指标，为回测提供真实基本面数据
- **数据源健康度追踪**：连续失败自动降级，渐进退避（300s→3600s），恢复后自动提升
- **增量缓存**：历史数据以天为单位增量更新，~5000 只股票本地 K 线缓存
- **多线程处理**：采用并发处理，提高数据抓取和计算效率
- **流式分析**：单次遍历4900只股票完成指标+K线+策略分析，峰值内存<100MB（替代旧版~1670MB）
- **数据采集/分析分离**：Fetch管道负责API调用，Analysis/Web管道零API调用，仅读DB/缓存
- **128 个后端 API**：18 个 Handler 模块覆盖数据、指标、策略、回测、交易、AI、IM、鉴权
- **60 个前端路由**：Vue 3 + TypeScript + Element Plus，完整覆盖所有业务场景
- **81 个测试文件**：1700+ 测试用例，覆盖核心逻辑与 API
- **Docker支持**：提供Docker镜像，一键部署

---

## 系统架构

### 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面层                                │
├─────────────────────────────────────────────────────────────────┤
│   Web Service (Tornado)    │    Vue Frontend (TypeScript)       │
│   端口: 9988               │    开发端口: 3000                   │
└─────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────┐
│                         业务逻辑层                                │
├─────────────────────────────────────────────────────────────────┤
│  策略选股  │  指标计算  │  K线形态  │  筹码分布  │  回测验证      │
│  strategy/ │ indicator/ │  pattern/ │   kline/   │  backtest/    │
└─────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────┐
│                         数据服务层                                │
├─────────────────────────────────────────────────────────────────┤
│               stockfetch.py (多数据源调度)                        │
│  ┌─────────────┬─────────────┬─────────────┐                    │
│  │  东方财富    │   腾讯财经   │   新浪财经   │                    │
│  │ (优先级: 1)  │  (优先级: 2) │  (优先级: 3) │                    │
│  └─────────────┴─────────────┴─────────────┘                    │
│               singleton_proxy.py (代理池管理)                     │
│  ┌─────────────────────────────────────────┐                    │
│  │ 12个免费代理源 → 验证 → 池管理 → 动态直连  │                    │
│  │ 仅东方财富使用代理，腾讯/新浪直连无需代理    │                    │
│  └─────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────┐
│                         数据存储层                                │
├─────────────────────────────────────────────────────────────────┤
│   MySQL Database (quantiadb)    │    File Cache (cache/hist/)   │
└─────────────────────────────────────────────────────────────────┘
```

### 数据采集/分析分离原则

系统严格遵循"数据采集和数据分析分离"原则：

| 管道 | 职责 | API调用 | 数据来源 |
|------|------|---------|---------|
| **Fetch管道** | 从外部数据源获取数据 | 是（东方财富/腾讯/新浪） | API → DB/缓存 |
| **Analysis管道** | 计算指标、识别形态、策略选股 | 否 | DB + 缓存 → DB |
| **Web管道** | 展示数据、K线图表 | 否 | DB + 缓存 → 前端 |

### API数据新鲜度检测机制

**原则**：API数据仅在「结算时间后 + 数据行数达标」时跳过重复获取。

#### 判定逻辑（_check_and_skip）

```
跳过条件（需同时满足）：
  ① QUANTIA_FORCE_FETCH != 1     （未强制获取）
  ② is_post_settlement() == True  （已过结算时间）
  ③ is_data_fresh() == True       （数据行数 >= 阈值）

is_post_settlement() 逻辑：
  当前日期 > 交易日 → True（隔日/周末，数据已稳定）
  当前日期 = 交易日 且 当前小时 >= QUANTIA_SETTLEMENT_HOUR(18) → True
  其他情况 → False（数据可能仍在更新）
```

#### 不同类型数据的处理策略

| 数据类型 | 示例 | 跳过策略 | 原因 |
|----------|------|----------|------|
| **API行情数据** | cn_stock_spot, cn_etf_spot | 结算后+行数达标可跳过 | 收盘后数据稳定 |
| **API选股数据** | cn_stock_selection | 结算后+行数达标可跳过 | 收盘后数据稳定 |
| **API延迟数据** | 龙虎榜、大宗交易、资金流向 | 每次执行都获取 | 无行数阈值检查，幂等覆盖 |
| **计算型数据** | 指标、策略、K线形态、回测 | 每次执行都计算 | 非API数据，需用最新基础数据 |

#### 结算时间配置

```bash
# .env
QUANTIA_SETTLEMENT_HOUR=18   # A股收盘15:00，龙虎榜/大宗交易等约17:00-18:00更新完毕
```

```
Fetch管道（有API调用）:
  fetch_daily_job → init_job → basic_data_daily_job
                  → selection_data_daily_job → basic_data_other_daily_job
                  → basic_data_after_close_daily_job → fetch_data_job(K线缓存)

Analysis管道（零API调用）:
  analysis_daily_job → gpt_value_data_job → streaming_analysis_job
                     → backtest_data_daily_job

Web管道（零API调用）:
  klineHandler.py → read_hist_from_cache()  # 缓存只读
  dataIndicatorsHandler.py → read_hist_from_cache()  # 缓存只读
```

### 代理池架构

```
singleton_proxy.py (单例模式，线程安全)
├── 12个免费GitHub代理源并发抓取
├── 20线程并发验证（HTTP+HTTPS双重验证）
├── 后台600秒定时刷新
├── 紧急补充机制（池耗尽时60秒防抖异步补充）
├── 动态直连概率调整：
│   ├── 池≥10个：30%直连
│   ├── 池3~9个：60%直连
│   └── 池<3个：80%直连
├── 代理健康管理：连续3次失败自动移除
└── 仅东方财富API使用代理，腾讯/新浪直连
```

---

## 目录结构

```
Quantia/
├── README.md                    # 项目说明文档
├── requirements.txt             # Python依赖包
├── LICENSE                      # 开源许可证
│
├── quantia/                     # 📦 核心代码目录
│   ├── __init__.py
│   │
│   ├── bin/                     # 🚀 启动脚本
│   │   ├── run_web.sh/.bat     # 启动Web服务
│   │   ├── run_job.sh/.bat     # 启动数据作业
│   │   ├── run_trade.bat       # 启动交易服务
│   │   └── run_cron.sh         # 启动定时任务
│   │
│   ├── config/                  # ⚙️ 配置文件
│   │   ├── proxy.txt           # 代理IP配置
│   │   ├── eastmoney_cookie.txt # 东方财富Cookie
│   │   └── trade_client.json   # 交易客户端配置
│   │
│   ├── core/                    # 🧠 核心业务模块
│   │   ├── stockfetch.py       # 数据获取核心（多数据源调度+增量缓存）
│   │   ├── eastmoney_fetcher.py # 东方财富HTTP客户端（代理轮换+Session管理）
│   │   ├── singleton_proxy.py  # 代理池管理单例（12源+紧急补充+动态直连）
│   │   ├── tablestructure.py   # 数据库表结构定义
│   │   ├── singleton_stock.py  # 股票数据单例
│   │   ├── singleton_trade_date.py # 交易日历单例（DB优先→新浪回退）
│   │   ├── singleton_stock_web_module_data.py # Web模块数据单例
│   │   ├── web_module_data.py  # Web模块数据配置
│   │   │
│   │   ├── crawling/           # 🕷️ 数据爬取模块
│   │   │   ├── stock_sina.py       # 新浪财经-股票实时行情
│   │   │   ├── stock_tencent.py    # 腾讯财经-股票实时行情
│   │   │   ├── stock_hist_em.py    # 东方财富-历史K线
│   │   │   ├── stock_hist_tencent.py # 腾讯财经-历史K线（新增）
│   │   │   ├── stock_hist_sina.py  # 新浪财经-历史K线
│   │   │   ├── stock_fund_em.py    # 东方财富-资金流向
│   │   │   ├── stock_fund_sina.py  # 新浪财经-资金流向
│   │   │   ├── stock_lhb_em.py     # 东方财富-龙虎榜
│   │   │   ├── stock_lhb_sina.py   # 新浪财经-龙虎榜
│   │   │   ├── stock_dzjy_em.py    # 大宗交易
│   │   │   ├── stock_fhps_em.py    # 分红配送
│   │   │   ├── stock_selection.py  # 综合选股
│   │   │   ├── stock_chip_race.py  # 早盘/尾盘抢筹
│   │   │   ├── stock_limitup_reason.py # 涨停原因
│   │   │   ├── fund_etf_em.py      # ETF数据
│   │   │   ├── etf_sina.py         # 新浪财经-ETF
│   │   │   ├── etf_tencent.py      # 腾讯财经-ETF
│   │   │   └── trade_date_hist.py  # 交易日历
│   │   │
│   │   ├── indicator/          # 📊 指标计算模块
│   │   │   └── calculate_indicator.py  # 32种技术指标计算
│   │   │
│   │   ├── pattern/            # 📈 K线形态识别
│   │   │   └── pattern_recognitions.py # 61种K线形态
│   │   │
│   │   ├── strategy/           # 💡 选股策略
│   │   │   ├── base.py               # 策略基类（ABC）及注册框架
│   │   │   ├── enter.py              # 放量上涨
│   │   │   ├── keep_increasing.py    # 均线多头
│   │   │   ├── parking_apron.py      # 停机坪
│   │   │   ├── backtrace_ma250.py    # 回踩年线
│   │   │   ├── breakthrough_platform.py # 突破平台
│   │   │   ├── low_backtrace_increase.py # 无大幅回撤
│   │   │   ├── turtle_trade.py       # 海龟交易法则
│   │   │   ├── high_tight_flag.py    # 高而窄的旗形
│   │   │   ├── climax_limitdown.py   # 放量跌停
│   │   │   ├── low_atr.py            # 低ATR成长
│   │   │   ├── gpt_value_strategy.py # GPT综合选股（基本面）
│   │   │   ├── technical/            # 技术策略扩展
│   │   │   │   ├── ma_strategies.py           # MA均线策略
│   │   │   │   └── value_invest_strategies.py # 趋势回调/超跌反弹/突破确认
│   │   │   ├── fundamental/          # 基本面策略
│   │   │   │   ├── fundamental_strategies.py  # 价值/成长/护城河/股息策略
│   │   │   │   ├── fundamental_filter.py      # 基本面过滤器
│   │   │   │   ├── moat_model.py              # 护城河评分模型
│   │   │   │   └── moat_ai_service.py         # AI护城河分析服务
│   │   │   ├── volume/               # 成交量策略
│   │   │   │   └── volume_strategies.py       # 放量上涨/放量跌停策略类
│   │   │   └── pattern/              # 形态策略
│   │   │       └── pattern_strategies.py      # 突破平台/停机坪等策略类
│   │   │
│   │   ├── kline/              # 📉 K线可视化
│   │   │   ├── cyq.py          # 筹码分布计算
│   │   │   ├── cyq.js          # 筹码分布JS
│   │   │   ├── visualization.py # K线可视化
│   │   │   └── indicator_web_dic.py # 指标字典
│   │   │
│   │   └── backtest/           # 🔄 回测模块
│   │       ├── rate_stats.py           # 收益率统计
│   │       ├── portfolio_engine.py     # 聚宽风格组合回测引擎
│   │       ├── fundamentals.py         # 基本面数据（真实财务数据优先，合成数据兜底）
│   │       ├── strategy_sandbox.py     # 策略安全沙箱
│   │       ├── strategy_context.py     # 回测上下文/持仓/交易
│   │       ├── data_feed.py            # K线数据加载层
│   │       └── risk_metrics.py         # 25项风险指标计算
│   │
│   ├── job/                     # ⏰ 定时作业
│   │   ├── execute_daily_job.py    # 整体作业调度（Phase 0→1→2→3→4 流水线）
│   │   ├── fetch_daily_job.py      # 数据获取管道（轻量API+K线缓存，可独立运行）
│   │   ├── analysis_daily_job.py   # 分析管道（GPT + 流式分析 + 回测，零API调用）
│   │   ├── streaming_analysis_job.py # Phase 4 流式分析（替代 indicators/klinepattern/strategy）
│   │   ├── init_job.py             # 初始化（创建数据库）
│   │   ├── fetch_data_job.py       # 数据获取作业（实时行情+历史K线+缓存清理）
│   │   ├── basic_data_daily_job.py # 基础数据实时作业
│   │   ├── basic_data_other_daily_job.py # 其他基础数据（龙虎榜/资金流向/分红等）
│   │   ├── basic_data_after_close_daily_job.py # 收盘后数据（大宗交易/尾盘抢筹）
│   │   ├── selection_data_daily_job.py # 综合选股数据
│   │   ├── gpt_value_data_job.py   # GPT综合选股作业（DB only，7天回退）
│   │   ├── backtest_data_daily_job.py # 回测数据作业
│   │   ├── indicators_data_daily_job.py # [旧版] 指标数据作业（已被streaming替代）
│   │   ├── klinepattern_data_daily_job.py # [旧版] K线形态作业（已被streaming替代）
│   │   ├── strategy_data_daily_job.py # [旧版] 策略选股作业（已被streaming替代）
│   │   └── stock_financial_data.py # 个股财务数据获取（AKShare东方财富，月度增量）
│   │
│   ├── paper_trading/           # 📈 模拟交易模块
│   │   ├── __init__.py
│   │   ├── paper_engine.py     # 模拟交易执行引擎（每日定时驱动，真实数据源）
│   │   └── state_manager.py    # 持仓/现金/NAV 状态持久化
│   │
│   ├── web/                     # 🌐 Web服务
│   │   ├── web_service.py      # Tornado主服务（路由注册）
│   │   ├── base.py             # 基础Handler（CORS、左侧菜单）
│   │   ├── dataTableHandler.py # 数据表Handler（分页、搜索）
│   │   ├── dataIndicatorsHandler.py # 指标/K线图Handler
│   │   ├── strategyParamsHandler.py # 策略参数配置Handler
│   │   ├── templates/          # HTML模板
│   │   └── static/             # 静态资源
│   │
│   ├── trade/                   # 💹 自动交易
│   │   ├── trade_service.py    # 交易服务主程序
│   │   ├── usage.md            # 交易使用说明
│   │   ├── robot/              # 交易机器人引擎
│   │   └── strategies/         # 交易策略
│   │
│   ├── lib/                     # 📚 公共库
│   │   ├── envconfig.py        # 集中式环境变量配置（.env 加载 + 类型安全读取）
│   │   ├── database.py         # 数据库连接（SQLAlchemy引擎）
│   │   ├── torndb.py           # Tornado数据库封装
│   │   ├── trade_time.py       # 交易时间/日历工具 + API 数据结算时间判定
│   │   ├── query_cache.py      # 线程安全LRU查询缓存
│   │   ├── run_template.py     # 运行模板（支持日期参数解析）
│   │   ├── singleton_type.py   # 单例类型
│   │   ├── crypto_aes.py       # AES加密
│   │   └── version.py          # 版本信息（v4.0.0）
│   │
│   ├── fontWeb/                 # 🎨 Vue前端（新版）
│   │   ├── package.json        # 前端依赖
│   │   ├── vite.config.ts      # Vite配置
│   │   ├── tsconfig.json       # TypeScript配置
│   │   └── src/                # Vue源代码
│   │       ├── api/            # API接口
│   │       ├── views/          # 页面视图
│   │       ├── router/         # 路由配置
│   │       ├── stores/         # Pinia状态管理
│   │       └── types/          # TypeScript类型
│   │
│   ├── cache/                   # 💾 缓存目录
│   │   └── hist/               # 历史数据缓存
│   │
│   └── log/                     # 📝 日志目录
│       ├── stock_execute_job.log # 作业日志
│       ├── stock_web.log       # Web服务日志
│       └── stock_trade.log     # 交易服务日志
│
├── docker/
│   └── stock/                 # Docker 构建上下文（保留历史目录结构）
│
├── cron/                        # ⏲️ 定时任务配置
│   ├── cron.hourly/            # 每小时任务
│   ├── cron.workdayly/         # 每工作日任务
│   └── cron.monthly/           # 每月任务（含财务数据增量更新）
│
├── supervisor/                  # 🔧 进程管理
│   └── supervisord.conf        # Supervisor配置
│
├── document/                    # 📖 文档目录
│   ├── database_schema.md      # 数据库设计文档
│   ├── API_REFERENCE.md        # API接口参考文档
│   └── hist_cache_incremental.md # 增量缓存说明
│
└── img/                         # 🖼️ 截图资源
```

---

## 模块详解

### 1. 数据获取模块 (crawling/)

支持多数据源自动切换，确保数据可用性：

| 数据类型 | 优先数据源 | 备选数据源 | 说明 |
|---------|-----------|-----------|------|
| 股票实时行情 | 东方财富 | 腾讯财经 → 新浪财经 | 包含40+字段 |
| ETF实时行情 | 东方财富 | 腾讯财经 → 新浪财经 | 含规模、换手率等 |
| 历史K线 | 东方财富 | 腾讯财经 → 新浪财经 | 支持增量更新，3源自动容错 |
| 资金流向 | 东方财富 | 新浪财经 | 主力/散户资金 |
| 龙虎榜 | 东方财富 | 新浪财经 | 机构买卖数据 |
| 综合选股 | 东方财富 | 新浪财经 | 200+筛选条件 |
| 个股财务指标 | AKShare(东方财富) | — | 20项财务分析指标，月度更新 |

### 2. 技术指标模块 (indicator/)

基于TA-Lib实现的32种技术指标：

```
趋势指标: MACD, SMA, TRIX, DMA, TEMA, Supertrend, ENE
动量指标: KDJ, RSI, ROC, CCI, WR, MFI, STOCHRSI
波动指标: BOLL, ATR, VHF
成交量指标: OBV, VR, VWMA
其他指标: CR, DMI, SAR, PSY, BRAR, EMV, BIAS, PPO, WT, DPO, RVI, FI
```

### 3. K线形态识别 (pattern/)

精准识别61种K线形态，包括：

- **反转形态**: 锤头、吊颈线、倒锤头、射击之星、早晨之星、黄昏之星
- **持续形态**: 三白兵、三乌鸦、上升三法、下降三法
- **中性形态**: 十字星、纺锤、高浪线

### 4. 选股策略 (strategy/)

策略分为两类：**K线技术策略**（归类在前端"K线形态"菜单下）和**策略选股**（归类在前端"策略选股"菜单下）。

#### K线技术策略

| 策略名称 | 核心逻辑 |
|---------|---------|
| 放量上涨 | 成交量/5日均量≥2，涨幅<2% |
| 均线多头 | MA30持续上涨超20% |
| 停机坪 | 涨停后连续3日高开小涨 |
| 回踩年线 | 突破250日均线后回踩确认 |
| 突破平台 | 放量突破60日均线 |
| 无大幅回撤 | 60日内无大幅回撤稳健上涨 |

#### 策略选股

| 策略名称 | 核心逻辑 |
|---------|---------|
| 海龟交易 | 收盘价创60日新高 |
| 高而窄的旗形 | 24日内涨幅≥90%，连续两日涨停 |
| 放量跌停 | 跌>9.5%，量≥5日均量×4 |
| 低ATR成长 | 10日内振幅>10% |
| 趋势回调 | 优质公司长期趋势向上时的回调买入 |
| 超跌反弹 | 市场恐慌但基本面未变时超跌修复买入 |
| 突破确认 | 横盘整理后放量突破确认买入 |
| GPT综合选股 | 基本面策略：负债率<60%、ROE≥15%、毛利率≥30%等 |

### 5. Web服务 (web/)

基于Tornado的Web服务，端口9988，共 128 个 API 路由、18 个 Handler 模块：

| Handler 模块 | 路由数 | 功能 |
|-------------|--------|------|
| `dataTableHandler` | 2 | 股票数据表 + 交易日 |
| `dataIndicatorsHandler` | 2 | 指标图表 + 关注 |
| `strategyParamsHandler` | 6 | 策略参数 CRUD + 动态筛选 |
| `klineHandler` | 1 | K线数据 |
| `backtestHandler` | 3 | 回测配置/运行/批量 |
| `backtestDashboardHandler` | 5 | 回测看板（总览/序列/分布/配对） |
| `portfolioBacktestHandler` | 21 | 组合回测 + 策略管理 + 文件夹 + 模板同步 |
| `paperTradingHandler` | 9 | 模拟交易（创建/运行/信号/历史/代码） |
| `tradeSignalHandler` | 2 | 交易信号 |
| `notificationAdminHandler` | 2 | 通知事件查看 |
| `notificationConfigHandler` | 6 | 通知配置 CRUD |
| `aiDecisionConfigHandler` | 4 | AI 决策配置 |
| `aiAssistantHandler` | 12 | AI 助手（生成/优化/chat/Agent/会话/KB） |
| `imCommandHandler` | 7 | IM 指令系统（钉钉回调） |
| `liveTradingHandler` | 2 | 实盘交易 |
| `authHandler` | 9 | 鉴权/注册/用户管理/审计 |
| `customIndicatorHandler` | 7 | 自定义综合指标 CRUD + 回测 |
| `verifyOptimizeHandler` | 11 | 选股验证优化（对比/优化/样本外） |
| `verifyFusionHandler` | 6 | 策略融合（v2 五维 × 4 模式） |
| `factorLabHandler` | 8 | 因子实验室 |

### 6. 策略参数配置模块 (web/strategyParamsHandler.py)

支持三类可配置策略参数，存储在 `cn_strategy_params` 表中：

| 参数集 | 说明 |
|--------|------|
| `gpt_value` | GPT选股筛选条件（财务安全、盈利能力、成长能力、估值指标） |
| `moat_scoring` | 护城河评分模型权重和阈值 |
| `ai_model` | AI/LLM API配置（接口地址、密钥、模型、温度、token数） |

### 7. 基本面策略框架 (strategy/fundamental/)

提供完整的基本面投资策略框架：

| 模块 | 说明 |
|------|------|
| `fundamental_strategies.py` | 价值投资、成长投资、护城河、股息增长策略 |
| `fundamental_filter.py` | 基本面过滤器、护城河评分 |
| `moat_model.py` | 护城河类别、风险等级、定量指标模型 |
| `moat_ai_service.py` | AI护城河分析服务 |

### 8. 查询缓存 (lib/query_cache.py)

线程安全的LRU缓存，带TTL过期机制：

| 缓存实例 | 容量 | TTL | 用途 |
|----------|------|-----|------|
| `stock_data_cache` | 512条 | 5分钟 | Web数据页面查询缓存 |
| `filter_result_cache` | 128条 | 10分钟 | 策略筛选结果缓存 |

### 9. 组合回测引擎 (core/backtest/)

聚宽(JoinQuant)风格的事件驱动组合回测引擎，支持多股票持仓、T+1交易和完整风险指标。

#### 架构总览

```
策略代码(Python字符串)
    ↓   compile_strategy()
安全沙箱 (strategy_sandbox.py)
    ↓   提取 initialize / handle_data / run_daily / run_weekly
回测引擎 (portfolio_engine.py)
    ↓   逐交易日驱动
    ├── 基本面数据 (fundamentals.py)  — 真实财务数据(cn_stock_financial) + 合成兜底
    ├── K线数据 (data_feed.py)        — 缓存 + DB补全 + EastMoney API
    ├── 策略上下文 (strategy_context.py) — Portfolio/Position/T+1
    └── 风险指标 (risk_metrics.py)     — 25项量化指标

模拟交易引擎 (paper_engine.py)
    │   每日定时驱动
    ├── 基本面数据: cn_stock_selection（70+列真实数据） — 与 GPT选股同源
    ├── K线行情: pickle缓存 → cn_stock_spot DB → EastMoney API
    ├── 策略沙箱 (strategy_sandbox.py) — 安全编译用户策略
    └── 状态管理 (state_manager.py)    — 持仓/现金/NAV 持久化
```

#### 支持的聚宽API

| API | 说明 |
|-----|------|
| `order(code, amount)` | 按股数下单 |
| `order_target(code, amount)` | 调整到目标持仓 |
| `order_value(code, value)` | 按金额下单 |
| `order_target_value(code, value)` | 调整到目标金额 |
| `order_target_percent(code, percent)` | 按目标仓位百分比调仓 |
| `history(code, count, field)` | 获取历史数据 |
| `get_price(code, start, end)` | 获取区间数据 |
| `set_benchmark(code)` | 设定基准指数 |
| `set_order_cost(OrderCost(...))` | 设定交易成本 |
| `run_daily(func, time)` | 注册日级回调 |
| `run_weekly(func, weekday, time)` | 注册周级回调 |
| `get_index_stocks(index_code)` | 获取指数成份股 |
| `get_fundamentals(query)` | 基本面数据查询 |
| `get_current_data()` | 当前数据（停牌检测） |
| `query(valuation.code, ...)` | 构建查询对象 |
| `valuation.market_cap` / `.pb_ratio` | 估值字段 |
| `valuation.code.in_(list)` | 代码过滤 |
| `record(**kwargs)` | 记录自定义指标 |
| `log.info(msg)` | 策略日志 |

#### 内置策略模板

| ID | 策略名称 | 说明 |
|----|---------|------|
| `small_cap` | 小市值策略 | 每月选市值最小的5只等权买入 |
| `dual_ma` | 双均线策略 | MA5/MA20 金叉死叉信号 |
| `bank_rotation` | 银行股轮动(聚宽) | PB最低银行股每周轮动 |
| `equal_weight` | 多股票等权 | 等分配置定期再平衡 |
| `momentum` | 动量策略 | 20日涨幅最大的股票 |
| `small_cap_jq` | 小市值策略(聚宽) | 20-30亿市值最小3只5日轮动 |

#### 基本面数据源（三级降级）

1. **数据库** `cn_stock_spot` — 最快，含PB(pbnewmrq)
2. **push2his API** — 东方财富实时数据(f12/f14/f2/f20/f23)，代理加速
3. **stock_zh_a_spot_em** — AkShare全市场API，备用

#### 财务数据源（回测 fundamentals.py）

回测引擎中 `get_fundamentals()` 查询 indicator/balance/cash_flow 字段时，优先从 `cn_stock_financial` 表读取真实财务数据（EPS、ROE、营收增长等20项指标），无数据时自动降级为确定性合成数据（基于股票代码+字段+季度的哈希值）。

财务数据由 `stock_financial_data.py` 通过 AKShare `stock_financial_analysis_indicator_em` 接口获取，月度增量更新。

#### 财务数据源（模拟交易 paper_engine.py）

模拟交易引擎的 `get_fundamentals()` **不使用合成数据**，直接查询 `cn_stock_selection` 表，该表由每日定时任务从东方财富选股器 API 获取，包含 70+ 列真实基本面数据：

| 聚宽字段 | cn_stock_selection 列 | 说明 |
|---------|----------------------|------|
| market_cap | total_market_cap / 1e8 | 总市值（亿元） |
| pe_ratio | pe9 | 市盈率 TTM |
| pb_ratio | pbnewmrq | 市净率 MRQ |
| roe | roe_weight | 净资产收益率 |
| eps | basic_eps | 每股收益 |
| gross_profit_margin | sale_gpr | 毛利率 |
| net_profit_margin | sale_npr | 净利率 |

核心原则：模拟交易中除账户金额是虚拟的外，所有数据均为实盘数据。

#### 数据缓存策略

- **K线缓存**: `cache/hist/{code}.gzip.pickle`，按股票代码独立文件
- **基本面缓存**: `cache/fundamental/fundamental_v3.pickle`，7天过期自动刷新
- **延迟加载**: `_ensure_stocks_loaded()` 自动加载策略引用的非候选股票并持久化缓存
- **缓存扩展**: 延迟加载的额外股票自动追加到基本面缓存，避免重复API请求

#### 线程安全

- **Web层**: `RunPortfolioBacktestHandler` 使用 `run_in_executor` + `ThreadPoolExecutor(max_workers=2)` 在线程池中运行回测，不阻塞Tornado IOLoop
- **代理池**: `singleton_proxy` 使用 `RLock` 保护所有共享状态
- **HTTP会话**: `eastmoney_fetcher` 使用 `threading.local()` 为每个线程提供独立的 requests.Session
- **K线缓存文件**: 每只股票独立文件，多线程并行写入无冲突

### 10. 自定义综合指标 (core/composite/)

Phase 9 多维因子打分系统，支持用户自定义选股指标：

| 模块 | 功能 |
|------|------|
| `composite_engine.py` | 主打分引擎（多因子加权聚合） |
| `normalizers.py` | 6 种归一化器（n_lin/n_wr/n_rank/n_supertrend/n_pctb/n_cci） |
| `hard_rules_engine.py` | AST 沙箱硬规则表达式（安全求值，阻止危险代码） |
| `risk_simulator.py` | 风险模拟器（止损/止盈/最大持有天数 + 基本面退出） |
| `dynamic_universe.py` | 动态股票池过滤（开盘前刷新候选） |
| `builtins.py` | 内置指标预设模板 |
| `indicators_enrich.py` | 指标数据丰富管道 |

### 11. 选股验证中心 (web/verify*)

提供策略验证、优化和研究工具：

| Handler | 路由数 | 功能 |
|---------|--------|------|
| `verifyOptimizeHandler` | 11 | 策略对比、买卖点优化、样本外验证 |
| `verifyFusionHandler` | 6 | 策略融合 v2（tech/fund/flow/sent/custom × weighted/vote/tree/rotation） |
| `factorLabHandler` | 8 | 因子实验室（IC/IR 分析、因子有效性验证） |

策略融合 v2 支持五维信号源 × 四种融合模式，内含 Shapley 值归因分析。

### 12. AI 策略助手 (ai_decision/)

多 Provider LLM 集成，支持策略生成、优化、修复和对话：

| 模块 | 功能 |
|------|------|
| `service.py` | AI 服务主入口（策略生成/优化/修复） |
| `config.py` | 多 Provider 配置（OpenAI-compatible） |
| `context_builder.py` | 上下文组装（市场数据 + 策略代码 + 错误信息） |
| `prompt_renderer.py` | Prompt 模板渲染 |
| `schema.py` | 请求/响应数据模型 |
| `providers/openai_compatible.py` | OpenAI 兼容 Provider |

配套知识库：`quantia/lib/ai/retrieval/indexer.py` 将策略模板、文档、用户策略写入 `cn_stock_ai_kb`（MySQL FULLTEXT），供检索增强。

### 13. 通知与 IM (notification/ + im/)

| 模块 | 功能 |
|------|------|
| `notification/service.py` | 通知分发服务（事件驱动） |
| `notification/templates.py` | 消息模板（模拟交易信号、系统告警） |
| `notification/channels/dingtalk.py` | 钉钉机器人 Webhook 通道 |
| `im/service.py` | IM 指令处理（钉钉回调 → 确认/拒绝交易信号） |
| `im/signature.py` | Webhook 签名验证 |

### 14. 用户鉴权 (auth/)

| 模块 | 功能 |
|------|------|
| `decorators.py` | `@require_login`、`@require_role` 装饰器 |
| `email_code.py` | 注册邮箱验证码 |
| `users.py` | 用户 CRUD、角色管理 |

支持开关控制：`QUANTIA_AUTH_ENABLED=true` 时全局鉴权生效，否则匿名访问。

### 15. 模拟交易 (paper_trading/)

| 模块 | 功能 |
|------|------|
| `paper_engine.py` | 模拟交易执行引擎（每日定时驱动，真实行情数据） |
| `scheduler.py` | 执行调度器 |
| `state_manager.py` | 持仓/现金/NAV 状态持久化 |

核心原则：除账户资金为虚拟外，所有行情、基本面数据均为实盘数据。
每日 NAV 写入 `cn_stock_paper_nav`，为权威净值曲线数据源。

---

## 安装部署

### 方式一：常规安装

#### 1. 环境要求

- Python 3.11+
- MySQL 8.0+
- TA-Lib C/C++库

#### 2. 安装步骤

```bash
# 克隆项目
git clone https://github.com/posbright/Quantia.git
cd Quantia

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 配置数据库 (复制 .env.example 为 .env)
QUANTIA_DB_HOST=localhost
QUANTIA_DB_USER=root
QUANTIA_DB_PASSWORD=your_password
QUANTIA_DB_DATABASE=quantiadb
```

#### 3. 启动服务

```bash
# Windows
cd quantia\bin
run_web.bat      # 启动Web服务
run_job.bat      # 运行数据作业

# Linux/Mac
cd quantia/bin
./run_web.sh     # 启动Web服务
./run_job.sh     # 运行数据作业
```

### 方式二：Docker部署

```bash
cd docker

# 使用本地数据库
docker-compose up -d

# 使用远程数据库
docker-compose -f docker-compose.remote-db.yml up -d
```

Docker 部署文件保留在 `docker/` 目录，详细部署文档待补充。

---

## 使用指南

### 1. 运行数据作业

系统采用 **5阶段流水线架构**，轻量任务优先执行，重量级操作放后：

| 阶段 | 说明 | 脚本 |
|------|------|------|
| Phase 0 | 初始化数据库 | `init_job.py` |
| Phase 1 | 轻量级数据入库（行情+选股+资金流向+GPT+收盘后） | `basic_data_daily_job.py` + `selection_data_daily_job.py` + `basic_data_other_daily_job.py` + `gpt_value_data_job.py` + `basic_data_after_close_daily_job.py` |
| Phase 2 | K线缓存批量更新（内存密集型，放在轻量任务之后） | `fetch_data_job.py` |
| Phase 3 | 数据分析（纯计算，无API调用） | `streaming_analysis_job.py`（整合指标+K线+策略，单次遍历） |
| Phase 4 | 回测与收尾 | `backtest_data_daily_job.py` + 数据健康检查 |

```bash
cd quantia/job

# 整体作业（包含所有数据处理，自动执行5个阶段）
python execute_daily_job.py

# 指定日期
python execute_daily_job.py 2024-01-15

# 日期范围
python execute_daily_job.py 2024-01-01 2024-01-31

# 多个日期
python execute_daily_job.py 2024-01-01,2024-01-15,2024-01-31
```

### 2. 单独运行模块

```bash
# ── 推荐：拆分运行（数据获取 + 数据分析分离） ──
# 数据获取管道（轻量API调用 + K线缓存更新，K线放最后以防OOM）
python fetch_daily_job.py

# 数据分析管道（GPT + 流式分析 + 回测，零API调用）
python analysis_daily_job.py

# ── 细粒度运行 ──
# 数据获取（实时行情 + 历史K线 + 缓存清理）
python fetch_data_job.py

# 基础数据（实时行情入库）
python basic_data_daily_job.py

# 综合选股数据
python selection_data_daily_job.py

# GPT综合选股（从DB读取cn_stock_selection，零API）
python gpt_value_data_job.py

# 流式分析（指标+K线+策略，零API，读缓存+写DB）
# 注：替代了旧版 indicators/klinepattern/strategy 三个独立作业
python streaming_analysis_job.py

# 回测数据
python backtest_data_daily_job.py

# ── 财务数据（月度运行，AKShare东方财富） ──
# 全量获取所有A股历史财务数据（首次运行，耗时较长）
python -m quantia.job.stock_financial_data

# 仅获取最近N年数据（推荐首次使用，减少耗时）
python -m quantia.job.stock_financial_data --years 5

# 增量更新（仅获取已入库股票的新报告期，月度定时任务使用）
python -m quantia.job.stock_financial_data --incremental

# 测试模式（仅获取前N只股票，用于验证）
python -m quantia.job.stock_financial_data --test 5

# 组合使用（测试模式 + 年份过滤）
python -m quantia.job.stock_financial_data --test 10 --years 3

# ── 旧版独立作业（仍可运行但内存较高，~1.6GB） ──
python indicators_data_daily_job.py
python klinepattern_data_daily_job.py
python strategy_data_daily_job.py
```

### 3. 手动拉取历史数据

当需要手动拉取或更新历史K线数据时，有以下几种方式：

#### 方式一：使用 fetch_data_job.py（推荐）

```bash
cd quantia/job

# 拉取当前交易日的最新数据（增量更新，自动补缺）
python fetch_data_job.py

# 指定日期拉取
python fetch_data_job.py 2024-06-15
```

该脚本会自动执行：
1. 清理过期/退市/除权缓存
2. 预加载全部股票的实时行情数据
3. 预加载全部股票的历史K线数据（首次全量获取，后续增量更新，支持 Spot 快速追加优化）
4. 更新指数K线缓存（~15个主要指数，增量模式）

#### 方式二：使用 Python 脚本自定义获取

```python
import datetime
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import quantia.core.stockfetch as stf

# 获取单只股票历史K线（默认10年历史）
data_base = (datetime.datetime.now(), '000001')
df = stf.fetch_stock_hist(data_base)
print(f"获取到 {len(df)} 条记录") if df is not None else print("获取失败")

# 自定义年数（如获取5年历史）
df = stf.fetch_stock_hist(data_base, years=5)

# 指定日期范围
df = stf.fetch_stock_hist(data_base, date_start='20230101', date_end='20231231')

# 不使用缓存，强制从API获取最新数据
df = stf.fetch_stock_hist(data_base, is_cache=False)

# 清理过期缓存（退市股票、除权除息数据）
cleaned = stf.clean_expired_cache()
print(f"清理了 {cleaned} 个缓存文件")
```

#### 方式三：通过环境变量调整默认获取年数

```bash
# 设置获取的历史数据年数（默认10年，Docker默认3年）
# Windows:
set HIST_DATA_DEFAULT_YEARS=10
python fetch_data_job.py

# Linux/Mac:
export HIST_DATA_DEFAULT_YEARS=10
python fetch_data_job.py
```

#### 方式四：强制重建全部缓存

如果缓存数据出现问题，可以清空缓存目录后重新获取：

```bash
# ⚠️ 注意：此操作会删除所有历史数据缓存，重新获取耗时较长
# Windows:
rd /s /q quantia\cache\hist
# Linux/Mac:
rm -rf quantia/cache/hist

# 然后重新拉取数据
cd quantia/job
python fetch_data_job.py
```

> **增量更新说明**：系统采用增量缓存机制，首次运行需从API获取全部历史数据（耗时较长），
> 后续运行只需补缺新增交易日数据（快速完成）。数据源优先级：东方财富 → 腾讯财经 → 新浪财经，
> 自动容错切换。详见 [历史数据缓存说明](document/hist_cache_incremental.md)。

### 4. 访问Web界面

启动Web服务后访问: http://localhost:9988

### 5. 自动交易

```bash
cd quantia/bin
run_trade.bat  # Windows

# 配置交易账户
# 编辑 quantia/config/trade_client.json
```

⚠️ **警告**: 交易日10:00会自动打新，不需要请删除相关策略。

---

## 配置说明

### 数据库配置

复制 `.env.example` 为 `.env`，并填写数据库连接:

```env
QUANTIA_DB_HOST=localhost
QUANTIA_DB_USER=root
QUANTIA_DB_PASSWORD=password
QUANTIA_DB_DATABASE=quantiadb
QUANTIA_DB_PORT=3306
```

或使用环境变量（Docker推荐）:

```bash
export QUANTIA_DB_HOST=localhost
export QUANTIA_DB_PASSWORD=your_password
```

### 代理配置

编辑 `quantia/config/proxy.txt`:

```
# 格式: ip:port 或 username:password@ip:port
127.0.0.1:7890
user:pass@192.168.1.100:8080
```

### 数据源配置

编辑 `quantia/core/stockfetch.py`:

```python
DATA_SOURCE_MAX_RETRIES = 2      # 最大重试次数
DATA_SOURCE_RETRY_INTERVAL = 90  # 基础重试间隔(秒)，实际使用指数退避（Docker默认30秒）
HIST_DATA_DEFAULT_YEARS = 10     # 默认获取历史数据年数（Docker默认3年）
# 注：缓存清理由 clean_expired_cache() 智能管理
```

### 历史数据获取配置

通过环境变量控制历史数据获取年数：

```bash
# Windows:
set HIST_DATA_DEFAULT_YEARS=10
# Linux/Mac:
export HIST_DATA_DEFAULT_YEARS=10
# Docker:
docker run -e HIST_DATA_DEFAULT_YEARS=5 ...
```

---

## API接口

### 获取股票数据

```
GET /quantia/api_data?table_name=cn_stock_spot&date=2024-01-15
```

### 获取指标图表

```
GET /quantia/data/indicators?code=000001&date=2024-01-15
```

### 管理关注

```
POST /quantia/control/attention
Body: {"code": "000001", "action": "add"}
```

---

## 扩展开发

### 添加新数据源

1. 在 `quantia/core/crawling/` 创建新模块
2. 在 `stockfetch.py` 中添加导入和调用逻辑
3. 遵循现有数据源的返回格式

### 添加新策略

1. 在 `quantia/core/strategy/` 创建策略文件
2. 实现策略函数（参考 `enter.py` 模板）
3. 在 `tablestructure.py` 注册策略

### 添加新指标

1. 在 `calculate_indicator.py` 添加指标计算
2. 在 `tablestructure.py` 添加字段定义
3. 更新 `indicator_web_dic.py` 用于Web显示

---

## 日志文件

| 文件 | 位置 | 说明 |
|-----|------|-----|
| stock_execute_job.log | quantia/log/ | 数据作业日志 |
| stock_web.log | quantia/log/ | Web服务日志 |
| stock_trade.log | quantia/log/ | 交易服务日志 |

---

## 技术栈

| 类别 | 技术 |
|-----|------|
| 后端框架 | Python 3.11+, Tornado |
| 数据库 | MySQL 8.0+, SQLAlchemy, PyMySQL |
| 数据处理 | Pandas, NumPy, TA-Lib |
| 前端(新) | Vue 3, TypeScript, Vite, Element Plus |
| 前端(旧) | Bootstrap, jQuery, DataTables |
| 可视化 | Bokeh, ECharts |
| 加密 | PyCryptodome (AES) |
| 交易 | easytrader, backtrader |
| 部署 | Docker, Supervisor |

---

## 许可证

本项目采用开源许可证，详见 [LICENSE](LICENSE) 文件。

---

## 安全注意事项

### 数据库凭据

`quantia/lib/envconfig.py` 统一加载项目根目录的 `.env` 文件，所有模块通过该模块读取配置。生产环境**务必**通过环境变量（Docker `-e` 或 `.env` 文件）配置，避免在源码中暴露凭据：

```bash
# 方式一：系统环境变量（优先级最高）
export QUANTIA_DB_HOST=your_host
export QUANTIA_DB_USER=your_user
export QUANTIA_DB_PASSWORD=your_password
export QUANTIA_DB_DATABASE=quantiadb

# 方式二：.env 文件（复制 .env.example 为 .env 并修改）
cp .env.example .env
```

完整的可配置变量及默认值见 `.env.example`。配置优先级：系统环境变量 > `.env` 文件 > 代码默认值。

### SQL 参数化

所有数据写入操作已使用参数化查询（`%s` 占位符），防止 SQL 注入。新增数据操作时请遵循此模式：

```python
# ✅ 正确：参数化查询
mdb.executeSql("DELETE FROM `table` WHERE `date` = %s", (date,))

# ❌ 错误：f-string 拼接
mdb.executeSql(f"DELETE FROM `table` WHERE `date` = '{date}'")
```

### Web 服务

- SPAHandler 已增加路径遍历防护（`os.path.realpath` 校验）
- Web 服务默认绑定所有网卡（`0.0.0.0:9988`），生产环境建议配置反向代理（Nginx）限制访问

---

## 致谢

感谢所有贡献者和开源社区的支持！

如有问题，请提交 Issue 或 Pull Request。
