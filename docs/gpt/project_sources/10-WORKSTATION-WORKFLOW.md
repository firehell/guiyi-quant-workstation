# Workstation Workflow

更新时间：2026-07-14

事实来源：`docs/workstation/`、`docs/workflows/`、`CODEX_TASKS.md`

当前状态：current，真实交付仍需按 TASK Gate 执行。

## 工具分工

- Browser GPT：阶段规划、架构取舍、风险审查。
- Codex：仓库内计划、实现、测试、文档更新。
- Cursor：人工检查和 Git checkpoint。
- WorkBuddy：需求整理、QA、交付报告，不改业务逻辑。
- CodeBuddy：受控远程执行入口，走 `scripts/ai/dispatch_task.sh`。

## 工作纪律

- 正式代码修改必须有 TASK_ID。
- L1/L2 正式开发不直接改 main。
- 不 push、merge、deploy。
- 不读取或提交凭据。
- 不静默 fallback 数据源。
- allowed_paths / forbidden_paths 由 TASK 决定。

## 本轮任务边界

本轮是文档事实源收口，只允许 Markdown/任务文档范围，不修改代码、数据或运行配置。

