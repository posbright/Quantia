# 生产环境部署检查清单

**文件名**: 生产环境上线前检查清单  
**适用**: W24 全量发布前必须执行  
**负责人**: DevOps Lead + Tech Lead + QA Lead  
**签字**: CTO / VP Engineering

---

## 检查清单总体结构

```
⊙ 前置条件检查 (必须 100%)
  ├─ 开发测试检查
  ├─ 代码质量检查
  └─ 依赖安全检查

⊙ 基础设施检查 (必须 100%)
  ├─ 计算资源检查
  ├─ 存储检查
  ├─ 网络检查
  └─ 备份恢复检查

⊙ 应用配置检查 (必须 100%)
  ├─ 数据库检查
  ├─ 缓存检查
  ├─ MQ 检查
  └─ 监控检查

⊙ 安全检查 (必须 100%)
  ├─ 认证授权检查
  ├─ 数据安全检查
  └─ 审计检查

⊙ 业务验收检查 (必须 95%+)
  ├─ 功能测试
  ├─ 性能测试
  ├─ 压力测试
  └─ 兼容性测试

⊙ 灾难恢复检查 (必须 100%)
  ├─ RTO 验证
  ├─ RPO 验证
  └─ 回滚预案验证
```

---

## ✅ 前置条件检查

### 开发测试检查

- [ ] **代码分支已合并**
  - PR 已 review, 所有 comment 已解决
  - 命令: `git log --oneline main | head -1`
  - 预期: 最新 commit 是生产版本代码

- [ ] **所有单元测试通过**
  - 命令: `mvn test -pl notification-svc`
  - 覆盖率: >= 80%
  - 命令: `mvn jacoco:report | grep "TOTAL"`

- [ ] **集成测试已通过**
  - 命令: `mvn verify -Pintegration`
  - 所有 E2E 场景已验证

- [ ] **部署测试已执行**
  - 在 Stage 环境部署成功
  - 灰度流程已完整演练

### 代码质量检查

- [ ] **SonarQube 扫描已通过**
  - 命令: `mvn clean verify sonar:sonar`
  - 代码坏味: <= 5
  - 技术债: 可接受
  - 评级: A 或 B

- [ ] **静态代码分析已通过**
  - Checkstyle: 0 个错误
  - FindBugs: 0 个严重错误
  - 命令: `mvn verify`

- [ ] **代码格式化已执行**
  - 命令: `mvn formatter:format`
  - Git diff: 仅格式化变更

### 依赖安全检查

- [ ] **CVE 扫描已通过 (Critical = 0)**
  - 命令: `trivy image registry.company.com/quantia/notification-svc:v1.0`
  - Critical CVE: 0 个
  - High CVE: 可接受 (<=2)

- [ ] **许可证合规检查**
  - 命令: `mvn license:check`
  - 所有依赖许可证: GPL/Proprietary 已获批

- [ ] **依赖过时检查**
  - 命令: `mvn versions:display-updates`
  - 没有过时的安全补丁版本

---

## ✅ 基础设施检查

### 计算资源检查

- [ ] **生产服务器资源充足**
  - CPU: >= 8 核 (推荐 16 核)
  - 内存: >= 32 GB (notification-svc: 4GB, im-gateway-svc: 4GB)
  - 检查: `lscpu && free -h`

- [ ] **Kubernetes 集群健康**
  - 命令: `kubectl get nodes`
  - 所有 Node: Ready 状态
  - 命令: `kubectl top nodes`
  - 内存使用: < 70%, CPU 使用: < 60%

- [ ] **容器镜像已构建和优化**
  - 镜像大小: < 500 MB
  - Base 镜像: openjdk:17-slim 或类似(不用 ubuntu)
  - 命令: `docker inspect registry.company.com/quantia/notification-svc:v1.0 | jq '.Size'`

### 存储检查

- [ ] **MySQL 磁盘空间充足**
  - 可用空间: > 100 GB
  - 增长率: 每月 < 10 GB (可预测)
  - 检查: `df -h /var/lib/mysql`

- [ ] **数据库备份已配置**
  - 备份频率: 每 6 小时全量备份
  - 备份存储: 异地存储 (AWS S3 或类似)
  - 备份测试: 每周恢复验证 1 次
  - 命令: `mysqldump --version && ls -lh /backup/mysql/`

- [ ] **RabbitMQ 持久化已启用**
  - 持久化卷: >= 50 GB
  - 检查: `rabbitmqctl status | grep disk_limit`
  - Mnesia 数据目录: 已配置持久化卷

- [ ] **Kafka 保留策略已配置**
  - 保留时间: 7 天
  - 保留大小: >= 100 GB (根据吞吐量)
  - 检查: 
    ```bash
    kafka-topics --describe --bootstrap-server kafka:9092 \
      --topic trading.commands
    ```

### 网络检查

- [ ] **负载均衡器已配置**
  - 类型: Nginx / HAProxy / AWS ALB
  - Health Check: 每 5 秒检查一次
  - 会话保持: 不需要 (无状态服务)

- [ ] **防火墙规则已配置**
  ```
  入站规则:
  - TCP 8081 (notification-svc): 仅内部网络
  - TCP 8082 (im-gateway-svc): 仅内部网络
  - TCP 3306 (MySQL): 仅 App 层
  - TCP 5672 (RabbitMQ): 仅 App 层
  
  出站规则:
  - DingTalk API: TCP 443 (已 whitelist)
  - 外部监控系统: TCP 443 (已 whitelist)
  ```

- [ ] **DNS 已配置**
  - notification-svc: notification.quantia.internal
  - im-gateway-svc: im-gateway.quantia.internal
  - 测试: `nslookup notification.quantia.internal`

### 备份恢复检查

- [ ] **备份策略已验证**
  ```
  MySQL:
  - 全量备份: 每天 02:00 UTC
  - 增量备份: 每 30 分钟
  - 保留期: 30 天
  
  Kafka:
  - 副本因子: >= 3
  - Rebalance: 配置 auto
  
  RabbitMQ:
  - 集群模式: 3 节点
  - 定义备份: 每日导出 definitions.json
  ```

- [ ] **恢复测试已通过**
  - 恢复时间 (RTO): < 1 小时
  - 数据丢失 (RPO): < 30 分钟
  - 测试时间: 每月末执行 1 次全恢复演练

---

## ✅ 应用配置检查

### 数据库检查

- [ ] **所有表已创建**
  ```bash
  mysql -h production-mysql -u root -pPROD_PWD quantiadb -e "SHOW TABLES;" | wc -l
  # 应该 >= 15 个表
  ```

- [ ] **数据库连接池已优化**
  ```yaml
  spring:
    datasource:
      hikari:
        maximum-pool-size: 20        # 生产: 20-50
        minimum-idle: 5
        connection-timeout: 30000
        idle-timeout: 600000
        max-lifetime: 1800000
  ```

- [ ] **数据库参数已优化**
  ```sql
  mysql> SHOW VARIABLES LIKE 'max_connections';  -- >= 1000
  mysql> SHOW VARIABLES LIKE 'innodb_buffer_pool_size';  -- >= 2GB
  mysql> SHOW VARIABLES LIKE 'slow_query_log';  -- ON
  ```

- [ ] **字符集已验证**
  ```sql
  mysql> SHOW CREATE TABLE cn_stock_notification_event;
  -- CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  ```

### 缓存检查

- [ ] **Redis 集群已启动**
  ```bash
  redis-cli -h production-redis ping
  # 应该返回 PONG
  ```

- [ ] **Redis 密码已设置**
  ```yaml
  spring:
    redis:
      password: ${REDIS_PASSWORD}  # 从环境变量读取
  ```

- [ ] **Redis 持久化已配置**
  ```bash
  redis-cli CONFIG GET save
  # 应该配置持久化
  ```

### MQ 检查

- [ ] **RabbitMQ 集群已启动 (3+ 节点)**
  ```bash
  rabbitmqctl cluster_status
  # 应该显示所有节点 running
  ```

- [ ] **RabbitMQ 交换机和队列已创建**
  ```bash
  rabbitmq-plugins enable rabbitmq_management
  rabbitmqctl list_exchanges
  rabbitmqctl list_queues
  # notification exchange, DLX 已存在
  ```

- [ ] **Kafka 集群已启动 (3+ broker)**
  ```bash
  kafka-broker-api-versions --bootstrap-server kafka:9092
  # 应该返回 3+ brokers
  ```

- [ ] **Kafka Topic 已创建**
  ```bash
  kafka-topics --list --bootstrap-server kafka:9092
  # trading.commands, trading.executions 已存在
  ```

### 监控检查

- [ ] **Prometheus 已启动并抓取指标**
  ```bash
  curl http://prometheus:9090/api/v1/targets
  # 所有 target: UP 状态
  ```

- [ ] **Grafana Dashboard 已创建**
  ```
  仪表板列表:
  - Quantia 通知服务
  - Quantia IM 网关
  - 系统基础设施
  - JVM 性能
  ```

- [ ] **告警规则已加载**
  ```bash
  curl http://prometheus:9090/api/v1/rules | jq '.data.groups | length'
  # 应该 >= 10 个告警规则组
  ```

- [ ] **日志聚合已配置**
  ```
  Elasticsearch: 已启动
  Kibana: 已启动
  Filebeat: 已在所有 App 服务器部署
  ```

---

## ✅ 安全检查

### 认证授权检查

- [ ] **服务间调用已认证**
  ```java
  // 所有 HTTP 调用都应该带 JWT token 或 mTLS
  @GetMapping("/notify")
  @PreAuthorize("hasRole('ADMIN')")
  public Response notify() { }
  ```

- [ ] **数据库账户权限已分离**
  ```sql
  -- App 用户只有 SELECT/INSERT/UPDATE 权限
  GRANT SELECT, INSERT, UPDATE ON quantiadb.* TO 'quantia_app'@'%';
  
  -- 备份用户只有 SELECT 权限
  GRANT SELECT ON quantiadb.* TO 'quantia_reader'@'%';
  
  -- 管理员用户有 ALL 权限(仅 DBA)
  ```

- [ ] **API 端点已保护**
  ```
  公开端点: 
  - /health, /metrics (仅内部网络)
  
  受保护端点:
  - /api/notify (需要认证)
  - /api/command (需要认证 + 风控检查)
  ```

### 数据安全检查

- [ ] **敏感数据已加密**
  ```
  钉钉 secret: 已加密存储
  用户信息: 已 AES-256 加密
  API token: 已 bcrypt 哈希
  ```

- [ ] **HTTPS 已启用**
  ```
  所有外部通信: HTTPS (443)
  内部通信: 可选 (IDC 内部网络)
  证书: 有效期 >= 30 天
  ```

- [ ] **SQL 注入防护**
  ```java
  // 所有 SQL 查询必须使用参数化
  @Query("SELECT * FROM cn_stock_notification_event WHERE id = ?1")
  // 或使用 JPA
  eventRepository.findById(id);
  ```

- [ ] **日志脱敏**
  ```java
  // 不应该在日志中输出密码、token、user_id 等敏感信息
  log.info("User notified"); // ✓
  log.info("Notified user_id: " + userId); // ✗ 敏感信息
  ```

### 审计检查

- [ ] **审计日志已启用**
  ```sql
  SELECT * FROM cn_audit_log 
  WHERE service_name = 'notification-svc' 
  ORDER BY created_at DESC LIMIT 10;
  ```

- [ ] **敏感操作已记录**
  - 配置修改: 记录操作人、时间、修改内容
  - 交易指令: 记录操作人、检查结果、执行结果
  - 数据库变更: 记录 schema 变更

---

## ✅ 业务验收检查

### 功能测试

- [ ] **通知功能已测试**
  ```
  场景 1: 模拟交易成交 → 钉钉收到通知
  场景 2: 消息失败 → 自动重试
  场景 3: 重试失败 → 进入 DLQ
  
  验证:
  - 通知内容正确
  - 送达时间 < 5s
  ```

- [ ] **IM 指令已测试**
  ```
  场景 1: 合法指令 → 执行
  场景 2: 超出风控 → 拒绝 + 提示
  场景 3: 签名错误 → 拒绝
  
  验证:
  - 指令解析正确
  - 风控规则生效
  ```

- [ ] **API 兼容性已测试**
  ```
  - Python web 能调用 Java 服务 ✓
  - 返回格式兼容 ✓
  - 错误处理一致 ✓
  ```

### 性能测试

- [ ] **性能基准已验证**
  ```
  notification-svc:
  - TPS: >= 500
  - 延迟 P99: < 5s
  - 内存使用: < 500 MB
  - CPU 使用: < 50%
  
  im-gateway-svc:
  - TPS: >= 100
  - 延迟 P99: < 2s
  ```

- [ ] **资源利用率已验证**
  ```bash
  # 在生产环境运行 1 小时压力测试
  jmeter -n -t notification_load_test.jmx -Jusers=100 -Jrampup=10 -Jduration=3600
  
  # 检查 JVM 内存
  curl http://notification-svc:8081/actuator/metrics/jvm.memory.used
  ```

### 压力测试

- [ ] **系统压力测试已执行**
  ```
  场景: 3 倍正常负载持续 1 小时
  
  目标:
  - 错误率: < 0.5%
  - 延迟稳定(无明显增长)
  - 内存稳定(无内存泄漏)
  ```

- [ ] **故障转移已测试**
  ```
  场景: 随机杀死 Pod 30 次
  
  验证:
  - 自动重启成功
  - 数据一致
  - 业务无间断
  ```

### 兼容性测试

- [ ] **浏览器兼容性已测试** (如有 Web 前端)
  - Chrome/Firefox/Safari: ✓

- [ ] **客户端兼容性已测试**
  - 旧版本 Python web (v0.9): ✓
  - 新版本 Python web (v1.0): ✓

---

## ✅ 灾难恢复检查

### RTO 验证 (恢复时间目标)

- [ ] **故障检测时间: < 2 分钟**
  ```
  告警延迟: < 1 分钟
  人工响应时间: < 1 分钟
  ```

- [ ] **恢复启动时间: < 30 分钟**
  ```
  Pod 重启: < 2 分钟
  数据库恢复: < 20 分钟
  应用预热: < 5 分钟
  ```

- [ ] **总 RTO: < 1 小时**

### RPO 验证 (恢复点目标)

- [ ] **MySQL 数据丢失: < 30 分钟**
  ```
  备份频率: 每 30 分钟
  WAL 日志: 持续备份
  ```

- [ ] **Kafka 消息丢失: 0**
  ```
  副本因子: 3
  acks=all: 确认所有副本写入
  ```

### 回滚预案验证

- [ ] **快速回滚脚本已测试**
  ```bash
  # 验证回滚脚本可工作
  ./rollback.sh --dry-run
  # 应该输出回滚步骤但不执行
  ```

- [ ] **回滚时间: < 10 分钟**
  ```
  流程:
  1. 停止 Java 服务 (1 min)
  2. 切换流量到 Python (1 min)
  3. 等待 Python Pod 就绪 (3 min)
  4. 验证业务正常 (2 min)
  5. 通知 Stakeholder (2 min)
  ```

---

## ✅ 上线前最终检查

### 文档完整性

- [ ] **上线文档已准备**
  - [ ] 部署指南 (./CANARY_DEPLOYMENT.md)
  - [ ] 故障排查手册 (./TROUBLESHOOTING.md)
  - [ ] 运维手册 (./OPERATIONS.md)
  - [ ] API 文档 (自动生成 Swagger)

- [ ] **团队培训已完成**
  - [ ] DevOps: 部署、监控、故障恢复
  - [ ] 开发: 代码改进、调试
  - [ ] QA: 测试策略、验收标准
  - [ ] 业务: 功能变化、使用流程

### 沟通准备

- [ ] **利益相关者已通知**
  - [ ] CTO: 已批准上线
  - [ ] VP Product: 已确认功能
  - [ ] 用户: 已通知功能变化
  - [ ] 支持团队: 已准备应急

- [ ] **值班人员已安排**
  - [ ] W24 灰度上线: 架构师 + DevOps
  - [ ] W24-W25: 7x24 现场支持

### 最后检查清单

- [ ] 所有 checklist 项都标记为 ✅
- [ ] 没有 ⚠️ 或 ❌ 项
- [ ] 所有 Critical 问题已解决
- [ ] 签字人已确认

---

## 📋 签字页

| 角色 | 姓名 | 签名 | 日期 | 备注 |
|---|---|---|---|---|
| **CTO** | | _____________ | _______ | |
| **VP Product** | | _____________ | _______ | |
| **Tech Lead** | | _____________ | _______ | |
| **QA Lead** | | _____________ | _______ | |
| **DevOps Lead** | | _____________ | _______ | |

**签字说明**: 所有签字人确认本清单所有项已验证完毕，风险可控，同意进行生产环境部署。

---

## 附录: 快速查询

### 常见问题排查

| 问题 | 快速检查 | 解决方案 |
|---|---|---|
| MySQL 连接失败 | `telnet mysql 3306` | 检查防火墙、密码 |
| RabbitMQ 队列积压 | `rabbitmqctl list_queues` | 增加消费者或 check 错误 |
| Kafka 消费延迟 | `kafka-consumer-groups` | 增加 partition 或消费者 |
| 内存溢出 | `kubectl top pod` | 增加内存限制或 check 泄漏 |
| 性能下降 | Prometheus metrics | 增加资源或优化查询 |

### 重要命令速查

```bash
# 查看 Pod 日志
kubectl logs -f deployment/notification-svc -n quantia-services

# 进入 Pod 容器
kubectl exec -it pod/notification-svc-xxx -n quantia-services -- /bin/bash

# 查看资源使用
kubectl top pod -n quantia-services

# 查看事件日志
kubectl describe pod <pod-name> -n quantia-services

# 重启服务
kubectl rollout restart deployment/notification-svc -n quantia-services

# 回滚到上一版本
kubectl rollout undo deployment/notification-svc -n quantia-services
```

---

**最后更新**: 2026-06-11  
**版本**: 1.0  
**所有者**: DevOps Team

