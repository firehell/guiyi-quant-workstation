# Current Task

## Task ID

`20260630-su-bing-daily-score2of4`

## 任务名称

苏冰 JM 日线 `v0.3.0-daily-score2of4` 独立策略实现、3 年日线回测与可信指标分析。

## 背景

本轮基于 `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily` 的冻结基线，新增独立研究版本 `v0.3.0-daily-score2of4`。

新版本验证用户提出的规则：原有 4 个日线条件中满足任意 2 个即可产生候选开仓，但必须保留方向锚点，避免 `macd_near_zero + volume_expanded` 这类无方向组合直接开仓。

当前 rollover P0 尚未完全关闭；本轮必须同时输出 raw metrics 和 trusted excluding cross-contract metrics，可信结论只基于后者。

## 本轮目标

- 新增独立策略包 `su_bing_jm_daily_score2of4`。
- 保留策略家族 `strategy_code=su_bing_jm_daily_ema21_macd_volume`。
- 新增 `strategy_version=v0.3.0-daily-score2of4`。
- 不修改 `v0.2.0-daily` 默认参数、入场、离场、MACD 阈值或量能规则。
- 新增后端固定任务入口，可选择 score2of4 日线回测。
- 输出 score、condition details、scene tags 和 review artifacts。
- 运行焦煤 JM 3 年日线研究回测，并输出 raw/trusted 指标和 v0.2/v0.3 对比。

## 允许修改范围

- `tasks/current.md`
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_score2of4/`
- `services/quant-api/app/backtest/v1b_jm_tasks.py`
- `services/quant-api/app/api/backtests.py`
- `services/quant-api/app/vnpy_integration/backtest_runner.py`
- `services/quant-api/app/vnpy_integration/result_converter.py`
- `services/quant-api/tests/test_su_bing_jm_daily_score2of4.py`
- `services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`
- `services/quant-api/tests/test_vnpy_integration.py`
- `services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py`
- `services/quant-api/tests/test_su_bing_report_10_review_export.py`
- `scripts/export_su_bing_daily_score2of4_package.py`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`
- `backtests/reports/su_bing_daily_score2of4/`

## 禁止修改范围

- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/` 的 v0.2.0 策略行为与默认参数。
- 数据库结构 / migration。
- Web。
- 实盘 / 模拟盘 / CTP / TqSdk 交易接口。
- `.env`、账号、密码、API Key、Token、license。
- 真实数据目录 `data/raw/`、`data/parquet/`、`data/processed/`。
- vn.py 源码。
- 多品种参数优化。

## 执行模式

- 总控计划已确认，当前执行实现。
- 低风险步骤自动继续。
- 触发 Gate 必须暂停。

## 任务步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 测试命令 | 测试结果 | 风险记录 |
|---|---|---|---|---|---|---|---|
| 0 | done | low | 分支初始化与任务记录 | `tasks/current.md`; 设计文档 | `git status --short`; `git branch --show-current` | 当前分支 `codex/su-bing-daily-score2of4` | 从 `main` 创建功能分支后执行 |
| 1 | done | low | v0.3 score2of4 设计文档 | `V0_3_SCORE2OF4_DESIGN.md` | 文档审查 | 已输出设计 | 仅设计，不修改 v0.2 |
| 2 | done | medium | score2of4 策略测试先行 | 新测试文件 | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_score2of4.py` | 先红：`ModuleNotFoundError`; 后绿：`8 passed` | 已按 TDD 红绿执行 |
| 3 | done | medium | 独立策略包实现 | 新策略包 | 同 Step 2 | `8 passed` | 未改 v0.2 策略包 |
| 4 | done | medium | 后端 task builder/API/result passthrough | backtest API/runner/converter/tests | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py`; `uv run --project services/quant-api pytest -q services/quant-api/tests/test_vnpy_integration.py` | `15 passed`; `15 passed` | 旧 daily EMA21 API 保持不变；新增 score2of4 API |
| 5 | done | medium | v0.3 导出与报告分析 | export script; reports; docs | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py`; export script | `8 passed`; report 11 导出成功 | trusted 结论排除 8 笔 cross-contract PnL |
| 6 | done | medium | 3 年 JM 日线回测 | DB task/run/export | inline `BacktestTaskRunner` | `task_id=18`; `report_id=11`; trade_count `47`; order_count `0` | vn.py orders 为空符合 `submit_vnpy_orders=false` 研究交易设计 |
| 7 | in_progress | low | 最终验证与交接 | handoff docs; tests | 全量指定测试 + ruff | 待最终执行 | 不做 Web 验收 |

## Gates

| Gate | 触发条件 | 暂停时必须报告 |
|---|---|---|
| Gate 0 | 仍在 `main` 且准备改文件 | 当前分支、工作区状态、建议分支 |
| Gate 1 | 工作区出现非本轮未提交改动 | 改动文件、是否相关、继续风险 |
| Gate 2 | 需要 migration、Web 改动、实盘/模拟盘接口、凭据读取或真实数据目录写入 | 触发原因、拟修改文件、风险和确认问题 |
| Gate 3 | 跨合约 PnL 被混入 trusted 结论 | 当前完成情况、受影响交易、后续方案 |
| Gate 4 | 测试、DB、vn.py、Redis/RQ 或回测运行失败 | 失败命令、错误摘要、拟修文件或下一步 |

## 验收标准

- [x] `v0.2.0-daily` 默认参数和交易行为保持不变。
- [x] 新增 `v0.3.0-daily-score2of4` 独立策略包。
- [x] long/short 4 条件评分、`min_entry_score=2`、方向锚点和同分冲突拒绝均有测试覆盖。
- [x] 每根 warmup 后日线 bar 输出 score/condition candidate。
- [x] 每笔交易输出 `entry_score`、`entry_grade`、`scene_tags` 和 `skill_notes`。
- [x] 信号确认为当前日线 close，成交为下一日线 open。
- [x] Review Tags 和 `immediate_failure_later` 不参与同一时点 `on_bar`。
- [x] 新后端固定任务入口可创建 score2of4 回测任务。
- [x] v0.3 报告输出 raw metrics 和 trusted excluding cross-contract metrics。
- [x] 不做 Web、migration、实盘/模拟盘、vn.py 源码修改。

## 3 年 JM 日线回测结果

- task_id: `18`
- report_id: `11`
- strategy_version: `v0.3.0-daily-score2of4`
- data_version: `rqdata_jm_standard_1d_20230103_20251231_v1`
- window: `2023-01-03T15:00:00+00:00` 至 `2025-12-31T15:00:00+00:00`
- raw_trade_count: `47`
- trusted_trade_count: `39`
- excluded_trade_count: `8`
- raw_net_pnl: `52798.083`
- trusted_net_pnl: `-34914.555`
- raw_win_rate: `0.3191489362`
- trusted_win_rate: `0.2051282051`
- raw_profit_loss_ratio: `3.4583804266`
- trusted_profit_loss_ratio: `2.1928229665`
- raw_max_drawdown: `0.1375073065`
- trusted_max_drawdown: `0.3728810309`
- raw_max_consecutive_losses: `7`
- trusted_max_consecutive_losses: `8`
- cross_contract_trades: `8`
- orders: `0`，符合 `submit_vnpy_orders=false` 的研究交易记录设计。

## score 分布结论

- score=2: signals `33`, trades `32`, trusted_net_pnl `-42716.19`
- score=3: signals `14`, trades `14`, trusted_net_pnl `-4748.826`
- score=4: signals `1`, trades `1`, trusted_net_pnl `12550.461`
- 最常见组合：`short_trend_ok+macd_near_zero`、`long_trend_ok+volume_expanded`、`short_trend_ok+macd_near_zero+volume_expanded`、`short_trend_ok+volume_expanded`

## 风险记录

- raw metrics 为正，但 trusted excluding cross-contract metrics 为负；可信结论必须使用 trusted 指标。
- score=2 信号显著增加交易频率，也显著增加噪声和回撤。
- cross-contract PnL 仍需 rollover-safe 数据任务处理。
- 当前不建议直接进入实盘、模拟盘或参数优化。

## 测试命令

```bash
git status --short
git branch --show-current
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_score2of4.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_vnpy_integration.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py
uv run --project services/quant-api ruff check .
```

## 浏览器验收

- 是否需要 Browser/Chrome：否。
- 页面地址：不涉及。
- 操作路径：不涉及。
- 需要观察的结果：不涉及。
- 是否需要截图：否。
- 是否需要检查控制台：否。

## 完成后输出要求

```markdown
## 总控目标
## 当前分支与 git 状态
## 阶段 0：计划与边界确认
## 阶段 1：v0.3.0 规则设计
## 阶段 2：v0.3.0 实现
## 阶段 3：测试结果
## 阶段 4：3 年 JM 日线回测
## 阶段 5：报告分析
## 阶段 6：最终交接
## 新增/修改文件
## v0.2.0 是否保持不变
## v0.3.0 规则摘要
## raw metrics
## trusted excluding cross-contract metrics
## v0.2.0 vs v0.3.0 对比
## score 分布结论
## Skill 标签结论
## 是否建议进入 v0.3.1
## 风险与后续 TODO
```
