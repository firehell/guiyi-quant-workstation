# D1 17 项日期合同修正、离线复验与剩余 21 日续行计划

固定研究截止：`2026-09-18T18:30:00+08:00`。

## 日期合同修正

- provider 传输身份固定为 `contract + [start, end]`。
- 研究目标身份固定为去重、升序且位于传输窗口内的 `target_dates`。
- Catalog 合约生命周期、RQData TradingCalendar 和逐品种 TradingSession 共同冻结
  `allowed_response_dates`，并分别记录日期集合哈希和权威对象哈希。
- 响应可以包含窗口内、已由上述权威证明的非目标交易日；这些行只保存为上下文，不进入目标计数、质量分类或修复范围。
- 缺目标日、越界日、未被权威证明的日期、错合约、重复日、乱序或异常 OHLCV 结构均 fail-closed。
- 原始数值按 source scalar 原样持久化；零价继续分类为 source fact，不改写为 `NO_TRADE`。
- 请求预算只计 provider call，目标预算只计 `target_dates`，上下文日期不扩大授权范围。

## 已保存响应离线复验

`subing-d1-response-validator-v2` 对原批次的 9 份已保存响应完成纯离线复验：

- provider 请求：`0`
- 数据写入：`0`
- 已保存响应：`9/9` 合法
- 响应总行：`55`
- 目标行：`45`
- 合法上下文行：`10`
- 第 9 份 PF2611 2025-12 响应：`22 = 12 target + 10 context`
- 目标分类保持：`32 NONPOSITIVE_CLOSE`、`8 POSITIVE_OHLC`、`5 ZERO_OHL_POSITIVE_CLOSE`

原 `invocation-receipt.json`、`journal.jsonl`、`source-only-result.json` 在复验前后哈希一致。
原执行状态继续保持 `failed`；本结论是离线 validator verdict，不是旧批次重试或执行成功。

详细哈希与逐响应结论见 `d1-17-source-verification-offline-v2.json`。

## 剩余 21 日续行批次

计划哈希：`c89cd8786323370ff86a178c6bf91ac9a3fe2ab88bac73ceb0daa00b7f5eeb1e`。

| 顺序 | 合约 | 传输窗口 | 目标日 | 允许上下文日 | 原请求索引 |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | RS2609 | 2026-08-12..2026-08-12 | 1 | 0 | 13 |
| 2 | RS2609 | 2026-09-02..2026-09-09 | 4 | 2 | 14 |
| 3 | RS2609 | 2025-11-24..2025-11-28 | 3 | 2 | 11 |
| 4 | RS2609 | 2025-12-02..2025-12-04 | 2 | 1 | 12 |
| 5 | PF2611 | 2026-01-19..2026-01-30 | 4 | 6 | 9 |
| 6 | PF2611 | 2026-02-03..2026-02-27 | 6 | 7 | 10 |
| 7 | Y2609 | 2026-09-09..2026-09-09 | 1 | 0 | 15 |

批次约束：

- `7` 个串行请求，`21` 个目标日，最多可能返回 `18` 个合法上下文日；
- RS2609 五个 rank1 目标日排在前两项；
- 排除原批次所有已开始索引 `0..8`，不重复失败索引 `8`；
- 新 plan claim、新 attempt 目录、零自动重试、单项失败即停止；
- Canonical、PostgreSQL、Redis 和 manager apply 写入均为 `0`；
- 精确请求、日期列表、权威哈希及旧 plan/result/journal/offline verdict 绑定见
  `d1-17-source-verification-continuation-candidate.json`。

## 续行执行结算

16 次冻结总预算由原批次 9 次和续行 7 次全部消耗，零重试；原第 9 次失败回执保持 `failed`，离线 v2 仅证明其已保存响应在目标日/上下文日分离合同下有效，不改写原执行历史。

owner 后续明确批准该冻结计划，实际来源采集于 `2026-09-19T12:21:41.610718+08:00`
完成：

- `7/7` 请求 started、saved、completed，`0` failed、`0` unexecuted、`0` retry；
- `21/21` 目标日全部观察，并保存 `18` 个权威允许的上下文日；
- RS2609、PF2611 的 20 个目标日均为 `NONPOSITIVE_CLOSE_SOURCE_FACT`，逐日与当前
  Canonical OHLCV 完全一致；
- Y2609/2026-09-09 为 `ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT`，该目标行不在当前
  Canonical 分区中，fresh source 仍不满足硬校验；
- RS 五个 rank1 日全部确认非正 Close，且与 Canonical 精确一致；
- 两批合计 66 个目标日已全部取得 source evidence：52 个非正 Close、6 个零 OHL 正
  Close、8 个正 OHLC；后 8 个属于 OI/PF 九月独立端点，但其分区仍混有 10 个非正 Close；
- 原 1,207 个异常日期现为 `1,207/1,207` 有保存的来源响应，未知项归零；
- 16 个目标 contract-month 中没有完整有效来源可进入生产修复，`223/240` 与 17 个 D1
  阻塞均未变化。

Canonical、PostgreSQL、Redis、manager apply、页面、Scope、通知、release 和 Runtime 写入均为
`0`。机器结算见 `d1-17-source-verification-complete.json`；原始响应、journal、回执和 plan
续行 claim 仅保留本机并由 `.gitignore` 排除；原批次 claim 已作为不含行情原文的历史执行身份随旧结算受控入库。
