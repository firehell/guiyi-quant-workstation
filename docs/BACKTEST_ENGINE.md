# BACKTEST_ENGINE.md

更新时间：2026-07-14

## 1. 定位

V1 使用 vn.py / VeighNa CTA BacktestingEngine。归一量化负责数据 Gate、任务编排、参数校验、结果转换、报告入库、Web 展示和可信审计。

回测不等于实盘，不生成自动交易指令。

## 2. 数据入口

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究使用 `quality_status=passed`。JM 最新主连六周期在当前文档口径中为 `primary / passed`；其中 5m/15m/30m/60m/1d 来自 passed 1m standard parquet 本地聚合。具体行数和 data_version 以 `docs/DATA_CENTER.md` 的当前表和对应 manifest/report 为准。

禁止 validation、legacy_reference、candidate、failed、live DB、旧 TqSdk / 天勤和交易练习者数据进入正式回测。

## 3. 调用链

```text
Backtest API
-> BacktestService
-> vn.py runner
-> ResultConverter
-> BacktestReport / Trade / Order
-> derived equity / drawdown / trusted metrics
-> trust audit CLI
```

- report 曲线从 closed trades 派生，忽略外部输入的 equity/drawdown 曲线。
- trade/order 保存 signal/fill/order 映射与 lineage summary。
- 当前 bar 信号采用 `next_bar_open` 成交，禁止当前 bar 提前成交。
- 手续费、滑点、乘数、price tick、保证金和真实合约映射必须可追溯。

## 4. Stage 13-G 结论

可信基线：

- report：`report_id=14`
- task：`BTV-20260709134008-0a42eca8`
- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- data：`local_parquet / primary / passed`
- trades：155，全部 `lineage_status=mapped`
- orders：239，全部 `mapping_status=mapped`
- trust audit：10/10 checks `passed`
- total return：`-0.1928553100985149`

`passed` 只代表数据、执行、成本、trade/order/equity/metrics 和敏感输出一致，不代表策略盈利、稳定或可实盘。

该结论也不代表 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 已达成；当前数据层最终状态仍是 `DATA_LAYER_PARTIAL`。

只读命令：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

## 5. 必查风险

- 未来函数和数据泄露。
- 分型/突破/方向信号是否等待确认 bar。
- 成交是否严格晚于 signal time。
- 手续费、滑点、乘数、保证金和 rollover 成本。
- 最大回撤、最大连续亏损、期望值和资金占用。
- 单笔交易能否回到 K 线和 review note。
- 样本内与样本外是否分离。

Stage 13 审计不重跑策略，不能单独证明没有未来函数或过拟合。XMA PoC 已明确存在重绘风险，不得进入正式回测或信号。

## 6. 下一步

- 保持 `report_id=14` 作为回归基线，不修改策略参数以改善收益。
- 独立设计样本外 / walk-forward 验证区间、版本和验收标准。
- 旧报告不自动回填 lineage；如需修复必须另开只读审计与受控 backfill Gate。
- `research_only` 字段语义拆分需先设计兼容 schema/API，本轮不重命名历史字段。
