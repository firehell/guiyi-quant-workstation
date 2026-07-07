# AI Development Workflow

生成时间：2026-07-07

## 1. 分工

| 工具 | 角色 |
|---|---|
| 浏览器 GPT | 需求分析、方案设计、任务拆分、外部审查 |
| Codex | 读取仓库、修改代码、跑测试、更新文档、输出变更摘要 |
| Cursor | 少量人工检查和必要手动处理 |
| Git / GitHub Desktop | checkpoint、提交、PR 管理 |
| 本地工作站 | 长期运行和远程执行环境 |

## 2. 当前事实源

新会话优先阅读：

1. `AGENTS.md`
2. `README.md`
3. `tasks/current.md`
4. `docs/gpt/CURRENT_STATE.md`
5. `docs/gpt/PROJECT_SNAPSHOT.md`
6. `docs/gpt/NEXT_STEPS.md`
7. `docs/ARCHITECTURE.md`
8. `docs/DATA_CENTER.md`
9. `docs/BACKTEST_ENGINE.md`
10. `docs/STRATEGY_CURRENT_STATE.md`

## 3. 当前阶段

Stage 2C / 2D / 2E 已完成。下一步：

1. `DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS`
2. `WEB-DATA-3B-DATA-PAGE-SMOKE`

Stage 3 建议新 Codex 会话 + Plan 模式。

## 4. Codex 执行规则

- 每轮先读 `tasks/current.md` 和相关事实源。
- 小步修改，保持可回滚。
- 不扩大任务范围。
- 不把未完成能力写成已完成。
- 修改后必须运行相关测试或说明无法运行原因。
- 完成后更新任务记录和 GPT 同步文件。
- 涉及数据写入、数据库 schema、worker、scheduler、回测口径或策略重大变化时，默认先 Plan 模式。

## 5. 安全边界

- 不提交 `.env`、账号、密码、API Key、webhook、token、license。
- 不打印密钥。
- 不自动下单。
- 不接实盘交易。
- 不把 validation、legacy_reference、candidate、failed 数据作为正式默认读取。
- 不覆盖 JM v1 / v2 数据，除非任务明确授权。

## 6. 完成报告格式

每轮完成后输出：

1. 本次做了什么。
2. 修改了哪些文件。
3. 新增了哪些关键逻辑。
4. 执行了哪些测试或检查命令。
5. 测试结果是否通过。
6. 风险、未完成项或人工确认点。
7. 是否建议开新 Codex 会话。
8. 是否建议使用 Plan 模式。
9. 建议同步给浏览器 GPT 的文件。
