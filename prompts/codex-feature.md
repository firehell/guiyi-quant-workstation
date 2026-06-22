# Codex 功能开发提示模板

## 使用方式

将此模板内容发送给 Codex 或 GPT-4，用于指导新功能的代码生成。

---

## 提示模板

```
你是归一量化工作站（guiyi-quant-workstation）的开发者。

项目技术栈：
- 前端：React 18 + TypeScript + Vite + MUI v5 + Tailwind CSS
- 后端：Python FastAPI + SQLAlchemy 2.0 + PostgreSQL
- 数据：Parquet 格式，存储于 data/parquet/

当前任务：
[在此描述具体功能需求]

约束条件：
1. TypeScript 严格模式，禁用 any
2. Python 必须有类型注解和 docstring
3. 资金计算必须使用 Decimal
4. 敏感配置从环境变量读取
5. 代码风格：Google Style Guide

请按以下顺序输出：
1. 方案简述（3-5 行）
2. 文件列表（哪些文件需要创建/修改）
3. 完整代码实现
4. 测试建议
```

---

## 常用功能模板

### 新 API 端点
```
实现 FastAPI 路由：[端点描述]
- 路径：/api/v1/[resource]/
- 方法：GET/POST/PUT/DELETE
- 请求参数：[参数列表]
- 响应格式：[字段列表]
- 需要鉴权：是/否
```

### 新 React 组件
```
实现 React 组件：[组件名称]
- 功能：[组件描述]
- Props：[属性列表]
- 使用 MUI 组件库
- 需要 WebSocket 实时更新：是/否
```

### 策略模块
```
实现量化策略：[策略名称]
- 继承 BaseStrategy 基类
- 核心逻辑：[信号描述]
- 参数：[参数列表]
- 支持日线/小时线/分钟线
```
