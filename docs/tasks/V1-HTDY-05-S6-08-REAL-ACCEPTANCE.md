# V1-HTDY-05 S6-08 真实自然事件验收

更新时间：2026-07-27

## 状态

```text
RUNTIME_LINEAGE_ADAPTER_FIX_READY
FRESH_APPROVAL_A_REISSUE_PENDING
S6_08_NATURAL_EVENT_GATE_PENDING
```

这不是 HTDY 历史验证、收益证明、通知 Ready、交易 Ready 或长稳 Ready。

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
