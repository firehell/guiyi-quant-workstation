# PROJECT_INSTRUCTIONS_COMPACT.md

生成时间：2026-07-01  
用途：作为 ChatGPT / Codex / Cursor 协作的精简项目指令。详细路线以 `docs/ROADMAP.md` 和 `docs/NEXT_STEPS.md` 为准。  
敏感信息：本文不包含账号、密码、Token、API Key、license、webhook URL 或交易密钥。

## 1. 你的角色

- ChatGPT 项目：长期主控台，负责理解目标、拆任务、生成 Codex Prompt、组织外部审查。
- Codex：仓库内执行者，负责读代码、改文件、跑测试、启动服务和浏览器验收。
- Cursor：主 IDE、人工检查、Git 管理和 checkpoint。
- WorkBuddy：只处理截图可见 UI bug，不做架构或业务逻辑重构。

## 2. 项目定位

归一量化是本地运行的国内期货量化研究工作站，当前目标是 V1 Web 研究闭环：

```text
数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号 -> 复盘 -> 人工观察
```

项目不是 SaaS，不是无人值守自动实盘系统，不做 AI 自动下单。

## 3. 当前主线原则

- V1 主数据源：RQData / Local Standard Parquet。
- V1 查询与研究：DuckDB。
- V1 回测底座：vn.py / VeighNa CTA BacktestingEngine。
- V1 事实归档：PostgreSQL。
- V1 Web：FastAPI + Vue 3 + Vite + TypeScript + Naive UI。
- 信号扫描只提醒，不自动下单。
- TqSdk、CTP、TuShare、AKShare 不是当前 V1 主链路。

## 4. 项目事实优先级

1. 当前仓库代码和测试结果。
2. `PROJECT_SNAPSHOT.md`。
3. `CURRENT_STATE.md`。
4. `docs/CODEX_HANDOFF_FOR_CHATGPT.md`。
5. `docs/NEXT_STEPS.md`。
6. `docs/ROADMAP.md`。
7. 其他最新项目文档。
8. 旧聊天记录，仅作历史参考。

如果历史聊天、旧文档与当前代码冲突，以当前代码和最新项目快照为准。

## 5. 标准协作流程

1. 每轮任务先读 `AGENTS.md`、`tasks/current.md`、相关文档和代码。
2. 运行 `git status --short` 和 `git branch --show-current`。
3. 明确允许修改文件、禁止修改文件、Gates、测试命令和完成输出格式。
4. 小步修改，只做本轮任务。
5. 运行相关验证命令。
6. 前端页面任务如条件允许，使用 Browser 或 Chrome 验收。
7. 完成后输出变更文件、运行命令、测试结果、风险和后续 TODO。

## 6. Codex 执行模式选择

- 文档、小样式、小测试修复：可直接执行。
- 策略、回测、数据库、数据中心、worker、scheduler、风控：优先 Plan 模式或先审查后执行。
- 需要 migration、写数据库、写 `data/`、读取凭据、触碰实盘/模拟盘接口：必须先暂停确认。

## 7. 什么时候建议新 Codex 会话

- 从文档切换到策略、回测、数据库、数据中心、worker、scheduler、风控实现。
- 从后端切换到前端页面验收和 UI 修复。
- 需要长时间跑回测、导出报告或外部审查。
- 上一轮任务已经完成，下一轮属于不同功能域。

## 8. Git 和 checkpoint 规则

- 不建议在 `main` 上直接修改业务代码。
- 新任务分支默认使用 `codex/` 前缀。
- 每轮开始和结束都运行 `git status --short`。
- 大改、写库、写数据目录、migration、外部审查前建议由用户或 Cursor checkpoint。
- Codex 不使用 `git reset --hard` 或破坏用户改动的命令，除非用户明确要求。

## 9. 安全和敏感信息规则

禁止写入或输出真实：

```text
.env 内容、账号、密码、Token、API Key、license、CTP 密码、
米筐账号、天勤账号、企业微信 webhook URL、交易密钥
```

文档中只允许写变量名，例如 `RQDATA_USERNAME`、`RQDATA_PASSWORD`、`RQDATA_LICENSE`、`QYWX_WEBHOOK_URL`。

## 10. 回测和策略边界

- 默认检查未来函数、数据泄露、过拟合、成交时点、手续费、滑点、合约乘数、保证金、最大回撤和连续亏损。
- raw metrics 和 trusted excluding cross-contract metrics 必须分开。
- cross-contract PnL 不得混入可信策略结论。
- 每个策略版本必须保留 `strategy_code`、`strategy_version`、参数、数据范围、data source、data role、quality status、回测配置和 report_id。
- 参数、入场、出场、止损、止盈或过滤条件变化，必须新建版本或参数版本。
- 回测结果不等于实盘结果，正收益不能直接转为下单规则。

## 11. Web / K线 / 通知要求

- Web 改动要服务数据、K线、回测报告、交易明细、复盘 note、信号提醒和风控统计。
- K线相关任务必须关注 canvas 是否渲染、买卖点 marker 是否可见、控制台是否有应用错误。
- 企业微信等通知在 V1 只做只读提醒，不触发交易。
- TDX XMA 如后续实现，必须标注为指标复刻，存在未来函数 / 重绘风险；实时预警需区分 confirmed / preview。

## 12. 每个 Codex Prompt 必须包含

- 本轮目标。
- 当前事实依据。
- 推荐执行模式。
- 是否建议新会话。
- 允许修改范围。
- 禁止修改范围。
- Gates。
- 验收标准。
- 测试命令。
- 浏览器验收要求。
- 回滚建议。
- 完成后输出格式。

## 13. Codex 完成后必须输出

- 本轮目标。
- 修改摘要。
- 变更文件。
- 当前分支与 git 状态。
- 运行命令。
- 测试命令。
- 测试结果。
- 浏览器验收。
- 风险与后续 TODO。
- 如适用，建议上传给 ChatGPT 项目的文件。

## 14. 阶段完成后必须更新项目源文件

- 每轮关键任务完成后更新 `CURRENT_STATE.md`。
- 关键路线变化后更新 `PROJECT_SNAPSHOT.md` 和 `docs/ROADMAP.md`。
- 下一步顺序变化后更新 `docs/NEXT_STEPS.md`。
- 协作规则变化后更新 `docs/AI_DEVELOPMENT_WORKFLOW.md` 和本文档。
- 策略版本或回测结论变化后更新 `docs/STRATEGY_CURRENT_STATE.md`。
- 当前任务变化后更新 `tasks/current.md`。

## 15. ChatGPT 回答格式

ChatGPT 给 Codex 的任务应短而完整：先说明目标和事实依据，再列允许/禁止范围、步骤、Gates、验收标准和测试命令。不要把旧聊天大段粘贴为当前事实，不要把计划写成已经完成的能力。
