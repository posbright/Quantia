# 测试文件

本目录包含项目的所有测试文件。

## 目录结构

```
tests/
├── setup.ts              # 测试环境设置
├── api/
│   └── handlers.test.ts  # API Mock 处理器测试
├── mock/
│   └── mockData.test.ts  # Mock 数据验证测试
├── router/
│   └── index.test.ts     # 路由配置测试
├── stores/
│   └── stock.test.ts     # Pinia Store 测试
├── utils/
│   └── index.test.ts     # 工具函数测试
└── views/
    ├── HomeView.test.ts  # 首页组件测试
    └── StockData.test.ts # 股票数据组件测试
```

## 运行测试

```bash
# 运行所有测试
npm run test

# 带 UI 界面运行测试
npm run test:ui

# 运行测试并生成覆盖率报告
npm run test:coverage
```

## 测试覆盖范围

- **组件测试**: 测试 Vue 组件的渲染和交互
- **Store 测试**: 测试 Pinia 状态管理逻辑
- **工具函数测试**: 测试格式化、日期处理等工具函数
- **Mock 数据测试**: 验证 Mock 数据的格式和范围
- **路由测试**: 测试路由配置和导航
- **API 测试**: 测试 Mock API 处理器
