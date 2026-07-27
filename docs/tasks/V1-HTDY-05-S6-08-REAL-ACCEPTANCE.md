# V1-HTDY-05 S6-08 真实自然事件验收

更新时间：2026-07-27

## 状态

```text
JM_LIVE_SIGNAL_EVENT_PASSED
LIVE_SIGNAL_EVENT_GATE_PASSED
HTDY_FIRST_SEEN_EVENT_OBSERVED
```

这不是 HTDY 历史验证、收益证明、通知 Ready、交易 Ready 或长稳 Ready。

## 真实验收结果

用户精确批准：

```text
deployment=af0f8f415e12f94c734c2cb4e971cb5117ca18dd5ae01cc2bbba0595310f8e3a
rebind=947830220377c9bf440e1ae98c411ea8ba33f7ba5c44a129c37584e24380e1c1
service_parent=c035ecb669c2d1e53c4d75012d8da1d1cc6e5bd1692d74e1aa83984c94ba6c53
```

三包在执行前按当前 Runtime、DB、Profile、source、policy、Web bundle、launchd 与
feature flags 重新验证通过。code-only deployment 将 Runtime 切换至
`844b3f9beded6aae3375e25e34a7e5250f0a1ae2`，S6-07 rebind 未重跑归档且没有修改
watermark、Profile 或 canonical asset。

`2026-07-27` 夜盘自然行情进入 `2026-07-28` DCE trading day 后，schema-v3 Gate
自动创建当日 child 与 mapping receipt。首轮产生唯一真实事件：

```text
event_id=4
product=jm
actual_contract=JM2609
period=15m
direction=long
event_type=signal_created
source_mode=live_realtime_repainting
strategy=htdy_original_realtime_first_seen/v1.0
indicator=huotian_dayou_original_v0/original-v0
policy=htdy_original_xma_15m_first_seen_v1
```

未构造行情、未注入测试 bar、未手工写 event。下一 scheduler cycle 对同一 observation
完成唯一一次幂等探测：

```text
created=0
unchanged=1
changed=0
blocked=0
```

随后立即关闭 `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED`，清空 approval packet/hash 并重启
scheduler；`GUIYI_WECHAT_AUTOSEND_ENABLED=false` 始终未改变。最终 verifier 确认
Signal/SignalEvent 各只增加 1，notification、scan task、ReviewNote、canonical asset、
Profile binding、backtest、order、trade 及相关 hash 全部零漂移；事件详情与冻结
Review lineage deep-link 均可读，未自动创建 ReviewNote。

create-only 证据目录：

```text
data/reports/jm_live_signal_event_s6_08/htdy_schema_v3/20260727-844b3f9b647f/
```

final receipt：

```text
file_sha256=e1a34399310c8a585127bea65851f6f49d78c73d428e285cb29e855db74f2d98
receipt_hash=9aee80f1be1b6041910b55ccfed3fdfbce3929c192aff7ec5b34ab71cb4001ea
canonical_hash_matches=true
```

关闭后的 Runtime 为 `844b3f9b…` tracked clean，PostgreSQL revision 仍为
`20260721_0025`，API/runtime/after-market health 检查通过。此结果只证明精确
HTDY observation-only 自然事件与幂等 Gate 通过；`notification_ready=false`、
`trading_ready=false`、`long_running_ready=false`，Stage 5
`REJECTED_RESEARCH_CANDIDATE` 与历史回测拒绝不变。

`20260727-6d0038d6d92d` 已按精确 Approval A 完成 code-only deployment 与
S6-07 rebind，但首次启用时 Runtime 预检以 `S607DatabaseRecoveryError` fail-closed。
根因是 deployment、rebind、parent 三个 CLI 已支持
`tracked_read_only_lineage_rebind_v1`，而 Runtime
`collect_current_bindings()` 仍只调用旧 recovery receipt verifier。授权随即关闭并清空，
live scheduler 恢复 running，autosend 保持 false；只读数据库审计确认 revision 仍为
`20260721_0025`、parent baseline counts/hashes 完全未变，且没有 daily child 或
SignalEvent。该 Approval A 已消费且不得复用。

`20260727-18cb6fb48208` 随后验证 Runtime lineage adapter 已生效，但第二次
Runtime 预检只剩 `service_bundle_sha256` 不一致。逐文件核对确认 parent builder 的
源码清单漏掉 `htdy_s6_08_daily_mapping.py`，Runtime verifier 已正确包含它；其他
Runtime/DB/Profile/mapping/policy/Web/flags/baseline facts 全部一致。授权再次立即关闭并
清空，无 daily child/event。修复改为 builder 与 Runtime 共用一个
`SERVICE_BUNDLE_PATHS` 合同，防止两份清单再次漂移；第二轮 Approval A 同样已消费。

`20260727-745164b756cc` 完成第三次 code-only deployment、S6-07 rebind、parent
零漂移验证并进入真实交易时段。基础 JM ingest/aggregation 用同一时点可完整成功，
但 HTDY handler 在生产构造 `HtDyRealtimeSnapshotResolver` 时漏传必需的
`project_root`，因此在 evaluator 前抛出 `TypeError`。SignalEvent 随即关闭、packet/hash
清空并重启 scheduler，autosend 始终为 false；parent 全事实复验确认 DB counts/hashes
零漂移，未产生 StrategySignal、SignalEvent、notification、order 或 trade。

失败事务前已 create-only 写出 `daily/2026-07-28/child_packet.json`，但 mapping 数据库
事务已回滚且没有 mapping receipt、accepted event 或 authorization-consumed receipt。
该 child 原样保留为孤立 superseded 审计证据，永久禁止复用。修复为 production handler
显式注入 canonical `PROJECT_ROOT`，并新增真实构造合同回归测试；第三轮 Approval A 已
消费，修复 checkpoint 必须重新生成三包并取得 fresh Approval A。

修复 checkpoint 后的新 packet preflight 在 7/28 夜盘开始时正确拒绝 stale historical
facts：基础 Runtime 要求前一 DCE 交易日为 7/27，而 canonical mapping、参数及
1m/5m/15m 仍停在 7/24。用户随后精确批准独立 S6-07 enable packet
`91f46f95…`，其 dry-run 只包含唯一 eligible day 7/27。真实归档在写资产前以
`provider_final_minute_key_mismatch` fail-closed，watermark 保持 7/24，未创建
7/27 mapping、historical asset 或 Profile binding；after-market automation 已立即关闭。

只读对照确认 RQData 的 7/27 trading-day 查询实际返回完整 345 根，其中 120 根夜盘的
自然时间为 7/24 21:01–23:00。旧实现先用通用 natural-date normalizer 生成
`trading_day=7/25`，再按 7/27 过滤，错误丢弃全部夜盘。修复保持 exact session minute
keys 为权威边界：provider trading-day 查询返回的 frame 统一绑定请求日 7/27，再继续执行
duplicate/missing/extra 和双 hash 稳定性校验。真实只读 RQData 复验为 345/345、两次稳定、
无 missing/extra。blocked checkpoint 只能通过新 code-only deployment 和同日
`--retry-failed-day 2026-07-27 --confirm-retry` Gate 恢复，旧 enable hash 永久不可复用。

`661ba526` code-only deployment 与显式 retry-arm 随后均通过，但首次物化轮次在
S6-03 actual-contract 1m 层再次调用同一个通用 normalizer，仍把 120 根周五夜盘过滤掉，
以 `provider_actual_row_count_mismatch:JM2609:2026-07-27:225!=345` fail-closed。
该轮只留下 create-only execution packet 和失败任务证据；DB rollback 完成，
`active_binding_changed=false`，watermark、Profile 与正式历史资产均未推进。
最终修复把“单交易日 provider 查询绑定请求交易日”下沉到 actual materializer，
多日查询保持原语义；真实 RQData 只读复验为 345/345，且 stable hash 与 preflight
packet 完全一致。由于代码事实再次变化，`661ba526` 的 deployment/enable 批准均已消费且
永久不可复用，必须使用新的精确 hash 重新部署和 retry。

用户批准 `deployment=389acb…` 与 `enable=23c067…` 后，Runtime code-only
部署至 `4d05370f`，DB revision 保持 `20260721_0025` 且 migration=false。
显式 retry-arm 与单日 cycle 均通过，checkpoint 为 success、watermark 推进至
`2026-07-27`，receipt gate 为 `JM_EOD_ARCHIVE_DAY_PASSED`。JM2609 目标日
1m 为完整 345 根（7/24 21:01 至 7/27 15:00），六周期 canonical 资产均
primary/passed，`live_observation_v1` 的 1m/5m/15m 已切换至新版本。
live/provider reconciliation 记录 3 根 OHLCV difference 作为只读对照证据，
没有缺失、额外或重复分钟，不回写 canonical。归档后 after-market service
保持 unloaded/disabled，SignalEvent 与 autosend 均为 false，既有 signal、
notification、order、trade 计数不变。

旧 recovery-lineage receipt 冻结的是归档前 DB/Profile/checkpoint 状态，合法 S6-07
归档使其按设计失效。后续只读 lineage receipt 必须同时保留原始 recovery 与 Step 4
tracked evidence 的旧基线 hash，并另行冻结归档后的当前 DB 状态；不得用更新当前 hash
覆盖历史基线、不得 migration、不得 DB write、不得重跑 Approval R。

## 精确观察合同

本任务只允许：

```text
product=jm
contract=当日 RQData rank=1 实际主力
period=15m
strategy=htdy_original_realtime_first_seen/v1.0
indicator=huotian_dayou_original_v0/original-v0
source_mode=live_realtime_repainting
policy=htdy_original_xma_15m_first_seen_v1
repaint_scan_bars=27
partial_allowed=true
first_seen_no_retraction=true
historical_backtest_allowed=false
wechat_autosend=false
auto_order=false
```

原版 XMA 含未来依赖且会重绘。事件只冻结首次检测快照，后续信号消失、反向或源
revision 不撤回、不修改。

## Step 5 前置修复与四日窗口

旧 Step 5 parent 冻结 `2026-07-27` 至 `2026-07-31`，但在部署前已超过首日
上海时间 `08:30`。目录 `20260727-ecd9aee4b919` 只作为
`SUPERSEDED_WINDOW_EVIDENCE / NOT_AUTHORIZED / NOT_DEPLOYED` 保留，且没有
deployment/rebind receipt；其中任何 hash 永久不可复用。

PostgreSQL DCE calendar 当前只核实至 `2026-07-31`。本轮按用户明确选择不补生产日历，
将 bounded parent 固定为以下四个已核实交易日：

```text
2026-07-28
2026-07-29
2026-07-30
2026-07-31
```

这仍满足“最多五个明确 DCE 交易日”，但若四日内没有自然事件，只能关闭授权并发布
`PENDING_NATURAL_HTDY_EVENT`，不得宣称 S6-08 通过。

原 `GuiyiRecoverySafe` receipt 后续确认未进入 Git 且原文件不可用。用户于 2026-07-27
单独批准 `tracked_read_only_lineage_rebind_v1`，它不是恢复 receipt 的复制、重建或迁移：

- 固定绑定原 Approval R packet hash、receipt hash 与文件 SHA-256；
- 逐字节校验主干中已归档的 recovery 结论文档、最终 deployment packet/receipt、
  S6-07 rebind packet/receipt 和 service parent；
- 当前 PostgreSQL 必须在 `SET TRANSACTION READ ONLY` 下重新采集，完整 state 必须与最终
  rebind receipt 一致，并显式 rollback；
- 只允许 create-only 写
  `recovery_lineage_rebind_receipt.json`；
- `migration_performed=false`、`database_write_performed=false`、
  `approval_r_rerun=false`、`runtime_modified=false`；
- lineage receipt 的 source commit 必须与 fresh deployment packet 的 source commit 完全相同。

任何归档证据、DB state、source commit 或 lineage receipt hash 漂移立即拒绝；不得退化为只信
文档文字或手工提供哈希。

Step 5 保持以下 fail-closed 边界：

- 每个 child day 首轮从 RQData 精确查询 `jm + rank=1 + 当日`；
- 只在既有 `main_contract_map` 创建一条 exact mapping，不新增 migration；
- DB duplicate/conflict、RQData 非 actual contract、日期漂移或已冻结 mapping 漂移均拒绝；
- mapping 与 create-only receipt 在同一 Runtime 事务提交后落盘，后续轮次只校验 receipt 与
  当前 DB 行，不重复修改；
- scheduler 启动预检只验证 parent，不进入 daily write phase；
- 每轮仅输出脱敏 `htdy_observation_summary`，包含 day/contract/bucket、候选/阻断数量、
  created/unchanged/changed 和最新 event id；
- 新 parent 必须在首日上海时间 `08:30` 前生成和 fresh verify，且必须确认
  首日无 HTDY event、无 daily child；过时或状态不洁立即拒绝，不静默换窗口。

## 执行顺序

取得新代码 checkpoint 对应的三个 fresh hash，并由用户在一条消息中精确批准后，才允许：

1. verify/execute code-only deployment；
2. verify/execute S6-07 code-only rebind；
3. verify service parent；
4. 只开启 live Runtime 与 SignalEvent，autosend 保持 false；
5. 在 `2026-07-28` 至 `2026-07-31` 自然等待，不注入行情、不手工写事件；
6. 首个事件后要求一次同 key `unchanged>0 / created=0 / changed=0`；
7. 立即关闭 SignalEvent 并清空 packet/hash；
8. 验证 Runtime/live/after-market、Web/Review deep-link 与全部禁写计数；
9. create-only 发布 schema-v3 final receipt。

若四个交易日没有自然事件，关闭授权并仅发布：

```text
PENDING_NATURAL_HTDY_EVENT
```

任何后续窗口都需要新 parent 与新 Approval A。
