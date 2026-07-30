# 归一量化 V1 最终验收（S6-11）

更新时间：2026-07-30

## 状态

```text
CONTRACT_SKELETON_FROZEN
FINAL_ACCEPTANCE_NOT_RUN
V1_READY=false
RELEASE_NOT_AUTHORIZED
```

## 目标

在所有独立 receipt、新版 S6-10 单日 Ledger 与同一 exact release 的独立恢复证据完成后
执行只读总审查，同步 canonical 状态，并准备 PR/tag 建议。发现硬失败必须输出 BLOCKED，
不修饰结果。

## 必须绑定

- 当前 main commit；
- V1 data/consumer、Stage 4/5、S6-03～S6-07 receipts；
- HTDY S6-08 schema-v3 receipt；
- S6-09 single-send receipt；
- full backup 与 isolated restore receipts；
- GY-S6-10-R2-RUN 单交易日 Ledger（夜盘、三段日盘、23 个 confirmed 15m 桶、EOD、
  幂等、零非法写入）；
- 同一 exact release 的 Runtime、RQData/网络与 Mac 独立恢复 evidence；
- Web V1 receipts。

旧 S6-10 schema-v4～v7 合同、receipt 和 evidence 仅作为 frozen historical 绑定，不得作为
新版通过条件，也不得改写。`LONG_RUNNING_READY=false` 以
`deprecated / not_applicable` 保留；本验收只能在用户最终批准后发布
`JM_RUNTIME_READY`，不得把单日 Gate 写成长期稳定、盈利、通知或交易 Ready。

## 永久边界

```text
HTDY_STAGE5_OUTCOME=REJECTED_RESEARCH_CANDIDATE
HTDY_ORIGINAL_HISTORICAL_VALIDATION=false
HTDY_ORIGINAL_FUTURE_LOOKING=true
HTDY_ORIGINAL_REPAINTING_ACCEPTED_FOR_EXACT_REALTIME_OBSERVATION=true
AUTO_TRADING_READY=false
GUIYI_WECHAT_AUTOSEND_ENABLED=false
```

验收必须确认 DB revision 仍为 `20260721_0025`，不存在
`htdy_observation_alerts` 表或 `20260725_0026` migration，且没有订单/交易路径、secret
或物理路径泄漏。真实 ReviewNote 缺失只保留 `WEB_V1_13_PARTIAL`，不得造数据冒充。

## Final release 与 Runtime 批准

旧 S6-10 schema-v4～v7 的 Approval D 已冻结为历史，不再是 S6-11 或新版
`GY-S6-10-R2-RUN` 的前置条件，也不得生成、复用或补签。

S6-11 只生成最终矩阵、canonical diff、final acceptance receipt 与 PR/tag/Runtime 建议。
进入批准流程前，必须绑定并独立复核：

1. `GY-S6-10-R2-RUN` final receipt；
2. 同一 exact release 的 Runtime、RQData/网络与 Mac 独立恢复 Review。

上述证据通过后，用户仍须分别批准：

```text
允许发布 main/tag
允许 Runtime promotion
```

release 批准不得自动继承为 Runtime promotion。缺少任一独立批准时，不得 merge release、
创建 tag、同步或切换 Runtime，也不得进入 maintenance mode。
