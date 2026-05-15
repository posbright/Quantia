---
description: "Use when editing Tornado web handlers (quantia/web/*Handler.py) or analysis jobs (quantia/job/*analysis*.py, indicators_*, strategy_*). Enforces fetch/analysis/web pipeline separation, correct table-structure imports, index-code routing, and dynamic-universe lazy K-line loading."
applyTo: "quantia/web/**/*Handler.py, quantia/job/**/*analysis*.py, quantia/job/**/indicators_*.py, quantia/job/**/strategy_*.py, quantia/job/**/backtest_*.py, quantia/core/backtest/**/*.py"
---
# 后端 Handler / 分析作业规范

## 数据管道隔离（最高优先级）
- **绝对禁止** 在 `quantia/web/*Handler.py` 与分析类作业中调用任何外部 API。
  - 不允许出现：`requests.get/post`、`akshare.*`、`urllib.request`、`httpx`、`aiohttp`，以及 `quantia.core.crawling.*`、`quantia.core.eastmoney_fetcher` 的直接调用。
  - 数据来源只能是 MySQL（通过 `quantia/lib/database.py`）+ `cache/hist/` 本地缓存。
- 仅以下路径允许调用外部 API：`quantia/job/fetch_*.py`、`quantia/core/stockfetch.py`、`quantia/core/crawling/`、`quantia/core/eastmoney_fetcher.py`。

## 表元数据导入
- 股票/ETF/指标表元数据**必须**从 [quantia/core/tablestructure.py](../../quantia/core/tablestructure.py) 导入。
- **不要**从 `quantia.lib.tablestructure` 导入股票元数据——那不是真源（历史踩坑）。

## 指数代码路由
- `000300`、`399xxx`、`000905`、`000852` 等指数代码在回测/数据加载中必须走 `load_benchmark_data`，**不能**走 `load_stock_data`。
- 错误路由会让 EastMoney 请求 `secid=0.000300` 直接返回 HTTP 500。

## 指数缓存写入
- `cache/hist/index/{code}.gzip.pickle` 保存的是**全量历史**。
- 修改 `quantia/core/backtest/data_feed.py::_save_index_cache` 时必须保持「合并 + drop_duplicates(date, keep='last')」语义。
- **不要**用 `df.to_pickle(cache_file)` 直接覆盖——会把全量缓存截断为本次回测窗口（历史 bug：000300 被压缩到 720 行）。

## 动态选股策略（基本面/综合指标）
- 候选池在 preload 之后才确定，回测/模拟盘的 `history`、`attribute_history` 路径必须做：
  1. **懒加载** K 线（首次访问时才拉缓存/DB）；
  2. 时间戳归一化为日级（`pd.Timestamp(date).normalize()`），否则订单价定位会错位。

## 模拟盘展示真源
- 当前总资产/现金/收益的真源是 `cn_stock_paper_nav` 的最新行；
- `cn_stock_paper_trading.current_value/current_cash` 可能滞后，**不要**直接用于展示。
- 全周期指标/曲线的基线用 `initial_cash`，**不要**用第一条 NAV。

## 内存与流式处理
- 单次处理 4900+ 股票时使用流式迭代（参考 [quantia/job/streaming_analysis_job.py](../../quantia/job/streaming_analysis_job.py)），峰值内存 < 100 MB。
- **不要**在 handler / job 里把全量 DataFrame 一次性 materialize。

## 修改后必须做的事
- Tornado `web_service.py` 是常驻进程并缓存模块，后端任何 Python 改动后必须重启：本地 [quantia/bin/run_web.bat](../../quantia/bin/run_web.bat)，远程 `/root/Quantia/quantia/bin/restart_web.sh`。
