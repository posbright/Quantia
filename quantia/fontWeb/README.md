# 玄枢 Quantia 前端项目

基于 Vue 3 + TypeScript + Element Plus + ECharts 构建的智能量化投资中枢前端。

## 技术栈

- **Vue 3** - 渐进式 JavaScript 框架
- **TypeScript** - JavaScript 的超集
- **Vite** - 下一代前端构建工具
- **Element Plus** - Vue 3 组件库
- **ECharts** - 可视化图表库
- **Pinia** - Vue 状态管理
- **Vue Router** - Vue 路由
- **Axios** - HTTP 客户端

## 项目结构

```
fontWeb/
├── public/                 # 静态资源
├── src/
│   ├── api/               # API 接口封装
│   ├── components/        # 公共组件
│   ├── layout/            # 布局组件
│   ├── router/            # 路由配置
│   ├── stores/            # Pinia 状态管理
│   ├── styles/            # 全局样式
│   ├── types/             # TypeScript 类型定义
│   ├── utils/             # 工具函数
│   ├── views/             # 页面视图
│   ├── App.vue            # 根组件
│   └── main.ts            # 入口文件
├── index.html             # HTML 模板
├── package.json           # 依赖配置
├── tsconfig.json          # TypeScript 配置
└── vite.config.ts         # Vite 配置
```

## 快速开始

### 安装依赖

```bash
cd quantia/fontWeb
npm install
```

### 开发模式

```bash
npm run dev
```

访问 http://localhost:3000

### 构建生产版本

```bash
npm run build
```

构建产物在 `dist` 目录

## 开发代理

开发模式下，API 请求会自动代理到后端服务 `http://localhost:9988`，配置在 `vite.config.ts` 中。

## 后端 CORS 支持

后端 `quantia/web/base.py` 已添加 CORS 支持，允许前端跨域访问。

## 功能模块

- **首页** - 系统概览和快速入口
- **综合选股** - 多维度股票筛选
- **股票基本数据** - 每日行情、资金流向、龙虎榜等
- **股票指标** - 技术指标计算和展示
- **K线形态** - K线形态识别
- **策略选股** - 多种内置选股策略
- **选股验证** - 策略回测验证（自定义回测 / 回测汇总 / 回测看板）
