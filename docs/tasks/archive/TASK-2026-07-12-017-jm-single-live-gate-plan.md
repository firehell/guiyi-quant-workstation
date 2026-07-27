# TASK-2026-07-12-017：JM 单次真实 live Gate Plan

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-017-jm-single-live-gate-plan |
| 日期 | 2026-07-12 |
| 分支 | `main` |
| Base | TASK-2026-07-12-015-supervisor-service-gate |
| 状态 | `DELIVERY_READY_PLAN_NO_WRITE` |
| 类型 | live runtime plan |

## 当前状态

基础监督服务 Gate 当前结果：

```text
SUPERVISOR_BASE_HEALTH_PASSED_WITH_RUNTIME_ROOT_NOTE
```

已知边界：

- 当前 launchd supervised runtime root 是 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate`。
- 当前主仓库 `/Volumes/扩展盘/guiyi-quant-workstation` 可做文档、只读检查和开发态 healthcheck。
- T3-real 尚未通过。
- Stage 9、企业微信、formal event、自动交易全部后置。

## 目标

规划一次 JM 单次真实 live Gate：

1. 动态解析 actual contract，不硬编码 `JM2609`。
2. 只执行一次 1m live 写入。
3. 验证 5m/15m/30m/60m/1d/1w 聚合。
4. 验证 checkpoint 和重复运行幂等。
5. 保持 live observation 与 historical active data 分离。

## 前置条件

- T1 基础服务健康。
- 人工确认运行目录：主仓库或 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate`。
- 人工确认当前处于 JM 可交易时间；否则只可能得到 `idle`。
- RQData、DB、Redis 环境变量 present，但不得打印值。
- `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false`。
- `GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false`。
- `GUIYI_WECHAT_AUTOSEND_ENABLED=false`。

## 环境变量要求

只记录 present/missing，不记录值：

- RQData 凭据 / license
- DB 连接配置
- Redis 连接配置
- `GUIYI_LIVE_RUNTIME_ENABLED`
- `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED`
- `GUIYI_AFTER_MARKET_ARCHIVE_ENABLED`
- `GUIYI_WECHAT_AUTOSEND_ENABLED`

## Phase 1：dry-run / readiness check

执行前：

```bash
git status --short --branch
./scripts/local-services-status.sh
./scripts/dev-healthcheck.sh --json --no-start
```

dry-run：

```bash
uv run --project services/quant-api python -m app.runtime_scheduler \
  --dry-run --product jm
```

预期：

- `writes_signal_event=false`
- `sends_notification=false`
- 不写 historical active
- 能显示 trading clock / actual contract 解析状态
- 如果返回 `idle`，记录为 `BLOCKED_BY_NON_TRADING_TIME`，不是 T3 passed

## Phase 2：人工确认后单次真实 live

必须收到人工确认后才允许执行：

```bash
GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run --project services/quant-api python -m app.runtime_scheduler \
  --once --confirm-live-write --product jm
```

写入范围仅限：

- `live_minute_bars`
- `live_ingest_checkpoints`
- `live_aggregated_bars`
- `live_aggregation_checkpoints`

禁止写入：

- `market_data_files`
- `data_quality_reports`
- `StrategySignal`
- `SignalEvent` formal event
- notification records
- 企业微信
- 任何订单或交易账户

## Phase 3：结果审计与回滚确认

检查：

- 新增 live 1m 行数。
- 聚合周期状态。
- checkpoint 是否前进。
- 重复运行是否幂等。
- `writes_historical_active=false`。
- `writes_signal_event=false`。
- `sends_notification=false`。
- runtime health 是否仍为 `ok`。

回滚 / 关闭：

- 确认单次命令退出。
- 确认没有长期加载 runtime scheduler。
- 确认四个真实开关恢复默认 false，或仅在当前命令进程内临时生效。
- 如需清理 live smoke 行，必须另开人工确认任务，不在本 Plan 内自动删除。

## 验收标准

T3-real 通过至少需要：

- 动态 actual contract 解析成功。
- 至少 1 根真实 confirmed 1m live bar 写入。
- 多周期聚合产生可解释状态。
- checkpoint / 幂等通过。
- 未进入 historical active。
- 未生成 formal signal event。
- 未发送企业微信。

## 必须暂停的 Gate

- 当前非交易时段。
- actual contract 无法动态解析。
- runtime health 非 `ok`。
- 任一非本 Gate 授权开关为 true。
- 日志或输出可能泄露凭据。
- live 写入路径试图触碰 historical active。

## Cursor 执行 Prompt

BEGIN CURSOR PROMPT

你现在在 `/Volumes/扩展盘/guiyi-quant-workstation` 仓库中工作。

任务：为 “JM 单次真实 live Gate” 生成 Plan。只做 Plan，不执行真实 live 写入。

先阅读：

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/LIVE_1M_INGEST_DESIGN.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`

目标：

1. 设计一次 JM 真实 live Gate 的最小执行路径。
2. 验证动态 actual contract，不允许硬编码 `JM2609` 为长期主力。
3. 只规划一次 1m 写入、5m/15m/30m/60m/1d/1w 聚合、进程重启续跑的验证。
4. 把 live observation 和 historical active data 分开。
5. 明确 Stage 9、企业微信、formal event、自动交易全部后置。

Plan 必须包含：

1. 当前状态；
2. 前置条件；
3. 环境变量要求，但不得打印具体值；
4. 拟运行命令；
5. 每一步 expected output；
6. 写入范围；
7. 回滚方式；
8. 验收标准；
9. 必须暂停等待人工确认的 Gate。

硬边界：

- 本轮不执行真实 live；
- 不写企业微信；
- 不生成正式 `StrategySignal`；
- 不发送 notification；
- 不自动交易；
- 不把 live 表写入 historical `market_data_files`；
- 不把 live warning 伪装成 passed；
- 不修改数据资产质量状态。

完成后输出一个可交给 Codex 执行的二阶段 Prompt：

1. Phase 1：dry-run / readiness check；
2. Phase 2：人工确认后单次真实 live；
3. Phase 3：结果审计与回滚确认。

END CURSOR PROMPT

