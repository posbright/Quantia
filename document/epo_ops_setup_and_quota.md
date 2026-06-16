# EPO OPS 注册与配额说明

> 面向 Quantia 专利 IPC 主备源 [`epo_ops_crawler.py`](../quantia/core/crawling/epo_ops_crawler.py) 的接入手册。
> EPO OPS（European Patent Office — Open Patent Services）是欧洲专利局官方、**免费**的 RESTful
> 专利数据服务，DOCDB 全球库**含中国（CN）专利**，带 IPC/CPC 分类、引用、同族等结构化字段，
> 是替换 / 主备 Google Patents 抓取 IPC 饼图与趋势的首选源（结论见
> [`patent_data_coverage_and_pipeline.md` §6](patent_data_coverage_and_pipeline.md)）。

---

## 1. 注册步骤（一次性，约 10 分钟）

1. 打开 OPS 开发者门户：<https://developers.epo.org/>（或 <https://www.epo.org/searching-for-patents/data/web-services/ops.html>）。
2. **注册账号**（"Register" / "Sign up"），用邮箱激活。免费档无需企业资质、无需付费。
3. 登录后进入 **"My Apps" / "Registered services"**，点击 **"Add app" / 新建应用**。
4. 应用创建后获得一对凭证：
   - **Consumer Key**（消费者密钥）
   - **Consumer Secret**（消费者密钥的密文）
5. 记录这对 Key/Secret——它们就是 OAuth2 `client_credentials` 的客户端凭证。
6. （可选）在控制台勾选/订阅 **OPS** 这个 API 产品，确保该 App 有 OPS 调用权限。

> OPS 当前版本为 **3.2**，REST 根地址 `https://ops.epo.org/3.2/`。注册门户偶尔改版，
> 但"注册账号 → 建 App → 拿 Consumer Key/Secret"这个流程始终不变。

---

## 2. 配置到 Quantia（环境变量）

crawler 通过两个环境变量读取凭证，**缺任一则整源静默禁用**（不报错、不影响年报主源与行业保底）：

| 变量 | 含义 | 必填 |
|------|------|------|
| `QUANTIA_EPO_OPS_KEY` | OPS Consumer Key | ✅ |
| `QUANTIA_EPO_OPS_SECRET` | OPS Consumer Secret | ✅ |
| `QUANTIA_EPO_OPS_INTERVAL` | 每次检索后 sleep 秒数（限流友好），默认 `2` | ❌ |
| `QUANTIA_EPO_OPS_CACHE_DAYS` | 本地结果缓存有效天数，默认 `90` | ❌ |
| `QUANTIA_EPO_OPS_CACHE_DIR` | 缓存目录，默认 `~/.quantia/epo_ops` | ❌ |

写入项目根目录 `.env`（`quantia/lib/envconfig.py` 启动时统一加载）：

```bash
# .env
QUANTIA_EPO_OPS_KEY=你的ConsumerKey
QUANTIA_EPO_OPS_SECRET=你的ConsumerSecret
# 可选调优
# QUANTIA_EPO_OPS_INTERVAL=2
# QUANTIA_EPO_OPS_CACHE_DAYS=90
```

> ⚠️ `.env` 含密钥，**勿提交到 git**（仓库 `.gitignore` 已排除 `.env`）。服务器单独配置。

验证是否生效：

```bash
cd /root/Quantia && source quantia_env/bin/activate
python -c "from quantia.core.crawling import epo_ops_crawler as e; print('enabled=', e.is_enabled())"
# enabled= True  → 凭证已读到；False → 检查 .env 是否两个变量都填了
```

---

## 3. 鉴权机制（crawler 已封装，了解即可）

- **OAuth2 `client_credentials`**：`POST https://ops.epo.org/3.2/auth/accesstoken`，
  请求头 `Authorization: Basic base64(Key:Secret)`，body `grant_type=client_credentials`。
- 返回 `access_token`（Bearer）+ `expires_in`（通常 1200s / 20 分钟）。
- crawler 在内存缓存 token，**提前 60s 过期**自动刷新；检索遇 `401` 强制刷新重试一次。
- 凭证错误 / 网络异常 / 非 200 → 返回 `None`，调用方优雅跳过（不抛出）。

---

## 4. 配额与限流（免费档）

EPO OPS 免费档（"Free / anonymous-registered"）的核心额度：

| 维度 | 免费档额度（官方口径，可能随政策调整）|
|------|------|
| **流量配额** | 约 **4 GB / 周**（按返回数据字节计；biblio 检索每次仅几十~几百 KB，足够日常）|
| **请求节流** | 服务端按出口 IP / token 滑动限流；突发过快会返回 `403`/`429`，需退避 |
| **单页结果** | biblio 检索单页上限 **100** 条（`X-OPS-Range` / `Range: 1-100`）|
| **配额超限** | 返回 `403` + `X-Rejection-Reason` 头（如 `RegisteredQuotaPerWeek` / `IndividualQuotaPerHour`）|

实务建议：

- crawler 默认 `QUANTIA_EPO_OPS_INTERVAL=2`（每次检索后 sleep 2s）+ 90 天结果缓存，
  正常单只股票一次检索 ≈ 1 个请求，远不会触达周配额。
- 全市场批量（~5000 只）建议**分批、错峰**跑，避免单 IP 短时密集请求触发小时级限流。
- 命中 `403 X-Rejection-Reason: *QuotaPer*` 时应**停止当批、等下个配额周期**，而非盲目重试。
- 配额按字节计：只取 biblio（书目）而非全文，已是最省流量的取法（crawler 走 `published-data/search/biblio`）。

> 若日常配额不够，EPO 提供**付费/认证档**（更高配额、可签 SLA），需在门户升级账号；
> 但对 Quantia 的"季度增量补 IPC"用量，免费档通常已足够。

---

## 5. 用法（接入后）

```bash
cd /root/Quantia && source quantia_env/bin/activate

# 单只验证（先小批，确认凭证与解析 OK）
python -m quantia.job.fetch_patent_data --source epo_ops --code 000157 --years 2024

# 季度增量补 IPC / 趋势（替代或与 Google Patents 互为冗余）
python -m quantia.job.fetch_patent_data --source epo_ops
```

- 数据写入 `cn_stock_patents`，`data_source='epo_ops'`，`confidence_score=85`。
- 与年报权威数量字段（`confidence=95`）合并时，**只补 IPC/引用/趋势/PCT**，不覆盖年报总数
  （遵循 master/slave 守卫）。
- 同 Google 路径一样依赖 `get_company_names(code)` 把上市公司简称映射到专利申请人全称——
  这是所有外部专利源共同的命中率瓶颈（见 §6 文档）。

---

## 6. 故障排查

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| `is_enabled()=False` | `.env` 缺 KEY 或 SECRET | 两个变量都要填；确认 `envconfig` 已加载 `.env` |
| 取 token HTTP 403/401 | Key/Secret 错 或 App 未订阅 OPS | 门户核对凭证、确认 App 已加 OPS 产品 |
| 检索 403 + `X-Rejection-Reason` | 触发周/小时配额 | 等配额周期；降低批量与频率；加大 `INTERVAL` |
| 检索 404 / 空结果 | 申请人全称未命中 CN 库 | 优化 `get_company_names`（补子公司/全称）|
| 解析 IPC 为空 | OPS 返回结构无 `classification-ipcr` | 正常（部分文献无 IPC）；crawler 已防御式跳过 |

---

## 7. 安全与合规

- 凭证仅放服务器 `.env`，不入库、不进日志、不提交 git。
- 遵守 EPO OPS [Fair Use / Terms of Use](https://www.epo.org/)：合理频率、不绕过配额、不二次分发原始数据。
- 属 Fetch 管道（AGENTS.md 规则 1）：仅在 job / crawler 内联网，**不得**在 Web handler / 分析 job 里直连。
