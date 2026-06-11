# 灰度部署操作手册

**文件名**: 此为灰度部署标准操作流程  
**周期**: W22-W24 (项目周期)  
**风险**: 低(已有完整回滚方案)  
**所有者**: DevOps + Product Owner

---

## 1. 灰度部署总体策略

### 1.1 分阶段上线

```
┌─────────────────────────────────────────────────────────┐
│ W22: Stage 1 - 5% 流量                                  │
│ 特性开关: 100% 控制，单机故障可止损                      │
│ 监控: 严密，每 1 分钟检查关键指标                        │
│ 观察期: 2-3 天                                          │
└─────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│ W23: Stage 2A - 25% 流量                                │
│ 监控: 持续严密，2 倍异常自动告警                         │
│ 观察期: 2 天                                            │
└─────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│ W23: Stage 2B - 50% 流量                                │
│ 条件: 无严重问题，1 倍异常自动告警                       │
│ 观察期: 1 天                                            │
└─────────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│ W24: Stage 3 - 100% 全量发布                            │
│ Python 版本保留为 2 周回滚版本                           │
│ 监控告警: 进入 SLA 模式                                 │
└─────────────────────────────────────────────────────────┘
```

### 1.2 流量切割方式

**Option 1: 基于用户 ID (推荐)**
```python
# Python web 层
if user_id % 100 < CANARY_PERCENTAGE:  # e.g., 5
    use_java_service = True
else:
    use_java_service = False
```

**Option 2: 基于负载均衡器**
```nginx
upstream notification_backend {
    server notification-java:8081 weight=5;    # 5% 
    server notification-python:9999 weight=95; # 95%
}
```

**Option 3: 基于 Feature Flag (最灵活)**
```java
// 在 Java 服务中
@GetMapping("/notify")
public Response notify() {
    if (featureFlagClient.isEnabled("notification.v2.rollout")) {
        return newImplementation();
    } else {
        return fallbackToPython();
    }
}
```

---

## 2. W22: Stage 1 灰度 (5% 流量)

### 2.1 前置检查清单

- [ ] **发布镜像已构建并通过安全扫描**
  - 命令: `trivy image registry.company.com/quantia/notification-svc:v1.0`
  - CVE 数: 0 个 Critical, 可接受 Medium

- [ ] **数据库迁移已验证**
  - 新表已创建: `cn_stock_notification_event`, `cn_stock_notification_config`
  - 兼容性: 无 schema breaking changes
  - 回滚方案: 旧版本可读取新表

- [ ] **Python 原始版本已备份**
  - 镜像已 tag: `notification-python:v0.9-stable`
  - 可直接回滚到此版本

- [ ] **监控告警已配置**
  - Prometheus 规则已加载
  - Grafana Dashboard 已创建
  - PagerDuty 集成已测试

- [ ] **Feature Flag 已部署**
  - 特性开关已激活 (5%)
  - 开关控制平面可用
  - 回滚按钮已验证可用

### 2.2 部署步骤

**Step 1: 在 K8s 中部署 Java 服务**
```bash
# 1. 创建 namespace (如果不存在)
kubectl create namespace quantia-services

# 2. 部署 Java 版本 notification-svc
kubectl apply -f notification-svc-k8s-deployment.yaml -n quantia-services

# 3. 验证 Pod 启动
kubectl get pods -n quantia-services
kubectl logs -f deployment/notification-svc -n quantia-services
```

**Step 2: 配置流量切割**

*方式 1: Python web 层实现*
```python
# quantia/web/service.py
CANARY_PERCENTAGE = 5  # 灰度比例

def route_notification_request(user_id, event):
    if user_id % 100 < CANARY_PERCENTAGE:
        # 发送到 Java 服务
        response = requests.post(
            'http://notification-svc:8081/api/notify',
            json=event,
            timeout=5
        )
    else:
        # 使用原有 Python 实现
        response = send_notification_python(event)
    return response
```

*方式 2: Nginx 负载均衡*
```nginx
upstream notification_backend {
    server notification-java:8081 weight=5;      # 新 Java 服务 5%
    server notification-python:9999 weight=95;   # 老 Python 服务 95%
}

server {
    listen 8080;
    location /api/notify {
        proxy_pass http://notification_backend;
    }
}
```

**Step 3: 验证服务健康**
```bash
# 1. 检查 K8s Pod 状态
kubectl get pods -n quantia-services -w

# 2. 检查 Java 服务日志
kubectl logs -f deployment/notification-svc -n quantia-services --tail=100

# 3. 检查应用指标
curl http://notification-svc:8081/actuator/metrics | jq

# 4. 验证数据库连接
curl http://notification-svc:8081/actuator/health
```

### 2.3 观察期监控 (2-3 天)

**关键指标**:
```
① 错误率: 应该 <= 原有错误率
   目标: <0.1%
   告警阈值: >0.5%

② 延迟 P99: 应该 <= 5s (符合 SLA)
   告警阈值: >8s

③ MQ 消费延迟: 应该 <100ms
   告警阈值: >1s

④ 数据库连接: 应该 <50
   告警阈值: >100

⑤ RabbitMQ 队列堆积: 应该 <1000
   告警阈值: >5000
```

**监控命令**:
```bash
# 查看 Prometheus 指标
curl 'http://prometheus:9090/api/v1/query?query=rate(http_requests_total[5m])'

# 查看 Grafana 面板
# 访问 http://grafana:3000 → Quantia Dashboard

# Kubernetes 监控
kubectl top pods -n quantia-services
kubectl describe pod <pod-name> -n quantia-services
```

### 2.4 Stage 1 完成标准

**必须满足的条件**:
- ✅ 无 Critical 错误日志
- ✅ 错误率 <= 原有错误率 × 1.5
- ✅ 延迟 P99 < 8s (健康)
- ✅ 用户反馈无异常

**如果不满足**:
→ 立即回滚 (见 3.1 章节)

---

## 3. W23: Stage 2 灰度 (25% → 50% 流量)

### 3.1 快速回滚流程

**全量回滚命令**:
```bash
# 1. 停用 Feature Flag (立即止损)
kubectl set env deployment/gateway CANARY_PERCENTAGE=0 -n quantia-services

# 2. 或删除 Java Pod (立即恢复 Python)
kubectl delete deployment notification-svc -n quantia-services

# 3. 验证流量已切回 Python
# 检查日志中是否只有 Python 实现的请求

# 4. 发出事件通知
# 发送告警到 PagerDuty 及 Slack
```

**部分回滚流程**:
```bash
# 1. 降低灰度比例
kubectl set env deployment/gateway CANARY_PERCENTAGE=2 -n quantia-services

# 2. 监控 15 分钟
sleep 900

# 3. 如果问题持续,继续全量回滚
```

### 3.2 Stage 2 部署

**25% 流量切割** (Stage 2A):
```bash
# 在 gateway 中更新灰度比例
kubectl set env deployment/gateway CANARY_PERCENTAGE=25 -n quantia-services

# 等待 2 天观察
```

**50% 流量切割** (Stage 2B):
```bash
# 在 gateway 中更新灰度比例
kubectl set env deployment/gateway CANARY_PERCENTAGE=50 -n quantia-services

# 等待 1 天观察
```

### 3.3 Stage 2 完成标准

- ✅ 无新增错误类型
- ✅ 性能指标稳定
- ✅ 用户反馈<1 条 (10000 用户量)
- ✅ 团队信心: Go/No-go 投票通过

---

## 4. W24: Stage 3 (100% 全量发布)

### 4.1 全量发布

```bash
# 1. 更新流量比例为 100%
kubectl set env deployment/gateway CANARY_PERCENTAGE=100 -n quantia-services

# 2. 验证所有流量已切换
kubectl logs -f deployment/gateway -n quantia-services | grep "routing.*java"

# 3. Python 版本改为"仅紧急回滚用"
# 停止定期更新,保留 2 周作为回滚版本
kubectl scale deployment notification-python --replicas=0 -n quantia-services
```

### 4.2 全量发布后监控 (1-2 周)

**SLA 监控**:
```
错误率: <= 0.1% (99.9% 可用性)
延迟 P99: < 5s
消费延迟: < 500ms
```

**每天检查清单**:
- [ ] 09:00 - 查看 Grafana 仪表板
- [ ] 12:00 - 检查 Error logs
- [ ] 16:00 - 业务方反馈调查
- [ ] 20:00 - 性能基准对比

### 4.3 稳定后处理

**2 周后**:
```bash
# 1. 删除 Python 备用版本
kubectl delete deployment notification-python -n quantia-services

# 2. 文档归档
# - 将灰度流程记录在项目 Wiki
# - 将学到的经验分享给团队

# 3. 下一步改造
# - 开始 im-gateway-svc 灰度
```

---

## 5. 灾难恢复场景

### 场景 1: RabbitMQ 宕机

```
观察症状: Java 服务日志 "Connection refused"

恢复步骤:
1. kubectl describe pod rabbitmq-0 -n quantia-services
   → 检查是否 CrashLoopBackOff
   
2. kubectl logs rabbitmq-0 -n quantia-services
   → 查看启动错误

3. kubectl delete pod rabbitmq-0 -n quantia-services
   → 触发自动重启

4. 等待 Pod 重新启动 (约 60 秒)

5. 验证:
   curl http://rabbitmq:15672 
   → 应该返回 200 OK
```

### 场景 2: 数据库连接耗尽

```
观察症状: "too many connections" 错误

恢复步骤:
1. 查看当前连接数
   mysql -h mysql -u root -proot -e "SHOW STATUS LIKE 'Threads%';"
   
2. 如果 > 95% 连接池:
   a) 快速回滚 (降低灰度比例)
   b) 等待连接释放 (约 5 分钟)
   c) 重试逐步上线

预防措施:
- 在 application.yml 中配置:
  hikari:
    maximum-pool-size: 20
    leak-detection-threshold: 60000
```

### 场景 3: 内存溢出

```
观察症状: Pod OOMKilled

恢复步骤:
1. 检查内存使用
   kubectl top pod <pod-name> -n quantia-services
   
2. 增加内存限制
   kubectl set resources deployment notification-svc \
     --limits=memory=2Gi \
     -n quantia-services
     
3. 重新部署
   kubectl rollout restart deployment/notification-svc -n quantia-services
```

---

## 6. 监控仪表板配置

### Grafana 关键指标

创建 Grafana Dashboard:
```json
{
  "dashboard": {
    "title": "Quantia 通知服务灰度部署",
    "panels": [
      {
        "title": "请求率 (RPM)",
        "targets": [
          {"expr": "rate(http_requests_total[1m])"}
        ]
      },
      {
        "title": "错误率 (%)",
        "targets": [
          {"expr": "rate(http_requests_total{status=~\"5..\"}[1m]) * 100"}
        ]
      },
      {
        "title": "延迟 P99 (ms)",
        "targets": [
          {"expr": "histogram_quantile(0.99, http_duration_ms)"}
        ]
      },
      {
        "title": "RabbitMQ 队列深度",
        "targets": [
          {"expr": "rabbitmq_queue_messages_ready"}
        ]
      }
    ]
  }
}
```

### 告警规则

```yaml
groups:
  - name: notification_canary
    rules:
      - alert: HighErrorRateCanary
        expr: rate(http_errors_total[5m]) > 0.005  # 0.5%
        for: 5m
        annotations:
          summary: "灰度部署错误率过高"
          
      - alert: HighP99Latency
        expr: histogram_quantile(0.99, http_duration_ms) > 8000
        for: 5m
        annotations:
          summary: "灰度部署延迟过高"
```

---

## 7. 文档和沟通

### 每阶段沟通模板

**Stage 1 启动邮件**:
```
主题: [通知] Quantia 通知服务灰度部署 Stage 1 启动

内容:
- 启动时间: 2026-06-15 10:00
- 灰度比例: 5%
- 监控仪表板: http://grafana:3000/...
- 问题反馈: #quantia-oncall 频道
- 预计完成: 2026-06-17 17:00

如发现问题,我们将立即回滚。
```

**日报模板**:
```
日期: 2026-06-15
灰度阶段: Stage 1 (5%)
错误率: 0.08% (正常)
延迟 P99: 3.2s (良好)
用户反馈: 无
下一步: 继续观察

签名: DevOps Team
```

---

## 8. 附录: 完整回滚脚本

```bash
#!/bin/bash
# 完整回滚脚本

set -e

echo "========== 灰度部署回滚脚本 =========="
echo "警告: 此脚本将完全回滚到 Python 版本"
read -p "确认执行回滚? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "取消回滚"
    exit 0
fi

NAMESPACE="quantia-services"

echo "Step 1: 停止 Java 服务..."
kubectl scale deployment notification-svc --replicas=0 -n $NAMESPACE

echo "Step 2: 切换 Feature Flag..."
kubectl set env deployment/gateway CANARY_PERCENTAGE=0 -n $NAMESPACE

echo "Step 3: 恢复 Python 服务..."
kubectl scale deployment notification-python --replicas=3 -n $NAMESPACE

echo "Step 4: 等待 Pod 就绪..."
kubectl wait --for=condition=ready pod \
  -l app=notification-python -n $NAMESPACE --timeout=300s

echo "Step 5: 验证流量..."
sleep 10
curl -s http://notification-python:9999/health | jq

echo "✅ 回滚完成! 已恢复到 Python 版本"
echo "请检查监控仪表板: http://grafana:3000"
```

保存为 `rollback.sh`,执行:
```bash
chmod +x rollback.sh
./rollback.sh
```

---

## 总结检查清单

- [ ] **W22 完成**: Stage 1 (5%) 运行 2-3 天无异常
- [ ] **W23 完成**: Stage 2 (25%→50%) 运行 3 天无异常
- [ ] **W24 完成**: Stage 3 (100%) 全量发布
- [ ] **后续**: Python 版本保留 2 周作为回滚版本
- [ ] **沟通**: 每日邮件通知项目 Stakeholder

