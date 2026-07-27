# TASK-2026-07-12-018：macOS 长期运行方案选择

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-018-macos-long-running-plan |
| 日期 | 2026-07-12 |
| 分支 | `main` |
| Base | TASK-2026-07-12-015-supervisor-service-gate |
| 状态 | `DELIVERY_READY_PLAN_NO_WRITE` |
| 类型 | local workstation operations plan |

## 当前状态

当前主仓库：

```text
/Volumes/扩展盘/guiyi-quant-workstation
```

当前 launchd supervised runtime root：

```text
/Volumes/扩展盘/guiyi-parallel/jm-live-gate
```

基础服务状态：

- API loaded
- Web loaded
- backtests worker loaded
- signals worker loaded
- log rotate loaded
- healthcheck passed

已知限制：

- 主仓库位于外接卷。
- macOS LaunchAgent 后台访问外接卷和 `.env` 可能受系统权限影响。
- 不能宣称主仓库开机自启通过。
- 不能把 launchd 绑定的 parallel runtime root 与主仓库开发状态混写。

## 方案 A：授权外接卷后台访问

做法：

- 保持运行副本在外接卷。
- 人工授权 LaunchAgent / Terminal / shell 访问外接卷。
- 继续使用当前数据和源码路径。

优点：

- 不需要复制仓库。
- 数据路径最短。
- 与当前开发目录一致。

风险：

- macOS 权限提示和后台访问不稳定。
- 重启后权限可能仍需人工确认。
- 外接卷未挂载时 launchd 会失败。
- 更容易把开发工作区和长期运行状态混在一起。

适用：

- 短期人工值守 smoke。
- 不要求无人值守开机自愈。

## 方案 B：本机磁盘运行副本 + 数据资产受控挂载

做法：

- 将长期运行副本放到本机磁盘，例如 `~/GuiyiRuntime/guiyi-quant-workstation-runtime`。
- 外接卷只作为数据资产目录，通过明确环境变量或只读挂载路径引用。
- launchd 只绑定本机磁盘运行副本。

优点：

- launchd 读取脚本、`.env`、日志路径更稳定。
- 开发主仓库和长期运行副本边界清楚。
- 更适合 5 个交易日长稳和重启恢复。

风险：

- 需要定义运行副本同步流程。
- 需要避免两个副本同时写同一数据资产。
- 需要明确 `.env` 和数据路径权限。

适用：

- 长期运行。
- 重启恢复。
- 后续真实服务器安全 smoke 前的本机基线。

## 推荐方案

推荐默认采用 **方案 B**。

理由：

- 当前目标是长期运行和 Gate 化验收，不只是一次人工 smoke。
- 本机磁盘运行副本更容易让 launchd 稳定管理。
- 外接卷可以继续承载大体量数据资产，但不应作为 launchd 脚本和环境文件的唯一依赖。

## 实施前 Gate

实施前必须确认：

1. 长期运行副本路径。
2. 数据资产路径只读/写入边界。
3. `.env` 迁移或同步方式，只记录路径，不提交内容。
4. 是否允许停止当前 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` launchd 绑定。
5. 是否允许在本机磁盘创建 runtime worktree。
6. 如何避免两个 runtime 同时写 live / archive。

## 后续实施 Prompt

BEGIN CODEX PROMPT

你现在在 `/Volumes/扩展盘/guiyi-quant-workstation` 仓库中工作。

任务：为 macOS 长期运行副本迁移生成实施 Plan。只做 Plan，不创建副本、不写 LaunchAgents、不读取或打印 `.env`。

先阅读：

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/tasks/TASK-2026-07-12-018-macos-long-running-plan.md`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
- `scripts/install-local-services.sh`
- `scripts/local-services-status.sh`
- `scripts/post-reboot-verify.sh`

目标：

1. 设计本机磁盘 runtime 副本方案；
2. 定义源码同步、环境文件、日志、PID、数据资产路径；
3. 定义单 runtime 写入锁和停旧启新流程；
4. 定义 launchd 加载和回滚步骤；
5. 定义重启 smoke 和 5 交易日长稳验收。

禁止：

- 不创建 runtime 副本；
- 不写 LaunchAgents；
- 不启动 live；
- 不打印 `.env`、password、token、webhook、license；
- 不改 FRP / Nginx；
- 不改 DB；
- 不自动 push / merge / deploy。

输出：

1. 当前状态；
2. 拟创建路径；
3. 拟修改文件；
4. 不修改范围；
5. 实施步骤；
6. 回滚方案；
7. 测试命令；
8. 需要人工确认的问题。

END CODEX PROMPT

## Cursor 执行 Prompt

BEGIN CURSOR PROMPT

你现在在 `/Volumes/扩展盘/guiyi-quant-workstation` 仓库中工作。

任务：评估 macOS 长期运行方案。只做检查和方案，不直接改 launchd 真实配置。

先阅读：

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- `scripts/post-reboot-verify.sh`
- `scripts/local-services-status.sh`

背景：

当前仓库位于外接卷，macOS launchd 后台读取 `.env` / 外接卷可能受权限影响。需要在两个方案中选择：

- 方案 A：给 LaunchAgent 授权外接卷后台访问；
- 方案 B：迁移长期运行副本到本机磁盘，数据资产通过受控路径挂载。

任务要求：

1. 检查当前仓库路径、分支、服务脚本、launchd 相关文档；
2. 总结当前 blocked 原因；
3. 比较方案 A 和方案 B 的风险；
4. 推荐一个默认方案；
5. 给出后续实施 Prompt。

禁止：

- 不读取或打印 `.env` 内容；
- 不写入 LaunchAgents；
- 不启动真实 live；
- 不改 FRP/Nginx；
- 不改数据库；
- 不提交凭据。

输出：

1. 当前状态；
2. 方案对比；
3. 推荐方案；
4. 实施前 Gate；
5. 建议同步给 GPT 的文件。

END CURSOR PROMPT

## 建议同步给 GPT

- `docs/tasks/TASK-2026-07-12-018-macos-long-running-plan.md`
- `docs/tasks/TASK-2026-07-12-015-supervisor-service-gate.md`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
- `docs/gpt/NEXT_STEPS.md`

