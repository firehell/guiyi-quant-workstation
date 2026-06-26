---
name: local-workstation
description: 当任务涉及归一量化本地工作站、Cursor、Codex、ChatGPT 外部审查、WorkBuddy、Git、Docker、规则文件、多 Agent 协作流程时使用。
---

# Local Workstation Skill

## 工具分工

- Cursor：主 IDE / 人工检查中心。
- Codex：主力开发 Agent。
- ChatGPT（外部）：架构和量化逻辑审查，人工粘贴 diff，不接入 IDE。
- WorkBuddy：截图可见 UI 修复，不改业务逻辑。
- Git：安全绳，大改前 checkpoint。

## 标准流程

1. `git status`。
2. 大改前 checkpoint。
3. Codex 执行单一清晰任务。
4. Cursor 查看 diff。
5. 本地运行测试。
6. 外部审查复杂逻辑（ChatGPT + docs/CODE_REVIEW.md）。
7. WorkBuddy 只修可见 UI。
8. 最终 commit。

## 禁止

- 多个 Agent 同时改同一个文件。
- WorkBuddy 重构业务逻辑。
- 外部审查工具直接改仓库。
- 提交密钥、账号、交易密码。
