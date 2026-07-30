# 开发、Review 与集成流程

更新时间：2026-07-30

本文只定义协作 Lane、会话、worktree、PR 与人工 Gate。产品、数据、回测、信号和 Runtime
业务语义分别由 `PROJECT_SOURCE.md`、`DECISIONS.md` 和对应 deep canonical 定义。

## Lane

| Lane | 适用范围 | 默认执行 |
|---|---|---|
| Lane 1 | typo、低风险测试与不改变行为的小修 | task worktree、验证、独立 Review、可自动集成 develop |
| Lane 2 | 文档、普通 API/Web、只读服务与局部工程实现 | Plan-then-execute、task worktree、测试、独立 Review、可自动集成 develop |
| Lane 3 | migration、正式数据/live 写入、策略/回测口径、通知、删除、release、Runtime | 代码/dry-run/隔离 migration/disabled 功能可自动集成；真实操作另需人工 Gate |

Lane 2 与 Lane 3 可以出现在同一长期流水线，但一个 task/PR 只执行一个明确任务。不得用
Lane 2 的代码或文档批准替代 Lane 3 的真实写入、删除、release 或 Runtime Gate。
冻结设计或总计划已经获得用户一次性预批准时，不再重复请求任务内 Plan、普通代码修改、
Review 修复或通过 Gate 后的 task→`develop` 集成批准。

## 会话与 worktree

1. 从刷新后的 `develop` exact SHA 创建独立 task branch/worktree。
2. `main`、`develop` 与 detached Runtime checkout 均不得直接修改。
3. 开始时记录 branch、worktree、base SHA、status 与最近提交；发现 base 漂移、相关并发修改
   或 active canonical 冲突时停止。
4. task worktree 位于 `/Volumes/扩展盘/GuiyiWorktrees/tasks/`。不得覆盖其他会话改动。
5. 每个可独立 Review 的任务使用独立实现上下文；独立 Review 不能由实现者自审代替。

## PR 与集成

```text
develop exact SHA
-> task branch/worktree
-> validation
-> commit
-> Draft PR to develop
-> independent Review
-> exact-head CI recheck
-> Codex GitHub merge commit to develop
-> ancestor/readback verification
-> cleanup
```

`task-worktree.sh` 仍只负责固定验证、commit、push 与 Draft PR；它不调用 `gh pr merge`。
Codex 编排层只在任务验收、CI、独立 Review 均通过且 PR head SHA 与已审查 task HEAD 精确
匹配时，才可将 PR 标记 ready 并通过 GitHub merge commit 合入 `develop`。Lane 3 只有代码、
测试、dry-run、隔离 migration 和默认 disabled 功能适用此规则。

生产 PostgreSQL migration apply、真实 RQData/canonical/DB 写入、删除、`main`/release/tag、
Runtime promotion、live enable、真实通知和 GitHub 规则变更始终保留人工 Gate。

只有 task worktree clean、task HEAD 已被 `develop` 包含且远端回读一致时，才可自动移除
task worktree/branch。Draft PR 创建后保留 worktree 以处理 Review；merge 失败或 head 漂移
时保留全部状态并 fail-closed。

## 验证与停止

每个任务先运行定向检查，再运行任务合同指定的模块/工程 Gate、引用扫描和
`git diff --check`。测试、代码完成与外部 Gate 必须分别陈述。

出现以下任一情况立即停止：范围需要扩大、需要新架构选择、三轮后验证仍失败、需要凭据、
真实数据/DB/通知/删除/release/Runtime 但缺少专用批准，或 base/active canonical 发生漂移。

## 权威边界

- 当前状态：`STATUS.md`
- 长期产品与数据边界：`PROJECT_SOURCE.md`、`DECISIONS.md`
- 工程执行规则：`AGENTS.md`
- 数据核心 V2 active 合同：`docs/tasks/GY-DATA-CORE-V2.md`
- worktree/release 细节：`docs/WORKTREE_RELEASE_WORKFLOW.md`

本文不得复制或重新解释业务 canonical。
