# TASK-2026-07-12-019：macOS 方案 B 本机磁盘 runtime 副本迁移实施

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-019-macos-scheme-b-migration-impl |
| 日期 | 2026-07-12 |
| 分支 | `main` |
| Base | TASK-2026-07-12-018-macos-long-running-plan |
| 状态 | `DELIVERY_READY_SCHEME_B_MIGRATION` |
| 类型 | local workstation operations |

## 用户决策

已确认 **方案 B 优先**：长期运行副本放到本机磁盘，外接卷继续承载数据资产与开发主仓库。

## 当前状态（迁移前）

| 项 | 值 |
|---|---|
| 开发主仓库 | `/Volumes/扩展盘/guiyi-quant-workstation` |
| 旧 supervised runtime root | `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` |
| 监督服务 Gate | `SUPERVISOR_BASE_HEALTH_PASSED_WITH_RUNTIME_ROOT_NOTE` |

## 拟创建路径

```text
~/GuiyiRuntime/guiyi-quant-workstation-runtime   # launchd 绑定副本（本机磁盘）
~/Library/Application Support/GuiyiQuant/project.env   # launchd 运行时 env（不入库）
/Volumes/扩展盘/guiyi-quant-workstation          # 开发主仓库（不变）
```

## 数据资产边界

| 资产 | 路径策略 | 读写 |
|---|---|---|
| PostgreSQL / Redis | localhost，两副本共用 | live 表写 DB；T3 不写 historical |
| Parquet / data | 外接卷 `data/`（经 env 指向） | T3 禁止写 historical active |
| 源码 | 本机 runtime 副本 | 只读运行 + 小步同步 |
| `.env` | 用户本地复制到 runtime 副本 + `project.env` | 不入库、不打印 |

## 单 runtime 写入锁

- launchd 只允许一个 `GUIYI_PROJECT_ROOT` 绑定。
- 迁移时先 `bootout` 旧 parallel plist，再 `bootstrap` 本机副本 plist。
- `runtime_scheduler` 已有 Redis singleton lock（`guiyi:runtime:scheduler:singleton`）。
- T3-real 前确认 parallel 副本 scheduler 未 loaded。

## 实施步骤

1. `git worktree add ~/GuiyiRuntime/guiyi-quant-workstation-runtime main`
2. 复制 `.env` 到 runtime 副本（`cp`，不读取内容）
3. 同步 `project.env` 到 `~/Library/Application Support/GuiyiQuant/`（从 runtime 副本 `.env`，不打印）
4. `uv sync --project services/quant-api` 于 runtime 副本
5. 确认 `apps/quant-web/dist` 存在（必要时 `pnpm build`）
6. 于 runtime 副本执行 `./scripts/install-local-services.sh --confirm-load`
7. `./scripts/local-services-status.sh` 验证 `supervised_runtime_root` = 本机路径
8. `./scripts/post-reboot-verify.sh` + `./scripts/dev-healthcheck.sh --json --no-start`

## 回滚

1. 保留 parallel 副本目录不删除。
2. 于 parallel 路径重新执行 `install-local-services.sh --confirm-load`（需 `GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1`）。
3. 确认本机副本 launchd 已 bootout。

## 验收标准

- [x] 5 个基础 LaunchAgent loaded 且 `supervised_runtime_root` = `~/GuiyiRuntime/guiyi-quant-workstation-runtime`
- [x] `dev-healthcheck` passed（web 需同步 `node_modules` 后通过）
- [x] parallel 副本不再为 active supervised root
- [ ] 仍不声明 `LONG_RUNNING_READY`（5 交易日长稳后置）

## 迁移执行记录（2026-07-12 Cursor）

```text
runtime_path=~/GuiyiRuntime/guiyi-quant-workstation-runtime
branch=ops/local-runtime-disk
worktree=git worktree add -b ops/local-runtime-disk
env=cp .env + project.env（未打印内容）
launchd=install-local-services.sh --confirm-load（先 bootout 旧 5 服务）
supervised_runtime_root=~/GuiyiRuntime/guiyi-quant-workstation-runtime（与 inspector_repo 一致）
dev-healthcheck=passed
post-reboot-verify=passed（PG/Redis running）
note=apps/quant-web/node_modules 从主仓库 rsync，dist 从主仓库 rsync
```

## 禁止

- 不打印 `.env` / token / webhook / license
- 不开启 `GUIYI_LIVE_RUNTIME_ENABLED` 长期 true
- 不加载 `com.guiyi.quant-runtime-scheduler`（T3 单独 `--once`）
- 不改 DB schema / Parquet / manifest

## Codex 执行 Prompt（T3-real，迁移完成后）

```text
前置：TASK-019 迁移完成 + JM 可交易时段 + 用户显式确认 Phase 2

于 ~/GuiyiRuntime/guiyi-quant-workstation-runtime 执行：

GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run --project services/quant-api python -m app.runtime_scheduler \
  --once --confirm-live-write --product jm

审计 live 四表 + checkpoint + 幂等；更新 JM-LIVE-GATE-EVIDENCE.md
```
