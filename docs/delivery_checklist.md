# Delivery Checklist

更新时间：2026-07-20

> **DEPRECATED 旧控制面指引已移除。** 正式流程见 `docs/DEVELOPMENT.md`；工程入口见 `scripts/engineering/*`。

在任意 Codex / GPT 辅助任务交付前使用本清单。

## Before Development

- [ ] 已读 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md` 与任务相关 deep canonical / Issue。
- [ ] 已检查 `git status --short --branch`。
- [ ] 首轮先 Plan / 只读，用户明确批准后再改代码。
- [ ] 使用独立 `codex/` 或 `feature/` 分支（不直接写 `main`）。
- [ ] 不依赖 WorkBuddy / CodeBuddy / dispatcher 作为正式架构。

## Safety Checks

- [ ] 未触碰 `.env`、secrets、tokens、webhook、cookie、凭据。
- [ ] 未删除或破坏性改写 `data/raw/`、`data/processed/`、`data/parquet/`。
- [ ] 未引入自动交易、订单草稿或无人值守执行。
- [ ] 未自动 push / merge / release / deploy。
- [ ] 企业微信行为仅为 preview / dry-run，或已单独授权。
- [ ] 高风险写入前运行 `scripts/engineering/production-write-check.sh`（未确认则 fail-closed）。

## Verification

- [ ] `git diff --check` 通过。
- [ ] 脚本变更时 `bash -n scripts/engineering/*.sh`（及相关脚本）通过。
- [ ] 优先：`scripts/engineering/preflight.sh` 与 `scripts/engineering/test.sh` / 定向 pytest。
- [ ] 后端 / 前端变更有对应定向测试或 build；跳过项写明原因。
- [ ] 已审阅 `git diff --stat`。

## Delivery Report

最终报告须包含：分支名、变更文件、关键逻辑、命令、测试结果、风险与未完成项、是否需用户 merge。

## GPT / 同步阅读（精简）

- `STATUS.md`
- `AGENTS.md`
- `docs/DEVELOPMENT.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- 任务相关：`docs/ARCHITECTURE.md` / `docs/DATA_CENTER.md` / `docs/BACKTEST_ENGINE.md` / `docs/SIGNAL_EVENTS.md`
- 本清单：`docs/delivery_checklist.md`

旧 WorkBuddy / CodeBuddy / dispatcher 协议与摘要包已归档：`docs/archive/workstation/`、`docs/archive/gpt-sources/`。
