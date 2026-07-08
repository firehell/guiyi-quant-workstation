# Codex 功能开发提示模板

## 使用方式

将此模板内容发送给 Codex 或 GPT-4，用于指导新功能的代码生成。

---

## 提示模板

```
你是归一量化工作站（guiyi-quant-workstation）的开发者。

项目技术栈：
- 前端：Vue 3 + Vite + TypeScript + Naive UI + Pinia + Vue Router + Lightweight Charts + ECharts
- 后端：Python 3.13 + FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL + Redis/RQ
- 数据：RQData / local standard parquet + DuckDB + PostgreSQL
- 回测：vn.py / VeighNa CTA BacktestingEngine，不直接修改 vn.py 源码

当前任务：
[在此描述具体功能需求]

约束条件：
1. V1 不做自动交易，不做无人值守实盘，不把信号直接当成交易指令
2. active 数据入口必须是 rqdata / local_parquet、primary、quality_status != failed
3. 敏感配置只能从环境变量读取，不写入代码、文档、日志或 Prompt
4. 不修改 .env、真实数据目录、vn.py 源码或无关模块
5. 修改前先读 AGENTS.md、docs/CODEX_HANDOFF.md、tasks/current.md 和相关文档
6. 高风险任务先 Plan，确认后再执行

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
- 是否只读：是/否
```

### 新 Vue 组件
```
实现 Vue 组件：[组件名称]
- 功能：[组件描述]
- Props：[属性列表]
- 使用 Naive UI 组件库
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
