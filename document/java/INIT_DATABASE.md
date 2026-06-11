# 数据库初始化脚本

**文件名**: `init.sql`  
**位置**: 项目根目录  
**用途**: MySQL 初始化时自动创建表和初始数据

```sql
-- ========================================
-- Quantia Java 微服务数据库初始化脚本
-- ========================================

-- 使用数据库
USE quantiadb;

-- ========================================
-- 1. 通知服务表 (notification-svc)
-- ========================================

-- 通知事件表
CREATE TABLE IF NOT EXISTS `cn_stock_notification_event` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `dedupe_key` VARCHAR(256) NOT NULL UNIQUE COMMENT '去重 key (SHA256)',
  `event_type` VARCHAR(50) NOT NULL COMMENT '事件类型: paper_trade, live_trade, 等',
  `channel` VARCHAR(50) NOT NULL COMMENT '通知渠道: dingtalk, email, sms',
  `paper_id` INT COMMENT '模拟交易账户 ID',
  `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态: pending, sent, failed, dlq',
  `payload_json` LONGTEXT NOT NULL COMMENT '事件负载 (JSON)',
  `response_json` LONGTEXT COMMENT '发送响应 (JSON)',
  `retry_count` INT NOT NULL DEFAULT 0 COMMENT '已重试次数',
  `max_retries` INT NOT NULL DEFAULT 3 COMMENT '最大重试次数',
  `next_retry_at` TIMESTAMP NULL COMMENT '下次重试时间',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `sent_at` TIMESTAMP NULL COMMENT '发送完成时间',
  `error_message` VARCHAR(500) COMMENT '错误信息',
  
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dedupe_key` (`dedupe_key`),
  KEY `idx_status_created` (`status`, `created_at`),
  KEY `idx_next_retry` (`next_retry_at`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='通知事件表,用于通知异步处理与重试';

-- 通知配置表
CREATE TABLE IF NOT EXISTS `cn_stock_notification_config` (
  `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `channel` VARCHAR(50) NOT NULL UNIQUE COMMENT '通知渠道',
  `enabled` TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用',
  `webhook_url` VARCHAR(500) COMMENT 'Webhook 地址',
  `secret_key` VARCHAR(256) COMMENT '密钥',
  `max_retries` INT DEFAULT 3 COMMENT '最大重试次数',
  `retry_interval_seconds` INT DEFAULT 60 COMMENT '重试间隔(秒)',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='通知配置';

-- ========================================
-- 2. IM 网关表 (im-gateway-svc)
-- ========================================

-- 交易指令表
CREATE TABLE IF NOT EXISTS `cn_stock_trade_command` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  `command_id` VARCHAR(256) NOT NULL UNIQUE COMMENT '指令唯一 ID (去重)',
  `operator` VARCHAR(50) NOT NULL COMMENT '操作人 (工号)',
  `command_type` VARCHAR(50) NOT NULL COMMENT '指令类型: buy, sell, cancel',
  `stock_code` VARCHAR(20) NOT NULL COMMENT '股票代码',
  `stock_name` VARCHAR(100) COMMENT '股票名称',
  `direction` VARCHAR(10) COMMENT 'buy/sell',
  `amount` INT COMMENT '数量',
  `price_limit` DECIMAL(10, 2) COMMENT '价格限制',
  `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending, approved, rejected, executed, cancelled',
  `estimated_value` DECIMAL(15, 2) COMMENT '估算金额',
  `risk_check_result` VARCHAR(20) COMMENT '风控检查结果',
  `risk_check_message` VARCHAR(500) COMMENT '风控检查信息',
  `execution_result` LONGTEXT COMMENT '执行结果 (JSON)',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `executed_at` TIMESTAMP NULL COMMENT '执行完成时间',
  
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_command_id` (`command_id`),
  KEY `idx_operator_created` (`operator`, `created_at`),
  KEY `idx_status_created` (`status`, `created_at`),
  KEY `idx_stock_code` (`stock_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='交易指令表,存储 IM 下单指令';

-- IM 操作员白名单
CREATE TABLE IF NOT EXISTS `cn_stock_im_operator` (
  `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `staff_id` VARCHAR(50) NOT NULL UNIQUE COMMENT '员工工号',
  `name` VARCHAR(100) NOT NULL COMMENT '员工名称',
  `phone` VARCHAR(20) COMMENT '电话',
  `enabled` TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用',
  `daily_limit` DECIMAL(15, 2) DEFAULT 10000000 COMMENT '日交易限额',
  `single_limit` DECIMAL(15, 2) DEFAULT 1000000 COMMENT '单笔限额',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='IM 操作员白名单';

-- IM 日风控表(每日统计)
CREATE TABLE IF NOT EXISTS `cn_stock_im_daily_limit` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `date` DATE NOT NULL,
  `staff_id` VARCHAR(50) NOT NULL,
  `total_amount` DECIMAL(15, 2) DEFAULT 0 COMMENT '当日已交易金额',
  `transaction_count` INT DEFAULT 0 COMMENT '当日交易笔数',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  UNIQUE KEY `uk_date_staff` (`date`, `staff_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='每日风控统计';

-- ========================================
-- 3. AI 决策表 (ai-decision-svc, 可选)
-- ========================================

CREATE TABLE IF NOT EXISTS `cn_stock_ai_score` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `request_id` VARCHAR(256) NOT NULL UNIQUE COMMENT '请求 ID (去重)',
  `code` VARCHAR(20) NOT NULL COMMENT '股票代码',
  `direction` VARCHAR(10) NOT NULL COMMENT 'buy/sell',
  `score` INT NOT NULL COMMENT '得分 0-100',
  `gate_result` VARCHAR(20) COMMENT 'PASS/REJECT',
  `model` VARCHAR(100) COMMENT '使用的模型',
  `prompt_hash` VARCHAR(256) COMMENT 'prompt 内容 hash',
  `latency_ms` INT COMMENT '处理耗时(ms)',
  `cached` TINYINT DEFAULT 0 COMMENT '是否来自缓存',
  `source` VARCHAR(50) COMMENT '评分来源',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `expires_at` TIMESTAMP NULL COMMENT '缓存过期时间',
  
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_request_id` (`request_id`),
  KEY `idx_code_direction` (`code`, `direction`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='AI 评分表';

-- ========================================
-- 4. 交易执行表 (live-trade-svc, 可选)
-- ========================================

CREATE TABLE IF NOT EXISTS `cn_stock_live_trade` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `order_id` VARCHAR(256) NOT NULL UNIQUE COMMENT '订单 ID (去重)',
  `command_id` VARCHAR(256) COMMENT '来源指令 ID',
  `stock_code` VARCHAR(20) NOT NULL,
  `direction` VARCHAR(10) NOT NULL,
  `amount` INT,
  `price` DECIMAL(10, 2),
  `status` VARCHAR(20) DEFAULT 'pending' COMMENT 'pending, partial, executed, failed, cancelled',
  `executed_amount` INT DEFAULT 0 COMMENT '已执行数量',
  `executed_price` DECIMAL(10, 2) COMMENT '平均执行价格',
  `commission` DECIMAL(10, 4) COMMENT '手续费',
  `broker_response` LONGTEXT COMMENT 'broker 响应',
  `reconciliation_status` VARCHAR(20) DEFAULT 'pending' COMMENT '对账状态',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `executed_at` TIMESTAMP NULL,
  
  UNIQUE KEY `uk_order_id` (`order_id`),
  KEY `idx_status_created` (`status`, `created_at`),
  KEY `idx_reconciliation` (`reconciliation_status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='实盘交易记录';

-- ========================================
-- 5. 基础配置表
-- ========================================

-- 系统配置表
CREATE TABLE IF NOT EXISTS `cn_system_config` (
  `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `key` VARCHAR(100) NOT NULL UNIQUE,
  `value` LONGTEXT,
  `description` VARCHAR(500),
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='系统配置表';

-- 审计日志表
CREATE TABLE IF NOT EXISTS `cn_audit_log` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `service_name` VARCHAR(100) NOT NULL COMMENT '服务名',
  `operation_type` VARCHAR(50) NOT NULL COMMENT '操作类型: CREATE, UPDATE, DELETE, EXECUTE',
  `operator` VARCHAR(50) COMMENT '操作人',
  `entity_type` VARCHAR(50) COMMENT '实体类型',
  `entity_id` VARCHAR(256) COMMENT '实体 ID',
  `before_value` LONGTEXT COMMENT '修改前值',
  `after_value` LONGTEXT COMMENT '修改后值',
  `status` VARCHAR(20) DEFAULT 'success' COMMENT 'success/failure',
  `error_message` VARCHAR(500),
  `trace_id` VARCHAR(256) COMMENT '链路追踪 ID',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  
  KEY `idx_service_created` (`service_name`, `created_at`),
  KEY `idx_entity` (`entity_type`, `entity_id`),
  KEY `idx_trace_id` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='审计日志表';

-- ========================================
-- 6. 初始数据插入
-- ========================================

-- 插入通知配置
INSERT IGNORE INTO `cn_stock_notification_config` 
(`channel`, `enabled`, `webhook_url`, `secret_key`, `max_retries`)
VALUES 
('dingtalk', 1, 'https://oapi.dingtalk.com/robot/send', '', 3),
('email', 0, NULL, NULL, 3);

-- 插入 IM 操作员
INSERT IGNORE INTO `cn_stock_im_operator` 
(`staff_id`, `name`, `phone`, `enabled`, `daily_limit`, `single_limit`)
VALUES
('tech001', '技术主管', '13800138000', 1, 50000000, 5000000),
('trader001', '交易员', '13800138001', 1, 10000000, 1000000),
('risk001', '风控员', '13800138002', 1, 0, 0);

-- ========================================
-- 7. 账户/授权相关表 (Python web 已存在,此处引用)
-- ========================================

-- 注: 以下表假设已由 Python 服务创建,这里只做描述
-- cn_stock_user - 用户表
-- cn_stock_paper_trading - 模拟交易账户
-- cn_stock_paper_trading_cash - 现金明细
-- cn_stock_paper_trading_holding - 持仓明细
-- cn_stock_strategy_* - 策略结果表(Python 写入)

-- ========================================
-- 8. 授权配置
-- ========================================

-- 创建用于 Java 服务的只读用户
CREATE USER IF NOT EXISTS 'quantia_reader'@'%' IDENTIFIED BY 'quantia_reader_pwd';
GRANT SELECT ON quantiadb.* TO 'quantia_reader'@'%';

-- 创建用于 Java 服务的读写用户(生产环境推荐分离)
CREATE USER IF NOT EXISTS 'quantia_app'@'%' IDENTIFIED BY 'quantia_app_pwd';
GRANT SELECT, INSERT, UPDATE ON quantiadb.* TO 'quantia_app'@'%';

-- ========================================
-- 9. 性能优化
-- ========================================

-- 禁用外键约束(开发环境)
SET foreign_key_checks = 0;

-- 调整表的自增 ID 起始值(避免重复)
ALTER TABLE `cn_stock_notification_event` AUTO_INCREMENT = 1000001;
ALTER TABLE `cn_stock_trade_command` AUTO_INCREMENT = 2000001;
ALTER TABLE `cn_stock_ai_score` AUTO_INCREMENT = 3000001;
ALTER TABLE `cn_stock_live_trade` AUTO_INCREMENT = 4000001;
ALTER TABLE `cn_audit_log` AUTO_INCREMENT = 5000001;

-- 显示初始化完成
SELECT '========== 数据库初始化完成 ==========' as status;
SELECT COUNT(*) as table_count FROM information_schema.tables WHERE table_schema = 'quantiadb';
```

---

## 使用说明

### 自动初始化
Docker Compose 启动时会自动执行此脚本:
```bash
docker-compose up mysql
# 自动创建所有表和初始数据
```

### 手动初始化
```bash
# 进入 MySQL 容器
docker exec -i quantia-mysql mysql -u root -proot < init.sql

# 或远程执行
mysql -h localhost -u root -proot quantiadb < init.sql
```

### 验证初始化
```bash
# 查看所有表
mysql -h localhost -u root -proot quantiadb -e "SHOW TABLES;"

# 查看表结构
mysql -h localhost -u root -proot quantiadb -e "DESC cn_stock_notification_event;"

# 查看初始数据
mysql -h localhost -u root -proot quantiadb -e "SELECT * FROM cn_stock_notification_config;"
```

---

## 重要说明

1. **默认密码**: 开发环境使用简单密码,生产环境必须修改
2. **连接池大小**: application.yml 中配置与此脚本无关,需在 Java 配置中设置
3. **自增 ID 起始值**: 不同服务使用不同范围避免冲突(生产建议用 UUID)
4. **备份策略**: 
   - 每日自动备份
   - 生产环境使用主从或集群
5. **监控告警**:
   - 表大小
   - 连接数
   - 慢查询

