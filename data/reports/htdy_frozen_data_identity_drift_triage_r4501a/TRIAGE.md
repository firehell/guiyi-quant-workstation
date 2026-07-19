# HTDY Frozen Data Identity Drift Triage R4501A

Gate: `HTDY_FROZEN_DATA_IDENTITY_DRIFT_ROOT_CAUSE_CONFIRMED`

Packet hash: `c661d8fb282fca0f2555d93e95564025a41e0f9945d08fa2b7ddbdd07b2e6d9b`

## 结论

旧资产没有发生物理 hash 漂移、事后截断或 manifest/历史登记身份冲突。R45-01 的 15 根差异来自一个确定的冻结契约错配：协议把实际只覆盖到 `2026-07-09 23:00` 的旧资产精确 path/hash，与 `full_window_end=2026-07-10 15:00` 绑定在了一起，却没有在 prepared/final frozen Gate 校验覆盖 invariant。

因此必须保持：

```text
R45-00 = STAGE45_CLOSEOUT_BASELINE_READY
R45-01 = STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT
```

本调查通过不等于 R45-01 通过。

## 关键时间线

| 时点 | 事件 | 证据含义 |
|---|---|---|
| 2026-07-10 08:02 +08 | old raw/1m 生成 | 请求结束日为 7 月 10 日，但物理最大 bar 为 7 月 9 日 23:00；此时日盘尚未发生。 |
| 2026-07-10 15:21 +08 | old 15m 写出 | `regenerate_jm_aggregated_bars.sh` 只读已有 passed 1m、不调用 RQData，所以无法补入日盘。 |
| 2026-07-12 20:46 +08 | new 15m 写出 | 后续全历史资产已覆盖 7 月 10 日 15:00。 |
| 2026-07-19 11:18 +08 | `f48e8203` protocol prepared | prepared 版本已经同时写入旧资产 hash 与超出其覆盖的 full-window end。 |
| 2026-07-19 12:45 +08 | `d731083e` final frozen | diff 只改变冻结状态和接受元数据，没有修改或重新校验 `frozen_data_policy`。 |

文件名中的 `20260710` 是请求结束日期，不是数据已覆盖到当日日盘的证明。旧资产内部 `max_trading_day=2026-07-10` 只说明 7 月 9 日夜盘归属于 7 月 10 日交易日，也不代表存在 7 月 10 日日盘。

## 身份闭环

| 项目 | old frozen asset | X5 execution asset |
|---|---|---|
| data version | `rqdata_jm_standard_15m_20230103_20260710_v2` | `rqdata_jm_standard_15m_20200102_20260711_v2` |
| file SHA-256 | `7161c515…bc70c` | `e1a78c06…80a1f` |
| rows（全文件） | 19,366 | 35,477 |
| protocol-window rows | 19,366 | 19,381 |
| last bar | 2026-07-09 23:00 | 2026-07-10 15:00 |
| metadata identity | file 55793 / quality 54552 | file 71338 / quality 68804 / binding 4945 |

旧 manifest、physical inventory、历史 DB inventory 和 quality snapshot 都与 old path/row/max/hash 一致。历史 DB inventory 仅作为当时快照证据，本任务没有查询或写入 live DB。

## 逐 bar 复算

- old/new SHA-256 与各自声明一致。
- R45 baseline 与 equivalence packet hash 均有效，重算 equivalence packet hash 仍为 `142de03ada02555ce2d734e532cee097b5c23e4d91b6f92d62121b8e771b4c47`。
- 共同区间 19,366 根 bar 的 exact ordered hash 均为 `5354608feb3f512da99e21b9e61db26c66121faf82278dd08fcf18bf5a458d46`。
- 双方重复 datetime 均为 0，旧侧没有新侧缺失 bar，字段差异计数为空。
- 唯一差异是 new 多出 `2026-07-10 09:15..15:00` 的 15 根日盘 bar。

## 根因与边界

唯一根因分类：`frozen_contract_asset_coverage_mismatch`。

不是：

- physical asset hash drift；
- 生成后截断；
- manifest/历史 DB identity 冲突；
- R45 comparator tolerance 或 datetime 误判。

本任务未修改 protocol、Parquet、manifest、Profile binding、DB 或 X5 证据，未重跑策略。若继续追求 R45-00/R45-01 双 PASS，必须另立任务创建新版本协议并重建其依赖证据链；不得原地改写 frozen v1 或把本调查 Gate 冒充为 R45-01 PASS。

## 主要证据

- `data/reports/htdy_stage45_closeout_r45/{baseline,data_equivalence}/`
- `data/manifests/rqdata_jm_v2_history_20230103_20260710.csv`
- `data/reports/full_history_residual_repair_20260710/closure_004b/post_repair_inventory_full/{physical_inventory,db_inventory}.csv`
- `docs/strategy_specs/htdy/GOLDEN_SAMPLE_ACCEPTANCE.md`
- `experiments/htdy_indicator/golden_sample_manifest.json`
- `scripts/regenerate_jm_aggregated_bars.sh`
- `configs/oos/htdy_strict_validation_protocol_v1.json`
