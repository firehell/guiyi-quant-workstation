# 开发态 Runtime 文档收口设计

日期：2026-08-10

## 1. 目的

将仓库文档统一到当前已实际执行的临时开发拓扑：launchd 直接绑定主工作区
`develop`，旧 detached Runtime worktree 已删除。同时删除已完成且无 active 引用的
Superpowers 设计/执行工件，避免旧计划继续被误读为当前状态或授权。

本次只收口仓库 Markdown 文档，不修改代码、launchd、Runtime、RQData、Canonical、
数据库、通知或品种范围。

## 2. 当前事实与长期边界

当前开发期拓扑：

```text
develop working tree
-> tests / type checks / build
-> explicit one-time deployment intent
-> launchd reload from develop
-> local API / Web / bounded Live observation
```

开发态部署不是热更新：

- Web 修改需要重新 build 并重载；
- API 与 Live 修改需要重载；
- 每次重载仍属于 Runtime switch，需要当次明确执行意图；
- 17:00 盘后任务会加载当时的 `develop`，因此 dirty 工作区不能形成稳定版本证据。

开发态部署只服务本地快速观察，不构成 Ready、release、Runtime promotion 或最终
MR-08 验收。项目功能收口后，重新创建独立 Runtime worktree，绑定精确提交并重新采集
自然时点证据。

## 3. 删除范围

删除以下已完成且无 active 引用的历史工件，需要时只从 Git history 追溯：

1. `docs/superpowers/plans/2026-08-09-audit-finding-matrix.md`
2. `docs/superpowers/specs/2026-08-09-audit-finding-matrix-design.md`
3. `docs/superpowers/plans/2026-08-09-scoped-data-audit-and-canary-preflight.md`
4. `docs/superpowers/specs/2026-08-09-scoped-data-audit-design.md`
5. `docs/superpowers/plans/2026-08-09-market-runtime-v1.md`

删除前和删除后均扫描文件名、路径与关键合同引用。若发现 active caller，必须在同一变更中转向
canonical；不为删除内容创建备份目录、镜像文档或删除 receipt。

## 4. 保留范围

以下文档不属于“已过期无用历史”：

- `docs/tasks/GY-MARKET-RUNTIME-V1.md`：MR-08 仍未完成自然时点验收；
- DFD-07 滚动单品种设计/计划：当前仍为 4/60；
- Market Research Workspace P0 设计/计划：尚未实施，但需要修正 Runtime 前提；
- `openspec/changes/archive/`：正式 OpenSpec 归档，保留结构化历史，不视为 active 授权；
- active OpenSpec、deep canonical 和当前 task contract。

## 5. Active canonical 更新范围

统一以下文档，不在多份文档中创建不同的部署规则：

- `AGENTS.md`：唯一执行规则，补充当前开发态拓扑和最终独立 Runtime 边界；
- `STATUS.md`：保持当前事实，不把开发态部署写成完成验收；
- `README.md`：给出日常启动与开发态部署的最短路由；
- `PROJECT_SOURCE.md`：保留长期边界，将临时部署根交由 `STATUS.md`；
- `DECISIONS.md`：记录“开发期可直接运行 develop，最终 Runtime 仍独立”的长期决策；
- `TESTING.md`：区分 render/test、开发态重载和最终 Runtime 验收；
- `docs/DEVELOPMENT.md`：说明修改不会自动生效及单次部署授权；
- `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md`：增加开发态部署流和 fail-closed 检查；
- `docs/ARCHITECTURE.md`：区分代码/模板默认关闭、当前本机已启用与部署根；
- `docs/tasks/README.md`：将 `GY-MARKET-RUNTIME-V1.md` 列为尚未完成自然验收的 active contract；
- `docs/tasks/GY-MARKET-RUNTIME-V1.md`：更新 disposition、当前拓扑和未完成 Gate；
- Market Research Workspace P0 设计/计划：从“Runtime 未启用”改为“复用当前已启用 seam，P0
  不改变 Runtime 范围或部署”。

## 6. 单一开发态部署流

```text
clean develop + exact intended commit
-> affected tests / Ruff / Mypy / Web build
-> user explicitly requests one deployment attempt
-> render and validate launchd plists
-> reload only requested API / Web / Live surfaces
-> read back project root, process health and bounded Live state
-> report actual result; no automatic retry or promotion claim
```

盘后任务不用手工命令代替自然 17:00 证据。开发态下收集的自然事件只证明当时的
`develop` 工作树，不直接转为最终独立 Runtime 证据。

## 7. 验收

1. 指定的 5 份过期文档已删除，无 active 引用。
2. Active canonical 对当前 develop 开发态部署、单次授权和最终独立 Runtime 的表述一致。
3. 无 active 文档仍宣称当前 Runtime 未启用、当前运行于旧 detached worktree，或修改会自动生效。
4. P0 和 DFD-07 文档保持与自身范围相关的 active 约束，不被误删。
5. 运行 active OpenSpec validate/status、task inventory、旧路径/旧 scheduler/删除文件引用扫描和
   `git diff --check`。
6. 本次无代码、Runtime、launchd、数据、数据库或通知变更。

## 8. 非目标

- 不因为文档收口就推送 release、合并 main、创建 tag 或新 Runtime worktree；
- 不改变 `operational_products.txt`、`auto_order=false` 或 Historical/Live 边界；
- 不删除 OpenSpec archive、active task contract 或未实施设计；
- 不把开发态运行证据写成稳定 Runtime、Ready 或项目闭环。
