# Docker Compose 一键启动配置 (完整版)

**文件名**: `docker-compose.yml`  
**位置**: 项目根目录 (`Quantia/`)  
**用途**: 本地开发环境一键启动所有必需服务

---

## 完整配置

```yaml
version: '3.9'

# 定义网络,便于服务间通信
networks:
  quantia-network:
    driver: bridge

# 持久化卷
volumes:
  mysql_data:
    driver: local
  rabbitmq_data:
    driver: local
  kafka_data:
    driver: local
  prometheus_data:
    driver: local

services:
  # ============================================
  # 1. MySQL 数据库 (主要存储)
  # ============================================
  mysql:
    image: mysql:8.0.33
    container_name: quantia-mysql
    hostname: mysql
    networks:
      - quantia-network
    ports:
      - "3306:3306"
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: quantiadb
      MYSQL_USER: quantia
      MYSQL_PASSWORD: quantia_pwd
      TZ: 'Asia/Shanghai'
      MYSQL_INITDB_SKIP_TZINFO: "yes"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
      - ./my.cnf:/etc/mysql/conf.d/my.cnf
    command: --default-authentication-plugin=mysql_native_password --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # ============================================
  # 2. RabbitMQ (通知消息队列)
  # ============================================
  rabbitmq:
    image: rabbitmq:3.11-management-alpine
    container_name: quantia-rabbitmq
    hostname: rabbitmq
    networks:
      - quantia-network
    ports:
      - "5672:5672"      # AMQP 端口
      - "15672:15672"    # 管理界面
    environment:
      RABBITMQ_DEFAULT_USER: quantia
      RABBITMQ_DEFAULT_PASS: quantia_pwd
      RABBITMQ_DEFAULT_VHOST: /
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
      - ./rabbitmq.conf:/etc/rabbitmq/rabbitmq.conf:ro
      - ./rabbitmq-definitions.json:/etc/rabbitmq/definitions.json:ro
    healthcheck:
      test: rabbitmq-diagnostics -q ping
      interval: 30s
      timeout: 10s
      retries: 5
    restart: unless-stopped

  # ============================================
  # 3. Zookeeper (Kafka 协调服务)
  # ============================================
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    container_name: quantia-zookeeper
    hostname: zookeeper
    networks:
      - quantia-network
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
      TZ: 'Asia/Shanghai'
    volumes:
      - ./zk-data:/var/lib/zookeeper/data
      - ./zk-logs:/var/lib/zookeeper/log
    restart: unless-stopped

  # ============================================
  # 4. Kafka (交易事件流)
  # ============================================
  kafka:
    image: confluentinc/cp-kafka:7.4.0
    container_name: quantia-kafka
    hostname: kafka
    networks:
      - quantia-network
    ports:
      - "9092:9092"      # 内外网访问
      - "29092:29092"    # 容器内访问
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://kafka:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
      TZ: 'Asia/Shanghai'
    volumes:
      - kafka_data:/var/lib/kafka/data
    restart: unless-stopped

  # ============================================
  # 5. Redis (缓存 & 锁)
  # ============================================
  redis:
    image: redis:7.0-alpine
    container_name: quantia-redis
    hostname: redis
    networks:
      - quantia-network
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes --requirepass quantia_pwd
    volumes:
      - ./redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # ============================================
  # 6. Zipkin (分布式链路追踪)
  # ============================================
  zipkin:
    image: openzipkin/zipkin:latest
    container_name: quantia-zipkin
    hostname: zipkin
    networks:
      - quantia-network
    ports:
      - "9411:9411"
    environment:
      STORAGE_TYPE: mem
      TZ: 'Asia/Shanghai'
    restart: unless-stopped

  # ============================================
  # 7. Prometheus (指标收集)
  # ============================================
  prometheus:
    image: prom/prometheus:latest
    container_name: quantia-prometheus
    hostname: prometheus
    networks:
      - quantia-network
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus-rules.yml:/etc/prometheus/rules.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    restart: unless-stopped

  # ============================================
  # 8. Grafana (监控可视化)
  # ============================================
  grafana:
    image: grafana/grafana:latest
    container_name: quantia-grafana
    hostname: grafana
    networks:
      - quantia-network
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_SECURITY_ADMIN_USER: admin
      GF_INSTALL_PLUGINS: 'grafana-piechart-panel'
      TZ: 'Asia/Shanghai'
    volumes:
      - ./grafana-datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml:ro
      - ./grafana-dashboards.yml:/etc/grafana/provisioning/dashboards/dashboards.yml:ro
    depends_on:
      - prometheus
    restart: unless-stopped
```

---

## 辅助配置文件

### my.cnf (MySQL 性能优化)

```ini
[mysqld]
# 连接池优化
max_connections = 1000
max_allowed_packet = 256M

# InnoDB 优化
innodb_buffer_pool_size = 2G
innodb_log_file_size = 512M
innodb_flush_log_at_trx_commit = 1

# 二进制日志
log_bin = mysql-bin
binlog_format = ROW
expire_logs_days = 7

# 慢查询日志
slow_query_log = ON
long_query_time = 2
slow_query_log_file = /var/log/mysql/slow.log

# 字符集
character_set_server = utf8mb4
collation_server = utf8mb4_unicode_ci

[mysql]
default-character-set = utf8mb4
```

### rabbitmq.conf (RabbitMQ 配置)

```
# 内存高水位
vm_memory_high_watermark.relative = 0.6

# 监听端口
listeners.ssl.default = 5671

# 管理插件
management.load_definitions = /etc/rabbitmq/definitions.json
management.listener.ssl = false
management.listener.port = 15672

# 集群
cluster_formation.peer_discovery_backend = rabbit_peer_discovery_classic_config
cluster_formation.classic_config.nodes.1 = rabbit@rabbitmq

# 队列 TTL
collect_statistics_interval = 5000
```

### rabbitmq-definitions.json (RabbitMQ 队列初始化)

```json
{
  "vhosts": [
    {"name": "/"}
  ],
  "exchanges": [
    {
      "name": "notification",
      "vhost": "/",
      "type": "topic",
      "durable": true,
      "auto_delete": false
    },
    {
      "name": "notification.dlx",
      "vhost": "/",
      "type": "direct",
      "durable": true,
      "auto_delete": false
    }
  ],
  "queues": [
    {
      "name": "notification.queue",
      "vhost": "/",
      "durable": true,
      "arguments": {
        "x-dead-letter-exchange": "notification.dlx",
        "x-message-ttl": 172800000
      }
    },
    {
      "name": "notification.dlq",
      "vhost": "/",
      "durable": true
    }
  ],
  "bindings": [
    {
      "source": "notification",
      "destination": "notification.queue",
      "destination_type": "queue",
      "routing_key": "#"
    },
    {
      "source": "notification.dlx",
      "destination": "notification.dlq",
      "destination_type": "queue",
      "routing_key": "#"
    }
  ]
}
```

### prometheus.yml (Prometheus 配置)

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    monitor: 'quantia-system'

rule_files:
  - "/etc/prometheus/rules.yml"

scrape_configs:
  - job_name: 'spring-boot'
    static_configs:
      - targets: ['localhost:8081', 'localhost:8082', 'localhost:8083']
    
  - job_name: 'mysql'
    static_configs:
      - targets: ['localhost:3306']
    
  - job_name: 'rabbitmq'
    static_configs:
      - targets: ['rabbitmq:15672']
    
  - job_name: 'kafka'
    static_configs:
      - targets: ['kafka:9092']
```

---

## 快速启动命令

### 启动所有服务

```bash
# 进入项目目录
cd Quantia

# 一键启动
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止所有服务
docker-compose down

# 清理所有数据(包括卷)
docker-compose down -v
```

### 创建 Kafka Topic

```bash
# 进入 Kafka 容器
docker exec -it quantia-kafka bash

# 创建交易命令 Topic (3 分片, 至少 1 副本)
kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic trading.commands \
  --partitions 3 \
  --replication-factor 1 \
  --config retention.ms=604800000

# 创建交易执行结果 Topic
kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic trading.executions \
  --partitions 3 \
  --replication-factor 1

# 列出所有 Topic
kafka-topics --list --bootstrap-server localhost:9092
```

### 初始化数据库

```bash
# 方式 1: 自动初始化(docker-compose up 时自动执行 init.sql)
docker-compose up mysql

# 方式 2: 手动执行 SQL
docker exec -i quantia-mysql mysql -u root -proot quantiadb < init.sql

# 验证表
docker exec -i quantia-mysql mysql -u root -proot quantiadb -e "SHOW TABLES;"
```

### 访问管理界面

| 服务 | URL | 用户名 | 密码 |
|---|---|---|---|
| RabbitMQ | http://localhost:15672 | quantia | quantia_pwd |
| Grafana | http://localhost:3000 | admin | admin |
| Prometheus | http://localhost:9090 | - | - |
| Zipkin | http://localhost:9411 | - | - |

---

## 本地开发环境检查清单

- [ ] Docker Desktop 已安装 (v20.10+)
- [ ] Docker Compose 已安装 (v2.10+)
- [ ] JDK 17 已安装
- [ ] Maven 3.9.0+ 已安装
- [ ] Git 已安装

启动后检查:
- [ ] MySQL 健康检查通过
- [ ] RabbitMQ 可访问 (http://localhost:15672)
- [ ] Kafka broker 启动成功
- [ ] Zipkin 可访问 (http://localhost:9411)
- [ ] Prometheus 可访问 (http://localhost:9090)
- [ ] Grafana 可访问 (http://localhost:3000)

---

## 故障排查

### MySQL 无法启动

```bash
# 检查日志
docker logs quantia-mysql

# 重新初始化(删除数据卷)
docker-compose down -v
docker-compose up mysql
```

### RabbitMQ 队列未初始化

```bash
# 检查定义文件
docker logs quantia-rabbitmq | grep definitions

# 手动创建(进入容器)
docker exec -it quantia-rabbitmq rabbitmq-plugins enable rabbitmq_management
```

### Kafka 消费消息失败

```bash
# 检查 Topic 是否存在
docker exec quantia-kafka kafka-topics \
  --list --bootstrap-server localhost:9092

# 查看 Partition 分布
docker exec quantia-kafka kafka-topics \
  --describe --bootstrap-server localhost:9092 \
  --topic trading.commands
```

---

## 性能参考

生产环境资源配置(推荐):
```
MySQL: 4 核 8GB 内存 (SSD)
RabbitMQ: 2 核 4GB 内存 × 3 节点
Kafka: 4 核 8GB 内存 × 3+ broker
Zipkin: 2 核 4GB 内存
Prometheus: 2 核 4GB 内存
Grafana: 1 核 2GB 内存
```

本地开发(最小配置):
```
单机 Docker: 6+ 核, 16GB 内存, 100GB SSD
```

