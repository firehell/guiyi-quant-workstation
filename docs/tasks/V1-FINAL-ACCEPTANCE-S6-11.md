# 归一量化 V1 最终验收（S6-11）

更新时间：2026-08-05

## 状态

```text
CONTRACT_SKELETON_FROZEN
FINAL_ACCEPTANCE_NOT_RUN
V1_READY=false
RELEASE_NOT_AUTHORIZED
```

## 目标

在可复现输入事实齐备后执行只读总审查，同步 canonical 状态，并准备 release/tag/Runtime
建议。发现硬失败必须输出 BLOCKED，不修饰结果。

普通开发与本地验证不要求 Issue、worktree、PR、独立 Review、required CI、exact-head、
packet、hash 或 receipt 作为授权。已记录的 receipt/SHA 只作为 Historical_Fact 或复现输入。

## 必须绑定的复现输入（Historical_Fact / 证据，非授权）

- 当前 main commit（若已有）；
- V1 data/consumer、Stage 4/5、S6-03～S6-07 已发生的验收事实；
- HTDY S6-08 schema-v3 观察事实；
- S6-09 single-send 观察事实；
- full backup 与 isolated restore 观察事实（若曾执行）；
- GY-S6-10-R2-RUN 单交易日 Ledger 事实（夜盘、三段日盘、23 个 confirmed 15m 桶、EOD、
  幂等、零非法写入）；
- Runtime、RQData/网络与主机恢复相关观察事实；
- Web V1 观察事实。

旧 S6-10 schema-v4～v7 合同与证据仅作为 frozen historical 绑定，不得作为新版通过条件，
也不得改写。`LONG_RUNNING_READY=false` 以 `deprecated / not_applicable` 保留；本验收只能在
用户分别给出 scoped intent 后建议 `JM_RUNTIME_READY`，不得把单日结果写成长期稳定、盈利、
通知或交易 Ready。

## 永久边界

```text
HTDY_STAGE5_OUTCOME=REJECTED_RESEARCH_CANDIDATE
HTDY_ORIGINAL_HISTORICAL_VALIDATION=false
HTDY_ORIGINAL_FUTURE_LOOKING=true
HTDY_ORIGINAL_REPAINTING_ACCEPTED_FOR_EXACT_REALTIME_OBSERVATION=true
AUTO_TRADING_READY=false
GUIYI_WECHAT_AUTOSEND_ENABLED=false
```

验收必须确认不存在订单/交易路径、secret 或物理路径泄漏；真实 ReviewNote 缺失只保留
`WEB_V1_13_PARTIAL`，不得造数据冒充。live、Runtime switching、真实通知/autosend 与订单
默认关闭；配置缺失、异常、过期或不一致时保持关闭。

## Final release 与 Runtime（分属不同 scoped intent）

旧 S6-10 schema-v4～v7 的 Approval D 已冻结为历史，不再是 S6-11 前置条件，也不得生成、
复用或补签。

S6-11 只生成最终矩阵、canonical diff 与建议。真正执行时：

1. `PublishBranch` / `PublishTag` 需要一次命名 remote/ref/tag 的 release 意图；
2. Runtime/live/notification 启用或切换需要另一次匹配的 scoped intent；
3. release 意图不授权 Runtime；Runtime 意图不授权 release；
4. dry-run/`-WhatIf` 不授权真实 mutation。

缺少匹配意图时，不得 merge release、创建 tag、同步或切换 Runtime，也不得进入 maintenance mode。
