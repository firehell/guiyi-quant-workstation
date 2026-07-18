# CONSUMER-GOLDEN-QUERY-FINAL-GATE-005

## 结论

```text
DATA_LAYER_PARTIAL
```

本次只读最终 Gate **未通过**。不得写入：

```text
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
```

前置五个阶段标记均存在，direct PostgreSQL 可用且事务为 `READ ONLY`。多数 strict 样本已证明 Market bars、EMA、Backtest resolver 与 Review exact-bars 使用相同 file ID、data version 和 binding snapshot；Signal 对 `.MAIN` 作为 actual 全部 fail-closed。但 12 个固定 Golden Query 中仍有不可接受的真实数据/契约缺口。

## 固定环境

- current commit: `de24202b892c495e88182aa48db9fb2bd1a9740b`
- Stage B acceptance commit: `d19b67dc68c7f28e8109720be51775390aed49d8`，是 current commit 祖先
- data root: `/Volumes/扩展盘/guiyi-quant-workstation`，与 Stage B 一致
- DB snapshot source: `direct_database`
- database: `guiyi_quant`
- PostgreSQL transaction read only: `on`
- Alembic revision: `20260718_0024`
- MarketDataFile / active binding / report count: `103307 / 4290 / 14`

## 精确阻断项

1. `GQ02 JM continuous 15m`：`intraday_research_v1 / jm / jm.MAIN / 15m` 的 active binding 指向 file `56067`，该文件当前为 `data_role=superseded`。Market Research 返回 `MARKET_PROFILE_IDENTITY_MISMATCH`，Backtest 返回 `BACKTEST_PROFILE_QUALITY_BLOCKED`，Indicator 与 Review 无法执行。
2. `GQ05 JM actual dominant 1m`：`intraday_research_v1 / jm / JM2609 / 1m` 缺 active binding。Market、Backtest、Signal 分别返回 `MARKET_PROFILE_BINDING_MISSING`、`BACKTEST_PROFILE_BINDING_MISSING`、`SIGNAL_PROFILE_BINDING_MISSING`。
3. `GQ09 quality warning browser`：file `82792` 及 direct `data_quality_reports.id=80595` 均为 `warning`，但 Browser API 返回 `quality=unchecked`。原因是读取层只接纳当前 `rqdata_structured_v1` check-rule，而该 canonical warning 证据为 `rqdata_jm_v2_direct_bars_v1`。Browser 没有被错误收紧为 passed-only，但 warning 未被显式返回，仍不符合观察模式契约。
4. 跨消费者返回中 `source_interval` 没有独立 lineage 字段，Golden bar payload 为 `null`；目前只能比较请求 `period`，不能完成题目要求的 source interval 证明。

## 已通过的核心保护

| Hard Gate | 结果 | 证据 |
|---|---|---|
| strict consumer escape paths = 0 | PASS | 50 个 Backtest/Signal/Market contract tests 通过；formal API 无客户端路径输入 |
| arbitrary path formal Backtest = 0 | PASS | `bar_data_path` / `auxiliary_bar_data_paths` 在 formal schema 阻断 |
| warning 进入 Backtest/Signal = 0 | PASS | TF strict 样本返回 `BACKTEST_PROFILE_QUALITY_BLOCKED`；Signal passed-only regression 通过 |
| `.MAIN` 作为 actual = 0 | PASS | continuous 样本均返回 `SIGNAL_ACTUAL_CONTRACT_REQUIRED` |
| bars/indicator binding mismatch = 0 | PASS | 7 个可解析 strict 样本 file ID/version/snapshot/token 一致 |
| daily duplicate = 0 | PASS | JM/AL 1d/1w 样本 trading_day 唯一 |
| different-value conflict 静默吞掉 = 0 | PASS | SN2608 `2026-06-29` 返回 conflict=1、字段和两个资产证据 |
| duplicate active binding = 0 | PASS | direct DB group query 为 0 |
| report 14 unchanged | PASS | MD5 `ae807ef77f7d9a4ce3067996558b57e8`，155 trades，239 orders |
| DB source = direct database | PASS | PostgreSQL read-only transaction |
| Stage B root/commit | PASS | 同一 data root；acceptance commit 是当前 commit 祖先 |

## Golden Query 摘要

- `GQ01` JM continuous 1m：Market/Indicator/Backtest/Review 一致；Signal 正确拒绝 `.MAIN` actual。
- `GQ02` JM continuous 15m：**FAIL**，binding 指向 superseded。
- `GQ03/GQ04` JM continuous 1d/1w：一致通过；Signal 正确拒绝 `.MAIN` actual。
- `GQ05` JM actual dominant 1m：**FAIL**，binding missing。
- `GQ06` AL full-history 1m：一致通过，225 bars，OHLCV hash `79ee8508...b6236f4`。
- `GQ07D/GQ07W` AL full-history 1d/1w：一致通过，无 trading-day duplicate。
- `GQ08` 首周样本：`2000-01-07` 唯一周 bar，一致通过。
- `GQ09` warning browser：**FAIL**，真实 warning 被显示为 unchecked。
- `GQ10` strict blocked：通过，warning/ineligible asset 未进入 Backtest。
- `GQ11` different-value conflict：通过，SN2608 冲突未被吞掉。
- `GQ12` binding missing：通过，Market Research fail-closed。

完整逐消费者数据见 `consumer_golden_matrix.csv`，结构化 Gate 见 `final_gate_evidence.json`。

## 验证

```text
direct PostgreSQL preflight: PASS, transaction_read_only=on
Golden service probes: completed against Market/Indicator/Backtest/Signal/Review
contract regression: 50 passed, 0 failed, 0 skipped
database/parquet/manifest/binding writes: 0
RQData/live runtime/notification: not invoked
```

## 后续边界

本任务是只读验收，不修复上述缺口。最小后续任务应分别处理：Profile binding 修复（JM continuous 15m 与 JM2609 actual 1m）、Browser legacy quality evidence 映射，以及 source interval lineage 暴露；修复后必须重新执行本 Gate，不能复用本次失败结论升级 Ready。
