# Spring Boot 项目结构与开发指南

**文件名**: 此为项目结构规范文档  
**适用**: 所有 Java 微服务 (notification-svc, im-gateway-svc, 等)  
**版本**: 1.0

---

## 项目整体结构

```
quantia-services/                          ← 父项目
├── pom.xml                                ← 父 POM (依赖管理)
├── docker-compose.yml                     ← Docker 一键启动
├── init.sql                               ← 数据库初始化
├── docs/                                  ← 项目文档
│   ├── API_SPEC.md
│   ├── DEPLOYMENT.md
│   └── TROUBLESHOOTING.md
│
├── gateway/                               ← Spring Cloud Gateway
│   ├── src/
│   │   ├── main/java/com/quantia/gateway/
│   │   │   ├── config/
│   │   │   │   ├── GatewayConfig.java      ← 网关路由配置
│   │   │   │   └── SecurityConfig.java     ← 安全配置
│   │   │   ├── filter/
│   │   │   │   ├── TraceFilter.java        ← 链路追踪过滤
│   │   │   │   ├── RateLimitFilter.java    ← 限流过滤
│   │   │   │   └── AuthFilter.java         ← 认证过滤
│   │   │   └── GatewayApplication.java
│   │   └── resources/
│   │       ├── application.yml
│   │       ├── application-dev.yml
│   │       └── application-prod.yml
│   └── pom.xml
│
├── notification-svc/                      ← 通知服务
│   ├── src/
│   │   ├── main/java/com/quantia/notification/
│   │   │   ├── controller/
│   │   │   │   ├── HealthController.java   ← 健康检查
│   │   │   │   └── MetricsController.java  ← 指标暴露
│   │   │   ├── service/
│   │   │   │   ├── NotificationService.java     ← 核心业务逻辑
│   │   │   │   ├── DingTalkService.java         ← 钉钉集成
│   │   │   │   ├── RetryService.java            ← 重试管理
│   │   │   │   └── ReconciliationService.java   ← 对账
│   │   │   ├── entity/
│   │   │   │   ├── NotificationEvent.java   ← JPA 实体
│   │   │   │   └── NotificationConfig.java
│   │   │   ├── repository/
│   │   │   │   ├── NotificationEventRepository.java   ← Spring Data JPA
│   │   │   │   └── NotificationConfigRepository.java
│   │   │   ├── mq/
│   │   │   │   ├── RabbitMQConsumer.java    ← RabbitMQ 消费者
│   │   │   │   ├── RabbitMQProducer.java    ← RabbitMQ 生产者(仅演示)
│   │   │   │   └── MessageListener.java     ← 消息监听器
│   │   │   ├── config/
│   │   │   │   ├── RabbitMQConfig.java      ← RabbitMQ 配置
│   │   │   │   ├── JpaConfig.java           ← JPA 配置
│   │   │   │   ├── HttpClientConfig.java    ← HTTP 客户端
│   │   │   │   ├── CacheConfig.java         ← 缓存配置
│   │   │   │   └── MicrometerConfig.java    ← 指标配置
│   │   │   ├── exception/
│   │   │   │   ├── BusinessException.java
│   │   │   │   ├── GlobalExceptionHandler.java  ← 全局异常处理
│   │   │   │   └── ErrorCode.java
│   │   │   ├── util/
│   │   │   │   ├── JsonUtils.java
│   │   │   │   ├── IdGenerator.java         ← 分布式 ID 生成
│   │   │   │   ├── CryptoUtils.java         ← 加密工具
│   │   │   │   └── HttpUtils.java
│   │   │   ├── interceptor/
│   │   │   │   ├── TraceInterceptor.java    ← 链路追踪拦截
│   │   │   │   └── LoggingInterceptor.java
│   │   │   ├── aspect/
│   │   │   │   └── MetricsAspect.java       ← 方法级指标
│   │   │   └── NotificationApplication.java ← 启动类
│   │   │
│   │   └── resources/
│   │       ├── application.yml               ← 开发配置
│   │       ├── application-dev.yml           ← 开发环境覆盖
│   │       ├── application-prod.yml          ← 生产环境覆盖
│   │       ├── application-test.yml          ← 测试环境覆盖
│   │       ├── logback-spring.xml            ← 日志配置
│   │       ├── messages.properties           ← 国际化
│   │       └── banner.txt                    ← 启动 banner
│   │
│   ├── test/java/com/quantia/notification/
│   │   ├── service/
│   │   │   └── NotificationServiceTest.java  ← 单元测试
│   │   ├── mq/
│   │   │   └── RabbitMQConsumerTest.java    ← MQ 测试
│   │   ├── integration/
│   │   │   └── NotificationIntegrationTest.java  ← 集成测试
│   │   └── config/
│   │       └── TestConfig.java               ← 测试配置
│   │
│   └── pom.xml                              ← 服务级 POM
│
├── im-gateway-svc/                        ← IM 网关服务(类似结构)
│   ├── src/main/java/com/quantia/im/
│   │   ├── controller/
│   │   │   ├── DingTalkCallbackController.java  ← 钉钉回调接收
│   │   │   └── CommandController.java
│   │   ├── service/
│   │   │   ├── IMService.java
│   │   │   ├── DingTalkService.java
│   │   │   ├── RiskControlEngine.java       ← 风控引擎
│   │   │   ├── CommandParser.java           ← 指令解析
│   │   │   ├── StateMachine.java            ← 状态机
│   │   │   └── KafkaProducer.java           ← Kafka 生产者
│   │   ├── entity/
│   │   ├── repository/
│   │   ├── mq/
│   │   ├── config/
│   │   │   ├── KafkaConfig.java             ← Kafka 配置
│   │   │   └── DingTalkConfig.java
│   │   └── util/
│   │       ├── SignatureValidator.java      ← 签名验证
│   │       └── CommandValidator.java
│   └── pom.xml
│
├── ai-decision-svc/                       ← AI 决策服务(可选)
│   └── (类似结构)
│
└── live-trade-svc/                        ← 实盘交易服务(可选)
    └── (类似结构)
```

---

## 关键配置文件示例

### Parent pom.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.quantia</groupId>
    <artifactId>quantia-services</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>

    <name>Quantia Microservices</name>
    <description>Java 微服务改造项目</description>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.1.0</version>
        <relativePath/>
    </parent>

    <properties>
        <java.version>17</java.version>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <spring-cloud.version>2022.0.3</spring-cloud.version>
        <micrometer.version>1.11.0</micrometer.version>
    </properties>

    <modules>
        <module>gateway</module>
        <module>notification-svc</module>
        <module>im-gateway-svc</module>
        <module>ai-decision-svc</module>
        <module>live-trade-svc</module>
    </modules>

    <dependencyManagement>
        <dependencies>
            <!-- Spring Cloud -->
            <dependency>
                <groupId>org.springframework.cloud</groupId>
                <artifactId>spring-cloud-dependencies</artifactId>
                <version>${spring-cloud.version}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>

            <!-- RabbitMQ -->
            <dependency>
                <groupId>com.rabbitmq</groupId>
                <artifactId>amqp-client</artifactId>
                <version>5.17.1</version>
            </dependency>

            <!-- Kafka -->
            <dependency>
                <groupId>org.apache.kafka</groupId>
                <artifactId>kafka-clients</artifactId>
                <version>7.4.0</version>
            </dependency>

            <!-- Redis -->
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-starter-data-redis</artifactId>
                <version>3.1.0</version>
            </dependency>
        </dependencies>
    </dependencyManagement>

    <dependencies>
        <!-- 基础依赖 -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>

        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>

        <!-- 链路追踪 -->
        <dependency>
          <groupId>io.micrometer</groupId>
          <artifactId>micrometer-tracing-bridge-brave</artifactId>
        </dependency>

        <!-- 指标收集 -->
        <dependency>
            <groupId>io.micrometer</groupId>
            <artifactId>micrometer-registry-prometheus</artifactId>
        </dependency>

        <!-- 配置管理 -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-configuration-processor</artifactId>
            <optional>true</optional>
        </dependency>

        <!-- 测试 -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
```

### application.yml (notification-svc 示例)

```yaml
spring:
  application:
    name: notification-svc
  
  # JPA 配置
  jpa:
    hibernate:
      ddl-auto: validate
    properties:
      hibernate:
        dialect: org.hibernate.dialect.MySQL8Dialect
  
  # 数据源
  datasource:
    url: jdbc:mysql://mysql:3306/quantiadb?useSSL=false&serverTimezone=UTC&characterEncoding=utf8mb4
    username: quantia
    password: ${MYSQL_PASSWORD:quantia_pwd}
    hikari:
      maximum-pool-size: 20
      minimum-idle: 5
      connection-timeout: 30000
  
  # RabbitMQ
  rabbitmq:
    host: rabbitmq
    port: 5672
    username: quantia
    password: ${RABBITMQ_PASSWORD:quantia_pwd}
    virtual-host: /
    listener:
      simple:
        concurrency: 10
        max-concurrency: 20
        prefetch: 1
  
  # Redis
  redis:
    host: redis
    port: 6379
    password: ${REDIS_PASSWORD:quantia_pwd}
    timeout: 2000
    lettuce:
      pool:
        max-active: 20
        max-idle: 10
  
  # Jackson JSON 配置
  jackson:
    default-property-inclusion: non_null
    date-format: yyyy-MM-dd'T'HH:mm:ss'Z'

# 服务端口
server:
  port: 8081
  servlet:
    context-path: /api

# 日志配置
logging:
  level:
    root: INFO
    com.quantia: DEBUG
  pattern:
    console: "%d{yyyy-MM-dd HH:mm:ss} [%thread] %-5level %logger{36} - %msg%n"

# Actuator (健康检查、指标)
management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics,prometheus
  endpoint:
    health:
      show-details: always

# Zipkin 链路追踪
zipkin:
  base-url: http://zipkin:9411
```

---

## 开发工作流

### 1. 启动开发环境

```bash
# 进入项目目录
cd quantia-services

# 启动所有 Docker 服务
docker-compose up -d

# 等待 MySQL 完全启动(约 30 秒)
sleep 30

# 创建 Kafka Topic (仅需执行一次)
docker exec quantia-kafka kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic trading.commands \
  --partitions 3 \
  --replication-factor 1

# 构建所有项目
mvn clean install -DskipTests

# 启动 gateway
mvn spring-boot:run -pl gateway

# 新开终端,启动 notification-svc
mvn spring-boot:run -pl notification-svc

# 新开终端,启动 im-gateway-svc
mvn spring-boot:run -pl im-gateway-svc
```

### 2. 本地调试

```bash
# IDE 运行配置 (IntelliJ IDEA):
# 1. Run → Edit Configurations
# 2. Add Maven 配置
# 3. Command line: spring-boot:run -Dspring-boot.run.arguments="--debug"
# 4. Run

# 远程 Debug (JDWP):
MAVEN_OPTS="-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5005" \
mvn spring-boot:run -pl notification-svc
```

### 3. 运行测试

```bash
# 全量测试
mvn test

# 仅运行单元测试
mvn test -P unit

# 仅运行集成测试
mvn test -P integration

# 跳过测试构建
mvn clean install -DskipTests

# 特定测试类
mvn test -Dtest=NotificationServiceTest
```

### 4. 代码检查

```bash
# SonarQube 代码质量
mvn clean verify sonar:sonar

# 依赖检查
mvn dependency-check:check

# CVE 扫描
mvn org.owasp:dependency-check-maven:check

# 代码格式化(Google Style)
mvn formatter:format
```

### 5. 打包部署

```bash
# 构建 JAR
mvn clean package -DskipTests

# 构建 Docker 镜像
docker build -t quantia/notification-svc:v1.0 -f notification-svc/Dockerfile notification-svc

# 推送到仓库
docker tag quantia/notification-svc:v1.0 registry.company.com/quantia/notification-svc:v1.0
docker push registry.company.com/quantia/notification-svc:v1.0
```

---

## 代码规范

### 包名约定

```
com.quantia.{service}.{layer}

Layer:
- controller: REST 端点
- service: 业务逻辑
- repository: 数据访问
- entity: JPA 实体
- mq: 消息队列
- config: Spring 配置
- util: 工具类
- exception: 异常定义
- interceptor: 拦截器
- aspect: AOP 切面
```

### 命名规范

| 类型 | 规范 | 示例 |
|---|---|---|
| 类 | PascalCase | NotificationService |
| 接口 | IxxxService 或 xxxService | INotificationService |
| 方法 | camelCase | sendNotification() |
| 常量 | UPPER_SNAKE_CASE | MAX_RETRIES |
| 变量 | camelCase | notificationId |

### 注释规范

```java
/**
 * 发送通知
 * 
 * @param eventId 事件 ID
 * @param channel 通知渠道 (dingtalk/email)
 * @return 是否发送成功
 * @throws BusinessException 业务异常
 */
public boolean sendNotification(String eventId, String channel) {
    // 实现逻辑
}
```

---

## 常见问题

**Q: 如何添加新的 Java 服务?**  
A: 
```bash
# 1. 复制现有服务结构
cp -r notification-svc new-service-svc

# 2. 修改 pom.xml 中的 artifactId
# 3. 在 parent pom.xml 中添加模块
# 4. mvn clean install
```

**Q: 如何连接本地数据库而非 Docker?**  
A: 修改 application-local.yml, 启动时加参数:
```bash
mvn spring-boot:run -Dspring.profiles.active=local
```

**Q: 如何关闭 Spring Security 进行开发?**  
A: 在 application-dev.yml 中:
```yaml
security:
  enabled: false  # 自定义配置
```

