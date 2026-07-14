# Data Layer

更新时间：2026-07-14

事实来源：`docs/DATA_CENTER.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md`

当前状态：current，数据层仍有外部 Gate。

## 当前结论

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

## active 入口

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测、Signal Gate 默认要求 `quality_status=passed`。

## Phase 3 指标

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |

105 条 `quality_warning` 不升级 passed。

## 阻塞项

- manifest / DB 对齐。
- pre-2020 周线 34 品种缺口或 N/A 判定。
- actual contract 缺口。
- 当前不能宣称全品种周线从上市以来完整。

