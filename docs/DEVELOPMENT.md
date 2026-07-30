# 开发、Review 与集成流程

更新时间：2026-07-30

本文只定义协作 Lane、会话、worktree、PR 与人工 Gate。产品、数据、回测、信号和 Runtime
业务语义分别由 `PROJECT_SOURCE.md`、`DECISIONS.md` 和对应 deep canonical 定义。

## Lane

| Lane | 适用范围 | 默认执行 |
|---|---|---|
| Lane 1 | typo、低风险测试与不改变行为的小修 | 定向验证、普通 Review |
| Lane 2 | 文档、普通 API/Web、只读服务与局部工程实现 | Plan-then-execute、task worktree、定向测试 |
| Lane 3 | migration、正式数据/live 写入、策略/回测口径、通知、删除、release、Runtime | 先 Plan；真实操作另需 exact SHA/scope/hash 绑定的人工 Gate |

Lane 2 与 Lane 3 可以出现在同一长期流水线，但一个 task/PR 只执行一个明确任务。不得用
Lane 2 的代码或文档批准替代 Lane 3 的真实写入、删除、release 或 Runtime Gate。

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
-> user/manual merge
```

合规 Lane 1/2 受控入口可在 ADR-WS-004 前置满足时执行 commit、push 与 Draft PR；不得自动
ready-for-review 或 merge。Lane 3、`main`、tag、release、Runtime promotion、真实通知和
GitHub 规则变更始终保留人工 Gate。

只有 task worktree clean、task HEAD 已被 `develop` 包含且用户允许清理时，才可移除 task
worktree/branch。Draft PR 创建后保留 worktree 以处理 Review。

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
