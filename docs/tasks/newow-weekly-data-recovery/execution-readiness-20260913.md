# Newow 周线恢复执行就绪记录（2026-09-13）

本记录只固化 R1–R4 的当前只读事实与下一次受控操作边界。它不授权 provider、PostgreSQL、
Canonical、Runtime、通知、Scope、main、tag 或 release 写入。

## 固定身份与原始证据

- task branch：`codex/newow-weekly-data-recovery`
- task base / current HEAD：`74d7a71fcd061d25eb23d7d2142a075420125886`
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
`blockers=[]`、Calendar 0，离线 plan/snapshot 语义校验和 journal 一一对应通过。当前生产 Catalog
只读重规划确认三个原 plan 未漂移；batch-03 的新计划为零。

| 顺序 | 批次 | plan SHA-256 | snapshot SHA-256 | targets | 日期 | Session 行 | 已有日期保留 |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |
| 1 | 04 | `a8178e215b376b054d1dafcbe8f5b60bd7706cb62dae8315b80017d5fb3459d1` | `a6fee971e5b3031166f8ef53f40068b56319afb7812edced62de2a45ff68e206` | 56 | 4,007 | 15,253 | 3,972 |
| 2 | 02 | `1ebae39934ed0d096585efebdb8223c6a17099921a03383a8db49543bb0ca3d7` | `8975ad46347a36da40179d5792724d6c494f6880d56dda15cc513a32a2357464` | 64 | 1,458 | 5,798 | 1,512 |
| 3 | 01 | `3a2b4df0a3cafc420bcc56b64d4a46394e499927e5404666ab6d68ac8862739f` | `178c4868a9c3a6faac7d4646a907134ab22fad6953162db9d1cc3c66f50a6b67` | 64 | 1,547 | 6,108 | 1,548 |

合计 184 targets、7,012 个日期、27,159 个 Session 行。输入均位于持久 evidence 根的
`metadata-plans-247/`，以对应 `batch-NN-plan.json` 与 `batch-NN-snapshot.json` 为权威。
每批只新建且不得覆盖以下六个同目录 evidence 文件：`batch-NN-apply-invocation.json`、
`batch-NN-apply.json`、`batch-NN-apply-result.json`、`batch-NN-apply-execution.json`、
`batch-NN-apply-readback.json`、`batch-NN-post-apply-plan.json`；04、02、01 的这些路径当前均不存在。

若 owner 明确授权，执行边界为：严格按 04 → 02 → 01 串行，各一次；每批在 5 秒锁超时的五表
`SHARE ROW EXCLUSIVE` 短事务内原生 recheck 相同后 insert-only commit。每批成功后用新只读事务逐行、
既有日期保留、共享 Session 解析和同 targets 零缺键/零请求读回；再进入下一批。任何漂移、失败或 commit
结果不明立即停止，不重试、不逆向删除。该清单不写 Calendar、MainContractMap、Canonical，也不调用 provider。

## MainContractMap 独立检查

按 operational 60 各产品 active history floor 至 `2026-09-11` 检查权威 Catalog 映射：60 个产品、
49,513 个预期交易日全部存在 rank=1/rule=2 映射；missing=0、extra=0、invalid rank/rule=0。
原报告中 45 个 `MAIN_CONTRACT_MAP_MISSING` 已在 batch-03 的 Session 补齐后消失，因此不设计或调用
MainContractMap writer。逐产品明细见上述 `current-catalog-investigation.json`。

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

因此 PF2611 与九个 RS 均保持 `REVIEW_REQUIRED`。在来源核验完成前，不生成普通 Canonical apply hash，
不使用 settlement 填 OHLC，不放宽 Newow 正价策略。

## 来源核验候选（尚未授权）

已将完整只读 provider 计划固定为 [source-verification-plan.json](source-verification-plan.json)：语义 plan
SHA-256 `ab15a71dac6fbed376d77b58cfdf4f544b634bc1f68bd37e44e3754bdf60afb4`，持久文件 SHA-256
`6c35272a8bf5f16f5532f30c6bf7106052b9070895635e023a895744407a85a5`。计划只使用
`futures.get_exchange_daily`，覆盖 PF2611 与九个 RS，共 41 个精确日期窗口、146 个预期源行、41 个目标
异常 bar；比较 date/OHLC/volume/total_turnover/open_interest，并把 settlement/prev_settlement 仅作证据。

执行规则为：首次错误停止、无重试、保留 provider 规范化响应、不做 OHLC 替代、零 DB/Canonical 写入。
获明确单次 provider 意图后，唯一持久输出目录固定为
`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-data-recovery-20260913/source-verification-ab15a71d/`；
该目录当前不存在，只新建 `source-verification-plan.json`、`source-responses.jsonl`、
`source-verification-result.json`、`source-verification-invocation.json` 与 `source-verification-execution.json`，
不覆盖现有 evidence。任何来源下载需要新的明确单次 provider 意图；来源响应即使证明本地损坏，也不自动
授权 Canonical 覆盖。

## 当前工程验证

定向 metadata、HistoricalDataManager、readiness、weekly acceptance、CLI、diagnostics、product reader 与
只读兼容共 `532 passed`。当前只读调查未复现生产代码缺陷，因此没有为了形成代码改动而添加推测补丁。
