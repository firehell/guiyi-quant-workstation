# 牛哇六品种 60m 依赖恢复设计

日期：2026-09-15。基线：`develop@336d14146a4702f43793b5bbe4c2db9c26fd1bbc`。

本设计只处理 A/AG/AL/AO/AP/PT 的牛哇三策略 completed `60m` 依赖。正式链保持
`RQData 1m -> staging/硬校验 -> Canonical 1m -> 同物理合约 Session 聚合 60m`。
不直接下载 RQData 60m，不改策略公式、产品开放开关、日周下载范围或 Runtime。

## 方案

在现有 recovery/campaign 中增加封闭 60m profile：

- prepare：`newow_hourly_recovery_prepare_v1`
- campaign：`newow_hourly_recovery_campaign_v1`
- 单元 apply：原生 `contract_warmup(frequency=60m)`，只规划/执行 `1m + 60m`
- 60m 不使用 `exchange_daily` journal，也不继承 W1/D1 来源隔离或 partial-exception 白名单

CLI 无六品种 universe：一次 prepare 可消费六份同 `as_of`、`frequency_scope=[60m]` 的原生
`newow-readiness` JSON，校验后并集 `repair_targets`。派生优先，下载批最多 5 个合约，
不截断 consumer 窗口。

证据根：`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-hourly-recovery/`。

## 验收

分别报告 `inventory_complete`、`recovery_complete`、`input_availability`。
60m 产品面与 explanation 保持 UNOPENED。真实 RQData/Canonical 写入需要冻结执行包的
精确单次批准。
