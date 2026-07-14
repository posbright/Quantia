# Kronos 滚动验证、批量预测与动态调优方案

> 审查日期：2026-07-13
> 适用范围：Quantia 日线预测、Kronos-base、本地推理服务、可选 C1 收益评分层
> 文档状态：实施规格；Phase 1 最小闭环已落地并完成真实烟测，Phase 2 控制面 MVP 实施中，Phase 2 数据闭环与 Phase 3～4 尚未上线

## 1. 分析结论

### 1.1 可行性结论

以下能力均可以实现，而且现有代码已经具备主要基础：

1. Kronos 已有 `KronosPredictor.predict_batch()`，可以对等长历史窗口、相同预测步数的多个标的执行批量推理。
2. Quantia 已有股票历史缓存、交易日历、工作日 Cron 和统一数据库写入封装，可以负责股票池、调度和持久化。
3. Kronos 已有单次验证/测试入口及 C1 的 IC、RankIC、Hit 指标，可以扩展为多锚点 walk-forward 验证。
4. 每次预测只要保存数据截止日、目标交易日、模型版本和配置哈希，等真实 K 线到齐后即可自动对齐并评估。
5. 可以根据滚动结果搜索参数，但不应让线上程序根据单日结果立即修改生产参数。推荐采用“候选生成 -> 离线滚动验证 -> 影子预测 -> 冠军/挑战者晋级”的受控闭环。

### 1.2 当前缺口

现有 `finetune_csv/run_validate.py` 和 `pipeline/eval_runner.py` 主要计算 tokenizer 重建 MSE 与 predictor loss。这些指标适合检查模型是否退化，但不能直接回答以下业务问题：

- 第 1、3、5、10、15、30 个交易日的收盘价误差是多少；
- 涨跌方向是否正确；
- C1 的截面排序是否有效；
- 不同市场状态下哪个 lookback 更稳定；
- 线上真实预测是否优于当前生产版本或简单基线。

因此后续必须增加“历史锚点生成式回放”和“线上到期结果评估”，不能只复用训练 loss 作为准确率。

### 1.3 推荐默认值不等于永久最优值

当前生产候选仍建议：

| 参数 | 默认值 | 后续候选空间 |
| --- | ---: | --- |
| `max_context` | 512 | 固定，Kronos-base 上限 |
| `lookback` | 256 | 90、128、256、384、512 |
| `max_pred_days` | 30 | 分别评估 1、3、5、10、15、30 日 |
| `sample_count` | 1 | 确定性主模型为 1；概率实验为 5、10 |
| `temperature` | 1.0 | 确定性模式固定；概率实验 0.7、0.9、1.0 |
| `top_k` | 1 | 确定性生产固定为 1 |
| `top_p` | 1.0 | 概率实验 0.85、0.9、0.95、1.0 |
| `clip` | 5.0 | 通常固定，仅在独立实验中搜索 |

预测周期不是一个可以混合比较的单一超参数。1 日和 30 日是不同任务，必须分别报告指标和选择配置。**当前 Quantia 生产语义是对 `days=1/3/5/10/15/30` 分别请求**；Kronos 自回归结果会随 `pred_len` 改变，真实验证已确认独立 5 日请求的第 5 步不等于 30 日请求的第 5 步。因此生产等价评测必须对每个 horizon 独立调用，不能用一条 30 日路径代替六次线上请求。若未来另建“固定 30 日路径模式”，只能作为不同的实验契约，必须使用独立 `mode/config_hash`，不得与当前线上指标混合。

服务代码保留 `max_pred_days<=120` 作为隔离的研究硬上限，但 Quantia 对外配置和当前评测白名单仍固定在 30 日以内。任何 30 日以上实验必须使用不同 `run_type/config_hash`，不得进入生产指标或晋级判断。

### 1.4 2026-07-13 深度审查后的实施修正

本轮结合实际数据库、缓存、HTTP 服务和真实模型运行确认并修复了以下问题：

1. `cn_stock_spot` 主键实际为 `(date, code)`，按单股日期区间查询不能使用 `code` 前缀索引。当前按需预测只允许在缓存后 **30 个自然日**内续接 DB 尾段，避免长期缺口股票反复扫描大表；全市场批量必须改用按日期批量读取/内存分发，不能逐股查询。
2. 文件缓存是 `qfq`，DB 快照是原始行情。续接前必须校验首行 `pre_close_price` 与缓存末收盘、后续行与前一收盘连续；除权除息导致价格基准不连续时拒绝拼接并等待缓存重建，不能制造虚假跳空。
3. Kronos 原 `model_version` 只覆盖 predictor，无法识别 tokenizer 变化。服务现已分别返回 `predictor_version`、`tokenizer_version`，并用二者生成组合 `model_version`。
4. lookback 原为进程级固定值，无法在同一服务上执行候选搜索。服务现支持请求级 `lookback`，并严格限制在 `32..max_context`。
5. Phase 1 CLI 首版若读取整张未来交易日历，会让数据加载器收到远未来截止日并误判已到期结果为 `not_traded`。现已将实际边界固定为 `min(MAX(cn_stock_spot.date), 最后完整交易日)`，也可用 `--actual-end` 固定可复现快照。

## 2. 总体架构与职责

```mermaid
flowchart LR
    A[Quantia 行情抓取] --> B[历史缓存与交易日历]
    B --> C[批量预测任务]
    C --> D[Kronos 本地批量推理]
    D --> E[预测结果表]
    A --> F[真实 K 线]
    E --> G[到期评估任务]
    F --> G
    G --> H[滚动指标与漂移检测]
    H --> I[候选参数搜索]
    I --> J[Walk-forward 验证]
    J --> K[影子预测]
    K --> L{晋级门禁}
    L -->|通过| M[更新生产配置版本]
    L -->|不通过| N[保留当前冠军]
```

职责边界：

- **Quantia**：选择股票池、读取缓存、生成交易日期、调度、任务状态、MySQL 持久化、真实值对齐、告警。
- **Kronos 服务**：加载一次模型，执行单只/批量推理，返回预测值、耗时和模型元数据。
- **C1**：只作为独立的 5 日截面收益评分层；当前质量门禁未通过，继续保持默认关闭。
- **Web Handler**：只读缓存/数据库并调用本地模型服务，不直接访问外部行情源。

Kronos 不直接连接 Quantia 生产数据库。这样可以保持两个 Python 环境隔离，也便于模型服务独立部署在 GPU 节点或纯 CPU 的 Linux 节点上（CPU-only 容量测算与降级策略见第 9 章）。

## 3. 滚动验证设计

### 3.1 两类验证必须分开

#### A. 冻结模型的推理参数验证

不重新训练 Kronos 权重，只在多个历史锚点上改变 `lookback`、采样参数和预测周期。这是当前最应先落地、成本最低的一层。

对每个锚点 $t$：

1. 输入只能使用日期 $\le t$ 的已完成日线；
2. 生成 $t$ 后第 1 到 $H$ 个交易日的预测；
3. 与真实 $t+1,\ldots,t+H$ 对齐；
4. 保存逐股票、逐步长指标；
5. 将锚点向前滚动 5 个交易日后重复。

#### B. 训练型 walk-forward

适用于 C1 重训或 Kronos 微调。每个锚点必须重新构建当时可见的数据集：

```text
train ----------------| embargo | validation | embargo | test
                      H days                  H days
```

`embargo` 至少等于标签周期 $H$。例如 C1 使用未来 5 日收益标签，则训练集最后 5 个交易日不能进入训练标签，防止标签跨越验证边界。

推荐节奏：

- 冻结模型推理参数：每周运行；
- C1 重训候选：每月运行；
- Kronos tokenizer/base 微调：季度或确认结构性漂移后运行，不应按日重训。

### 3.2 锚点与样本范围

第一阶段建议：

| 项目 | 建议 |
| --- | --- |
| 回放区间 | 至少最近 2 年，覆盖上涨、下跌、震荡阶段 |
| 锚点步长 | 5 个交易日 |
| 股票池 | 先固定 100～300 只有充足历史的股票，再扩全市场 |
| 最少历史 | `lookback + 20` 个有效交易日 |
| 预测周期 | 1、3、5、10、15、30 分开评估 |
| 评估聚合 | 按日期、股票、行业、波动率分组、市场状态分别聚合 |

股票池必须在锚点时刻可知。不能使用今天的成分股列表回测多年前的市场，否则会产生幸存者偏差。第一阶段若没有历史成分股快照，应明确标注为“固定现存股票池技术验证”，不能作为无偏收益结论。

当前 Quantia 可用于两年回放的主要事实源是 `cache/hist/**/**qfq.gzip.pickle`；`cn_stock_spot` 实库当前只覆盖约 99 个交易日，不能单独承担两年回放。缓存是随时间重算的 qfq 快照，并非逐日冻结的数据版本，因此 Phase 1 MVP 只能用于技术/参数比较，不能宣称完全消除了复权因子和数据修订带来的时点偏差。要形成无偏生产证据，后续必须保存不可变 `data_snapshot_id`（至少包含文件哈希、复权方式和生成时间），或建设按交易日版本化的行情事实表。

### 3.3 指标体系

#### K 线数值指标

相对最后真实收盘价 $C_t$ 计算未来第 $h$ 步收益：

$$
\hat r_{t,h}=\frac{\hat C_{t+h}}{C_t}-1,\qquad
r_{t,h}=\frac{C_{t+h}}{C_t}-1
$$

推荐指标：

- Close MAE / RMSE；
- Close sMAPE，避免普通 MAPE 的非对称问题；
- 归一化误差：$|\hat C-C|/ATR_{20}$；
- 收益方向准确率：$\mathbb{1}[\operatorname{sign}(\hat r)=\operatorname{sign}(r)]$；
- 涨跌幅误差：$|\hat r-r|$；
- OHLC 合法率：`low <= open/close <= high`；
- 若启用多样本采样：分位区间覆盖率与区间宽度。

不能把 `pred_close > pred_open` 当成唯一方向指标。业务预测方向应相对锚点真实收盘价 $C_t$，否则隔夜缺口会使定义偏离实际持有收益。

#### C1 截面指标

- Pearson IC；
- Spearman RankIC；
- Hit rate；
- Top/Bottom decile spread；
- 分组单调性；
- 加入手续费、滑点和涨跌停约束后的组合收益、最大回撤和换手率。

C1 标签固定为未来 5 日收益，只能与 5 日结果比较。

#### 基线

每项结果必须同时报告以下基线：

1. Random walk：未来收盘价等于 $C_t$；
2. 最近收益延续或移动平均基线；
3. 当前线上冠军配置；
4. C1 对比零分/行业中性简单排序。

只有“统计上稳定优于冠军和简单基线”才有晋级意义，单看方向准确率超过 50% 不够。

### 3.4 聚合与统计显著性

禁止把同一股票相邻锚点的高度重叠预测当作独立样本直接计算普通置信区间。建议按交易日做 block bootstrap，或按非重叠持有周期采样。

最少门禁建议：

- 至少 60 个到期交易日；
- 至少 100 只有效股票；
- 真实值覆盖率不低于 95%；
- 对冠军的核心指标改善在 block bootstrap 95% 置信区间下不劣；
- 至少三个市场状态中不存在显著崩溃；
- 延迟、显存和失败率满足运行预算。

`55%` 方向准确率只能作为早期观察线，不应硬编码成通用生产真理。

## 4. 批量预测设计

### 4.1 执行时点

日线批量任务应加入现有 `cron.workdayly/run_workdayly` 串行编排，放在 `run_kline_cache` 成功之后；18:30 只能作为启动时间，不能替代上游成功门禁：

1. 验证当天是交易日且已经结算；
2. 验证缓存最后日期等于当天；
3. 以当天为 `as_of_data_date`；
4. 从下一交易日开始生成未来 1～30 日预测，并按标准 horizon 保存/评测。

盘中按需预测仍遵循现有规则：中午只使用上一完整交易日，并从今天开始预测。盘中结果和结算后批量结果必须使用不同 `batch_id` 和 `as_of_data_date`，不能互相覆盖。

### 4.2 批处理方式

`KronosPredictor.predict_batch()` 要求同一批次的所有序列具有相同 `lookback` 和 `pred_len`。推荐流程（GPU、CPU 通用）：

1. 按 `model_version + config_hash + lookback + pred_len` 分桶；
2. 过滤历史不足、停牌或数据过期的标的；
3. 每桶按硬件资源预算（GPU 显存或 CPU 内存/线程数）切成 micro-batch；micro-batch 大小必须先在目标机型实测，不能沿用开发机数值；
4. 同一模型进程串行执行各 micro-batch；
5. 每个 micro-batch 完成后立即持久化并更新 checkpoint；
6. 失败标的记录错误类型，重试时只处理失败项。

不要用 `ThreadPoolExecutor` 或多进程并发调用同一个模型实例来"加速"。GPU 场景优先使用 `predict_batch` 做张量级并行；CPU 场景 PyTorch 已经在算子内部用多线程做 BLAS 并行，叠加 Python 线程池或额外进程会造成核心争抢，通常更慢而不是更快。CPU-only 部署的容量测算、线程配置和降级策略见第 9 章。

### 4.3 幂等与恢复

每个批次生成 UUID `batch_id`。任务状态：

```text
created -> running -> partial/succeeded/failed
                    -> resumed -> succeeded/failed
```

批次表必须另设业务唯一键，不能只靠每次新生成的 UUID `batch_id`。推荐：

```text
(run_type, model_version, config_hash, data_snapshot_id, as_of_data_date, universe_id)
```

预测明细必须显式区分 `request_horizon` 与 `path_step`。当前生产等价模式只保存每个独立请求的终点，明细业务键为 `(batch_id, code, request_horizon, target_date)`；若未来保存完整路径，则改为 `(batch_id, code, request_horizon, path_step)`。同一参数重跑采用 upsert；改变参数或 horizon 语义会创建新版本记录，不覆盖旧预测。所有数据库写入使用 Quantia `quantia.lib.database`，保持 `chunksize=500` 和 NaN/inf 清洗规则。

## 5. 持久化数据模型

部署前必须通过 `INFORMATION_SCHEMA.COLUMNS` 核对生产库，表结构以实际迁移脚本为准。建议新增四张表。

### 5.1 批次表 `cn_kronos_prediction_batch`

关键字段：

- `batch_id`：UUID，唯一；
- `run_type`：`eod|intraday|walk_forward|shadow`；
- `as_of_data_date`、`generated_at`；
- `model_version`、`tokenizer_version`、`c1_version`；
- `config_hash`、`code_git_sha`、`data_snapshot_id`；
- `lookback`、`pred_len`、采样参数；
- `universe_id`、计划/成功/失败数量；
- `status`、`error_summary`、开始/结束时间。

### 5.2 预测明细表 `cn_stock_kronos_prediction`

每只股票、每个目标交易日一行：

- `batch_id`、`code`；
- `as_of_data_date`、`target_date`、`request_horizon`、`path_step`；
- `last_actual_close`；
- `pred_open/high/low/close/volume/amount`；
- `pred_return`、可选分位数区间；
- `c1_score`、`c1_rank`（仅兼容 5 日时填写）；
- `latency_ms`、`status`、`error_code`、`error_message`。

当前终点模式唯一键：`(batch_id, code, request_horizon, target_date)`。不能只用 `(batch_id, code, target_date)`，否则未来保存多个独立请求的重叠路径时会互相覆盖。

### 5.3 真实值与评估表 `cn_stock_kronos_evaluation`

- 使用不可变 `prediction_id` 关联预测事实；
- `actual_open/high/low/close/volume/amount`；
- `actual_return`；
- `close_abs_error`、`close_smape`、`return_abs_error`；
- `direction_correct`、`ohlc_valid`；
- `actual_data_version`、`evaluated_at`；
- `status`：`pending|observed|invalidated`。

唯一键应为 `(prediction_id, actual_data_version)`，并另设 `is_current` 或当前版本视图。真实行情后续发生复权或纠错时，不修改原始预测；增加真实数据版本并重新计算评估。若目标区间跨越除权除息且无法把真实价转换到预测生成时的价格基准，状态必须记为 `price_basis_break`/`invalidated` 并排除出价格误差聚合，不能直接比较 qfq 与原始价。

### 5.4 聚合表 `cn_kronos_model_metric`

按 `model_version + config_hash + window + request_horizon + segment` 保存：

- 样本数、覆盖率；
- MAE、RMSE、sMAPE、方向准确率；
- IC、RankIC、分组收益；
- 推理 p50/p95/p99、失败率；
- 相对冠军和基线的差值及置信区间；
- 指标窗口起止日期、计算时间。

明细是事实来源，聚合表可以安全重建。

## 6. 真实结果到期评估

评估任务每天在行情缓存更新后运行，不需要为每个历史批次单独设置 Cron：

1. 查询 `target_date <= latest_complete_trade_date` 且状态为 `pending` 的预测；
2. 从 Quantia 缓存/数据库读取对应真实 K 线；
3. 数据缺失时保持 pending，并记录缺失原因；只有目标日之后该股票重新出现有效 K 线，才能确认目标日为 `not_traded`，数据尾端缺失一律记为 `actual_missing`，不能把缓存过期/价格基准断裂误判为停牌；
4. 对齐后写评估明细；
5. 更新最近 20、60、120 个交易日的聚合指标；
6. 检查覆盖率、漂移和挑战者门禁；
7. 生成 JSON/CSV 报告供审计，不依赖报告文件作为事实来源。

需要区分：

- `request_horizon=1`：目标日一到即可评估；
- 完整 `pred_len=10` 批次：第 10 个目标交易日到齐后才标记 complete；
- 停牌：若目标交易日该股票无成交，应标记 `not_traded`，不能自动挪到下一交易日并假装原预测命中。
- 锚点成熟度：输出必须包含选中锚点数、已成熟锚点数和因未来交易日不足跳过的锚点数，禁止静默缩小样本。
- 同一批运行若观察到多个 `model_version`，必须标记 `mixed_model_versions=true` 并禁止用于参数比较或晋级。

## 7. 动态调优闭环

### 7.1 不推荐的方案

以下做法风险过高：

- 根据最近一天准确率自动修改 YAML；
- 在同一测试区间反复选参并报告该区间为“测试集”；
- 市场大跌后只用最近一周数据立即重训并替换生产模型；
- 搜索大量参数后只保留最优结果，不保存全部试验；
- C1 负 IC 时通过反转分数直接宣称可生产。

这些做法容易造成追涨杀跌、数据窥探和不可复现。

### 7.2 推荐冠军/挑战者流程

```mermaid
stateDiagram-v2
    [*] --> Candidate
    Candidate --> Rejected: Walk-forward 未通过
    Candidate --> Shadow: Walk-forward 通过
    Shadow --> Rejected: 线上到期指标退化
    Shadow --> Canary: 至少 60 个到期交易日且显著改善
    Canary --> Champion: 运行与效果门禁通过
    Canary --> Rejected: 任一硬门禁失败
    Champion --> RolledBack: 持续漂移或运行故障
    RolledBack --> Champion: 回滚至上一稳定版本
```

晋级条件建议同时满足：

1. walk-forward 主指标优于当前冠军；
2. 测试窗口从未参与候选参数选择；
3. 影子预测至少积累 60 个到期交易日；
4. 覆盖率、OHLC 合法率、失败率和延迟通过；
5. 改善经过 block bootstrap 或按日配对检验；
6. 配置、模型、代码和数据快照均可复现；
7. 由人工审批更新生产配置，不直接由评估脚本写生产 YAML。

### 7.3 搜索策略

分层搜索，避免组合爆炸：

1. **推理窗口层**：`lookback=[90,128,256,384,512]`，确定性参数固定；
2. **概率采样层**：只对前两名 lookback 搜索 `sample_count/temperature/top_p`；
3. **C1 层**：独立搜索特征、正则化和模型参数，仅评价 5 日截面指标；
4. **微调层**：只有冻结模型持续退化且数据量足够时，才启动 tokenizer/base 微调实验。

推荐使用随机搜索或 Optuna 的受限搜索，而不是全排列。每个 trial 必须保存：

- 参数、随机种子和配置哈希；
- 模型/tokenizer/C1 版本；
- Git SHA；
- 数据快照、股票池版本和时间边界；
- 各锚点明细、聚合指标、耗时和硬件信息。

选择目标不能只有一个 MAPE。建议使用带硬约束的综合目标：先剔除覆盖率、失败率、延迟不达标的候选，再在剩余候选中按方向准确率、sMAPE、稳定性和运行成本排序。

### 7.4 漂移触发

调优任务建议周度汇总、月度决策。触发条件可包括：

- 最近 20 日相对冠军方向准确率下降，且置信区间确认非随机波动；
- sMAPE 或 ATR 归一化误差连续多个窗口恶化；
- 行业/波动率分组出现集中失效；
- 数据分布 PSI/KS 超阈值；
- 预测覆盖率或服务失败率异常。

触发只创建候选实验，不自动替换生产版本。

## 8. 可视化设计

### 8.1 定位与原则

这是内部研发/风控可观测面板，不是面向普通用户的选股功能，默认不出现在公开导航中。设计原则：

1. 前端只读第 5 章持久化表的**聚合结果**，不在浏览器里重新计算逐笔误差或截面排名，避免页面卡顿。
2. 复用 Quantia 现有前端基础设施：Vue 3 + Element Plus + ECharts，图表交互风格与 [indicator/index.vue](../quantia/fontWeb/src/views/indicator/index.vue) 保持一致。
3. 按仓库 `AGENTS.md` 的移动端适配规则，新页面必须做响应式：宽对比表格提供卡片视图，ECharts 在 tab 切换后必须 `resize()`，弹窗遵循 `isMobile` 全屏规则。这是一条硬约束，不因为是内部页面而豁免。
4. 图表默认查询窗口不超过最近 120 个交易日；需要更长区间时要求用户显式选择，防止一次性拉取过多历史点位。
5. 每个图表都必须能看出"样本量是否足够"，例如叠加到期交易日计数，避免把仅有 5～10 个样本的早期噪声误读成稳定结论。

### 8.2 页面结构

新增 `quantia/fontWeb/src/views/kronos-monitor/`，建议拆分为以下 Tab：

| Tab | 核心用途 |
| --- | --- |
| 总览 | 当前冠军版本信息卡片（`model_version`/`lookback`/`pred_len`/生效时间）+ 关键 KPI（近 20 日方向准确率、sMAPE、覆盖率、失败率）+ 告警条 |
| 滚动验证 | 多锚点、多 horizon 的历史回放指标趋势 |
| 批量预测监控 | 批次状态、延迟分布、失败标的清单 |
| 准确率评估 | 误差分布、预测 vs 实际散点/校准曲线、K 线抽查对比 |
| C1 截面 | IC/RankIC 时间序列、分层收益 |
| 冠军 / 挑战者 | 多维度对比 + 晋级门禁检查单 |

### 8.3 关键图表规格

1. **滚动验证时间序列**（折线图）：横轴为锚点日期，每个 horizon（1/3/5/10/15/30 日）一条线，叠加冠军基线和随机游走基线的虚线；默认只显示 1/5/30 以避免六条线拥挤，其余通过图例切换。置信区间用半透明面积（upper/lower 两条辅助 series + `areaStyle`）表示，避免用户把单点波动误认为趋势拐点。
2. **误差分布箱线图**：按 horizon 或按行业/波动率分组的 `close_smape`、方向准确率分布，后端需要预先计算 `[min, Q1, median, Q3, max]` 再传给 ECharts `boxplot`，不要把全部原始样本传到前端。
3. **预测 vs 实际收益散点/校准曲线**：横轴预测收益 $\hat r_{t,h}$，纵轴真实收益 $r_{t,h}$，叠加 $y=x$ 参考线和线性拟合线，标注该窗口的 IC/RankIC 数值；用于直观判断模型是否系统性偏多或偏空。
4. **K 线抽查叠加图**：复用现有蜡烛图组件，用同一坐标轴叠加"预测蜡烛"（半透明或虚线描边）与"真实蜡烛"，用于人工抽查而非替代统计指标。
5. **C1 分层收益条形图**：按预测分位数（如十分位）分组的未来实际收益均值，用于判断截面排序单调性；非单调应在图上高亮提示。
6. **漂移监控折线图**：PSI/KS 等分布漂移指标随时间变化，叠加 `markLine` 标出告警阈值。
7. **冠军 / 挑战者对比**：多维指标（方向准确率、sMAPE、覆盖率、延迟、样本数）归一化后用雷达图或并列柱状图对比，旁边配 7.2 节晋级门禁的检查单组件（每项显示 ✅/❌ 及当前数值）。
8. **批量任务运行监控**：按日期的批次状态日历（成功/部分成功/失败三色），配合延迟 P50/P95/P99 趋势线和吞吐（symbols/秒）趋势线；用于判断第 9 章的容量假设是否仍然成立。

### 8.4 数据契约

新增只读 handler `quantia/web/kronosMonitorHandler.py`，建议路由：

- `GET /quantia/api/kronos/monitor/rolling_metrics`
- `GET /quantia/api/kronos/monitor/evaluation_summary`
- `GET /quantia/api/kronos/monitor/champion_challenger`
- `GET /quantia/api/kronos/monitor/batch_health`

所有接口直接查询 `cn_kronos_model_metric`、`cn_kronos_prediction_batch` 等聚合/状态表，返回已经算好、与图表 series 字段一一对应的 JSON，不在 Web 层做重计算，也不反向触发批量或评估任务。

## 9. CPU-only Linux 部署可行性分析

### 9.1 结论

功能上完全可行：本地服务默认配置 `model.device: cpu`，此前所有真实推理验证（包括 300308 黑盒调用）都是在 CPU 上完成的，不依赖 GPU。**真正的约束是吞吐**：单机 CPU 能否在夜间批处理窗口内完成目标股票池的批量预测，需要在目标机型实测后才能下结论，不能直接假设"能"或"不能"。

### 9.2 已核实的事实

- 当前 `local_kpred.yaml` 的 `model.device` 默认值就是 `cpu`（见 [local_kpred.yaml](../../Kronos/finetune_csv/configs/local_kpred.yaml)），CPU 是当前实现的默认路径而非陌生场景。
- 模型体积：`Kronos-base/model.safetensors` 约 390 MB，`Kronos-Tokenizer-base/model.safetensors` 约 15 MB，磁盘合计约 405 MB。常驻推理时的实际内存占用还包含激活值和框架开销，需要在目标机型用 `/usr/bin/time -v` 或 `ps`/`smem` 实测，不能直接套用磁盘体积估算。
- 已实测延迟（Windows 开发机 CPU，`lookback=90`）：单步约 133 ms，5 步约 595 ms；`300308` 真实缓存场景 3 步 376～483 ms。
- 2026-07-13 实测：Windows 开发机 CPU、`lookback=256`、`pred_len=30`、`sample_count=1`、`top_k=1`，单股 30 日请求约 **10 秒**。服务修复后使用 DB 连续补齐至 2026-07-10 的新鲜历史，按需接口已返回 HTTP 200。
- 生产等价评测需要分别执行六个 horizon，不能再用“单次 30 日耗时 × 股票数”低估成本。Phase 1 真实烟测（300308、锚点 2026-06-30、lookback 64）独立 1/3 日请求分别约 109/277 ms；完整六档和长 lookback 仍需单独测量。因此纯 CPU 全市场逐股串行不可作为生产方案；批量端点和目标机 micro-batch 实测是 Phase 2 的硬门禁。

### 9.2.1 2026-07-13 规模化实测结果（Phase 2 门禁判定）

使用 `quantia.job.kronos_rolling_validation_job`，锚点范围 2026-04-01～2026-05-29（5 个成熟锚点，无跳过），实际数据边界 2026-07-10，共两组独立跑批：

- **run A**（`runs/kronos_validation/phase1_scale_20260713.json`，config_hash=`738ebcd82ed56ab9`）：6 只流动性股票（000001/600519/000858/601318/000002/300750）× lookback∈{64,256} × horizon∈{1,3,5,10,15,30}，360 条记录，覆盖率 100%，0 条 provider_error，模型版本单一（`kronos:bundle:46871e6dab81`，无 mixed_model_versions）。
- **run B**（`runs/kronos_validation/phase1_tuning_h135_20260713.json`，config_hash=`61f80d13b793deb9`）：同 6 只股票 × lookback∈{32,64,128} × horizon∈{1,3,5}，270 条记录，覆盖率 100%。

汇总结论（`close_mae_vs_baseline` = 模型 MAE − 随机游走/收盘不变基线 MAE，正值代表模型更差）：

| lookback | horizon | close_mae | baseline_mae | delta | 方向准确率 |
| --- | --- | --- | --- | --- | --- |
| 64 | 1 | 6.60 | 6.41 | +0.20 | — |
| 128 | 1 | 6.40 | 6.41 | **−0.0018** | 53.3% |
| 256 | 1 | 8.09 | 6.41 | +1.68 | — |
| 64 | 5 | 8.71 | 7.58 | +1.14 | — |
| 128 | 5 | 9.81 | 7.58 | +2.23 | — |
| 256 | 30 | 39.59 | 33.93 | +5.66 | — |

（完整 18 组 lookback×horizon 结果见对应 JSON 的 `summary` 字段。）

**结论：在当前采样配置（`temperature=1, top_k=1, top_p=1, sample_count=1`，即近似贪心解码）下，630 条独立评测样本中仅 `lookback=128,horizon=1` 与基线打平（差距在噪声范围内，n=30 时方向准确率 53.3% 不具统计显著性），其余全部 17 组均明显劣于“收盘价不变”基线。** 这是一个真实的负面信号，不是实现 bug——`run_rolling_validation` 的核对（去重、成熟锚点审计、单一模型版本）已排除数据泄漏、锚点不成熟、模型版本混用等混杂因素。

**Phase 2 门禁判定：暂不满足晋级条件。** 在没有找到能稳定跑赢基线的配置之前，投入批量 HTTP 端点、数据库表、Cron 编排等 Phase 2 基础设施属于对一个当前无实证优势模型的过早工程投入。建议下一步优先在 Phase 1 范围内做：

1. **采样策略**：当前 `top_k=1` 接近贪心解码，缺乏路径多样性；应先测试 `sample_count∈{5,10,30}` + 多路径平均，以及 `temperature∈{0.7,1.0,1.3}`、`top_p∈{0.85,0.95}` 的小网格，观察是否能把至少短 horizon（1～5 日）的 `close_mae_vs_baseline` 稳定转负。
2. **更长评测窗口**：当前只覆盖 5 个锚点、约 2 个月窗口，样本量偏小（尤其 horizon=30 只有 n=30 级别观测），不足以下结论性判断，需要更长锚点窗口和更多股票以提升统计功效。
3. 只有当某个配置在扩大样本后依然稳定跑赢基线，才回到本节评估是否投入 Phase 2 基础设施。

### 9.2.2 2026-07-14 长回看（256/384/512）扩大验证结果

按用户要求，在决定是否进入 Phase 2 之前先扩大 Phase 1 规模验证，并优先测试 `lookback=256` 及更长的取值。使用 `quantia.job.kronos_rolling_validation_job`，锚点范围固定为 2026-03-02～2026-05-29、`anchor-step=5`、实际数据边界 2026-07-10、六个独立 horizon（1/3/5/10/15/30），采样参数与 9.2.1 一致（近似贪心解码）。每个 lookback 拆成两组互不重叠的 4 只股票（A：000001/600519/000858/601318；B：000002/300750/600036/601012）分别运行，规避单进程长时间常驻导致的内存增长（见 9.6）：

- `lookback=256`：`max-anchors=8`，A/B 各 192 条记录，config_hash 分别为 `c419914e9fabdb9e`、`6f28d5354a0196e6`。
- `lookback=384`：`max-anchors=8`，A/B 各 192 条记录，config_hash 分别为 `20b1964072641a29`、`299d839af4aa0466`。
- `lookback=512`：`max-anchors=5`（超时代价更高，降低锚点数控制总耗时），A 组 120 条记录（config_hash `c0235a34af29a9ba`，覆盖率 85%～95%，12 条 `provider_error`：9 条 `INFERENCE_BUSY`、3 条 `PROVIDER_TIMEOUT`，均为单次推理超过 180 秒客户端超时后触发，后续把 `--timeout` 提升到 600 秒），B 组 120 条记录（config_hash `49826bf5ef9b5e8c`，覆盖率 100%，0 条 provider_error）。

A/B 两组按 `n_observed` 加权合并后（`close_mae_vs_baseline` 正值代表模型比“收盘价不变”基线更差）：

| lookback | horizon | n_observed | 覆盖率 | close_mae | baseline_mae | delta | 方向准确率 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 256 | 1 | 64 | 100% | 4.49 | 3.03 | +1.46 | 0.50 |
| 256 | 3 | 64 | 100% | 9.53 | 5.33 | +4.20 | 0.42 |
| 256 | 5 | 64 | 100% | 11.44 | 7.30 | +4.14 | 0.47 |
| 256 | 10 | 64 | 100% | 14.20 | 8.08 | +6.12 | 0.47 |
| 256 | 15 | 64 | 100% | 15.54 | 10.55 | +4.99 | 0.50 |
| 256 | 30 | 64 | 100% | 22.94 | 17.08 | +5.86 | 0.38 |
| 384 | 1 | 64 | 100% | 5.20 | 3.03 | +2.17 | 0.45 |
| 384 | 3 | 64 | 100% | 10.74 | 5.33 | +5.42 | 0.45 |
| 384 | 5 | 64 | 100% | 13.10 | 7.30 | +5.79 | 0.47 |
| 384 | 10 | 64 | 100% | 15.97 | 8.08 | +7.89 | 0.53 |
| 384 | 15 | 64 | 100% | 19.32 | 10.55 | +8.77 | 0.48 |
| 384 | 30 | 64 | 100% | 29.26 | 17.08 | +12.18 | 0.33 |
| 512 | 1 | 38 | 95% | 6.72 | 3.31 | +3.41 | 0.47 |
| 512 | 3 | 39 | 97% | 13.74 | 4.69 | +9.05 | 0.56 |
| 512 | 5 | 37 | 93% | 20.85 | 8.82 | +12.02 | 0.41 |
| 512 | 10 | 38 | 95% | 20.38 | 8.15 | +12.23 | 0.50 |
| 512 | 15 | 38 | 95% | 23.38 | 9.50 | +13.88 | 0.47 |
| 512 | 30 | 38 | 95% | 34.44 | 13.80 | +20.64 | 0.37 |

（`lookback=512` 的覆盖率分母是 40（4 股票 × 5 锚点 × 2 组），与 256/384 的分母 64（4 股票 × 8 锚点 × 2 组）不同，表格中已按各自实际请求数换算成百分比，可直接横向比较。）

**结论：加上本轮 6 × 64 = 384 条新独立评测样本后，累计样本量达到 630 + 384 = 1014 条，`lookback` 越长、`close_mae_vs_baseline` 越差的趋势在全部 6 个 horizon 上都是单调且一致的（256 < 384 < 512），不存在任何一个 horizon 在更长回看下反而转优的情况。** 这与 2.4 节“回看越长不必然越准”的既有结论方向一致，但本轮进一步证明：在当前贪心解码配置下，长回看（384/512）不仅没有帮助，反而显著放大误差和推理延迟（512 的单次推理需要数十秒到超过 180 秒，是 12 条样本触发 provider 超时/排队错误的直接原因）。`lookback=256` 仍是当前三个取值中相对最优的，但即使是 256，六个 horizon 也全部劣于基线，与 9.2.1 的结论一致。

**Phase 2 门禁判定（更新）：维持“暂不满足晋级条件”，且新增证据强化该判定。** 本轮验证没有找到任何更长回看窗口能反转结论的证据，因此不建议把“增大 lookback”作为后续调优方向；后续调优应聚焦于 9.2.1 已提出的采样策略网格（`sample_count`、`temperature`、`top_p`）和更短、更精细的 lookback 网格（如 32～200 区间），而不是继续扩大 lookback。

### 9.2.3 Phase 1 参数搜索与可靠跑批实现

2026-07-14 已在 Quantia 落地 `quantia.job.kronos_parameter_search_job`，只用于 Phase 1 离线候选发现，不会修改生产 YAML、自动晋级 champion 或进入 Phase 2：

- 单配置任务支持 `sample_count/temperature/top_k/top_p/clip`，参数同时进入 Kronos 请求、逐条记录、artifact settings 和 `config_hash`；
- 每个 `code/anchor/lookback/horizon` 使用稳定任务键；`--resume` 只跳过同一配置中已完成的任务，配置不一致会直接拒绝，防止实验串线；
- 默认每完成 1 次 provider 调用即使用 `.tmp -> replace` 原子更新检查点，检查点 `complete=false`，整批完成后才写入 summary 并标记 `complete=true`；
- 续跑默认删除并重试旧 `provider_error`，成功后替换为唯一新记录，不会让超时/服务重启造成永久缺口或重复加权；可用 `--no-retry-provider-errors` 保留失败事实而不重试；
- 网格协调器为每个配置启动独立子进程并写独立 JSON，降低长期单进程 PyTorch 内存增长风险；`manifest.json` 原子记录 running/completed/failed、配置、输出路径、门禁失败原因和合格数量；
- 门禁分为三层：`operational_qualified` 要求所有 horizon 同时满足 coverage=100%、provider_error=0、`close_mae_vs_baseline<0`；`robust_qualified` 要求每个 horizon 的有效股票数不少于 `--min-symbols`、按股票等权的胜率严格大于 `--min-symbol-win-rate`，且股票簇 bootstrap 的 97.5% 均值上界小于 0；最终 `qualified` 仅在两层同时通过时为真。
- 稳健性计算先对每只股票跨锚点的 delta 取均值，再以股票为簇做固定种子 bootstrap；胜率按原始收盘 MAE delta 的符号计算，bootstrap 使用尺度无关的 return MAE delta，避免把同一股票的高度相关锚点或高价股绝对误差重复加权。`manifest.json` 同时保存 `robustness_gate`、逐 horizon 稳健指标、两层失败原因、`operational_qualified_count` 和最终 `qualified_count`。
- 最终门禁还会审计 artifact 自洽性：必须 `complete=true`、只含一个 lookback、计划中的每个“股票 × 成熟锚点 × horizon”恰好一条记录、无重复任务键、observed 误差均为有限数、summary delta 可由 records 精确重算，并且 model/predictor/tokenizer 三类指纹各自单一。任何一项失败都会进入 `artifact_failures` 并阻止 operational 通过。
- 默认 `--min-symbols 8 --min-symbol-win-rate 0.5 --bootstrap-samples 5000`；正式独立复验应把 `--min-symbols` 提高到实际 holdout 股票数。只有最终 `qualified=true` 才可进入 Phase 2 评审，单独 `operational_qualified=true` 仍只代表任务可靠且总体均值过线。

推荐先跑低成本 smoke，再扩大股票和锚点：

```powershell
cd C:\xapproject\Quantia\Quantia
C:\xapproject\Quantia\.venv\Scripts\python.exe `
  -m quantia.job.kronos_parameter_search_job `
  --codes 000001,600519,000858,601318 `
  --anchor-start 2026-03-02 --anchor-end 2026-05-29 --actual-end 2026-07-10 `
  --lookbacks 64,128,192,256 --horizons 1,3,5 `
  --sample-counts 5,10 --temperatures 0.7,1.0 `
  --top-ks 0 --top-ps 0.85,0.95 --clips 5.0 `
  --anchor-step 5 --max-anchors 3 --timeout 600 `
  --bootstrap-samples 5000 --min-symbols 8 --min-symbol-win-rate 0.5 `
  --checkpoint-every 1 --max-configs 4 --resume `
  --output-dir runs\kronos_validation\phase1_parameter_search
```

先用 `--max-configs 1` 验证服务和数据，再逐步提高到 4/8/全部配置。相同命令配合 `--resume` 可在关机、服务重启或单配置失败后继续；不要复用同一个 output-dir 跑不同股票池、日期范围或 horizon，单配置 worker 会拒绝 settings 不一致的 artifact。

### 9.2.4 2026-07-14 关键缺陷：Kronos 服务此前忽略逐请求采样参数

首轮 8 配置 pilot 网格（`lookback∈{64,128}` × `sample_count∈{5,10}` × `temperature∈{0.7,1.0}`）跑完后发现：**同一 `lookback` 下全部 4 个采样组合给出完全相同的指标**（例如 `lookback=64` 的 4 组结果逐位一致：`h1 delta=+0.85, h3 delta=+0.44, h5 delta=+1.23`）。深入排查 [local_kpred_service.py](../../Kronos/finetune_csv/local_kpred_service.py) 的 `LocalKpredEngine.predict()` 发现根因：

- `predict()` 已经支持逐请求覆盖 `lookback`（`payload.get("lookback", self.lookback)`），但 `sample_count/temperature/top_k/top_p/clip` 全部硬编码读取 `self.*`（服务启动时从 YAML/环境变量固定一次），完全忽略了 Quantia 滚动验证引擎随请求发送的同名字段。
- 结果是：不论 Quantia 发送什么采样参数，Kronos 实际推理永远使用服务启动时的固定配置（默认 `sample_count=1, temperature=1.0, top_k=1, top_p=1.0`，近似贪心解码）。此前所有“采样网格”实验（包括本文档 9.2.1 提到的概率采样候选）如果通过请求传参而非重启服务改配置，均未产生真实差异。

修复：`predict()` 新增逐请求覆盖，与 `lookback` 使用相同的边界钳制并回落到服务默认值，响应体新增回显字段 `sample_count/temperature/top_k/top_p/clip` 供审计（[local_kpred_service.py](../../Kronos/finetune_csv/local_kpred_service.py)）。新增 3 个单元测试覆盖生效、边界钳制和缺省回落（[test_local_kpred_service.py](../../Kronos/tests/test_local_kpred_service.py)），Kronos 服务全部 17 个测试通过。

真实黑盒验证（同一 `300308`/锚点 2026-06-30/`lookback=64`）：

| 配置 | predicted_close |
| --- | ---: |
| `sample_count=1, temperature=1.0, top_k=1, top_p=1.0`（服务默认） | 1279.2948 |
| `sample_count=10, temperature=0.7, top_k=0, top_p=0.85`（请求覆盖） | 1282.9514 |

两次调用返回不同预测值，证明修复后请求参数确实影响推理路径。**修复前用请求参数做的所有采样网格结果应视为无效**（本文档 9.2.4 之前记录的任何“采样策略”结论均需在修复后重新验证）；已用新的 `phase1_parameter_search_pilot_fixed_20260714` 目录重新运行 8 配置 pilot 网格。

**审计加固**：仅记录“请求参数”不足以证明 provider 真正生效（旧服务、未重启、静默钳制均可造成假象）。因此在 `run_rolling_validation` 新增强制校验：provider 响应必须回显 `sample_count/temperature/top_k/top_p/clip` 五个字段，且与请求值逐一相等（经过与服务端一致的边界钳制），否则整条记录标记为 `provider_error` 并写入 `error_code=ValueError`，不会被误判为“已验证的采样结果”。同时把 Quantia 与 Kronos 两侧的取值域对齐为 `sample_count∈[1,64]`、`temperature∈[0.05,5.0]`、`top_k∈[0,1024]`、`top_p∈[0.01,1.0]`、`clip∈[1.0,20.0]`，`sample_count/top_k` 必须为整数，禁止 `NaN`/`Infinity`/`null`。相关改动：[rolling_validation.py](../quantia/kronos/rolling_validation.py)、[local_kpred_service.py](../../Kronos/finetune_csv/local_kpred_service.py)，新增/更新单测覆盖匹配回显、缺失回显、参数不一致、非法数值边界。

**8 配置 pilot 最终结论（`000001/600519/000858/601318`，3 锚点/配置，`horizon∈{1,3,5}`，均 100% 覆盖、0 provider_error）**：

| 配置（lookback/sample_count/temperature） | 平均 `close_mae_vs_baseline` | 最差 horizon delta | 是否通过候选门禁 |
| --- | ---: | ---: | :--- |
| lb=64, sc=10, T=1.0 | **-0.82** | +0.67 (h1) | 否 |
| lb=64, sc=5, T=1.0 | -0.58 | +1.43 (h3) | 否 |
| lb=64, sc=5, T=0.7 | +0.08 | +1.38 (h1) | 否 |
| lb=64, sc=10, T=0.7 | +0.22 | +1.07 (h1) | 否 |
| lb=128, sc=5, T=0.7 | +1.47 | +1.82 (h5) | 否 |
| lb=128, sc=10, T=0.7 | +2.11 | +3.15 (h5) | 否 |
| lb=128, sc=10, T=1.0 | +2.48 | +2.81 (h3) | 否 |
| lb=128, sc=5, T=1.0 | +2.79 | +3.24 (h5) | 否 |

结论：

1. **8 个配置全部未通过候选门禁**（要求全部 horizon `close_mae_vs_baseline < 0`）——本轮 pilot 未找到能全面跑赢“收盘不变基线”的采样组合。
2. **`lookback=64` 在全部 4 个采样组合上一致优于对应的 `lookback=128`**，与本文档 9.2.2 记录的长 lookback 单调变差结论方向一致；短 lookback 仍是更优先的探索方向。
3. 当前最优候选 `lb=64, sc=10, T=1.0` 仅在 horizon=1 落后基线（+0.67），horizon=3/5 均已反超（-0.01、-3.13）。按 000858/600519/601318/000001 拆开看，h1 的落后并非单一股票主导（4 只股票均非负），但样本量（每配置仅 3 锚点 × 4 股票）过小，不能作为参数结论，只能作为下一轮扩大验证的优先方向。
4. 下一步：以 `lb=64` 为中心，扩大锚点数（`--max-anchors` 提高、`--anchor-step` 缩小）和股票池，重点扩展 `sample_count≥10`、`temperature∈[0.9,1.1]` 附近的网格，并要求新的 pilot 全部通过审计加固后的强制回显校验。

### 9.2.5 2026-07-14 扩大验证：操作门禁通过，但稳健性不足

按 9.2.4 的方向，将股票池扩大到 8 只（`000001/600519/000858/601318/000002/300750/600036/601012`），每个配置使用 5 个锚点、3 个 horizon，共 120 条记录；固定 `lookback=64, sample_count=10, top_k=0, top_p=0.85, clip=5.0`，比较 `temperature∈{0.9,1.0,1.1}`。产物位于 `runs/kronos_validation/phase1_parameter_search_expanded_20260714`。

三个配置合计 360/360 条记录均为 `observed`，coverage 100%，0 provider_error；每条记录均保存并通过 requested/applied 五参数一致性校验，模型、predictor、tokenizer 指纹全程各只有一个版本。

| temperature | h1 delta | h3 delta | h5 delta | 原候选门禁 |
| ---: | ---: | ---: | ---: | :--- |
| 0.9 | +0.0500 | +0.0427 | -0.3021 | 不通过 |
| 1.0 | **-0.0077** | **-0.0144** | **-0.8488** | 通过 |
| 1.1 | +0.4772 | -0.7238 | -0.9000 | 不通过 |

`temperature=1.0` 是首个满足原候选门禁（所有 horizon `close_mae_vs_baseline < 0`）的配置，但进一步稳健性检查表明不能直接晋级：

- 对每个 horizon 的 40 条逐记录 delta 做 5000 次固定种子 bootstrap，95% 区间分别为 h1 `[-0.59,+0.62]`、h3 `[-1.01,+0.97]`、h5 `[-3.05,+1.08]`，全部跨 0；bootstrap 中均值小于 0 的比例仅为 54%、52%、80%。
- 优势存在明显股票集中度：`600519` 对 h1/h3/h5 的单股平均 delta 分别为 `-0.53/-1.98/-9.65`。剔除 `600519` 后，三条总体 delta 反转为 `+0.07/+0.27/+0.41`，全部落后基线。
- h1/h3 的总体优势绝对值仅 `0.0077/0.0144`，远小于抽样波动，不足以证明可推广的模型优势。

因此结论分为两层：

1. **操作门禁通过**：参数确实生效，跑批可靠，覆盖率、provider 错误和原始 baseline delta 条件均满足；`lb=64, sc=10, T=1.0, top_k=0, top_p=0.85, clip=5.0` 可保留为下一轮候选。
2. **稳健性门禁未通过**：结果尚不支持进入 Phase 2 或生产推广。下一轮必须扩大股票横截面和锚点，并新增“bootstrap 上界 < 0”或“按股票等权多数胜出”等抗集中度条件；在此之前不能把 `qualified=1` 解读为稳定跑赢基线。

### 9.2.6 2026-07-14 独立 holdout 复验：候选明确淘汰

使用未参与前两轮参数选择的 20 只股票做独立复验，覆盖消费、家电、金融、医药、新能源、科技、交通和公用事业等行业。固定候选 `lookback=64, sample_count=10, temperature=1.0, top_k=0, top_p=0.85, clip=5.0`，每只股票取 8 个锚点和 3 个 horizon，共 480 条记录。门禁设置为 `min_symbols=20`、股票胜率严格大于 50%、股票簇 bootstrap 5000 次的 97.5% 上界小于 0。产物位于 `runs/kronos_validation/phase1_holdout_robust_20260714`。

运行可靠性符合预期：480/480 条均为 `observed`，coverage 100%，0 provider_error，480 条均保存并通过 requested/applied 参数审计；模型 bundle、predictor 和 tokenizer 指纹全程各只有一个版本。运行期间 `600009` 出现“DB 尾段与 qfq 缓存价格基准不连续，跳过合并”警告，但其缓存已覆盖全部评测锚点和真实值窗口，最终每个 horizon 均有完整 8 条记录，无缺失或 provider 错误，因此不影响本轮统计完整性。

| horizon | Kronos MAE | 基线 MAE | delta | 股票胜出数/20 | 胜率 | return delta bootstrap 97.5% 上界 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.1510 | 1.6029 | **+0.5481** | 4 | 20% | +0.00366 |
| 3 | 4.1951 | 2.9912 | **+1.2039** | 5 | 25% | +0.00667 |
| 5 | 6.1850 | 4.0368 | **+2.1482** | 5 | 25% | +0.01097 |

`300308` 的高价格尺度对原始 MAE 有明显放大作用，但不是淘汰结论的唯一来源：剔除该股票后，三条按股票等权 delta 仍为 `+0.0434/+0.0058/+0.0496`，横截面中位数分别为 `+0.0469/+0.0563/+0.0959`，方向仍全部落后基线。更关键的是，三个 horizon 的股票胜率均远低于严格多数，与 bootstrap 上界判定一致。

**阶段决策：`operational_qualified=false`、`robust_qualified=false`、最终 `qualified=false`。** `temperature=1.0` 在 8 股票开发集上的微弱总体优势没有在独立 20 股票 holdout 上复现，且所有 horizon 同时失败，不应进入 Phase 2，也不应继续通过增加同配置样本来寻求翻转。Phase 1 后续若继续，应注册新的候选假设，并优先采用尺度无关指标（例如相对误差改善或按股票标准化 delta）做参数发现；最终门禁仍须保留原始业务指标、按股票多数胜出和独立 holdout，不能用重新定义指标追认本候选。

使用加固后的 artifact 审计重放本轮 480 条产物，`artifact_failures=[]`，证明淘汰不是由缺失锚点、重复记录、summary 漂移或混用模型版本导致。改用 return MAE delta 做股票簇 bootstrap 后，三个上界仍全部显著大于 0，因此价格尺度调整不改变结论。

### 9.2.7 H2 预注册：短上下文与中等采样

新的候选假设已写入机器可读的 [Kronos候选假设注册表.json](Kronos候选假设注册表.json)，ID 为 `H2-short-context-moderate-sampling`。核心假设是：相较 H1，`lookback=32/48/64`、`temperature=0.8/0.9` 与 `sample_count=10/20` 的组合能够降低按股票等权的 return MAE delta，同时保持横截面多数股票受益；固定 `top_k=0, top_p=0.85, clip=5.0`，共 12 个配置。

预注册约束如下：

1. 参数发现仅使用既有 8 股票开发集，每只至少 8 个成熟锚点；按“三个 horizon 的按股票等权 return MAE delta 均值”排序，最差 horizon、平均股票胜率和延迟依次作为 tie-breaker，最多选择 1 个候选。
2. 进入最终 holdout 前，候选必须无 artifact 审计失败、coverage 100%、0 provider_error，且所有 horizon 同时满足原始 close MAE delta < 0、return MAE delta < 0、股票胜率严格大于 50%。
3. 最终 holdout 至少 20 只、每只至少 8 个成熟锚点，股票代码必须与此前所有开发集和 holdout 完全不重叠，只允许一次性评估；仍要求 return delta cluster-bootstrap 97.5% 上界小于 0。
4. 修改门禁或排序指标必须注册新的 hypothesis ID；H1 和本轮 20 股票 holdout 均不得被重新用于 H2 参数选择，也不得用事后指标翻案。

### 9.3 容量测算方法

在目标 Linux 机型（而不是开发机）上执行基准测试：

1. 固定 `lookback=256`，分别对独立 `pred_len ∈ {1,3,5,10,15,30}`、若干 `micro_batch_size`（如 1、8、16、32）跑真实历史数据，记录各 horizon 的 P50/P95 延迟和吞吐（symbols/秒）；
2. 用 $T_{batch}\approx\frac{N_{symbols}}{\text{throughput(symbols/s)}}$ 估算覆盖目标股票池所需时间；
3. 与可用批处理窗口（例如收盘数据结算后到次日开盘前）比较，判断能否覆盖目标股票池；
4. 把结果连同硬件型号、核数、`torch`/`OMP` 线程配置一并记录到 [`finetune_csv/bench_cpu_capacity.py`](新增) 的产出文件中，作为后续容量决策的依据，不能只凭一次性口头结论。

### 9.4 CPU 线程与并发配置

- 单进程常驻模型，显式调用 `torch.set_num_threads(物理核数)`，并设置 `OMP_NUM_THREADS`/`MKL_NUM_THREADS` 环境变量，避免和同机的 Quantia 行情抓取、指标计算等任务抢核；
- `predict_batch()` 已经把多只股票的矩阵运算合并成一次前向调用，是 CPU 上最有效的并行方式；不要再叠加线程池或多进程重复调用同一模型实例，那样只会造成核心争抢、拖慢整体吞吐（呼应 4.2 节）；
- 如确需水平扩展（例如按股票池分片、每个分片一个独立进程），必须显式限制每个进程的线程数，确认所有进程线程数之和不超过物理核数，且总内存不超过机器可用内存（单进程内存 × 进程数）；
- 容器化部署（Docker/K8s）必须显式设置 CPU limit，并提前固定线程数环境变量；否则 PyTorch 默认按宿主机核数分配线程，在共享节点上会过度订阅，拖慢所有共享该节点的服务。

### 9.5 分层部署策略

在完成 9.3 的实测之前，不应默认承诺"CPU 可以覆盖全市场夜间批量"。建议按下列优先级分层，具体分界点由实测吞吐决定：

- **Tier 1（核心关注股票池，如 100～300 只自选/重点标的）**：若保持当前生产语义，CPU 每日分别执行 1/3/5/10/15/30 日请求；若容量不足，只能明确缩减 horizon，不能偷换成一条 30 日路径后沿用原指标名称；可选叠加 C1。
- **Tier 2（全市场其余标的）**：若实测吞吐不足以覆盖全市场夜间批次，按成本从低到高降级：
  1. 缩小 horizon 集合（例如只保留 1 日和 5 日）；
  2. 降低批频率（Tier 1 每日，Tier 2 每周）；
  3. 评估体积更小的 Kronos-small 是否能满足精度要求，以降低单步计算量（需要额外验证，当前仓库默认权重是 base）；
  4. 增加一台 GPU 节点专门跑全市场批次，CPU 节点只保留 Tier 1 与按需请求；
  5. 全市场其余标的改用开销远低于生成式 Transformer 的传统因子/C1 打分，Kronos 蜡烛预测只保留给 Tier 1。

该分层不是最终结论，必须先完成 9.3 的实测，再确定具体股票数量和 micro-batch 参数。

### 9.6 风险与缓解

- **长尾延迟**：进入张量 micro-batch 后无法对单个标的设置可中断超时。必须先完成历史长度、有限值、价格基准连续性等预校验；整批设置超时/看门狗，失败后缩小 micro-batch 或逐标的隔离重试。
- **内存增长**：常驻服务需要监控 RSS，超过阈值应告警并考虑重启或降低并发；
- **与 Quantia 同机资源竞争**：若 Kronos 服务与 Quantia Web/Cron 部署在同一台 Linux 机器，需要用 cgroup 或进程优先级隔离，防止批量推理挤占实时 Web 请求；
- **时区一致性**：容器时区必须设为 `Asia/Shanghai`，否则 `_completed_daily_cutoff`/`is_post_settlement` 等基于本地时间的判断会发生偏移。

### 9.6.1 2026-07-14 Windows CPU OOM 复盘与修复

H2 网格运行至约 61% 时出现系统级 OOM。原子 checkpoint 审计确认已完成配置和未完成配置的已落盘任务均为合法 JSON、任务键唯一且无 provider error，因此无需整批重跑；重启服务后使用同一输出目录和 `--resume` 可从最后任务键继续。

根因证据如下：

1. OOM 前 Kronos 服务进程 Private Bytes 约 36.3 GB，而 Working Set 仅约 0.5 GB，Windows 剩余虚拟内存约 1.3 GB；故障来自进程提交内存/pagefile 额度耗尽，而非单纯物理内存常驻集过大。
2. 服务进程始终只有 2 个线程、约 328 个句柄，排除 `ThreadingHTTPServer` 线程或句柄持续泄漏。
3. 重启后完成约 23 个 `sample_count=20` 请求，Private Bytes 从约 0.9 GB 抬升到 3.84 GB；随后完成约 100 个同类请求只升到约 3.97 GB。增长呈“新张量形状触发阶梯高水位、同形状随后平台化”，不符合 Python 对象按请求线性泄漏特征。
4. Kronos-base 为 12 层、`d_model=832`、`ff_dim=2048`。自回归每一步都会对完整上下文重算注意力和 FFN，且 `sample_count` 会直接复制输入批次。H2 依次切换 `lookback × sample_count × horizon`，PyTorch 2.12.1 CPU 后端在 Windows 上保留不同形状的大块原生工作区，长进程累计高水位最终耗尽提交额度。

已在 Kronos 侧实现以下修复，待下一次服务启动生效：

- `sample_count` 继续表示总随机路径数，但新增内部 `sample_batch_size`，默认 5；例如 20 路按 `5+5+5+5` 分块、10 路按 `5+5` 分块，最终按各块样本数加权平均。统计语义和请求/响应审计值不变，Transformer 主要中间张量的峰值批次由 20 降至 5。
- 推理上下文由 `torch.no_grad()` 改为 `torch.inference_mode()`，减少推理元数据。
- `sample_batch_size`、服务实现和核心推理代码进入 `runtime_version`，并参与组合 `model_version` 哈希；不同运行时不能在 artifact 门禁中静默混用。
- 聚焦回归已通过 20 个测试和 3 个子测试，并覆盖分块序列、加权均值及运行时指纹变化。

运行约束：正在执行的正式实验不得中途重启到新运行时，否则会触发 mixed model/runtime version 并失去可比性。旧运行时若再次逼近提交内存阈值，只能在 checkpoint 后重启同一旧版本进程并续跑；新分块运行时必须先做 300～500 请求稳定性压测，再用于下一轮正式实验。生产部署还应增加 Private Bytes/RSS 与系统 commit 余量监控，达到软阈值时停止接收新批任务并受控回收进程。

## 10. 推荐模块与配置

### 10.0 参数化与近似最优预设

控制面允许先使用“近似最优预设”打通影子预测、监控和评估链路，但该预设必须满足以下约束：

- 状态固定为 `shadow/not_qualified`，不能显示为已验证生产冠军，也不能参与交易决策；
- `lookback/sample_count/temperature/top_k/top_p/clip/horizons/sample_batch_size` 全部由版本化配置提供，不在 Handler、任务或前端硬编码；
- 保存配置时生成稳定 `config_hash`，历史批次继续引用原配置，修改参数创建新版本，不覆盖旧事实；
- 参数搜索只可产生 challenger；晋级 champion 仍需独立 holdout、完整 artifact 门禁与人工审批；
- 当前近似预设采用短上下文、中等采样方向：`lookback=48, sample_count=10, temperature=0.9, top_k=0, top_p=0.85, clip=5.0, horizons=[1,3,5], sample_batch_size=5`。它用于工程联调，不代表 H2 最终胜出；H2 完整结果出来后可通过配置替换，无需改代码。

Phase 2 控制面 MVP 先提供：配置读取/原子保存、参数边界校验、Kronos 健康与运行时指纹、Phase 1 artifact 汇总、批次进度与门禁结果、响应式前端总览和参数编辑。四张事实表、EOD 批量任务、到期评估和聚合任务仍按 Phase 2～3 顺序接入；在生产 schema 未核对和迁移未部署前，Web Handler 不直接创建表或执行猜测字段的 SQL。

### 10.1 Kronos 侧

已落地：

- `local_kpred_service.py`：请求级 `lookback`（32～`max_context`）、predictor/tokenizer 独立指纹及组合 `model_version`；
- 现有单只端点仍为 `/v1/open-api/kpred` 和 `/v1/kline/predict`。

Phase 2 仍待新增：

- `finetune_csv/rolling_forecast_validator.py`：历史锚点生成式回放；
- `finetune_csv/evaluation_metrics.py`：OHLC/收益/截面指标；
- `finetune_csv/parameter_search.py`：候选试验编排；
- `finetune_csv/bench_cpu_capacity.py`：CPU-only 容量测算脚本（见 9.3）；
- 本地服务 `/v1/kline/predict-batch`：当前不存在；待按 micro-batch 推理并返回逐标的状态后，才能开始 Phase 2 全市场容量验收。

`finetune_csv/pipeline/forecast_evaluation.py` 已支持对**一条固定预测路径**按 step 评测，适合 path-mode 研究，但不能替代当前生产等价的独立 horizon 请求。其可执行入口为：

```bash
python finetune_csv/evaluate_kpred_results.py \
  --prediction-json runs/predictions/300308_20260713.json \
  --actual-csv DataSet/actual/300308.csv \
  --horizons 1,3,5,10,15,30 \
  --output runs/evaluation/300308_20260713.json
```

输入预测 JSON 使用本地服务的响应契约；真实 CSV 至少包含 `date/open/high/low/close`。尚未到期或缺失的真实交易日输出 `pending`，不会被当作错误或分母中的命中；预测路径不足则输出 `not_predicted`。聚合结果按 horizon 分别给出覆盖率、Close MAE/sMAPE、收益 MAE、方向准确率和 OHLC 合法率，可直接映射到第 5 章数据表与第 8 章图表。

复用：

- `model/kronos.py::KronosPredictor.predict_batch`；
- `finetune_csv/pipeline/splits.py::rolling_date_splits`；
- `finetune_csv/train_c1_bundle.py` 中的 IC/RankIC/Hit 计算；
- `finetune_csv/local_kpred_service.py` 的模型加载、配置和质量门禁。

### 10.2 Quantia 侧

Phase 2 控制面 MVP 已落地：

- `quantia/kronos/runtime_config.py` + `runtime_config.json`：近似预设、严格参数边界、稳定 `config_hash`、Windows 兼容原子保存；未合格配置不能启用自动批量或切换到 canary/production。
- `quantia/kronos/monitor.py`：只读扫描 Phase 1 manifest/artifact，汇总配置进度、observed/provider error/参数审计和三层门禁，不在 Web 请求中重算模型指标。
- `quantia/web/kronosMonitorHandler.py`：提供 `/config`、`/monitor/overview`、`/monitor/runs`、`/monitor/health` 四个接口；健康接口只查询本地 Kronos 服务，不访问外部行情源。
- `quantia/fontWeb/src/views/kronos-monitor/`：参数预设、运行批次和候选门禁三个工作区；桌面使用表格，移动端使用卡片，并明确显示“未通过门禁、不参与交易决策”。
- 页面注册在“选股验证 -> Kronos 验证”，而非生产选股入口。后续四张事实表上线时保持现有 API 契约，将 artifact 聚合实现替换为数据库聚合查询即可。

控制面只解决“可配置、可观察、可审计”，不代表 Phase 2 数据闭环已经完成。EOD 批量预测、预测事实入库、到期评估、20/60/120 日聚合、Cron 和人工晋级审批仍按 Phase 2～4 顺序实现；在这些能力验收前 `enabled` 保持 false。

Phase 1 已落地：

- `quantia/kronos/rolling_validation.py`：锚点切片、独立 horizon 调用、状态记录、random-walk 基线和分组汇总；
- `quantia/job/kronos_rolling_validation_job.py`：只读缓存/DB 的 CLI，支持代码列表、锚点范围、lookback/horizon、固定 `actual_end` 和原子 JSON 输出；
- `tests/test_kronos_rolling_validation.py`：独立请求、停牌、错误响应与基线契约；
- `runs/kronos_validation/`：本地审计产物目录，已加入 `.gitignore`，不是事实数据库。

真实烟测命令：

```bash
python -m quantia.job.kronos_rolling_validation_job \
  --codes 300308 \
  --anchor-start 2026-06-30 --anchor-end 2026-06-30 \
  --lookbacks 64 --horizons 1,3 --anchor-step 1 \
  --actual-end 2026-07-10 \
  --output runs/kronos_validation/smoke_300308_20260630.json
```

已验证输出 2 条 `observed`：目标日 2026-07-01、2026-07-03，覆盖率均为 100%。该结果只证明执行链和日期对齐正确，不构成准确率通过。

Phase 2～3 待新增：

- `quantia/job/kronos_batch_prediction_job.py`；
- `quantia/job/kronos_prediction_evaluation_job.py`；
- `quantia/job/kronos_metric_aggregation_job.py`；
- `cron/cron.workdayly/run_kronos_batch_prediction`；
- `cron/cron.workdayly/run_kronos_prediction_evaluation`；
- `quantia/web/kronosMonitorHandler.py`：第 8 章可视化面板的只读聚合接口；
- `quantia/fontWeb/src/views/kronos-monitor/`：第 8 章可视化面板前端页面；
- 表结构和迁移脚本，以及必要的只读查询 API。

配置建议扩展：

```yaml
batch:
  enabled: false
  schedule_after: "18:30"
  horizons: [1, 3, 5, 10, 15, 30]
  micro_batch_size: 16
  min_history: 276
  persist_json: true
  resume_failed: true

rolling_validation:
  enabled: false
  anchor_step_days: 5
  history_years: 2
  horizons: [1, 3, 5, 10, 15, 30]
  lookbacks: [90, 128, 256, 384, 512]
  min_symbols: 100
  embargo_days: 10

promotion:
  min_mature_trade_days: 60
  min_coverage: 0.95
  require_human_approval: true
```

这些段落初始必须保持 `enabled: false`，待实现和测试后再启用。

## 11. 分阶段实施计划

### Phase 1：离线滚动验证（MVP 已落地）

已交付：

- 生产等价的独立 horizon 历史锚点回放；
- 逐记录 Close MAE/sMAPE、收益 MAE、方向、random-walk 基线；
- `observed/not_traded/actual_missing/provider_error` 状态及稳定 `error_code`；
- 成熟/未成熟锚点审计计数、运行中模型版本集合与混合版本标记；
- 模型/tokenizer 指纹、lookback、实际数据截止日和配置哈希；
- 原子 JSON 审计产物与真实模型烟测。
- 参数网格协调、每配置独立子进程与原子 manifest；
- 采样参数审计、增量检查点、同配置断点续跑和 provider_error 替换重试。

仍待扩展：

- 大股票池 1/3/5/10/15/30 全量运行；
- 行业/波动率/市场状态分组和 block bootstrap 置信区间；
- 固定股票池局限说明；
- 采样参数候选的大股票池复验与统计显著性报告。

MVP 验收已通过：单股单锚点真实请求可重复运行、日期严格按交易日对齐、不读取锚点后的历史输入。完整 Phase 1 验收仍要求固定不可变数据快照并完成 100～300 股票池运行。

### Phase 2：小股票池批量预测

先用 20～100 只股票影子运行：

- 按第 9 章方法完成目标机型（尤其是 CPU-only Linux）的容量基准测试，确定初始 micro_batch_size 和预期吸吐量；
- 批量端点和 micro-batch；
- 四张表、幂等 upsert、断点恢复；
- EOD Cron；
- 逐标的错误分类和运行指标。

验收：重复执行不产生重复事实记录，单只失败不影响整批，服务重启后可续做。

### Phase 3：到期评估闭环

交付：

- pending 预测自动对齐真实值；
- 20/60/120 日聚合；
- 漂移告警；
- 第 8 章定义的滚动验证/准确率评估/冠军挑战者可视化面板上线。

验收：停牌、缺失、复权修订和跨节假日场景均有明确状态；面板能实时反映这些状态。

### Phase 4：受控动态调优

交付：

- 参数搜索试验注册表；
- 周度候选、月度晋级；
- shadow/canary/production 状态；
- 人工审批和一键回滚。

验收：任何生产版本都能追溯到模型、配置、代码、数据和完整评估证据。

## 12. 最终建议

1. 先实现 Phase 1，不要直接做自动调参。当前最重要的问题是建立可信、无泄漏的业务指标基线。
2. 批量预测首期只做影子记录，不参与交易决策；至少积累 60 个到期交易日后再讨论晋级。
3. 采用 Quantia 编排与持久化、Kronos 专注推理的边界。部署形态不预设 GPU：CPU-only Linux 在功能上可行，但全市场夜间批量的吸吐量必须先用第 9 章的方法实测，不能默认假定 CPU 能覆盖全市场；实测不足时优先采用分层部署（重点股票池每日全 horizon，其余股票降频或降级为轻量因子评分），而不是预先采购 GPU。
4. 线上当前仍使用 `lookback=256`、确定性生成，但它只能称为现状基线，不能称为已通过的生产冠军。本轮真实单股到期结果显示其短期方向虽命中、3/5 日幅度严重失真；仓库也没有“base 模型 30 步 golden 准确率通过”的测试。是否保留 256 必须由独立 horizon 滚动证据和目标 Linux 机型容量测试共同决定。
5. C1 继续关闭。只有新的 5 日 walk-forward IC/RankIC 和影子结果通过门禁后才能启用。
6. 动态调优应是“自动发现候选、自动验证、人工晋级”，而不是“自动改参数并上线”。
7. 滚动调优数据、准确率评估、漂移监控必须有第 8 章描述的可视化面板支撑，不能只依赖 JSON 报告文件人工比对。
