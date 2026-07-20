# ADR-WS-001: GitHub Native Control Plane

日期：2026-07-14

状态：Accepted

2026-07-16 更新：WorkBuddy Unified V3 已将远程入口收敛为 WorkBuddy facade；CodeBuddy 保留 compatibility-only 回退。本文的五层事实模型继续有效。

任务：`WS-GH-002`

## 背景

归一量化工作站已经具备 V2 控制平面：TASK、dispatcher、approval、worktree、scope、resource lock、runtime gate、Issue 留痕、result bundle 和 workstation tests。

旧流程仍假设：

```text
WorkBuddy 生成 TASK
-> 用户复制或保存 TASK
-> 本地脚本创建 Issue
-> CodeBuddy 调 Codex
-> 用户把结果或文件重新提供给浏览器 GPT
```

现在 GitHub private repository 已经可以作为 GPT、WorkBuddy、CodeBuddy、Codex、Cursor 和用户共享的事实面。继续依赖人工复制会导致上下文断层、重复创建任务、Issue/TASK/PR 状态漂移。

## 决策

采用 GitHub Native Control Plane 作为 V3 AI 工程控制平面。

权威事实模型为五层：

| 层级 | 权威位置 | 职责 |
|---|---|---|
| 项目事实 | GitHub `main` canonical docs | 长期目标、状态、边界、架构决策 |
| 执行契约 | task branch `docs/tasks/<TASK_ID>.md` | dispatcher 和 Codex 的正式输入 |
| 生命周期 | GitHub Issue | 状态、讨论、远程入口、脱敏摘要 |
| 变更交付 | Draft PR / PR | diff、CI、review、交付讨论 |
| 本地证据 | `.ai/results/<TASK_ID>/` | logs、Plan、approval、test、result、evidence |

冻结以下决策：

1. Issue 不取代 TASK。
2. GPT 默认只在任务分支写文档和任务契约。
3. GPT 不直接写 `main`。
4. Draft PR 是任务从设计到交付的共享容器。
5. `.ai/results` 保持 local-first。
6. WorkBuddy 从默认 TASK 创建者调整为远程 PM / QA。
7. CodeBuddy 保留 compatibility-only 本地执行控制器，不再新增编排功能。
8. Codex 仍是唯一编码执行器。
9. 用户保留 Plan、生产写入、merge 和 deploy 的最终批准权。

## 影响

### 正向影响

- GPT、WorkBuddy、CodeBuddy 兼容入口、Codex、Cursor 和用户围绕同一个 Issue / TASK / PR 工作，减少人工搬运。
- TASK 仍保留 allowed paths、forbidden paths、required tests、risk、approval scope、branch、worktree、resource lock 等机器可读字段。
- Draft PR 成为任务的共享工作区，适合承载设计、diff、CI 和 Review。
- `.ai/results` 继续保存本地执行证据，避免把长日志和敏感上下文完整上传 GitHub。

### 代价

- 需要新增 Issue-first bootstrap、远程 task branch 接管、PR template 和 GPT PR Review protocol。
- 需要修订旧文档中“GPT 外部审查需人工粘贴 diff”和“WorkBuddy 默认创建 TASK”的表述。
- 需要修复当前 GitHub Actions workstation-test 红灯，避免 V3 PR 长期处于不可用 CI 基线。

## 不做事项

- 不重写 dispatcher。
- 不删除 V2 TASK Schema。
- 不把 Issue 改成唯一执行契约。
- 不把 `.ai/results` 完整上传 GitHub。
- 不允许 GPT、WorkBuddy、CodeBuddy、Codex 自动 merge、deploy 或关闭高风险 Issue。
- 不改变数据链路、策略、回测、信号、复盘或实盘边界。

## 验收标准

- GitHub Issue / PR 作为任务生命周期事实面（详见当时控制面文档；原文已随文档树清理删除，见 Git 历史）。
- `PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/DEVELOPMENT.md` 与本 ADR 的「Issue/PR 事实面」不冲突。
- 注：后续 Step 5 将 supersede 本 ADR 中仍强制 dispatcher / V2 schema / WorkBuddy 的条款；本步仅修复断链，不改写决策正文结论。

## 参考

- `AGENTS.md`
- `docs/DEVELOPMENT.md`
- `DECISIONS.md`
- `PROJECT_SOURCE.md`
- 历史控制面正文：Git 历史（原 `docs/workstation/**` / `docs/workflows/**` / `CODEBUDDY.md` 已删除）
