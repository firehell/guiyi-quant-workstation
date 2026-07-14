# 归一量化 [AGENTS.md](http://AGENTS.md)

## 1. 项目定位

归一量化是一个本地运行的国内期货量化研究、回测、复盘、信号扫描和后期半自动实盘辅助系统。

项目不是公开 SaaS，不是普通网站，也不是机构级全自动交易平台。

核心目标是帮助用户从主观期货交易逐步过渡到：

```text

规则化

→ 数据化

→ 回测化

→ 复盘化

→ 预警化

→ 模拟验证

→ 小资金半自动实盘

```

当前项目重点是 V1 Web 研究闭环，不做无人值守自动实盘。

---

## 1.1 当前阶段：V1-B

当前阶段命名：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

V1-B 当前目标：

1. 使用焦煤 JM 最近 3 年真实 RQData / local standard parquet 数据。
2. 日线只用于确定方向。
3. 15分钟可以独立入场。
4. 5分钟可以独立入场。
5. 15m 入场后只持有 5-8 根 15m K线。
6. 5m 入场后只持有 5-8 根 5m K线。
7. 行情不利时按止损方法退出。
8. 回测报告必须入库并能在 Web 展示。
9. K线上必须显示买卖点。
10. 单笔交易必须可以创建复盘 note。
11. 信号扫描只提醒，不自动下单。

旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再作为当前目标。

V1-B 仍属于 V1 研究闭环，不属于 V1.5 / V2 实盘阶段。

---

## 2. 当前 V1 重构路线

本项目 V1 已调整为：

```text

米筐 RQData

→ 标准 Parquet 数据湖

→ DuckDB 查询 / 周期合成

→ [vn.py](http://vn.py) CTA 回测底座

→ 回测结果标准化

→ PostgreSQL 归档

→ Vue Web 展示

→ K线复盘

→ 信号扫描

→ 人工观察

```

### V1 主数据源

```text

米筐 RQData

```

米筐用于：

- 期货历史分钟数据。

- 合约基础信息。

- 主力映射。

- 复权因子。

- 交易参数。

- 手续费、保证金、合约乘数等回测基础字段。

- V1 回测和信号扫描的主数据底稿。

### V1 回测底座

```text

[vn.py](http://vn.py) / VeighNa CTA BacktestingEngine

```

[vn.py](http://vn.py) 用于：

- CTA 策略模板。

- bar 级回测。

- 参数优化候选。

- 后期 CTP 实盘接口候选。

注意：[vn.py](http://vn.py) 是底层框架，不是归一量化最终产品。

### V1 Web

继续使用自定义 Web：

```text

Vue 3 + Vite + TypeScript + Naive UI

```

不要使用 [vn.py](http://vn.py) Studio 作为主项目依赖，不使用 [vn.py](http://vn.py) 自带界面作为最终 Web。

---

## 3. 数据源口径

### 主数据源

| 数据源 | 当前角色 |

|---|---|

| RQData / 米筐 | V1 主数据源 |

| Local Parquet | V1 本地正式数据湖 |

| DuckDB | V1 本地研究查询 |

| PostgreSQL | V1 业务事实库 |

### 降级和候选数据源

| 数据源 | 当前角色 |

|---|---|

| TqSdk / 天勤 | V2 模拟 / 半自动实盘阶段候选，不是 V1 必需依赖 |

| TuShare | V1 移除，后期宏观 / 股票 / 辅助数据候选 |

| AKShare | V1 不作为主链路，仅作为后期辅助候选 |

`.env.example` 中 TqSdk、TuShare、CTP 字段仅作为禁用候选占位，不代表 V1 主链路配置。

### 旧数据处理

| 数据来源 | 处理方式 |

|---|---|

| 早期米筐数据 | 清洗后可并入 standard parquet |

| 天勤旧数据 | 归档为 validation source，仅用于交叉校验 |

| 交易练习者数据 | 标记为 legacy_reference，仅用于页面测试和对照，不用于正式回测 |

正式回测默认只读取：

```text

data_role = primary

source = rqdata / local_parquet

quality_status != failed

```

---

## 4. 固定技术栈

### 前端

- Vue 3

- Vite

- TypeScript

- Naive UI

- Pinia

- Vue Router

- Axios / TanStack Query Vue

- TradingView Lightweight Charts

- Apache ECharts / vue-echarts

- WebSocket

### 后端

- Python 3.13

- FastAPI

- Pydantic / pydantic-settings

- SQLAlchemy 2

- Alembic

- Redis + RQ

- APScheduler / RQ Scheduler

- pandas / Polars

- DuckDB

- PyArrow

- pytest

- ruff

- mypy

### 回测和策略

- [vn.py](http://vn.py) / VeighNa CTA BacktestingEngine

- [vn.py](http://vn.py) CtaTemplate 策略

- 归一量化自定义 Adapter / Runner / ResultConverter

- 不直接修改 [vn.py](http://vn.py) 源码

### 数据仓

- PostgreSQL：合约、品种、任务、策略、报告、信号、复盘、风控。

- Parquet：历史 K线、分钟数据、大体量行情。

- DuckDB：本地研究查询和回测前读取。

- Redis：任务队列和临时状态，不存长期事实。

### 部署

- 本地 Mac / 本地工作站。

- Docker Compose。

- V1 不上云。

- V1 不做多用户权限。

- V1 不做手机 App。

---

## 5. V1 功能范围

V1 必做：

1. 数据中心。

2. 合约管理。

3. 品种池管理。

4. 米筐数据下载与标准化。

5. Parquet 数据湖。

6. DuckDB 查询。

7. 数据质量检查。

8. K线工作台。

9. 策略中心。

10. 策略版本管理。

11. [vn.py](http://vn.py) 回测适配。

12. 回测任务。

13. 回测报告。

14. 交易明细。

15. K线买卖点标记。

16. 信号扫描。

17. 单笔复盘。

18. 风控统计。

19. 系统设置。

V1 不做：

1. 全自动实盘。

2. tick 级高频回测。

3. 复杂盘口队列撮合。

4. Web 策略代码编辑器。

5. AI 自动生成策略并直接运行。

6. 多账户资金管理。

7. 云端 SaaS。

8. 多用户权限。

9. 手机 App。

10. 无人值守自动交易。

---

## 6. 策略方向

V1 优先策略：

1. 苏冰 EMA21 趋势系统。

2. 均线突破 + 趋势过滤系统。

3. N 字结构 / 分型系统。

所有策略必须转成：

```text

入场条件

出场条件

止损规则

止盈规则

过滤条件

参数配置

适用品种

适用周期

回测字段

复盘标签

风控约束

```

V1 策略优先写为 [vn.py](http://vn.py) `CtaTemplate` 版本。

---

## 7. 风控要求

涉及策略、回测、信号、模拟、实盘时，必须默认检查：

1. 是否存在未来函数。

2. 是否存在数据泄露。

3. 是否存在过拟合。

4. 信号生成和成交撮合是否错位合理。

5. 手续费是否计入。

6. 滑点是否计入。

7. 合约乘数是否正确。

8. 保证金占用是否考虑。

9. 单笔风险是否受控。

10. 最大回撤是否统计。

11. 最大连续亏损是否统计。

12. 回测结果是否能复盘到单笔交易。

13. 回测结果不等于实盘结果。

14. 实盘前必须先模拟和小资金验证。

---

## 8. 实盘边界

V1 不接实盘，不下单。

V1.5 可做：

```text

信号扫描

→ Web 展示

→ 人工观察

→ 手动下单

→ 手工录入实际成交

→ 理论成交 vs 实际成交对比

```

V2 再评估：

```text

[vn.py](http://vn.py) CTP Gateway

天勤 TqSdk

继续人工确认下单

```

V2 也必须优先采用：

```text

信号

→ 风控检查

→ 人工确认

→ 发单

→ 成交回报

→ 日志归档

```

禁止第一阶段做：

- 无人值守自动实盘。

- AI 自动下单。

- 高频交易。

- 没有风控拦截的实盘执行。

---

## 8.1 AI 工作站执行规则

居家与远程是**两个入口**，共享同一套 GitHub Native V3 控制平面、TASK 协议与调度器。详细流程见 [`docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`](docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md)、[`docs/workstation/HOME_DEVELOPMENT.md`](docs/workstation/HOME_DEVELOPMENT.md) 与 [`docs/workstation/REMOTE_DEVELOPMENT.md`](docs/workstation/REMOTE_DEVELOPMENT.md)。

所有 Agent / 入口（GPT + GitHub、WorkBuddy、CodeBuddy、Codex、Cursor）必须遵守：

1. **五层事实模型**：GitHub `main` canonical docs 是项目事实源；task branch 中的 `docs/tasks/<TASK_ID>.md` 是执行契约；Issue 是生命周期；Draft PR / PR 是交付容器；`.ai/results/<TASK_ID>/` 是 local-first 执行证据。Issue 不取代 TASK。
2. **开始前读取 TASK 与最近作用域 AGENTS.md**：根目录 `AGENTS.md` 及任务相关子目录规则（若存在）。
3. **不修改 main/master**：GPT、WorkBuddy、CodeBuddy、Codex 不直接写 `main`；L1/L2 正式开发只在 TASK 指定的 branch 与 worktree 中进行。
4. **不 push、merge、deploy**：Git 写操作由用户或 Cursor 人工决定。
5. **不读取、显示或提交凭据**：禁止触碰 `.env`、token、webhook、账号、license。
6. **不静默 fallback**：环境变量、挂载点、数据源缺失时必须 fail-closed 并报告，见 [`docs/workstation/ENVIRONMENT_FAIL_CLOSED.md`](docs/workstation/ENVIRONMENT_FAIL_CLOSED.md)。
7. **数据和挂载 fail-closed**：不得自动创建外置盘、`data/raw/`、`data/parquet/` 或切换降级数据源。
8. **时间序列禁止未来数据**：策略、回测、信号任务默认检查未来函数与数据泄露，见 §7 风控要求。
9. **修改范围服从 allowed_paths / forbidden_paths**：TASK §7 白名单/黑名单由 `collect_result.sh` 校验。
10. **必须运行 required_tests**：TASK §18.0 声明的自动化测试命令必须执行并记录结果。
11. **必须输出修改文件、测试、风险和未完成项**：每步交付须可审查。
12. **Cursor 与 Codex 不得同时写同一 worktree**：人工接管前须获取 writer lock，见 [`docs/workstation/WRITER_LOCK_HANDOFF.md`](docs/workstation/WRITER_LOCK_HANDOFF.md)。

统一调度入口：`scripts/ai/dispatch_task.sh <TASK_ID> <stage>`（stages: `route | plan | dev | fix | test | review | result | pause | resume | cancel | status`）。模型与权限路由见 [`docs/workstation/ROUTING_POLICY.md`](docs/workstation/ROUTING_POLICY.md)。

---

## 9. 开发协作规则

### 工具分工

| 工具 | 角色 |

|---|---|

| Cursor | 人工 IDE / 调试 / Git 管理 / 最终验收 |

| Codex | 唯一代码执行器；按 TASK、dispatcher 和 Gate 执行 Plan / Dev / Test / Review / Result |

| CodeBuddy | Issue-first 本地执行控制器，接收 Issue #N / TASK_ID / PR #N，只调用受控 dispatcher |

| GPT + GitHub | 需求分析、架构、TASK / Issue / Draft PR 创建、外部 PR Review |

| WorkBuddy | 远程 PM、QA、视觉验收、交付摘要；优先读取已有 Issue / TASK / PR，不创建第二套任务状态 |

| GitHub | 全局项目控制平面：main docs、task branch、Issue、Draft PR、PR、CI、历史记录 |

| 用户 | 最终审批、Plan 批准、生产写入授权、merge、deploy 和任务关闭决策 |

| Git | 安全绳 |

### 企业微信半自动协作规则

微信 / 企业微信远程协作的默认链路是：

```text
GPT + GitHub 创建 Issue / task branch / TASK / Draft PR
-> WorkBuddy 远程 PM / QA / 交付摘要（不创建第二套任务）
-> CodeBuddy Issue-first 本地远程入口
-> scripts/ai/dispatch_task.sh <TASK_ID> plan
-> 用户确认 + approve_task.sh
-> scripts/ai/dispatch_task.sh <TASK_ID> dev|test|review|result
-> Issue / PR 回填脱敏摘要
-> 用户 / Cursor 人工验收 / merge
```

硬规则：

1. WorkBuddy 优先读取已有 GitHub Issue、TASK 和 Draft PR，做需求补充、QA 清单、视觉验收和交付摘要；不得创建与 GitHub 脱节的第二套任务状态。
2. CodeBuddy 是远程执行控制器，优先接收 Issue #N，也兼容 TASK_ID；只调用 `scripts/ai/dispatch_task.sh`，不得拼接自由 shell 命令绕过 Gate。
3. CodeBuddy 第一轮必须 dispatch `plan` 阶段；未经用户明确确认，不得进入 `dev`。
4. 开发必须在 TASK 指定 branch/worktree 中执行；不得裸 `codex exec` 或 danger sandbox。
5. 不允许 GPT、WorkBuddy、CodeBuddy、Codex 直接写 `main`，不允许通过企业微信远程自动 push、merge、release、部署或触发真实交易。
6. 不允许打印或写入 `QYWX_WEBHOOK_URL`、CodeBuddy / WorkBuddy Bot Secret、RQData 凭证、cookie、token、license。
7. 远程执行必须先报告 `pwd`、`git rev-parse --show-toplevel`、`git status --short --branch`。
8. 详细流程以 `CODEBUDDY.md`、`docs/workstation/REMOTE_DEVELOPMENT.md` 和 `docs/AI_WECHAT_WORKFLOW.md` 为准。

### 工作级别纪律（L0 / L1 / L2）

详见 `docs/workflows/work_levels.md`。五条纪律：

1. 任何正式代码修改必须有 TASK_ID。
2. 一个 TASK 只对应一个分支和一个 worktree（L1/L2）。
3. 正式开发仍经过 Plan、审批、Dev、测试。
4. 任何入口都写入同一个 `.ai/results/<TASK_ID>/`。
5. 换场景前必须提交或明确记录工作区状态。

### Codex 执行规则

Codex 每次任务必须：

1. 先读 `tasks/current.md`、相关文档和代码。

2. 先输出计划，再修改。

3. 明确允许修改的文件。

4. 明确禁止修改的文件。

5. 小步修改。

6. 修改后说明改了哪些文件。

7. 给出运行命令。

8. 给出测试命令。

9. 不得把账号、密码、token、license 写入代码库。

10. 不得擅自删除旧代码和旧文档。

11. 任务完成后必须说明：

```text

实际修改了哪些文件

为什么这么改

运行命令

测试命令

风险点

遗留问题

下一步建议

```

12. 如果没有运行某项测试，必须明确说明原因。

13. 以当前代码和最新项目快照为准；如果历史聊天、旧文档与当前代码冲突，以当前代码为准。

14. 不得扩大本轮任务范围，不得做无关重构。

15. 策略、回测、数据库、数据中心、worker、scheduler、风控相关任务默认优先 Plan 模式。

16. 前端页面 bug 修复后，如条件允许，使用 Browser 或 Chrome 做页面验收，并说明页面、操作路径、控制台或截图结论。

17. 修改后必须输出变更文件、运行方式、测试结果、风险和后续 TODO。

18. 每轮任务开始前必须读取 `tasks/current.md`；如果文件缺失，先报告缺失项，不得凭历史聊天直接执行。

19. 如果 `tasks/current.md` 是多步骤任务计划，必须按 Steps 顺序执行，不允许跳步、合并高风险步骤或跨任务自动执行。

20. 不允许跳过 Gate；触发 Gate 时必须暂停，报告触发原因、当前完成情况、拟修改文件、风险判断和需要用户确认的问题。

21. 不允许无确认执行高风险步骤；策略、回测、数据库、数据中心、风控任务默认先审查后执行或 Plan 模式。

22. 完成每一步后必须更新任务状态，记录测试命令、测试结果、变更文件和风险；无法更新任务文件时，必须在回复中说明原因。

23. 每一步都必须输出本步变更文件、测试命令、测试结果和风险；如果没有运行某项测试，必须明确说明原因。

24. 前端页面任务完成后，如条件允许，使用 Browser 或 Chrome 验收，并说明页面、操作路径、控制台或截图结论。

### Codex 账号切换流程

旧账号交接前：

1. 运行 `git status --short`，确认工作区状态。

2. 必要时由用户或 Cursor 创建 git checkpoint。

3. 更新 `docs/CODEX_HANDOFF.md`。

4. 更新 `tasks/current.md`。

5. 在最终回复中写清修改文件、运行命令、测试命令、风险点和下一步。

新账号接手后：

1. 先读 `AGENTS.md`、`docs/CODEX_HANDOFF.md`、`tasks/current.md`、`docs/gpt/NEXT_STEPS.md`、`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md` 和 `docs/AGENT_WORKFLOW.md`。

2. 先输出项目理解和接手计划。

3. 明确准备修改哪些文件，以及每个文件准备怎么改。

4. 不依赖历史聊天记忆，以仓库文档和代码为准。

5. 未经用户确认，不直接改代码。

### 禁止

1. 不允许多个 Agent 同时修改同一个文件。

2. 不允许 WorkBuddy 做架构重构或直接修改后端业务逻辑、数据链路、策略、回测、数据库。

3. GPT 可在任务分支创建或修改文档、设计和 TASK 契约；外部审查不得直接改业务代码或 `main`。

4. 不允许 GPT / WorkBuddy / CodeBuddy / Codex 通过远程消息自动 push、merge、release、部署。

5. 不允许 Agent 接实盘自动交易。

6. 不允许提交 `.env`、账号、密码、API Key、CTP 密码、米筐账号、天勤账号。

7. 不允许直接修改 [vn.py](http://vn.py) 源码。

8. 不允许把交易练习者数据混入正式回测。

9. 不允许把 GPT 浏览器聊天中的敏感内容、账号、Token 或交易密钥写入仓库。

---

## 10. 推荐执行顺序

V1 重构必须单线程推进：

```text

1. 文档统一

2. [vn.py](http://vn.py) + RQData 实验目录

3. data_sources 模块

4. vnpy_integration Adapter

5. 苏冰 EMA21 [vn.py](http://vn.py) 策略草稿

6. 回测任务 API

7. Web 回测页面

8. 测试与外部审查（ChatGPT）

```

每一步完成后：

```text

git diff

→ 本地测试

→ 外部审查（ChatGPT）

→ git commit

```
