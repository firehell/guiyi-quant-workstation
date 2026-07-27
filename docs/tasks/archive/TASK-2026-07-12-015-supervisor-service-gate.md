# TASK-2026-07-12-015：基础监督服务 Gate

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-015-supervisor-service-gate |
| 日期 | 2026-07-12 |
| 分支 | `main` |
| Base | DATA-PART-TARGET-CLOSURE |
| 状态 | `DELIVERY_READY_READONLY_GATE` |
| 类型 | local workstation / runtime gate |

## 目标

确认基础本地监督服务是否可观察、可健康检查，并为后续 JM 单次真实 live Gate 提供前置判断。

本任务只覆盖基础服务：

- API
- Web
- backtests worker
- signals worker
- log rotate
- PostgreSQL / Redis 容器健康

## 不做事项

- 不启用 `GUIYI_LIVE_RUNTIME_ENABLED=true`。
- 不加载 runtime scheduler。
- 不加载 notification worker。
- 不发送企业微信。
- 不写 live 表。
- 不写 historical `market_data_files`。
- 不做自动交易、实盘账户或订单接口。
- 不打印 `.env`、DB URL、Redis password、webhook、license。

## 执行计划

1. 检查分支和当前任务状态。
2. 确认数据部分仍是 `DATA-PART-TARGET-CLOSURE DELIVERY_READY`。
3. 读取 `local-services-status.sh`、`dev-healthcheck.sh`、`post-reboot-verify.sh` 的边界。
4. 运行基础服务状态检查。
5. 记录 supervised runtime root 与当前 repo 是否一致。
6. 记录 healthcheck pass/block 状态。

## 已执行命令和结果

### `git status --short --branch`

结果：

```text
## main...origin/main
```

执行本任务前工作区无未提交输出。

### `sed -n '1,220p' tasks/current.md`

结果确认：

```text
状态：DELIVERY_READY_DATA_PART_TARGET_CLOSURE
covered_passed=17203
covered_warning=105
metadata_gap=0
issue_register_rows=105
quality_warning=105
```

### `./scripts/local-services-status.sh`

结果：

```text
inspector_repo=/Volumes/扩展盘/guiyi-quant-workstation
supervised_runtime_root=/Volumes/扩展盘/guiyi-parallel/jm-live-gate
note=launchd 当前未绑定本仓库
com.guiyi.quant-api loaded
com.guiyi.quant-worker-backtests loaded
com.guiyi.quant-worker-signals loaded
com.guiyi.quant-web loaded
com.guiyi.quant-log-rotate loaded
```

结论：

- 基础 5 个 LaunchAgent 均 loaded。
- 当前 launchd 长期运行副本绑定的是 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate`，不是主仓库 `/Volumes/扩展盘/guiyi-quant-workstation`。
- 本结论不能写成“主仓库已绑定 launchd”。

### `./scripts/dev-healthcheck.sh --json --no-start`

结果：

```text
status=passed
api_healthz=passed http_200
api_health=passed http_200
runtime_health=passed http_200_business_ok
web_home=passed http_200
postgres=passed ok
redis=passed ok
```

结论：本地 API/Web/runtime health/PG/Redis 健康检查通过。

### `./scripts/post-reboot-verify.sh`

结果摘要：

```text
Docker daemon: running
PostgreSQL / Redis 容器已在运行，跳过 docker compose up
local-services-status: 基础 5 个 LaunchAgent loaded
dev-status: 本仓库 .run/dev pid 文件为 stale，但 8000/5173 端口 listening
dev-healthcheck: status=passed
```

结论：

- 基础运行面可用。
- 本仓库 `.run/dev` pid stale 属于开发态 PID 文件与 launchd 运行副本不一致，不等同于服务不可用。
- 后续若要验收 kill/recovery，必须在当前 supervised runtime root 上执行，而不是只看主仓库 `.run/dev`。

## Gate 结论

当前可标记：

```text
SUPERVISOR_BASE_HEALTH_PASSED_WITH_RUNTIME_ROOT_NOTE
```

不能标记：

```text
JM_RUNTIME_READY
LONG_RUNNING_READY
T3_REAL_PASSED
```

## 是否可以进入 JM 单次真实 live Gate

可以进入 **JM 单次真实 live Gate Plan / readiness check**。

进入真实写入前仍需人工确认：

1. 运行地点是 supervised runtime root 还是主仓库。
2. 四个真实开关只有本 Gate 需要的一个为 true。
3. 当前时间处于 JM 可交易窗口，否则可能只得到 `idle`。
4. RQData / DB / Redis 凭据只做 present/missing 检查，不打印值。

## Cursor 执行 Prompt

BEGIN CURSOR PROMPT

你现在在 `/Volumes/扩展盘/guiyi-quant-workstation` 仓库中工作。

任务：执行并整理“基础监督服务 Gate”的只读/最小验证方案。

先阅读：

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md`
- `scripts/dev-healthcheck.sh`
- `scripts/post-reboot-verify.sh`
- `scripts/local-services-status.sh`

目标：

1. 确认当前数据部分已是 `DATA-PART-TARGET-CLOSURE DELIVERY_READY`。
2. 设计并执行基础监督服务 Gate 的最小检查。
3. 只验证 API/Web/backtest worker/signal worker 的本地健康状态。
4. 不启用 live runtime。
5. 不开启企业微信。
6. 不做真实数据写入。
7. 不改数据库 schema。
8. 不提交任何凭据或环境变量值。

必须先输出 Plan，说明：

1. 当前仓库状态和分支；
2. 拟检查的脚本和服务；
3. 不修改范围；
4. 计划运行的命令；
5. 可能触发的 Gate；
6. 预期验收标准。

允许运行的命令优先包括：

- `git status --short --branch`
- `sed -n '1,220p' tasks/current.md`
- `./scripts/local-services-status.sh`
- `./scripts/dev-healthcheck.sh --json --no-start`
- `./scripts/post-reboot-verify.sh`

禁止：

- 不设置 `GUIYI_LIVE_RUNTIME_ENABLED=true`
- 不运行真实 live ingest / archive / notification
- 不打印 `.env`、DB URL、Redis password、webhook、license
- 不 push、不 merge、不部署

完成后输出：

1. 本次检查了什么；
2. 运行了哪些命令；
3. 每个命令结果；
4. 哪些服务通过；
5. 哪些服务 blocked；
6. 是否可以进入 JM 单次真实 live Gate；
7. 需要同步给 GPT 的文件。

END CURSOR PROMPT

## 建议同步给 GPT

- `docs/tasks/TASK-2026-07-12-015-supervisor-service-gate.md`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

