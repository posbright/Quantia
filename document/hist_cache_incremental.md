# 历史数据增量缓存功能说明

## 功能概述

本功能实现了股票历史K线数据的增量更新缓存机制，主要特点：

1. **增量更新**：以天为单位追加更新历史数据，避免每次全量获取
1. **多数据源**：优先使用东方财富，备选腾讯财经、新浪财经，自动容错切换
3. **自定义范围**：用户可以指定历史数据的获取年数或日期范围
4. **自动清理**：支持定期清理过期缓存数据（退市股票、除权除息数据）
5. **数据格式统一**：所有数据源输出统一为：volume=手、amount=元、date=YYYY-MM-DD

## 核心函数

### 1. `stock_hist_cache_incremental(code, date_start, date_end, is_cache=True, adjust='')`

增量更新的股票历史数据缓存函数。

**参数：**
- `code`: 股票代码，如 "000001"
- `date_start`: 起始日期，格式 YYYYMMDD
- `date_end`: 结束日期，格式 YYYYMMDD
- `is_cache`: 是否使用缓存，默认 True
- `adjust`: 复权类型，"qfq"前复权，"hfq"后复权，""不复权

**工作流程：**
1. 检查缓存是否存在
2. 如果有缓存，读取缓存中的最后日期
3. 只获取缓存最后日期之后的增量数据
4. 合并增量数据到缓存
5. 保存更新后的缓存

**数据源优先级：**
1. 东方财富 (`stock_hist_em.py`)
2. 腾讯财经 (`stock_hist_tencent.py`)
3. 新浪财经 (`stock_hist_sina.py`)

**数据格式统一标准：**
- 列顺序：[date, open, close, high, low, volume, amount, amplitude, quote_change, ups_downs, turnover]
- volume 单位：手（100股）
- amount 单位：元
- date 格式：YYYY-MM-DD

### 2. `fetch_stock_hist(data_base, date_start=None, date_end=None, is_cache=True, years=None)`

获取股票历史数据的高级接口。

**参数：**
- `data_base`: 元组 (日期, 股票代码)
- `date_start`: 起始日期，默认根据 years 计算
- `date_end`: 结束日期，默认当前日期
- `is_cache`: 是否使用缓存
- `years`: 历史数据年数，默认 10 年（通过环境变量 `HIST_DATA_DEFAULT_YEARS` 调整）

### 3. `clean_expired_cache(expire_days=None)`

智能清理缓存文件：
- 删除已退市股票（不在当前股票列表中）的缓存
- 刷新近 35 天内除权除息股票的前复权缓存
- 删除损坏的 `.meta` 文件
- 自动跳过 `index/` 子目录（指数缓存不受退市清理影响）

**参数：**
- `expire_days`: 兼容参数，不再使用（保留以避免调用方报错）

### 4. `update_index_caches(date_start, date_end, index_codes=None)`

批量更新指数K线缓存（~15个主要指数）。

**特性：**
- meta 预检查：已最新的指数自动跳过（零 API 调用）
- 延迟可配置：`QUANTIA_INDEX_DELAY_MIN/MAX`
- 缓存目录：`cache/hist/index/`

## 配置参数

在 `stockfetch.py` 中可配置：

```python
# 数据源重试配置
DATA_SOURCE_MAX_RETRIES = 2      # 最大重试次数
DATA_SOURCE_RETRY_INTERVAL = 90  # 基础重试间隔（秒），实际使用指数退避（Docker默认30秒）

# 历史数据配置
HIST_DATA_DEFAULT_YEARS = 10     # 默认获取历史数据年数（Docker默认3年）
# 缓存清理由 clean_expired_cache() 智能管理（清理已退市股票、除权除息股票缓存）
```

## 缓存目录结构

```
quantia/cache/hist/
├── index/                   # 指数K线缓存
│   ├── 000001.gzip.pickle  # 上证指数
│   ├── 000001.meta
│   ├── 399001.gzip.pickle  # 深证成指
│   └── ...
├── 000/                    # 按股票代码前3位分组
│   ├── 000001.gzip.pickle  # 压缩的缓存数据
│   ├── 000001.meta         # 缓存元数据（最后更新日期）
│   ├── 000002.gzip.pickle
│   └── 000002.meta
├── 600/
│   ├── 600000.gzip.pickle
│   └── 600000.meta
└── ...
```

## 使用示例

```python
import datetime
import quantia.core.stockfetch as stf

# 示例1: 使用默认配置（3年历史数据）
data_base = (datetime.datetime.now(), '000001')
df = stf.fetch_stock_hist(data_base)

# 示例2: 自定义日期范围
df = stf.fetch_stock_hist(data_base, date_start='20230101', date_end='20231231')

# 示例3: 自定义年数
df = stf.fetch_stock_hist(data_base, years=5)

# 示例4: 直接使用增量缓存函数
df = stf.stock_hist_cache_incremental('000001', '20240101', '20240630')

# 示例5: 清理过期缓存
cleaned = stf.clean_expired_cache()
print(f'清理了 {cleaned} 个过期缓存文件')

# 示例6: 更新指数K线缓存
success, fail = stf.update_index_caches(date_start='20240101', date_end='20240630')
print(f'指数缓存更新：成功 {success}，失败 {fail}')
```

## 数据源模块

### 东方财富历史数据 (`stock_hist_em.py`)

```python
from quantia.core.crawling.stock_hist_em import stock_zh_a_hist

df = stock_zh_a_hist(
    symbol="000001",
    period="daily",      # daily, weekly, monthly
    start_date="20240101",
    end_date="20240630",
    adjust=""            # "", "qfq", "hfq"
)
```

### 腾讯财经历史数据 (`stock_hist_tencent.py`)

```python
from quantia.core.crawling.stock_hist_tencent import stock_zh_a_hist_tencent

df = stock_zh_a_hist_tencent(
    symbol="000001",
    period="daily",      # daily, weekly, monthly
    start_date="20240101",
    end_date="20240630",
    adjust=""            # "", "qfq", "hfq"
)
```

### 新浪财经历史数据 (`stock_hist_sina.py`)

```python
from quantia.core.crawling.stock_hist_sina import stock_zh_a_hist_sina

df = stock_zh_a_hist_sina(
    symbol="000001",
    period="daily",      # daily, weekly, monthly
    start_date="20240101",
    end_date="20240630",
    adjust=""            # "", "qfq", "hfq"
)
```

## 手动拉取历史数据

### 方式一：使用 fetch_data_job.py（推荐）

```bash
cd quantia/job

# 拉取当前交易日的最新数据（增量更新）
python fetch_data_job.py

# 指定日期拉取
python fetch_data_job.py 2024-06-15
```

### 方式二：通过环境变量调整获取年数

```bash
# 默认10年，Docker默认3年
# Windows:
set HIST_DATA_DEFAULT_YEARS=10
python fetch_data_job.py

# Linux/Mac:
export HIST_DATA_DEFAULT_YEARS=10
python fetch_data_job.py
```

### 方式三：强制重建全部缓存

```bash
# ⚠️ 清空缓存后重新获取（耗时较长）
# Windows:
rd /s /q quantia\cache\hist
# Linux/Mac:
rm -rf quantia/cache/hist

cd quantia/job && python fetch_data_job.py
```

### 方式四：Docker 环境手动拉取

```bash
docker exec -it Quantia bash
cd /data/Quantia/quantia/job

# 拉取最新数据
python fetch_data_job.py

# 调整历史年数
HIST_DATA_DEFAULT_YEARS=5 python fetch_data_job.py
```

## 性能优势

1. **减少网络请求**：增量更新只获取新数据，减少API调用
2. **提高响应速度**：缓存命中时直接返回本地数据
3. **数据源容错**：多数据源自动切换，提高可用性
4. **存储优化**：使用gzip压缩，节省磁盘空间

## 注意事项

1. 缓存数据按股票代码组织，而非按日期
2. 增量更新以天为单位，每次只获取缺失的交易日数据
3. 元数据文件记录最后更新时间，用于缓存过期判断
4. 建议定期调用 `clean_expired_cache()` 清理过期缓存
