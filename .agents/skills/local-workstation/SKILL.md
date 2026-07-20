---
name: local-workstation
description: 当任务涉及归一量化本地工作站、Cursor、Codex、ChatGPT 外部审查、Git、Docker、规则文件与工程入口时使用。
---

# Local Workstation Skill

## 工具模型

- Cursor：主 IDE / 人工检查。
- Codex：主力开发 Agent。
- GPT + GitHub：架构、Issue / PR / diff 审查。
- 用户：Plan / 生产写入 / merge / deploy 批准。
- Git：安全绳。

WorkBuddy / CodeBuddy / dispatcher 已退出正式架构。见 `docs/DEVELOPMENT.md`。

## 标准流程

1. `git status` / `bash scripts/engineering/preflight.sh`
2. 大改前 checkpoint；非 `main` 分支开发。
3. 实现后：`bash scripts/engineering/test.sh` 或定向 pytest。
4. 生产写入前：`bash scripts/engineering/production-write-check.sh --action <name> --confirm-production-write`
5. Cursor 查看 diff；复杂逻辑可交 GPT 审查。
6. 用户 merge；不自动 push/merge/deploy。

## 禁止

- 多个 Agent 同时改同一个 worktree。
- 提交 `.env`、token、密码、license。
- 静默降级数据源或削弱 secret Gate。
- 自动交易 / 自动 merge。
