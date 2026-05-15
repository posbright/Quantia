# Quantia 数据库设计文档

## 一、数据库配置

### 1.1 连接配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `QUANTIA_DB_HOST` | `localhost` | 数据库服务主机 |
| `QUANTIA_DB_USER` | `root` | 数据库访问用户 |
| `QUANTIA_DB_PASSWORD` | 空 | 数据库访问密码 |
| `QUANTIA_DB_DATABASE` | `quantiadb` | 数据库名称 |
| `QUANTIA_DB_PORT` | `3306` | 数据库服务端口 |
| `QUANTIA_DB_CHARSET` | `utf8mb4` | 数据库字符集 |

### 1.2 环境变量配置

支持通过环境变量覆盖默认配置（用于 Docker 部署）：

```bash
export QUANTIA_DB_HOST=localhost
export QUANTIA_DB_USER=root
export QUANTIA_DB_PASSWORD=your_password
export QUANTIA_DB_DATABASE=quantiadb
export QUANTIA_DB_PORT=3306
```

---

## 二、创建数据库

```sql
-- 创建数据库
CREATE DATABASE IF NOT EXISTS `quantiadb`
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_general_ci;

-- 使用数据库
USE `quantiadb`;
```

已有数据库可通过 `QUANTIA_DB_DATABASE` 指定实际库名；新部署建议统一使用 `quantiadb`。

---

## 三、数据表结构

### 3.1 我的关注表 (cn_stock_attention)

存储用户关注的股票列表。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_attention` (
    `datetime` DATETIME NOT NULL COMMENT '关注时间',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    PRIMARY KEY (`datetime`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='我的关注';
```

| 字段 | 类型 | 说明 |
|------|------|------|
| datetime | DATETIME | 关注时间 |
| code | VARCHAR(6) | 股票代码 |

---

### 3.2 每日股票数据表 (cn_stock_spot)

存储每日股票行情数据，包含基本面信息。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_spot` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    `new_price` FLOAT COMMENT '最新价',
    `change_rate` FLOAT COMMENT '涨跌幅',
    `ups_downs` FLOAT COMMENT '涨跌额',
    `volume` BIGINT COMMENT '成交量',
    `deal_amount` BIGINT COMMENT '成交额',
    `amplitude` FLOAT COMMENT '振幅',
    `turnoverrate` FLOAT COMMENT '换手率',
    `volume_ratio` FLOAT COMMENT '量比',
    `open_price` FLOAT COMMENT '今开',
    `high_price` FLOAT COMMENT '最高',
    `low_price` FLOAT COMMENT '最低',
    `pre_close_price` FLOAT COMMENT '昨收',
    `speed_increase` FLOAT COMMENT '涨速',
    `speed_increase_5` FLOAT COMMENT '5分钟涨跌',
    `speed_increase_60` FLOAT COMMENT '60日涨跌幅',
    `speed_increase_all` FLOAT COMMENT '年初至今涨跌幅',
    `dtsyl` FLOAT COMMENT '市盈率动',
    `pe9` FLOAT COMMENT '市盈率TTM',
    `pe` FLOAT COMMENT '市盈率静',
    `pbnewmrq` FLOAT COMMENT '市净率',
    `basic_eps` FLOAT COMMENT '每股收益',
    `bvps` FLOAT COMMENT '每股净资产',
    `per_capital_reserve` FLOAT COMMENT '每股公积金',
    `per_unassign_profit` FLOAT COMMENT '每股未分配利润',
    `roe_weight` FLOAT COMMENT '加权净资产收益率',
    `sale_gpr` FLOAT COMMENT '毛利率',
    `debt_asset_ratio` FLOAT COMMENT '资产负债率',
    `total_operate_income` BIGINT COMMENT '营业收入',
    `toi_yoy_ratio` FLOAT COMMENT '营业收入同比增长',
    `parent_netprofit` BIGINT COMMENT '归属净利润',
    `netprofit_yoy_ratio` FLOAT COMMENT '归属净利润同比增长',
    `report_date` DATE COMMENT '报告期',
    `total_shares` BIGINT COMMENT '总股本',
    `free_shares` BIGINT COMMENT '已流通股份',
    `total_market_cap` BIGINT COMMENT '总市值',
    `free_cap` BIGINT COMMENT '流通市值',
    `industry` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '所处行业',
    `listing_date` DATE COMMENT '上市时间',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`),
    INDEX `idx_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='每日股票数据';
```

---

### 3.3 每日ETF数据表 (cn_etf_spot)

存储每日ETF行情数据。

```sql
CREATE TABLE IF NOT EXISTS `cn_etf_spot` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT 'ETF代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT 'ETF名称',
    `new_price` FLOAT COMMENT '最新价',
    `change_rate` FLOAT COMMENT '涨跌幅',
    `ups_downs` FLOAT COMMENT '涨跌额',
    `volume` BIGINT COMMENT '成交量',
    `deal_amount` BIGINT COMMENT '成交额',
    `open_price` FLOAT COMMENT '开盘价',
    `high_price` FLOAT COMMENT '最高价',
    `low_price` FLOAT COMMENT '最低价',
    `pre_close_price` FLOAT COMMENT '昨收',
    `turnoverrate` FLOAT COMMENT '换手率',
    `total_market_cap` BIGINT COMMENT '总市值',
    `free_cap` BIGINT COMMENT '流通市值',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='每日ETF数据';
```

---

### 3.4 股票资金流向表 (cn_stock_fund_flow)

存储股票资金流向数据，包含今日、3日、5日、10日资金流向。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_fund_flow` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    `new_price` FLOAT COMMENT '最新价',
    `change_rate` FLOAT COMMENT '今日涨跌幅',
    -- 今日资金流向
    `fund_amount` BIGINT COMMENT '今日主力净流入-净额',
    `fund_rate` FLOAT COMMENT '今日主力净流入-净占比',
    `fund_amount_super` BIGINT COMMENT '今日超大单净流入-净额',
    `fund_rate_super` FLOAT COMMENT '今日超大单净流入-净占比',
    `fund_amount_large` BIGINT COMMENT '今日大单净流入-净额',
    `fund_rate_large` FLOAT COMMENT '今日大单净流入-净占比',
    `fund_amount_medium` BIGINT COMMENT '今日中单净流入-净额',
    `fund_rate_medium` FLOAT COMMENT '今日中单净流入-净占比',
    `fund_amount_small` BIGINT COMMENT '今日小单净流入-净额',
    `fund_rate_small` FLOAT COMMENT '今日小单净流入-净占比',
    -- 3日资金流向
    `change_rate_3` FLOAT COMMENT '3日涨跌幅',
    `fund_amount_3` BIGINT COMMENT '3日主力净流入-净额',
    `fund_rate_3` FLOAT COMMENT '3日主力净流入-净占比',
    `fund_amount_super_3` BIGINT COMMENT '3日超大单净流入-净额',
    `fund_rate_super_3` FLOAT COMMENT '3日超大单净流入-净占比',
    `fund_amount_large_3` BIGINT COMMENT '3日大单净流入-净额',
    `fund_rate_large_3` FLOAT COMMENT '3日大单净流入-净占比',
    `fund_amount_medium_3` BIGINT COMMENT '3日中单净流入-净额',
    `fund_rate_medium_3` FLOAT COMMENT '3日中单净流入-净占比',
    `fund_amount_small_3` BIGINT COMMENT '3日小单净流入-净额',
    `fund_rate_small_3` FLOAT COMMENT '3日小单净流入-净占比',
    -- 5日资金流向
    `change_rate_5` FLOAT COMMENT '5日涨跌幅',
    `fund_amount_5` BIGINT COMMENT '5日主力净流入-净额',
    `fund_rate_5` FLOAT COMMENT '5日主力净流入-净占比',
    `fund_amount_super_5` BIGINT COMMENT '5日超大单净流入-净额',
    `fund_rate_super_5` FLOAT COMMENT '5日超大单净流入-净占比',
    `fund_amount_large_5` BIGINT COMMENT '5日大单净流入-净额',
    `fund_rate_large_5` FLOAT COMMENT '5日大单净流入-净占比',
    `fund_amount_medium_5` BIGINT COMMENT '5日中单净流入-净额',
    `fund_rate_medium_5` FLOAT COMMENT '5日中单净流入-净占比',
    `fund_amount_small_5` BIGINT COMMENT '5日小单净流入-净额',
    `fund_rate_small_5` FLOAT COMMENT '5日小单净流入-净占比',
    -- 10日资金流向
    `change_rate_10` FLOAT COMMENT '10日涨跌幅',
    `fund_amount_10` BIGINT COMMENT '10日主力净流入-净额',
    `fund_rate_10` FLOAT COMMENT '10日主力净流入-净占比',
    `fund_amount_super_10` BIGINT COMMENT '10日超大单净流入-净额',
    `fund_rate_super_10` FLOAT COMMENT '10日超大单净流入-净占比',
    `fund_amount_large_10` BIGINT COMMENT '10日大单净流入-净额',
    `fund_rate_large_10` FLOAT COMMENT '10日大单净流入-净占比',
    `fund_amount_medium_10` BIGINT COMMENT '10日中单净流入-净额',
    `fund_rate_medium_10` FLOAT COMMENT '10日中单净流入-净占比',
    `fund_amount_small_10` BIGINT COMMENT '10日小单净流入-净额',
    `fund_rate_small_10` FLOAT COMMENT '10日小单净流入-净占比',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票资金流向';
```

---

### 3.5 行业资金流向表 (cn_stock_fund_flow_industry)

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_fund_flow_industry` (
    `date` DATE NOT NULL COMMENT '日期',
    `name` VARCHAR(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '行业名称',
    `change_rate` FLOAT COMMENT '今日涨跌幅',
    `fund_amount` BIGINT COMMENT '今日主力净流入-净额',
    `fund_rate` FLOAT COMMENT '今日主力净流入-净占比',
    `stock_name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '今日主力净流入最大股',
    `change_rate_5` FLOAT COMMENT '5日涨跌幅',
    `fund_amount_5` BIGINT COMMENT '5日主力净流入-净额',
    `stock_name_5` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '5日主力净流入最大股',
    `change_rate_10` FLOAT COMMENT '10日涨跌幅',
    `fund_amount_10` BIGINT COMMENT '10日主力净流入-净额',
    `stock_name_10` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '10日主力净流入最大股',
    PRIMARY KEY (`date`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='行业资金流向';
```

---

### 3.6 概念资金流向表 (cn_stock_fund_flow_concept)

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_fund_flow_concept` (
    `date` DATE NOT NULL COMMENT '日期',
    `name` VARCHAR(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '概念名称',
    `change_rate` FLOAT COMMENT '今日涨跌幅',
    `fund_amount` BIGINT COMMENT '今日主力净流入-净额',
    `fund_rate` FLOAT COMMENT '今日主力净流入-净占比',
    `stock_name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '今日主力净流入最大股',
    `change_rate_5` FLOAT COMMENT '5日涨跌幅',
    `fund_amount_5` BIGINT COMMENT '5日主力净流入-净额',
    `stock_name_5` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '5日主力净流入最大股',
    `change_rate_10` FLOAT COMMENT '10日涨跌幅',
    `fund_amount_10` BIGINT COMMENT '10日主力净流入-净额',
    `stock_name_10` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '10日主力净流入最大股',
    PRIMARY KEY (`date`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='概念资金流向';
```

---

### 3.7 股票分红配送表 (cn_stock_bonus)

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_bonus` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    `convertible_total_rate` FLOAT COMMENT '送转股份-送转总比例',
    `convertible_rate` FLOAT COMMENT '送转股份-送转比例',
    `convertible_transfer_rate` FLOAT COMMENT '送转股份-转股比例',
    `bonusaward_rate` FLOAT COMMENT '现金分红-现金分红比例',
    `bonusaward_yield` FLOAT COMMENT '现金分红-股息率',
    `basic_eps` FLOAT COMMENT '每股收益',
    `bvps` FLOAT COMMENT '每股净资产',
    `per_capital_reserve` FLOAT COMMENT '每股公积金',
    `per_unassign_profit` FLOAT COMMENT '每股未分配利润',
    `netprofit_yoy_ratio` FLOAT COMMENT '净利润同比增长',
    `total_shares` BIGINT COMMENT '总股本',
    `plan_date` DATE COMMENT '预案公告日',
    `record_date` DATE COMMENT '股权登记日',
    `ex_dividend_date` DATE COMMENT '除权除息日',
    `progress` VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '方案进度',
    `report_date` DATE COMMENT '最新公告日期',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票分红配送';
```

---

### 3.8 股票龙虎榜表 (cn_stock_lhb)

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_lhb` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    `ranking_times` DATE COMMENT '上榜日',
    `interpret` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '解读',
    `new_price` FLOAT COMMENT '收盘价',
    `change_rate` FLOAT COMMENT '涨跌幅',
    `net_amount_buy` FLOAT COMMENT '龙虎榜净买额',
    `sum_buy` FLOAT COMMENT '龙虎榜买入额',
    `sum_sell` FLOAT COMMENT '龙虎榜卖出额',
    `lhb_amount` FLOAT COMMENT '龙虎榜成交额',
    `market_amount` FLOAT COMMENT '市场总成交额',
    `net_amount_rate` FLOAT COMMENT '净买额占总成交比',
    `sum_rate` FLOAT COMMENT '成交额占总成交比',
    `turnoverrate` FLOAT COMMENT '换手率',
    `free_cap` BIGINT COMMENT '流通市值',
    `reason` VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '上榜原因',
    `ranking_after_1` FLOAT COMMENT '上榜后1日',
    `ranking_after_2` FLOAT COMMENT '上榜后2日',
    `ranking_after_5` FLOAT COMMENT '上榜后5日',
    `ranking_after_10` FLOAT COMMENT '上榜后10日',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票龙虎榜';
```

---

### 3.9 股票大宗交易表 (cn_stock_blocktrade)

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_blocktrade` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    `new_price` FLOAT COMMENT '收盘价',
    `change_rate` FLOAT COMMENT '涨跌幅',
    `average_price` FLOAT COMMENT '成交均价',
    `overflow_rate` FLOAT COMMENT '折溢率',
    `trade_number` FLOAT COMMENT '成交笔数',
    `sum_volume` FLOAT COMMENT '成交总量',
    `sum_turnover` FLOAT COMMENT '成交总额',
    `turnover_market_rate` FLOAT COMMENT '成交占比流通市值',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票大宗交易';
```

---

### 3.10 股票指标数据表 (cn_stock_indicators)

存储股票技术指标计算结果，包含 32 种技术指标。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_indicators` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    `close` FLOAT COMMENT '收盘价',
    -- MACD 指标
    `macd` FLOAT COMMENT 'MACD-DIF',
    `macds` FLOAT COMMENT 'MACD信号线',
    `macdh` FLOAT COMMENT 'MACD柱状图',
    -- KDJ 指标
    `kdjk` FLOAT COMMENT 'KDJ-K值',
    `kdjd` FLOAT COMMENT 'KDJ-D值',
    `kdjj` FLOAT COMMENT 'KDJ-J值',
    -- BOLL 指标
    `boll_ub` FLOAT COMMENT 'BOLL上轨',
    `boll` FLOAT COMMENT 'BOLL中轨',
    `boll_lb` FLOAT COMMENT 'BOLL下轨',
    -- RSI 指标
    `rsi_6` FLOAT COMMENT 'RSI(6)',
    `rsi_12` FLOAT COMMENT 'RSI(12)',
    `rsi` FLOAT COMMENT 'RSI',
    `rsi_24` FLOAT COMMENT 'RSI(24)',
    -- 其他指标
    `trix` FLOAT COMMENT 'TRIX',
    `trix_20_sma` FLOAT COMMENT 'TRIX均线',
    `tema` FLOAT COMMENT 'TEMA',
    `cr` FLOAT COMMENT 'CR',
    `vr` FLOAT COMMENT 'VR',
    `roc` FLOAT COMMENT 'ROC',
    `rocma` FLOAT COMMENT 'ROC均线',
    `pdi` FLOAT COMMENT 'PDI',
    `mdi` FLOAT COMMENT 'MDI',
    `dx` FLOAT COMMENT 'DX',
    `adx` FLOAT COMMENT 'ADX',
    `adxr` FLOAT COMMENT 'ADXR',
    `wr_6` FLOAT COMMENT 'WR(6)',
    `wr_10` FLOAT COMMENT 'WR(10)',
    `wr_14` FLOAT COMMENT 'WR(14)',
    `cci` FLOAT COMMENT 'CCI',
    `cci_84` FLOAT COMMENT 'CCI(84)',
    `tr` FLOAT COMMENT 'TR',
    `atr` FLOAT COMMENT 'ATR',
    `dma` FLOAT COMMENT 'DMA',
    `obv` FLOAT COMMENT 'OBV',
    `sar` FLOAT COMMENT 'SAR',
    `psy` FLOAT COMMENT 'PSY',
    `psyma` FLOAT COMMENT 'PSY均线',
    `br` FLOAT COMMENT 'BR',
    `ar` FLOAT COMMENT 'AR',
    `emv` FLOAT COMMENT 'EMV',
    `emva` FLOAT COMMENT 'EMV均线',
    `bias` FLOAT COMMENT 'BIAS',
    `mfi` FLOAT COMMENT 'MFI',
    `vwma` FLOAT COMMENT 'VWMA',
    `ppo` FLOAT COMMENT 'PPO',
    `ppos` FLOAT COMMENT 'PPO信号线',
    `ppoh` FLOAT COMMENT 'PPO柱状图',
    `wt1` FLOAT COMMENT 'WT1',
    `wt2` FLOAT COMMENT 'WT2',
    `supertrend_ub` FLOAT COMMENT 'SuperTrend上轨',
    `supertrend` FLOAT COMMENT 'SuperTrend',
    `supertrend_lb` FLOAT COMMENT 'SuperTrend下轨',
    `dpo` FLOAT COMMENT 'DPO',
    `vhf` FLOAT COMMENT 'VHF',
    `rvi` FLOAT COMMENT 'RVI',
    `fi` FLOAT COMMENT 'FI',
    `ene_ue` FLOAT COMMENT 'ENE上轨',
    `ene` FLOAT COMMENT 'ENE',
    `ene_le` FLOAT COMMENT 'ENE下轨',
    `stochrsi_k` FLOAT COMMENT 'StochRSI-K',
    `stochrsi_d` FLOAT COMMENT 'StochRSI-D',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票指标数据';
```

---

### 3.11 股票指标买入/卖出信号表

```sql
-- 指标买入信号表
CREATE TABLE IF NOT EXISTS `cn_stock_indicators_buy` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    -- 1-100日收益率字段
    `rate_1` FLOAT COMMENT '1日收益率',
    `rate_2` FLOAT COMMENT '2日收益率',
    `rate_3` FLOAT COMMENT '3日收益率',
    `rate_5` FLOAT COMMENT '5日收益率',
    `rate_10` FLOAT COMMENT '10日收益率',
    `rate_20` FLOAT COMMENT '20日收益率',
    `rate_30` FLOAT COMMENT '30日收益率',
    `rate_60` FLOAT COMMENT '60日收益率',
    `rate_100` FLOAT COMMENT '100日收益率',
    -- ... 其他收益率字段 (rate_4 到 rate_99)
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票指标买入信号';

-- 指标卖出信号表
CREATE TABLE IF NOT EXISTS `cn_stock_indicators_sell` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    -- 收益率字段同上
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票指标卖出信号';
```

---

### 3.12 K线形态识别表 (cn_stock_kline_pattern)

存储 61 种 K 线形态识别结果。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_kline_pattern` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    -- K线形态字段 (值: -100=看跌, 0=无信号, 100=看涨)
    `tow_crows` SMALLINT COMMENT '两只乌鸦',
    `upside_gap_two_crows` SMALLINT COMMENT '向上跳空的两只乌鸦',
    `three_black_crows` SMALLINT COMMENT '三只乌鸦',
    `identical_three_crows` SMALLINT COMMENT '三胞胎乌鸦',
    `three_line_strike` SMALLINT COMMENT '三线打击',
    `dark_cloud_cover` SMALLINT COMMENT '乌云压顶',
    `evening_doji_star` SMALLINT COMMENT '十字暮星',
    `doji_Star` SMALLINT COMMENT '十字星',
    `hanging_man` SMALLINT COMMENT '上吊线',
    `hikkake_pattern` SMALLINT COMMENT '陷阱',
    `modified_hikkake_pattern` SMALLINT COMMENT '修正陷阱',
    `in_neck_pattern` SMALLINT COMMENT '颈内线',
    `on_neck_pattern` SMALLINT COMMENT '颈上线',
    `thrusting_pattern` SMALLINT COMMENT '插入',
    `shooting_star` SMALLINT COMMENT '射击之星',
    `stalled_pattern` SMALLINT COMMENT '停顿形态',
    `advance_block` SMALLINT COMMENT '大敌当前',
    `high_wave_candle` SMALLINT COMMENT '风高浪大线',
    `engulfing_pattern` SMALLINT COMMENT '吞噬模式',
    `abandoned_baby` SMALLINT COMMENT '弃婴',
    `closing_marubozu` SMALLINT COMMENT '收盘缺影线',
    `doji` SMALLINT COMMENT '十字',
    `long_legged_doji` SMALLINT COMMENT '长脚十字',
    `rickshaw_man` SMALLINT COMMENT '黄包车夫',
    `marubozu` SMALLINT COMMENT '光头光脚/缺影线',
    `three_inside_up_down` SMALLINT COMMENT '三内部上涨和下跌',
    `three_outside_up_down` SMALLINT COMMENT '三外部上涨和下跌',
    `three_stars_in_the_south` SMALLINT COMMENT '南方三星',
    `three_white_soldiers` SMALLINT COMMENT '三个白兵',
    `belt_hold` SMALLINT COMMENT '捉腰带线',
    `breakaway` SMALLINT COMMENT '脱离',
    `concealing_baby_swallow` SMALLINT COMMENT '藏婴吞没',
    `counterattack` SMALLINT COMMENT '反击线',
    `dragonfly_doji` SMALLINT COMMENT '蜻蜓十字/T形十字',
    `evening_star` SMALLINT COMMENT '暮星',
    `gravestone_doji` SMALLINT COMMENT '墓碑十字/倒T十字',
    `hammer` SMALLINT COMMENT '锤头',
    `harami_pattern` SMALLINT COMMENT '母子线',
    `harami_cross_pattern` SMALLINT COMMENT '十字孕线',
    `homing_pigeon` SMALLINT COMMENT '家鸽',
    `inverted_hammer` SMALLINT COMMENT '倒锤头',
    `kicking` SMALLINT COMMENT '反冲形态',
    `ladder_bottom` SMALLINT COMMENT '梯底',
    `long_line_candle` SMALLINT COMMENT '长蜡烛',
    `matching_low` SMALLINT COMMENT '相同低价',
    `mat_hold` SMALLINT COMMENT '铺垫',
    `morning_doji_star` SMALLINT COMMENT '十字晨星',
    `morning_star` SMALLINT COMMENT '晨星',
    `piercing_pattern` SMALLINT COMMENT '刺透形态',
    `rising_falling_three` SMALLINT COMMENT '上升/下降三法',
    `separating_lines` SMALLINT COMMENT '分离线',
    `short_line_candle` SMALLINT COMMENT '短蜡烛',
    `spinning_top` SMALLINT COMMENT '纺锤',
    `stick_sandwich` SMALLINT COMMENT '条形三明治',
    `takuri` SMALLINT COMMENT '探水竿',
    `tasuki_gap` SMALLINT COMMENT '跳空并列阴阳线',
    `tristar_pattern` SMALLINT COMMENT '三星',
    `unique_3_river` SMALLINT COMMENT '奇特三河床',
    `upside_downside_gap` SMALLINT COMMENT '上升/下降跳空三法',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票K线形态';
```

---

### 3.13 策略选股表

系统内置 14 种选股策略，每种策略对应一张表。其中前 13 种为 K线/技术类策略，GPT综合选股为基本面策略。

```sql
-- 放量上涨策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_enter` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    -- 收益率回测字段
    `rate_1` FLOAT COMMENT '1日收益率',
    `rate_5` FLOAT COMMENT '5日收益率',
    `rate_10` FLOAT COMMENT '10日收益率',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='策略-放量上涨';

-- 均线多头策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_keep_increasing` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_keep_increasing` COMMENT='策略-均线多头';

-- 停机坪策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_parking_apron` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_parking_apron` COMMENT='策略-停机坪';

-- 回踩年线策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_backtrace_ma250` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_backtrace_ma250` COMMENT='策略-回踩年线';

-- 突破平台策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_breakthrough_platform` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_breakthrough_platform` COMMENT='策略-突破平台';

-- 无大幅回撤策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_low_backtrace_increase` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_low_backtrace_increase` COMMENT='策略-无大幅回撤';

-- 海龟交易法则策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_turtle_trade` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_turtle_trade` COMMENT='策略-海龟交易法则';

-- 高而窄的旗形策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_high_tight_flag` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_high_tight_flag` COMMENT='策略-高而窄的旗形';

-- 放量跌停策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_climax_limitdown` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_climax_limitdown` COMMENT='策略-放量跌停';

-- 低ATR成长策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_low_atr` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_low_atr` COMMENT='策略-低ATR成长';

-- 趋势回调策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_trend_pullback` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_trend_pullback` COMMENT='策略-趋势回调';

-- 超跌反弹策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_oversold_rebound` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_oversold_rebound` COMMENT='策略-超跌反弹';

-- 突破确认策略
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_breakout_confirm` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_breakout_confirm` COMMENT='策略-突破确认';

-- GPT综合选股策略（基本面策略，独立作业 gpt_value_data_job）
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_gpt_value` LIKE `cn_stock_strategy_enter`;
ALTER TABLE `cn_stock_strategy_gpt_value` COMMENT='策略-GPT综合选股';
```

---

### 3.14 综合选股表 (cn_stock_selection)

综合选股条件筛选结果，包含 70+ 个筛选字段。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_selection` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `name` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '股票名称',
    -- 行情数据
    `new_price` FLOAT COMMENT '最新价',
    `change_rate` FLOAT COMMENT '涨跌幅',
    `volume_ratio` FLOAT COMMENT '量比',
    `high_price` FLOAT COMMENT '最高价',
    `low_price` FLOAT COMMENT '最低价',
    `pre_close_price` FLOAT COMMENT '昨收价',
    `volume` BIGINT COMMENT '成交量',
    `deal_amount` BIGINT COMMENT '成交额',
    `turnoverrate` FLOAT COMMENT '换手率',
    `listing_date` DATE COMMENT '上市时间',
    -- 分类信息
    `industry` VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '行业',
    `area` VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '地区',
    `concept` VARCHAR(800) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '概念',
    `style` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '板块',
    -- 指数成分
    `is_hs300` VARCHAR(2) COMMENT '沪深300成分',
    `is_sz50` VARCHAR(2) COMMENT '上证50成分',
    `is_zz500` VARCHAR(2) COMMENT '中证500成分',
    `is_zz1000` VARCHAR(2) COMMENT '中证1000成分',
    `is_cy50` VARCHAR(2) COMMENT '创业板50成分',
    -- 估值指标
    `pe9` FLOAT COMMENT '市盈率TTM',
    `pbnewmrq` FLOAT COMMENT '市净率MRQ',
    `dtsyl` FLOAT COMMENT '动态市盈率',
    `total_market_cap` BIGINT COMMENT '总市值',
    `free_cap` BIGINT COMMENT '流通市值',
    -- 盈利能力
    `basic_eps` FLOAT COMMENT '每股收益',
    `roe_weight` FLOAT COMMENT '净资产收益率ROE',
    `jroa` FLOAT COMMENT '总资产净利率ROA',
    `sale_gpr` FLOAT COMMENT '毛利率',
    `sale_npr` FLOAT COMMENT '净利率',
    -- 成长能力
    `netprofit_yoy_ratio` FLOAT COMMENT '净利润增长率',
    `toi_yoy_ratio` FLOAT COMMENT '营收增长率',
    `netprofit_growthrate_3y` FLOAT COMMENT '净利润3年复合增长率',
    -- 财务风险
    `debt_asset_ratio` FLOAT COMMENT '资产负债率',
    `current_ratio` FLOAT COMMENT '流动比率',
    `speed_ratio` FLOAT COMMENT '速动比率',
    -- 股东信息
    `total_shares` BIGINT COMMENT '总股本',
    `free_shares` BIGINT COMMENT '流通股本',
    `holder_newest` BIGINT COMMENT '最新股东户数',
    `holder_ratio` FLOAT COMMENT '股东户数增长率',
    -- 技术指标信号 (BIT类型)
    `macd_golden_fork` BIT(1) COMMENT 'MACD金叉日线',
    `kdj_golden_fork` BIT(1) COMMENT 'KDJ金叉日线',
    `break_through` BIT(1) COMMENT '放量突破',
    `long_avg_array` BIT(1) COMMENT '均线多头排列',
    `morning_star` BIT(1) COMMENT '早晨之星',
    PRIMARY KEY (`date`, `code`),
    INDEX `idx_code` (`code`),
    INDEX `idx_industry` (`industry`),
    INDEX `idx_area` (`area`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='综合选股';
```

---

### 3.15 个股财务分析指标表 (cn_stock_financial)

存储个股历史财务分析指标数据（东方财富数据源），为回测引擎提供真实基本面数据支持。由 `stock_financial_data.py` 作业填充，月度增量更新。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_financial` (
    `code`                   VARCHAR(6)    NOT NULL COMMENT '股票代码',
    `report_date`            DATE          NOT NULL COMMENT '报告期',
    `report_name`            VARCHAR(20)   COMMENT '报告期名称',
    `eps`                    FLOAT         COMMENT '基本每股收益(元)',
    `bps`                    FLOAT         COMMENT '每股净资产(元)',
    `ocfps`                  FLOAT         COMMENT '每股经营现金流(元)',
    `revenue`                FLOAT         COMMENT '营业总收入(元)',
    `net_profit`             FLOAT         COMMENT '归母净利润(元)',
    `revenue_yoy`            FLOAT         COMMENT '营收同比增长',
    `net_profit_yoy`         FLOAT         COMMENT '净利润同比增长',
    `roe`                    FLOAT         COMMENT 'ROE净资产收益率',
    `roa`                    FLOAT         COMMENT '总资产净利率',
    `gross_margin`           FLOAT         COMMENT '毛利率',
    `net_profit_margin`      FLOAT         COMMENT '净利率',
    `asset_liability_ratio`  FLOAT         COMMENT '资产负债率',
    `current_ratio`          FLOAT         COMMENT '流动比率',
    `quick_ratio`            FLOAT         COMMENT '速动比率',
    `total_asset_turnover`   FLOAT         COMMENT '总资产周转率(次)',
    `inventory_turnover`     FLOAT         COMMENT '存货周转率(次)',
    `receivable_turnover`    FLOAT         COMMENT '应收账款周转率(次)',
    `updated_at`             DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`code`, `report_date`),
    INDEX `idx_report_date` (`report_date`),
    INDEX `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='个股财务分析指标-东方财富(回测用)';
```

| 字段 | 类型 | 说明 |
|------|------|------|
| code | VARCHAR(6) | 股票代码 |
| report_date | DATE | 报告期（如 2024-12-31） |
| report_name | VARCHAR(20) | 报告期名称（如"2024年年报"） |
| eps | FLOAT | 基本每股收益（元） |
| bps | FLOAT | 每股净资产（元） |
| ocfps | FLOAT | 每股经营现金流（元） |
| revenue | FLOAT | 营业总收入（元） |
| net_profit | FLOAT | 归属母公司净利润（元） |
| revenue_yoy | FLOAT | 营收同比增长率 |
| net_profit_yoy | FLOAT | 净利润同比增长率 |
| roe | FLOAT | 净资产收益率（ROE） |
| roa | FLOAT | 总资产净利率（ROA） |
| gross_margin | FLOAT | 销售毛利率 |
| net_profit_margin | FLOAT | 销售净利率 |
| asset_liability_ratio | FLOAT | 资产负债率 |
| current_ratio | FLOAT | 流动比率 |
| quick_ratio | FLOAT | 速动比率 |
| total_asset_turnover | FLOAT | 总资产周转率（次） |
| inventory_turnover | FLOAT | 存货周转率（次） |
| receivable_turnover | FLOAT | 应收账款周转率（次） |
| updated_at | DATETIME | 记录更新时间 |

**数据来源**：AKShare `stock_financial_analysis_indicator_em` 接口（东方财富）

---

### 3.16 股票回测数据表 (cn_stock_backtest_data)

存储策略回测收益率数据。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_backtest_data` (
    `date` DATE NOT NULL COMMENT '日期',
    `code` VARCHAR(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    -- 1-100日收益率
    `rate_1` FLOAT COMMENT '1日收益率',
    `rate_2` FLOAT COMMENT '2日收益率',
    `rate_3` FLOAT COMMENT '3日收益率',
    `rate_4` FLOAT COMMENT '4日收益率',
    `rate_5` FLOAT COMMENT '5日收益率',
    -- ... (rate_6 到 rate_99)
    `rate_100` FLOAT COMMENT '100日收益率',
    PRIMARY KEY (`date`, `code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='股票回测数据';
```

---

## 四、表关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                        核心数据表                                 │
├─────────────────────────────────────────────────────────────────┤
│  cn_stock_spot (每日股票数据)                                     │
│       ├── cn_stock_fund_flow (资金流向)                          │
│       ├── cn_stock_bonus (分红配送)                              │
│       ├── cn_stock_lhb (龙虎榜)                                  │
│       ├── cn_stock_blocktrade (大宗交易)                         │
│       ├── cn_stock_indicators (技术指标)                         │
│       │       ├── cn_stock_indicators_buy (买入信号)             │
│       │       └── cn_stock_indicators_sell (卖出信号)            │
│       ├── cn_stock_kline_pattern (K线形态)                       │
│       └── cn_stock_strategy_* (14种策略表)                       │
├─────────────────────────────────────────────────────────────────┤
│  cn_etf_spot (每日ETF数据)                                       │
├─────────────────────────────────────────────────────────────────┤
│  cn_stock_selection (综合选股)                                    │
├─────────────────────────────────────────────────────────────────┤
│  cn_stock_attention (我的关注)                                    │
├─────────────────────────────────────────────────────────────────┤
│  cn_stock_financial (个股财务分析指标，回测用)                      │
├─────────────────────────────────────────────────────────────────┤
│  cn_stock_trade_date (交易日历)                                   │
├─────────────────────────────────────────────────────────────────┤
│  cn_stock_fund_flow_industry (行业资金流向)                       │
│  cn_stock_fund_flow_concept (概念资金流向)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、数据表汇总

| 序号 | 表名 | 中文名 | 主要用途 |
|------|------|--------|----------|
| 1 | cn_stock_attention | 我的关注 | 用户关注的股票列表 |
| 2 | cn_stock_spot | 每日股票数据 | 股票基础行情和基本面数据 |
| 3 | cn_etf_spot | 每日ETF数据 | ETF基础行情数据 |
| 4 | cn_stock_fund_flow | 股票资金流向 | 个股资金流入流出数据 |
| 5 | cn_stock_fund_flow_industry | 行业资金流向 | 行业板块资金流向 |
| 6 | cn_stock_fund_flow_concept | 概念资金流向 | 概念板块资金流向 |
| 7 | cn_stock_bonus | 股票分红配送 | 分红送转信息 |
| 8 | cn_stock_lhb | 股票龙虎榜 | 龙虎榜上榜数据 |
| 9 | cn_stock_blocktrade | 股票大宗交易 | 大宗交易记录 |
| 10 | cn_stock_indicators | 股票指标数据 | 32种技术指标计算结果 |
| 11 | cn_stock_indicators_buy | 股票指标买入 | 买入信号及回测收益 |
| 12 | cn_stock_indicators_sell | 股票指标卖出 | 卖出信号及回测收益 |
| 13 | cn_stock_kline_pattern | 股票K线形态 | 61种K线形态识别结果 |
| 14 | cn_stock_strategy_enter | 放量上涨 | 策略选股结果 |
| 15 | cn_stock_strategy_keep_increasing | 均线多头 | 策略选股结果 |
| 16 | cn_stock_strategy_parking_apron | 停机坪 | 策略选股结果 |
| 17 | cn_stock_strategy_backtrace_ma250 | 回踩年线 | 策略选股结果 |
| 18 | cn_stock_strategy_breakthrough_platform | 突破平台 | 策略选股结果 |
| 19 | cn_stock_strategy_low_backtrace_increase | 无大幅回撤 | 策略选股结果 |
| 20 | cn_stock_strategy_turtle_trade | 海龟交易法则 | 策略选股结果 |
| 21 | cn_stock_strategy_high_tight_flag | 高而窄的旗形 | 策略选股结果 |
| 22 | cn_stock_strategy_climax_limitdown | 放量跌停 | 策略选股结果 |
| 23 | cn_stock_strategy_low_atr | 低ATR成长 | 策略选股结果 |
| 24 | cn_stock_strategy_trend_pullback | 趋势回调 | 策略选股结果 |
| 25 | cn_stock_strategy_oversold_rebound | 超跌反弹 | 策略选股结果 |
| 26 | cn_stock_strategy_breakout_confirm | 突破确认 | 策略选股结果 |
| 27 | cn_stock_strategy_gpt_value | GPT综合选股 | 基本面策略选股结果 |
| 28 | cn_stock_selection | 综合选股 | 多条件综合筛选结果 |
| 29 | cn_stock_backtest_data | 股票回测数据 | 策略回测收益率数据 |
| 30 | cn_stock_backtest | 回测验证汇总 | 策略回测汇总统计 |
| 31 | cn_stock_chip_race_open | 早盘抢筹数据 | 早盘集合竞价抢筹数据 |
| 32 | cn_stock_chip_race_end | 尾盘抢筹数据 | 尾盘集合竞价抢筹数据 |
| 33 | cn_stock_limitup_reason | 涨停原因揭密 | 涨停原因分析数据 |
| 34 | cn_strategy_params | 策略参数配置 | 可配置策略筛选参数 |
| 35 | cn_stock_spot_buy | 基本面选股 | 基本面选股中间结果 |
| 36 | cn_stock_top | 股票龙虎榜(新浪) | 新浪数据源龙虎榜（未启用） |
| 37 | cn_stock_foreign_key | 股票外键 | 股票代码→市场前缀映射 |
| 38 | cn_stock_financial | 个股财务分析指标 | 回测用历史财务数据（东方财富） |
| 39 | cn_stock_trade_date | 交易日历 | A股交易日历表 |

---

## 六、策略参数配置表 (cn_strategy_params)

存储用户可配置的策略筛选参数，支持三类策略参数集：

| 参数集 | 说明 |
|--------|------|
| `gpt_value` | GPT选股筛选条件（财务安全、盈利能力、成长能力、估值指标） |
| `moat_scoring` | 护城河评分模型权重和阈值 |
| `ai_model` | AI/LLM API配置（接口地址、密钥、模型、温度、token数） |

---

## 八、快速初始化脚本

将上述所有建表语句保存为 `init_database.sql`，执行以下命令初始化：

```bash
mysql -u root -p < init_database.sql
```

或在 MySQL 客户端中执行：

```sql
source /path/to/init_database.sql;
```

---

## 七、数据流水线与表关系

系统采用 5 阶段流水线架构，数据获取与分析彻底分离：

```
Phase 1 (数据获取):
  fetch_data_job → 实时行情 → cn_stock_spot, cn_etf_spot
                → 历史K线 → cache/hist/ (Parquet文件缓存)

Phase 2 (基础数据):
  basic_data_daily_job → 实时行情入库 → cn_stock_spot
  selection_data_daily_job → 综合选股数据 → cn_stock_selection

Phase 3 (扩展数据):
  basic_data_other_daily_job → 资金流向 → cn_stock_fund_flow
                             → 行业资金 → cn_stock_fund_flow_industry
                             → 概念资金 → cn_stock_fund_flow_concept
                             → 龙虎榜 → cn_stock_lhb
                             → 分红配送 → cn_stock_bonus
                             → 涨停原因 → cn_stock_limitup_reason
                             → 早盘抢筹 → cn_stock_chip_race_open
  gpt_value_data_job → 读 cn_stock_selection → 写 cn_stock_strategy_gpt_value

Phase 4 (流式分析，零API调用):
  streaming_analysis_job → 读 cache/hist/ + cn_stock_lhb
                         → 写 cn_stock_indicators (32种指标)
                         → 写 cn_stock_indicators_buy/sell (买卖信号)
                         → 写 cn_stock_kline_pattern (61种K线形态)
                         → 写 cn_stock_strategy_* (13种策略)

Phase 5 (回测与收尾):
  backtest_data_daily_job → 读 cache/hist/ → 写 cn_stock_backtest_data
                          → 读所有策略表 → 写 cn_stock_backtest (统计汇总)
  basic_data_after_close_daily_job → 大宗交易 → cn_stock_blocktrade
                                   → 尾盘抢筹 → cn_stock_chip_race_end
```

> **注意**：Phase 1-3 涉及外部 API 调用（东方财富/腾讯/新浪），Phase 4-5 仅读写本地 DB 和缓存，零 API 调用。

---

*文档生成时间：2026-01-20*
*项目地址：玄枢 Quantia 智能量化投资中枢*
