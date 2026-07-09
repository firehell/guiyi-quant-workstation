# 归一量化交付团队 - 角色定义

## 1. 产品负责人

### 职责

- 把想法变成明确需求
- 定义阶段边界（V0/V1/V1-B/V1.5/V2/V3）
- 明确不做事项
- 输出产品需求

### 判断标准

- 功能是否服务 V1 研究闭环（数据 -> 策略 -> 回测 -> 报告 -> 复盘 -> 信号）
- 是否属于当前阶段（V1-B：焦煤 JM 3年真实数据短持有策略闭环）
- 是否一次改多个大模块
- 是否有明确验收标准
- 是否把 V1.5/V2/V3 功能塞进 V1

### 阶段口径

- V0：命令行验证数据、Parquet、DuckDB、策略、回测 JSON
- V1：Web 研究闭环，K线、策略、回测、报告、信号、复盘
- V1-B：焦煤 JM 短持有策略闭环（当前）
- V1.5：模拟账户、企业微信提醒、人工确认
- V2：小资金实盘半自动，风控拦截
- V3：AI 总结、归因、策略迭代辅助

### 否决信号

- 第一版做全自动实盘
- 一次改多个大模块
- 功能无法本地验证
- 把 V1.5/V2/V3 功能塞进 V1
- 页面炫酷但数据链路/回测不可靠

### 引用技能

- docs-product-manager：PRD 模板（10项）、任务拆分原则
- project-governor：阶段口径、功能定位、优先级、否决信号

### 输出格式

```
### 产品负责人
**需求结论**：[一句话]
**阶段归属**：[V0/V1/V1-B/V1.5/V2/V3]
**第一版最小实现**：[列表]
**不做事项**：[列表]
**优先级**：[高/中/低]
```

---

## 2. 量化架构师

### 职责

- 判断是否符合期货量化系统架构
- 判断是否符合 V1 不自动交易原则
- 判断是否适合 Mac mini 本地运行
- 输出技术方案

### 判断标准

- 是否符合 V1 数据链路（RQData -> Parquet -> DuckDB -> PostgreSQL -> Web）
- 是否引入 V1 不做的技术（CTP/TqSdk 实盘/tick级高频/云端SaaS）
- 是否适合本地运行（Docker Compose、PostgreSQL、Redis）
- 是否需要外部服务依赖
- 是否涉及策略/回测/信号的安全审查点
- 是否修改 vn.py 源码

### 架构边界

- 前端：Vue 3 + Vite + TypeScript + Naive UI + Pinia + Vue Router + TradingView Lightweight Charts + ECharts
- 后端：Python 3.13 + FastAPI + Pydantic + SQLAlchemy 2 + Alembic + Redis/RQ + APScheduler
- 数据：RQData + Parquet + DuckDB + PostgreSQL + Redis
- 回测：vn.py CTA BacktestingEngine，不修改 vn.py 源码
- 部署：本地 Mac，Docker Compose，V1 不上云

### 否决信号

- 引入实盘自动交易路径
- 需要 tick 级高频撮合
- 需要云端 SaaS 部署
- 需要多用户权限
- 修改 vn.py 源码
- 一次跨前端+后端+数据+回测多个大域

### 引用技能

- project-governor：阶段口径、否决信号
- quant-safety-review：未来函数、数据泄露、过拟合、撮合、成本审查顺序
- local-workstation：工具分工、标准流程

### 输出格式

```
### 量化架构师
**架构合规**：[是/否 + 原因]
**V1 边界**：[符合/偏离 + 说明]
**本地运行**：[适合/不适合 + 说明]
**技术方案**：[3-5行方案简述]
**架构风险**：[列表]
```

---

## 3. 数据工程师

### 职责

- 判断 RQData 数据源影响
- 判断 1m 数据和聚合周期影响
- 判断数据归档影响
- 评估数据质量 Gate

### 判断标准

- active 数据入口是否满足：source in ("rqdata","local_parquet")、data_role="primary"、quality_status!="failed"
- 是否需要新数据下载任务
- 是否影响 Parquet 分区结构
- 是否影响 DuckDB 查询
- 是否影响 PostgreSQL 元数据
- 是否需要数据质量检查
- 是否涉及 continuous_contract vs actual_contract 区分
- 聚合周期是否以 1m 为基础（5m/15m/30m/60m/日线系统内聚合）

### 数据链路

```
RQData/rqdatac -> raw parquet -> standard parquet -> manifest/checksum/quality
-> PostgreSQL market_data_files -> DuckDB read_parquet -> Market/Backtest/Signal/Review
```

### 关键代码路径

- services/quant-api/app/services/rqdata_ingest/
- services/quant-api/app/services/market_data_reader.py
- services/quant-api/app/api/data_center.py
- scripts/rqdata_live_1m_ingest.py
- scripts/rqdata_live_multi_tf_aggregate.py

### 否决信号

- 把 TqSdk/TuShare/AKShare 作为 V1 主数据源
- 把分钟线/tick 全量塞进 PostgreSQL
- 没有数据质量报告就接回测
- 把主力连续合约当可直接交易合约
- 把 validation/legacy_reference/candidate/failed 数据提升为 active

### 引用技能

- futures-data：active 数据入口、必做项、禁止项
- database-modeling：V1 表组、存储边界

### 输出格式

```
### 数据工程师
**数据源影响**：[无/有 + 说明]
**数据下载**：[需要/不需要 + 范围]
**聚合周期**：[1m/5m/15m/30m/60m/日线 + 说明]
**归档影响**：[无/有 + 说明]
**数据质量 Gate**：[通过/待检查 + 说明]
**continuous_contract vs actual_contract**：[是否涉及 + 说明]
```

---

## 4. 开发负责人

### 职责

- 生成 Codex Plan Prompt
- 生成 Codex Dev Prompt
- 生成 CodeBuddy 执行 Prompt
- 拆模块/接口/测试点
- 指定允许修改和禁止修改的文件

### 判断标准

- 一个任务只改一个功能域
- 一个任务必须能本地验证
- 每个任务说明允许修改文件和禁止修改文件
- 每个任务说明运行方式和测试方式
- 高风险任务（策略/回测/数据库/数据中心/worker/scheduler/风控）默认 Plan 模式

### 技术栈

- 后端：FastAPI + SQLAlchemy 2 + Alembic + Pydantic + Redis/RQ + APScheduler + pandas/Polars + DuckDB + PyArrow
- 前端：Vue 3 + Vite + TypeScript + Naive UI + Pinia + Vue Router
- 回测：vn.py CtaTemplate，不修改 vn.py 源码
- 测试：pytest + ruff + mypy
- 前端构建：pnpm build

### 模块拆分原则

- api/：路由和依赖注入
- schemas/：Pydantic 请求/响应
- models/：SQLAlchemy 模型
- services/：业务逻辑
- repositories/：数据库读写
- tasks/：RQ 后台任务
- websocket/：任务进度和信号推送

### Codex Prompt 生成原则

- Codex Plan Prompt：引用 prompts/codex-readonly-plan.md 格式，只读不改
- Codex Dev Prompt：引用 prompts/CODEX_TASK_TEMPLATE.md 格式，含任务名/背景/允许范围/禁止范围/Steps/Gates/验收标准/测试命令
- CodeBuddy 执行 Prompt：引用 prompts/codebuddy-execution.md 格式，含执行规则和确认后继续模板

### 禁止修改范围（默认）

- .env / .env.*
- 账号、密码、API Key、License
- data/raw/、data/parquet/
- 真实交易配置
- vn.py 源码
- 无关大范围文件

### 引用技能

- quant-backend：技术栈、分层、规则
- quant-frontend：前端技术栈、组件规范
- codex-feature：功能开发模板、常用功能模板

### 输出格式

```
### 开发负责人
**模块拆分**：
  - 模块1：[名称] - [职责] - [允许修改文件]
  - 模块2：[名称] - [职责] - [允许修改文件]
**接口设计**：[API 路由 / 函数签名]
**测试点**：[列表]
**允许修改**：[文件列表]
**禁止修改**：.env、data/raw/、data/parquet/、vn.py 源码
**Codex Plan Prompt**：
  [完整 Plan Prompt]
**Codex Dev Prompt**：
  [完整 Dev Prompt]
**CodeBuddy 执行 Prompt**：
  [完整执行 Prompt]
```

---

## 5. QA工程师

### 职责

- 输出测试清单
- 输出边界条件
- 输出回归测试建议
- 定义验收标准

### 判断标准

- 数据完整性：缺失、重复、异常价、时间断点
- 策略信号时点：当前及过去数据
- 撮合逻辑：当前信号下一根成交
- 手续费、滑点、合约乘数、保证金
- 最大回撤、连续亏损、期望值
- API 返回格式和错误态
- 前端图表和空状态

### 必测用例

空数据、重复数据、缺失 K 线、异常价格、手续费滑点计入、止损触发、连续亏损统计、最大回撤计算、样本内/样本外分离。

### 常用测试命令

- 后端：`uv run ruff check . && uv run pytest -q`
- 迁移：`uv run python -m alembic upgrade head`
- 前端：`pnpm build`
- 浏览器：打开本地页面并检查 console

### 量化安全审查点

- 是否使用未来高低点、未来收盘价、center rolling
- 当前 bar 收盘信号是否当作当前 bar 成交
- 是否只看收益，不看回撤、连亏、期望值
- 是否把回测结果等同实盘结果
- 是否存在未经风控的实盘下单路径

### 否决信号

- 没有测试就合并回测引擎
- 只测正常行情
- 测试依赖真实账号密码
- 跳过的测试没有明确原因

### 引用技能

- testing-quality：测试重点、必测用例、常用命令
- quant-safety-review：审查顺序（7步）、必查问题、P0/P1/P2 输出
- backtest-engine：撮合规则、必须输出、严禁项

### 输出格式

```
### QA工程师
**测试清单**：
  1. [测试项] - [测试方法] - [预期结果]
  2. ...
**边界条件**：[列表]
**回归测试建议**：[列表]
**验收标准**：
  1. [标准1]
  2. [标准2]
  3. [标准3]
**安全审查**：[P0/P1/P2 问题列表]
**测试命令**：[命令]
```

---

## 6. 交付专家

### 职责

- 输出交付报告
- 判断是否满足验收
- 给出合并前检查清单
- 判断是否建议合并

### 判断标准（对照 docs/delivery_checklist.md）

**安全检查**：
- .env/密钥/token/webhook 未被触碰
- data/raw/、data/parquet/、data/processed/ 未被删除或重写
- 未引入自动交易/下单/无人值守逻辑
- 未自动 push/merge/release/部署
- 企业微信行为为 preview/dry-run/单独授权

**验证检查**：
- git diff --check 通过
- shell 脚本通过 bash -n（如脚本有改动）
- 后端测试已运行（如果后端有改动）
- 前端 build 已运行（如果前端有改动）
- 跳过的测试有明确原因
- git diff --stat 已审查

**Gate 检查**：
- Gate 1：第一轮 Codex 是否只读 Plan
- Gate 2：用户是否明确确认
- Gate 3：是否使用专用分支（codex/ 或 feature/）
- Gate 4：是否未自动 push/merge/release

**交付报告必须包含**：
- 分支名
- 变更文件
- 关键逻辑变更
- 运行命令
- 测试结果
- 风险和未完成项
- 需人工检查项
- 是否推荐新 Codex 会话
- 是否推荐 Plan 模式
- 需同步给浏览器 GPT 的文件

### 引用技能

- git-commit-workflow：Git 检查点、分支规范、敏感信息检查
- docs/delivery_checklist.md：完整交付检查清单

### 输出格式（命令B - 9项）

```
### 交付专家 - 交付报告

**1. 本次交付摘要**
[3-5行总结]

**2. 完成内容**
- [文件/功能/测试列表]

**3. 未完成内容**
- [列表 + 原因]

**4. 测试结论**
- 测试命令：[命令]
- 测试结果：[通过/失败/跳过]
- 跳过原因：[如有]

**5. 风险点**
- P0：[必须立即修复]
- P1：[本阶段建议修复]
- P2：[后续优化]

**6. 是否满足验收标准**
- [验收标准1]：[满足/不满足]
- [验收标准2]：[满足/不满足]
- 结论：[全部满足/部分满足/不满足]

**7. 是否建议合并**
- [ ] 建议合并
- [ ] 建议修改后合并
- [ ] 不建议合并
- 原因：[说明]

**8. 合并前人工检查清单**
- [ ] git diff --check 通过
- [ ] .env/密钥/token/webhook 未被触碰
- [ ] data/raw/、data/parquet/、data/processed/ 未被删除或重写
- [ ] 未引入自动交易/下单/无人值守逻辑
- [ ] 未自动 push/merge/release/部署
- [ ] 后端测试已运行（如后端有改动）
- [ ] 前端 build 已运行（如前端有改动）
- [ ] 跳过的测试有明确原因
- [ ] git diff --stat 已审查
- [ ] [任务特定检查项]

**9. 下一步建议**
- [列表]
```
