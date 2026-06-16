# 专利 / 护城河数据管道：覆盖率诊断与运维手册

> 2026-06 排查产出。回答"为什么每天都在采集专利，但股票详情页『知识产权/护城河』卡片几乎全是空白"。

## 1. 现象

指标详情页 [`PatentCard.vue`](../quantia/fontWeb/src/components/PatentCard.vue) 对绝大多数股票显示
"暂无专利数据"；即便少数有数据，IPC 饼图与近 5 年趋势图也空白。

## 2. 根因（已用生产库证实）

| 环节 | 事实 |
|---|---|
| 前端只读一张表 | `PatentCard` → `GET /quantia/api/stock/patents` → 读 `cn_stock_patents` 最权威年份 |
| 覆盖率极低 | `cn_stock_patents` 仅 **131 / 4928 只 (2.7%)** 有行 → 97% 股票命中空状态 |
| 有行的也"薄" | 131 行里 130 行 `confidence=70`（每日公告聚合），仅 1 行 `confidence=95`（真实年报解析） |
| 图表字段缺失 | 公告聚合行 `ipc_primary` / `tech_domain` / `trend_5y` 全 NULL → 图表必然空白 |
| 计数失真 | 源表 `cn_stock_patent_info.patent_count` 全 NULL → 聚合 `COALESCE(...,1)` → `total_patents` 实为"公告条数" |
| 主源此前 100% 失败 | `fetch_patent_data.py` 解析年报 PDF 依赖 `pdfplumber`，运行环境**未安装** → parse 全部抛错 → 入库 0 股 |
| 标签错误 | 聚合写入未显式设置 `data_source`，继承列 DEFAULT `annual_report` → 公告行被误标为年报 |

**一句话**：前端依赖的权威全市场源（年报解析）因缺 `pdfplumber` 从未成功，只剩每日公告聚合
产出的薄数据覆盖 2.7%，且这些薄行没有图表所需字段。

## 3. 数据管道

```
                         每工作日                            每年 5 月 / 每季度
 巨潮公告搜索                                巨潮年报 PDF + Google Patents
 stock_patent_crawler.py                     fetch_patent_data.py
        │ 写                                          │ 写 (confidence=95)
        ▼                                              ▼
 cn_stock_patent_info  ──聚合(confidence=70)──►  cn_stock_patents  ◄── 前端只读这里
        aggregate_patent_data.py
```

- **Compute 管道**：`annual_report_parser.py`（不触网，正则解析 PDF 文本）。
- **Fetch 管道**：`stock_patent_crawler.py` / `fetch_patent_data.py` / `google_patents_crawler.py` / `epo_ops_crawler.py`（触网）。
- master/slave 守卫：聚合路径 `confidence=70`，遇到 `confidence>70` 的年报行不覆盖其数量/趋势字段。

## 4. 本次修复（待提交）

1. **装回 `pdfplumber`**：[requirements.txt](../requirements.txt) 第 35 行早有声明，运行环境漏装是主源全失败的根因。
   装好后年报解析不再抛错。
2. **`data_source` 不再误标**：[`aggregate_patent_data._upsert_records`](../quantia/job/aggregate_patent_data.py)
   公告聚合行显式写 `data_source='announcement'`。
3. **PatentCard 取最权威年份**：[`stockPatentHandler._fetch_latest`](../quantia/web/stockPatentHandler.py)
   改 `ORDER BY confidence_score DESC, year DESC`，避免最新一年的薄公告盖住真实年报数据。
4. **年报抽取召回增强**：[`annual_report_parser.extract_patent_counts`](../quantia/core/crawling/annual_report_parser.py)
   新增大型公司常见表述：
   - `拥有/持有专利及专利申请(合计)?(达)? N 项`（宁德时代 43,354；此前被截断漏匹配）
   - `累计申请专利 N 件`（格力口径，>50000 仍由校验拦截）
5. **Google Patents 限流重试**：[`google_patents_crawler.search_patents`](../quantia/core/crawling/google_patents_crawler.py)
   对 429/503/5xx 做"换 IP + 指数退避"重试（上限 3 次），耗尽后优雅返回 `[]`。
6. **行业 → IPC 保底估算（防图表空白）**：新增 [`patent_industry_ipc.estimate_ipc_distribution`](../quantia/core/patent_industry_ipc.py)（Compute 管道，不触网）。
   当某股**已有真实 `total_patents`** 但 IPC 分布缺失时，[`stockPatentHandler._fill_estimated_ipc`](../quantia/web/stockPatentHandler.py)
   按 `cn_stock_selection.industry`（东财 F10 行业）→ 典型 IPC 大类构成 合成粗粒度饼图，
   响应带 `ipc_estimated=true` / `ipc_source='industry'` / `ipc_estimate_industry`，
   前端 [`PatentCard.vue`](../quantia/fontWeb/src/components/PatentCard.vue) 显示"按行业估算·{行业}"角标。
   **无真实专利数的股票不估算**（返回 null，保持诚实，不臆造数据）。
7. **EPO OPS 结构化主备源接入（§6 结论落地）**：新增 [`epo_ops_crawler.py`](../quantia/core/crawling/epo_ops_crawler.py)（Fetch 管道）。
   OAuth2 `client_credentials` 取 token（内存缓存）→ 按申请人 CQL `pa=` 检索 OPS biblio →
   防御式解析 IPC/国别/公开年 → 复用 `patent_ipc_mapping` 聚合 `ipc_primary/distribution/tech_domain/trend`
   （`data_source='epo_ops'`, `confidence=85`）。已接入 [`fetch_patent_data.py`](../quantia/job/fetch_patent_data.py)
   `--source epo_ops`（`process_epo_ops`）。**凭证缺失（`QUANTIA_EPO_OPS_KEY/SECRET`）时整源静默禁用**
   （`is_enabled()=False` → `fetch_and_aggregate` 返回 `{}` → skipped），不影响年报主源与行业保底。
   纯解析/聚合函数离线可测，单测 [`test_epo_ops_crawler.py`](../tests/test_epo_ops_crawler.py)（16 例，mock 网络）。
   **不持久化估算 IPC**：行业估算仍只在读取时合成、不入库，DB 中 IPC 字段为真实采集（EPO/Google）或 NULL。

### 4.1 本次验证 / 清理记录（生产库 `instockdb`）

- **实跑验证**：[`_verify_patent_fetch.py`](../_verify_patent_fetch.py) 选 6 只科技股跑 2024 年报：
  300750 宁德时代 `None→43354`（召回增强生效）、002475 立讯 7164、300059 东财 32 入库 ok；
  000651 格力 129524 被校验正确拦截（累计申请量）；002594 比亚迪 / 300760 迈瑞 年报未披露总数 → 跳过。
- **坏数据清理**：删除 131 行 `confidence=70 AND data_source='annual_report'`（公告聚合被误标、且为薄计数）。
  删除前全字段备份至 `_backup_patents_conf70_*.json`（可回滚）。清理后 `cn_stock_patents`
  仅余 5 行真实 `confidence=95` 年报数据。无真实数据的股票前端显示"暂无数据"而非误导性的"1 项"。
- **基本面选股股票池验证**（`cn_stock_spot_buy` 最新交易日 775 只）：抽 5 只跑 2024 年报 →
  000157 中联重科 `17849`、000513 丽珠集团 `722` 入库 ok（真实总数）；
  000333 美的 / 002001 新和成 / 002032 苏泊尔 年报未披露专利总数 → 诚实跳过（前端 `data:null`，不臆造）。
  黑盒接口校验：000157 → IPC 饼图 `{B23:30,F16:20,...}` tech_domain=机械/运输（按行业"专用设备"估算）；
  000513 → `{A61:55,C07:20,...}` tech_domain=生物医药（按"化学制药"估算），均带 `ipc_estimated=true` 角标。
  汇总 ok=2 / skipped=3 / failed=0，无错误、无伪造。

## 5. 已知限制（需后续投入，非一次性可解）

- **年报不含 IPC 代码**：真实 `ipc_primary` / `ipc_distribution` / `tech_domain`
  **只能**由专利结构化源（Google Patents / EPO OPS / Lens 等）填充；现已用"行业估算"保底，
  但估算为粗粒度经验值，需 UI 明确标注，不等于真实采集。
- **Google Patents 易被限流**：`patents.google.com/xhr/query` 实测在本地经代理池仍 503。
  重试退避能提高成功率但不保证；彻底可靠需服务器侧不同出口网络，或启用 Playwright 方案
  （crawler 已预留、未启用）。
- **大型公司披露口径**：年报多以"专利及专利申请"或"累计申请专利"披露（含未授权申请），
  数量远大于授权专利且 >50000 会被 `validate_patent_data` 拦截。属语义限制，非 bug。
- **公司简称 → 专利申请人全称**：所有外部专利源（含 Google/EPO/Lens）都需用申请人全称（含子公司）
  检索，上市公司简称命中率低——这是覆盖率与准确率的**真正瓶颈**，也是商业数据库（智慧芽/incoPat）
  的核心收费点。

## 6. IPC 数据来源对比（替换 / 备选 Google Patents 的结论）

> 针对"IPC 饼图 / 趋势图除 Google Patents 外的获取途径"的深入调研结论。

| 来源 | 免费 | CN 覆盖 + IPC | 接入方式 | 结论 |
|---|---|---|---|---|
| **EPO OPS / Espacenet** | ✅ 免费（注册 OAuth，~4GB/周配额） | DOCDB 全球库**含 CN**，带 IPC/CPC、引用、同族 | RESTful XML，官方 | **首选替换 / 主备选**：官方、免费、字段全 |
| **Lens.org API** | ✅ 免费注册档 | 全球含 CN，IPC/CPC | REST JSON | 良好二级备选 |
| PatentsView (USPTO) | ✅ 免费 | **仅美国** → A 股≈0 | REST JSON | 不适用 |
| CNIPA 专利检索系统 | ⚠️ 需登录/验证码 | 权威 CN 全量 | 无公开 API，反爬强 | ToS/反爬风险高，不建议爬 |
| 智慧芽 / incoPat / 佰腾 | ❌ 商业付费 | 最优质 + 子公司归集 | 商业 API | 仅在有预算时考虑 |
| 巨潮年报本体 | ✅ 已用 | **几乎不含 IPC 代码** | 已接 | 只能给总数/发明数，给不了 IPC |
| **行业 → IPC 经验映射（本次新增）** | ✅ 本地无网络 | 粗粒度估算，永不空白 | 纯查表 | **保底层**：低置信、需标注，防大面积空白 |

**结论与建议落地顺序：**

1. **保底层（已落地）**：`patent_industry_ipc` 行业映射 —— 只要有真实专利总数，IPC 饼图就不再空白。
2. **结构化主源（已落地，待配置凭证）**：[`epo_ops_crawler`](../quantia/core/crawling/epo_ops_crawler.py)
   已接入 **EPO OPS**（免费、官方、含 IPC/CPC/引用/同族），作为 Google Patents 的等价替换/主备选；
   OAuth client_credentials 取 token（内存缓存）、按申请人 CQL 检索、防御式解析 biblio JSON、
   复用 `patent_ipc_mapping` 聚合。**环境变量门控** `QUANTIA_EPO_OPS_KEY` / `QUANTIA_EPO_OPS_SECRET`，
   缺凭证则整源静默禁用、不影响年报源与行业保底。`fetch_patent_data.py --source epo_ops` 可调度。
   纯解析/聚合函数离线可测（`tests/test_epo_ops_crawler.py` 16 例全过）。
3. **二级备选**：**Lens.org** REST API，与 EPO 互为冗余。
4. **真正瓶颈**：无论用哪个源，都要先解决"上市公司简称 → 专利申请人全称(含子公司)"映射，
   否则命中率受限。可由年报"公司全称" + 工商关联补全，或引入商业归集（付费）。

### 6.1 基本面选股本地验证（2026-06-16）

从 `cn_stock_spot_buy`（基本面选股，最新日期 2026-06-15 共 753 只）抽样 5 只跑 Fetch 管道实跑写库：

| 代码 | 名称 | 年报专利总数 | 入库 | 端点 IPC 饼图（行业估算）|
|---|---|---|---|---|
| 000157 | 中联重科 | 17849（发明 7956）| ✅ ok | `{B23:30,F16:20,...}` 机械/运输（专用设备）|
| 000513 | 丽珠集团 | 722（发明 462）| ✅ ok | `{A61:55,C07:20,...}` 生物医药（化学制药）|
| 000333 | 美的集团 | 未披露 | ⏭ skipped | `data:null`（无真实数据不杜撰）|
| 002001 | 新和成 | 未披露 | ⏭ skipped | `data:null` |
| 002032 | 苏泊尔 | 未披露 | ⏭ skipped | `data:null` |

汇总 ok=2 / skipped=3 / failed=0：有真实总数的股票 IPC 饼图非空且分类正确，无真实数据的诚实返回
`null`（不杜撰）。EPO OPS 端到端取数需配置凭证后方可验证（本地无凭证 → 静默禁用，符合预期）。

## 7. 生产运维 Runbook（在 `115.29.213.22` / `/root/Quantia`）

```bash
cd /root/Quantia
source quantia_env/bin/activate

# ① 关键：确保 pdfplumber 已装（缺它年报解析全失败）
python -c "import pdfplumber; print(pdfplumber.__version__)" || pip install -r requirements.txt

# ② 小批验证解析成功率（写库少，可回看日志）
python -m quantia.job.fetch_patent_data --limit 20 --years 2024

# ③ 全市场最近 5 年（重任务，nohup 后台跑，约数小时）
nohup python -m quantia.job.fetch_patent_data > quantia/log/fetch_patent_full.log 2>&1 &
tail -f quantia/log/fetch_patent_full.log

# ④ 补 Google Patents 增量（填 IPC / 引用 / 趋势 = 图表数据）
python -m quantia.job.fetch_patent_data --source google_patents

# ④' 或用 EPO OPS 官方源补 IPC（需先配置 QUANTIA_EPO_OPS_KEY / QUANTIA_EPO_OPS_SECRET）
python -m quantia.job.fetch_patent_data --source epo_ops

# ⑤ 重新聚合（对齐公告数据并写正确 data_source）
python -m quantia.job.aggregate_patent_data

# ⑥ 重启 web 服务让 PatentCard 取到新数据
bash quantia/bin/restart_web.sh
```

> ⚠️ 本地开发机的 DB 指向**生产库** `115.29.213.22/instockdb`；在本地跑 `fetch_patent_data`
> 会直接写生产库，勿擅自全量。
