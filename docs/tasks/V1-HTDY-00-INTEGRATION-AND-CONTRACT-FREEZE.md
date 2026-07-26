# V1-HTDY-00 集成盘点、旧授权撤销与新契约冻结

更新时间：2026-07-26

## 结论

```text
HTDY_REALTIME_EXCEPTION_CONTRACT_FROZEN
OLD_S6_08_AUTHORIZATION_REVOKED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
```

旧 JM V1-B schema-v2 packet 在本步骤开始时已不被 Runtime 引用；本步骤仍执行既有
`--disable` 幂等收口，并且只重启 live scheduler。旧 packet 文件和两个来源 worktree 均保留。

## Worktree 盘点

| 角色 | branch / state | commit | 结论 |
|---|---|---|---|
| main 基线 | `main` | `1805af2e` | clean，手册指定基线 |
| HTDY 来源 | `codex/htdy-original-realtime-alert` | `ebf172cc` | clean，1 commit，52 files，4561 insertions/53 deletions |
| S6-08 来源 | `codex/s6-08-live-signal-event-acceptance` | `c864a5a2` | clean，相对 main 无未合并 diff |
| Runtime | detached | `1805af2e` | clean，未修改代码 |
| 唯一集成 | `codex/v1-htdy-realtime-closure` | `1805af2e` 起点 | 本任务唯一写入 worktree |

## 保留矩阵

| 分类 | 内容 | 处理 |
|---|---|---|
| KEEP | HTDY original production kernel 思路、XMA/golden/repaint tests、Web 风险标签与 marker 思路 | 后续按文件选择性迁入并重新测试 |
| KEEP | S6-08 code-only deploy、service packet、final verifier、Runtime identity/lock、S6-07 receipt lineage 思路 | 在 schema-v3 中复用安全结构 |
| REWORK | HTDY scheduler/evaluator/writer、partial 15m、first-seen dedupe、Stage 9、Review/Web | 重写为既有表 + lineage v2 + exact policy |
| REWORK | S6-08 schema-v2 JM V1-B 单日 packet | 改为 HTDY schema-v3 bounded parent + exact child |
| DROP | `htdy_observation_alerts` 独立表与 `20260725_0026` migration | 不进入集成分支 |
| DROP | 平行 HTDY notification/delivery/worker 链 | 复用既有 Stage 9/SignalNotification |
| DROP | 自动撤回、修改首次事件或 HTDY `signal_changed` | first-seen snapshot 永久冻结 |
| DROP | 把 HTDY original 写成历史可信、OOS 有效或 validated | Stage 5 rejection 永久保留 |
| HISTORICAL | 旧 JM V1-B S6-08 packet、health、schema-v2 实现与 receipt 语义 | create-only 保留，不得重新作为 active 授权 |
| HISTORICAL | S6-03～S6-07 receipts、report 14/15、task 23 | 不修改 |

来源文件族的具体处理：

- KEEP（选择性迁入）：`packages/quant-core/guiyi_quant/indicators/htdy_original.py`、
  `services/quant-api/tests/test_htdy_indicator_risk.py`、HTDY Python/Web golden 与 repaint
  测试思想、Web 风险文案和 marker 交互。
- REWORK：`services/quant-api/app/services/htdy_realtime_signal.py`、
  `htdy_realtime_alert.py`、`htdy_realtime_alert_gate.py`、`runtime_scheduler.py`、
  observation API/Web panel；必须按 actual-contract partial snapshot、既有表、first-seen
  no-retraction 和 lineage v2 重写，不能整体 cherry-pick。
- DROP：`services/quant-api/alembic/versions/20260725_0026_htdy_observation_alerts.py`、
  `htdy_notification_dispatch.py`、`signal/htdy_wechat.py`、
  `signal/htdy_wechat_delivery.py`、独立 observation ORM/API/table。
- HISTORICAL：HTDY 来源分支自己的 plan/task/status 文档和旧 S6-08 schema-v2 packet/health；
  它们可用于审查 lineage，不直接合入 active canonical 状态。

## 旧授权身份与撤销

旧 packet：

```text
schema_version=2
strategy=jm_v1b_daily_direction_fast_entry/v1b.0
target_trading_day=2026-07-27
packet_hash=cdebf46cd28b7408201f94fc479aa2a16dd0ab0e6a430dc5bb083f92a9f2b432
packet_file_sha256=acb3741b37e99c9d71cf5a1ecac426fa6b749334158c7df7e88e76c2b092e570
```

步骤开始时 Runtime 已是 `flag=false / packet空 / hash空 / autosend=false`，因此不存在
“仍在 active 的旧授权”。幂等 disable 后只重启 `com.guiyi.quant-runtime-scheduler`：

```text
pid 37762 -> 48831
runs 33 -> 34
heartbeat_age_seconds=1
signal_event_gate_status=disabled
authorization_hash=null
```

Runtime、DB、Redis、live checkpoints 与 after-market scheduler 均为 `ok`。只读 PostgreSQL
前后验证确认 revision=`20260721_0025`、Profile hash、EOD watermark、SignalEvent=3、
Notification=1、StrategySignal=5 及回测/数据/Profile 表计数全部不变；
`htdy_observation_alerts` 表不存在。完整脱敏证据：

```text
data/reports/v1_htdy_integration_contract_freeze_20260726/revocation_evidence.json
```

## 冻结合同

```text
strategy_code=htdy_original_realtime_first_seen
strategy_version=v1.0
indicator_code=huotian_dayou_original_v0
indicator_version=original-v0
source_mode=live_realtime_repainting
signal_policy=htdy_original_xma_15m_first_seen_v1
product=jm
contract=当日 MainContractMap.rank=1 实际主力
period=15m
partial_allowed=true
future_looking=true
repainting_accepted=true
first_seen_no_retraction=true
historical_backtest_allowed=false
auto_order=false
```

该合同是精确实时观察例外，不是 Registry 全局放宽。事件只允许 `signal_created`；同桶后续
消失、反向、重绘或 revision 不更新、不撤回、不新增。它不翻转 Stage 5 rejection，不授权
历史回测、OOS、收益声明、真实企业微信发送、长稳、订单或自动交易。

## 下一步范围

Step 1 只允许修改 production indicator kernel、exact policy validator、Python/Web golden
和 repaint/future-tail tests；禁止 Runtime、DB、migration、SignalEvent、Notification、
Stage 5/report 14/15 变更。
