# BACKTEST_ENGINE.md

更新时间：2026-07-18

## 1. 定位

V1 使用 vn.py / VeighNa CTA BacktestingEngine。归一量化负责数据 Gate、任务编排、参数校验、结果转换、报告入库、Web 展示和可信审计。

回测不等于实盘，不生成自动交易指令。

## 2. 数据入口

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_policy = "passed_only"
quality_status = "passed"
```

公开 `/api/backtests/tasks`、inline `/run`、`/run-batch` 和 fixed JM 均属于 formal consumer。客户端只提交行情 identity 和可选 `profile_id`，不得提交主/辅助本地路径、data role、quality、data version 或 warning override。服务端通过 `ProfileLineageResolver` 固定 active Profile binding；主资产与辅助资产必须属于同一 Profile。

低层 `GuiyiBacktestRequest` 仍可接收路径，但仅供显式 `research_only` 的 legacy、experiment 和 test fixture 使用，不能通过公开 formal API 持久化为正式任务或报告。

Formal contract 错误采用稳定 code：`BACKTEST_FORMAL_PATH_FORBIDDEN`、`BACKTEST_PROFILE_NOT_FOUND`、`BACKTEST_PROFILE_BINDING_MISSING`、`BACKTEST_PROFILE_MARKET_FILE_MISSING`、`BACKTEST_PROFILE_QUALITY_BLOCKED`、`BACKTEST_PROFILE_RANGE_NOT_COVERED`、`BACKTEST_PROFILE_FILE_MISSING`、`BACKTEST_PROFILE_IDENTITY_MISMATCH`、`BACKTEST_PROFILE_BINDING_CHANGED`。错误 context 不返回物理文件路径；并发 binding 切换使用 HTTP 409，其余契约拒绝使用 HTTP 422。

禁止 validation、legacy_reference、candidate、failed、live DB、旧 TqSdk / 天勤和交易练习者数据进入正式回测。

## 3. 调用链

```text
Backtest API
-> BacktestService
-> ProfileLineageResolver (active / passed_only)
-> immutable binding snapshot
-> vn.py runner
-> ResultConverter
-> BacktestReport / Trade / Order
-> derived equity / drawdown / trusted metrics
-> trust audit CLI
```

- report 曲线从 closed trades 派生，忽略外部输入的 equity/drawdown 曲线。
- task 保存 `profile_id`、主 `market_data_file_id` 和包含全部辅助资产的 immutable snapshot；report 深拷贝 task snapshot，不按当前 binding 重新解析。
- snapshot 记录 `resolver_name=ProfileLineageResolver`、`resolver_contract_version=backtest_profile_v1` 和 `quality_policy=passed_only`。
- batch task 可因多资产令顶层 `market_data_file_id` 为空，但 snapshot 必须列出全部资产，且每个 report 的文件 ID 必须非空。
- runner 只执行 snapshot 固定的文件 ID/路径，并要求 Parquet 显式携带 `data_role=primary`、`quality_status=passed`；缺字段不再默认通过。
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

该结论本身不证明策略盈利、稳定或实盘准入。消费者数据准入已由 C2-05 取得 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`；`DATA_LAYER_REAUDIT_REQUIRED` 仍只保留给全历史 residual 治理，不改变 report 14 的冻结边界。

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

- `20260718_0024` 仅新增 task/report nullable JSON snapshot，无 UPDATE、server default 或历史 backfill。包含 report 14 的隔离 PostgreSQL 已完成 `0023 -> head -> 0023 -> head` roundtrip，canonical PostgreSQL 已应用；report 14、trades、orders 和 trust audit 与迁移前副本一致，历史 snapshot 保持 null。
- 保持 `report_id=14` 作为回归基线，不修改策略参数以改善收益。
- 阶段 4 先冻结 indicator policy 与 strict candidate 输入；阶段 5 再创建独立候选报告、运行 trust audit，并设计样本外 / walk-forward 验证区间、版本和验收标准。
- OOS / walk-forward 默认仅输出文件或隔离数据库；任何 canonical PostgreSQL 写入都需独立审批包和用户明确批准。trust audit passed 不能直接写为策略有效，最终候选结论必须留给阶段验收任务。
- 旧报告不自动回填 lineage；如需修复必须另开只读审计与受控 backfill Gate。
- `research_only` 字段语义拆分需先设计兼容 schema/API，本轮不重命名历史字段。
