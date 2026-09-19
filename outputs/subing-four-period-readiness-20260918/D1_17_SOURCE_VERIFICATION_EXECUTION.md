# D1 17 项来源验证执行结算

固定研究截止：`2026-09-18T18:30:00+08:00`。真实来源观察日期：2026-09-19。fresh 响应属于当前 provider vintage，一致只能证明本次观察，不证明历史数据从未变化。

## 执行结论

- 冻结 plan：`2c764158c097919fdb7a87ec3935c364905a122ff95d10cc96bf82b1c1c785bb`。
- 计划 16 请求、66 日期；实际 started 9、saved 9、完成 8、失败 1、未执行 7；零重试。
- 第 9 项 `PF2611 / 2025-12` 保存了 22 行，其中冻结目标 12 行全部存在，但 provider 同时返回区间内 10 个额外交易日，因精确日期身份不相等触发 `SOURCE_RESPONSE_IDENTITY_INVALID`，批次按合同停止。
- 保存 raw 55 行，其中冻结目标 45 行、额外 10 行；剩余 21 个目标日期未执行。
- Canonical 写入 0、数据库写入 0、manager apply 0。plan claim 已占用，禁止更换 attempt-id 重跑。
- 原 1,207 个异常日期的来源证据由 1,159 日增加至 1,186 日；仍缺 21 日，分别为 PF2611 10 日、RS2609 10 日、Y2609 1 日。

## 45 个已观察目标日期

- `ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT`：5 日（C、EB、I、P），与既有 Catalog source-quality 分类一致，继续阻塞。
- `NONPOSITIVE_CLOSE_SOURCE_FACT`：32 日。PF2611 目标日与现有 Canonical OHLCV 零值逐日一致；OI2609/PF2609 九月仍含非正 Close，无法形成完整有效分区。
- `POSITIVE_OHLC_SOURCE_FACT`：8 日，均位于 OI2609/PF2609 九月混合分区；单日事实有效但不足以发布含异常日期的完整分区。
- 可准备生产修复的完整分区：**0**。

## OI/PF 九月 18 日

- OI2609：9 日均观察，6 日正 OHLC、3 日非正 Close。
- PF2609：9 日均观察，2 日正 OHLC、7 日非正 Close。
- 两个分区均继续 `BLOCKED_MIXED_VALID_AND_NONPOSITIVE_SOURCE_FACTS`。

## RS 五个 rank1 日

`2026-08-12`、`2026-09-02`、`09-04`、`09-08`、`09-09` 均位于停止点之后，未执行，状态保持 `UNKNOWN_UNEXECUTED_AFTER_FAIL_STOP`。

## 未执行范围

PF2611 2026-01/02 共 10 日、RS2609 共 10 日、Y2609 1 日，合计 21 日。当前 plan 禁止重试；继续这些日期需要新的精确计划与新授权。

机器可读逐请求、逐日期结算见 [d1-17-source-verification-execution.json](d1-17-source-verification-execution.json)。完整原始响应、journal 与执行回执保留在本机未入库目录 `outputs/subing-four-period-readiness-20260918/d1-source-only-20260919-001/`；远端仅保存其 SHA-256 和聚合结算，避免外传受许可行情原文。
