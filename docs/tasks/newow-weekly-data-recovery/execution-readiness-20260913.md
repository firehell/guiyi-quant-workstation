# Newow 周线恢复执行记录与后续 Gate（2026-09-13/14）

本记录固化 R1–R4 已完成事实、R5 候选与下一次受控操作边界。已消费的 metadata apply 意图不得重放；
本文件不授权任何后续 provider、PostgreSQL、Canonical、Runtime、通知、Scope、main、tag 或 release 写入。

## 固定身份与原始证据

- task branch：`codex/newow-weekly-data-recovery`
- task base：`74d7a71fcd061d25eb23d7d2142a075420125886`
- 固定只读源码：`5b31cf7c1ceb5350d4a5ea0a3d9328635d0ea62d`
- 固定源码清单摘要：`cb0eb0aacf38442a54c43496e251301586cd1c62daf65110201fd2461eb8e1fe`
- as-of：`2026-09-13T06:36:13+00:00`
- 原始完整报告 SHA-256：
  `787393d159b0bde955b7258e1251ad24730d45cd18b5a6dfc073db6f33879ff8`
- 原始报告大小：21,468,106 bytes
- 本轮完整只读调查 evidence：
  `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-data-recovery-20260913/readonly-investigation-dfac5b22/`
  - `current-catalog-investigation.json`：
    `dfac5b229c28e2322bc94dd771f7dd3b9d04a1052b2dd27838c05e78dd3fa4b8`
  - `current-special-plans.json`：
    `12d028df9dc30a0ee963ca59b152b46d5e2ac5bfb2602c3e78b1497f902dd837`

当前 develop 中有界 metadata、HistoricalDataManager、Newow readiness/product reader 与固定源码逐文件
比较无差异。原报告中的 896 普通候选、494 proposals 和联合 READY 6 只作为写入前基线，不是当前计数。

## Metadata 终态与一次性写入清单

batch-03 已完成且不得重做：6,065 个 Session 行、1,696 个日期、63 个目标；独立读回和共享
`SessionWindowBatch` 解析通过，原 targets 重规划缺键/请求为 0。PT2608/PT2610 也不得重做。

04、02、01 的 23,537 个 adapter 规范化响应已全部下载，三个 snapshot 均为 `prepared`、
`blockers=[]`、Calendar 0，离线 plan/snapshot 语义校验和 journal 一一对应通过。owner 于 2026-09-14
明确授权后，三批严格按 04 → 02 → 01 各执行一次 insert-only apply，全部返回 commit success。

| 顺序 | 批次 | plan SHA-256 | snapshot SHA-256 | targets | 日期 | Session 行 | 写后 plan SHA-256 |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | 04 | `a8178e215b376b054d1dafcbe8f5b60bd7706cb62dae8315b80017d5fb3459d1` | `a6fee971e5b3031166f8ef53f40068b56319afb7812edced62de2a45ff68e206` | 56 | 4,007 | 15,253 | `4e97bae0c1c6b7a98a740d6f7b3f3cb14a588ee9af25ea2a45a66f74c940ba25` |
| 2 | 02 | `1ebae39934ed0d096585efebdb8223c6a17099921a03383a8db49543bb0ca3d7` | `8975ad46347a36da40179d5792724d6c494f6880d56dda15cc513a32a2357464` | 64 | 1,458 | 5,798 | `84c7b064044ffed887d3b665d4935d9f12f50733ed3af6570d360635831df7fe` |
| 3 | 01 | `3a2b4df0a3cafc420bcc56b64d4a46394e499927e5404666ab6d68ac8862739f` | `178c4868a9c3a6faac7d4646a907134ab22fad6953162db9d1cc3c66f50a6b67` | 64 | 1,547 | 6,108 | `9583a1668fd06cbfe5649538658724f92b7cad79f4fb633449360c7a816c982d` |

合计 184 targets、7,012 个日期、27,159 个 Session 行。输入均位于持久 evidence 根的
`metadata-plans-247/`，以对应 `batch-NN-plan.json` 与 `batch-NN-snapshot.json` 为权威。
每批已新建且未覆盖以下六个同目录 evidence 文件：`batch-NN-apply-invocation.json`、
`batch-NN-apply.json`、`batch-NN-apply-result.json`、`batch-NN-apply-execution.json`、
`batch-NN-apply-readback.json`、`batch-NN-post-apply-plan.json`。

三批均为 apply_calls=1、retries=0、provider requests=0、Canonical writes=0、Calendar 0；新只读事务确认
27,159 行和 7,012 日期逐项匹配、共享 Session 解析通过、既有行保留，同 targets 写后缺键和请求均为 0。
本次 metadata apply 意图已经消费完毕，不授权重放。

## MainContractMap 独立检查

按 operational 60 各产品 active history floor 至 `2026-09-11` 检查权威 Catalog 映射：60 个产品、
49,513 个预期交易日全部存在 rank=1/rule=2 映射；missing=0、extra=0、invalid rank/rule=0。
原报告中 45 个 `MAIN_CONTRACT_MAP_MISSING` 已在 batch-03 的 Session 补齐后消失，因此不设计或调用
MainContractMap writer。逐产品明细见上述 `current-catalog-investigation.json`。

## Metadata 后 W1 依赖重规划

固定源码和 as-of 下，使用外部 `project.env` 的正式 Canonical 身份完成一次 operational 60、W1、非 matrix
依赖审计。完整证据位于
`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-data-recovery-20260913/post-metadata-dependency-project-env-5b31cf7c-asof-20260913/`；
`full-dependency-audit.json` SHA-256 为
`4df491b7508887127488369f19427f379623e46341b75df5e1022d765356802e`。审计 exit 0、complete=true、
budget_exhausted=false、provider requests=0、writes=0，固定源码与配置元数据前后未变。

结果为 98 个 `DATA_READY`、2,320 个 `DATA_UNAVAILABLE`、20 个 `NOT_APPLICABLE`、2 个 PF2611
`SOURCE_EXCEPTION` 依赖；原生去重后有 1,139 个普通 `PROPOSED` contract plans、11 个 RS
`REVIEW_REQUIRED`、metadata proposals 0、UNKNOWN 0。11 个 RS 包含专项九个以及新显现的旧
RS2309/RS2311；后两者不得替代专项对象，也不自动扩大已冻结的 PF/九 RS provider 核验范围。

首次同范围审计误用了仓库 fallback `.env`，从错误 Canonical 身份得到 2,420 个统一
`DATA_INTEGRITY_INVALID`，证据目录 `post-metadata-dependency-5b31cf7c-asof-20260913/` 保留但已被正式报告
明确 supersede，不得用于候选或完成结论。单品种 a 在外部 `project.env` 下复现为 16 `DATA_READY`、
22 真缺口及 11 `PROPOSED`，证明问题属于执行配置身份，而非 readiness 生产代码缺陷。

R5 最小健康试点候选为 SI2308/W1，through `2023-07-05`，plan SHA-256
`20bff8500814cf062e12cd6301962aa05be02671c558d6153295634e776f751a`：只含 2022-12 的 1d companion
7 个 bars 与 1w 2 个 bars，共 2 个原生 provider requests、9 个 expected bars；scope diagnostics 无
source/integrity reason。它只是 apply 候选，尚无 provider 或 Canonical 写入意图。

## PF2611 与九个 RS 的隔离结论

PF2611 的 `1w/2025-11/part.parquet` SHA-256 为
`6f3febb68c514937cf143893303a43bc30dcb83a07fb87167e569a7bf4e4cd49`；2025-11-21 的 OHLC、volume、
turnover、open interest 均为 0。当前普通 warm-up plan 为 0 targets / 0 provider requests，只报告
`SOURCE_NONPOSITIVE_PRICE`，所以不能把 PF2611 当普通缺口修复。

九个 RS 的原报告 178 个 diagnostic partitions 已按 Catalog 精确 URI、hash 和 strict store read 全部复核；
35 个原标记非正分区与现场观察完全相等，无漏标或多标。现场存在 91 个分区、缺失 87 个分区；现存分区
合计 85 个非正价行。Catalog/分区逐项事实见上述 `current-catalog-investigation.json`，原生只读 warm-up
计划见上述 `current-special-plans.json`。各合约不能因同时存在缺失分区而降级成普通队列：

| 合约 | diagnostics | 存在 / 缺失 | 非正分区 / 行 | 当前普通 dry-run requests |
| --- | ---: | ---: | ---: | ---: |
| RS2407 | 16 | 6 / 10 | 4 / 18 | 15 |
| RS2409 | 12 | 7 / 5 | 7 / 16 | 10 |
| RS2411 | 26 | 20 / 6 | 4 / 5 | 8 |
| RS2507 | 25 | 17 / 8 | 1 / 1 | 10 |
| RS2509 | 25 | 5 / 20 | 1 / 1 | 21 |
| RS2511 | 26 | 6 / 20 | 4 / 11 | 21 |
| RS2608 | 8 | 2 / 6 | 1 / 1 | 8 |
| RS2607 | 14 | 7 / 7 | 6 / 18 | 12 |
| RS2609 | 26 | 21 / 5 | 7 / 14 | 10 |

初始隔离结论因此将 PF2611 与九个 RS 均置为 `REVIEW_REQUIRED`。来源核验本身不生成普通 Canonical apply
hash，不使用 settlement 填 OHLC，也不放宽 Newow 正价策略。

## 来源核验结果（COMPLETED）

已将完整只读 provider 计划固定为 [source-verification-plan.json](source-verification-plan.json)：语义 plan
SHA-256 `ab15a71dac6fbed376d77b58cfdf4f544b634bc1f68bd37e44e3754bdf60afb4`，持久文件 SHA-256
`6c35272a8bf5f16f5532f30c6bf7106052b9070895635e023a895744407a85a5`。计划只使用
`futures.get_exchange_daily`，覆盖 PF2611 与九个 RS，共 41 个精确日期窗口、146 个预期源行、41 个目标
异常 bar；比较 date/OHLC/volume/total_turnover/open_interest，并把 settlement/prev_settlement 仅作证据。

执行规则为：首次错误停止、无重试、保留 provider 规范化响应、不做 OHLC 替代、零 DB/Canonical 写入。
owner 于 2026-09-14 明确授权后，唯一一次 provider 调用链已完成；持久输出目录为
`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-data-recovery-20260913/source-verification-ab15a71d/`；
只新建 `source-verification-plan.json`、`source-responses.jsonl`、
`source-verification-result.json`、`source-verification-invocation.json` 与 `source-verification-execution.json`，
未覆盖现有 evidence。41/41 个请求均返回，146/146 个预期源行和全部预期日期齐全；retries=0、
database writes=0、Canonical writes=0，固定源码、配置元数据与本地 41 个目标快照前后未变。

`source-responses.jsonl` SHA-256 为
`c9171f3529fde145876319e659bce0cf8277f9d88993155406965adcda686fc4`，
`source-verification-result.json` 为
`741238014cc1edc92243488688a688f31ef457c19bf4a605803a2d583c6898da`，
`source-verification-execution.json` 为
`372c6d5ba1758be8a30ddb50ec5076705a5513d8293ff1d10ea783d714ef40b8`。

41 个目标全部分类为 `AUTHORITATIVE_SOURCE_NONPOSITIVE_MATCHES_CANONICAL`：RQData 原始交易所日行情按
现有 D1/W1 口径聚合后，与本地 Canonical 的 OHLC、volume、turnover、open interest 逐字段相等；其中
low 非正 41 个、open 非正 26 个、high 非正 15 个、close 非正 30 个。41 个目标的 settlement 与
prev_settlement 均为正，但只保留为来源证据，不替代 OHLC。因此 PF2611 与专项九个 RS 的根因已闭环为
权威源本身非正价格，继续保持 `REVIEW_REQUIRED` 和 Newow 阻断，不生成 Canonical 修复计划。

RS2309/RS2311 不在该冻结来源计划内，仍作为独立 `REVIEW_REQUIRED` 保留；不得用本结果外推。该次 provider
意图已消费，任何新增来源下载或 Canonical apply 均需新的精确单次意图。

## 当前工程验证

定向 metadata、HistoricalDataManager、readiness、weekly acceptance、CLI、diagnostics、product reader 与
只读兼容共 `532 passed`。当前只读调查未复现生产代码缺陷，因此没有为了形成代码改动而添加推测补丁。
