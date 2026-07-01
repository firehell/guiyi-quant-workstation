# Current Task

## Task ID

`20260630-su-bing-daily-trend-cross-score2`

## 任务名称

苏冰 JM 日线 `v0.3.1-daily-trend-cross-score2` 收敛策略实现、3 年日线回测与 Web 复盘展示。

## 背景

本轮基于已冻结的 `v0.2.0-daily` 和已实现的 `v0.3.0-daily-score2of4`，新增独立研究版本 `v0.3.1-daily-trend-cross-score2`。

`v0.3.0` 的 raw 指标为正，但 trusted excluding cross-contract 指标为负，且 score=2 噪声明显。本轮不修改历史版本，而是新建更严格版本：仍保留 4 条件评分与参数追溯，但默认开仓必须同时满足趋势方向环境和对应方向 MACD 交叉；MACD 近零轴与放量作为评分、复盘和可信度分析字段。

## 本轮目标

- 新增独立策略包 `su_bing_jm_daily_trend_cross_score2`。
- 保留策略家族 `strategy_code=su_bing_jm_daily_ema21_macd_volume`。
- 新增 `strategy_version=v0.3.1-daily-trend-cross-score2`。
- 不修改 `v0.2.0-daily` 或 `v0.3.0-daily-score2of4` 的默认参数和交易行为。
- 新增后端固定任务入口，可创建 v0.3.1 日线回测任务。
- 报告继续入库，不做 migration；score、conditions、scene tags 继续进入 `raw_payload`。
- Web 回测/行情页轻量展示 entry score、条件组合和 scene tags。
- 运行焦煤 JM 3 年日线研究回测，并输出 raw/trusted 指标和 v0.2/v0.3/v0.3.1 对比。

## 允许修改范围

- `tasks/current.md`
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_trend_cross_score2/`
- `services/quant-api/app/backtest/v1b_jm_tasks.py`
- `services/quant-api/app/api/backtests.py`
- `services/quant-api/app/vnpy_integration/result_converter.py`
- `services/quant-api/app/backtest/service.py`
- `services/quant-api/tests/test_su_bing_jm_daily_trend_cross_score2.py`
- `services/quant-api/tests/test_su_bing_jm_daily_score2of4.py`
- `services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`
- `services/quant-api/tests/test_vnpy_integration.py`
- `services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py`
- `services/quant-api/tests/test_su_bing_report_10_review_export.py`
- `scripts/export_su_bing_daily_trend_cross_score2_package.py`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`
- `backtests/reports/su_bing_daily_trend_cross_score2/`
- `apps/quant-web/src/types/backtest.ts`
- `apps/quant-web/src/pages/backtest/index.vue`
- `apps/quant-web/src/pages/market/index.vue`

## 禁止修改范围

- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/` 的 v0.2.0 策略行为与默认参数。
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_score2of4/` 的 v0.3.0 策略行为与默认参数。
- 数据库结构 / migration。
- 实盘 / 模拟盘 / CTP / TqSdk 交易接口。
- `.env`、账号、密码、API Key、Token、license。
- 真实数据目录 `data/raw/`、`data/parquet/`、`data/processed/`。
- vn.py 源码。
- 多品种参数优化。

## 执行模式

- 总控计划已确认，当前执行实现。
- 按 TDD 执行策略和后端关键行为。
- 低风险步骤自动继续。
- 触发 Gate 必须暂停。

## 任务步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 测试命令 | 测试结果 | 风险记录 |
|---|---|---|---|---|---|---|---|
| 0 | completed | low | 分支初始化与任务记录 | `tasks/current.md` | `git status --short`; `git branch --show-current` | 分支 `codex/su-bing-daily-trend-cross-score2` | 从 `main` 创建功能分支后执行 |
| 1 | completed | medium | v0.3.1 策略测试先行 | 新测试文件 | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_trend_cross_score2.py` | 先红：策略包缺失；后绿：5 passed | 必须先红后绿 |
| 2 | completed | medium | 独立策略包实现 | 新策略包 | 同 Step 1 | 5 passed | 不改 v0.2/v0.3 |
| 3 | completed | medium | 后端 task builder/API 接入 | backtest API/tests | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py` | 先红：builder/route 缺失；后绿：17 passed | 新增 v0.3.1 固定任务 |
| 4 | completed | medium | 报告导出与 trusted 分析 | export script/docs/reports/tests | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py` | 先红：导出脚本缺失；后绿：10 passed | trusted 结论排除 cross-contract PnL |
| 5 | completed | medium | Web 轻量展示 | Web types/pages | `cd apps/quant-web && pnpm build` | passed；浏览器烟测 passed | 不做前端核心策略计算 |
| 6 | completed | medium | 3 年 JM 日线回测 | DB task/run/export | inline `BacktestTaskRunner` + export script | report 13 success；raw -3401.457；trusted -20632.125 | raw 只审计，trusted 才用于判断 |
| 7 | completed | low | 最终验证与交接 | tests/docs | 全量指定测试 + ruff + build | 63 pytest passed；ruff passed；pnpm build passed | Playwright CLI 阻塞，改用 Node Playwright system Chrome 烟测通过 |

## Gates

| Gate | 触发条件 | 暂停时必须报告 |
|---|---|---|
| Gate 0 | 仍在 `main` 且准备改文件 | 当前分支、工作区状态、建议分支 |
| Gate 1 | 工作区出现非本轮未提交改动 | 改动文件、是否相关、继续风险 |
| Gate 2 | 需要 migration、实盘/模拟盘接口、凭据读取或真实数据目录写入 | 触发原因、拟修改文件、风险和确认问题 |
| Gate 3 | 跨合约 PnL 被混入 trusted 结论 | 当前完成情况、受影响交易、后续方案 |
| Gate 4 | 测试、DB、vn.py、Redis/RQ、前端 build 或回测运行失败 | 失败命令、错误摘要、拟修文件或下一步 |

## 验收标准

- [x] `v0.2.0-daily` 默认参数和交易行为保持不变。
- [x] `v0.3.0-daily-score2of4` 默认参数和交易行为保持不变。
- [x] 新增 `v0.3.1-daily-trend-cross-score2` 独立策略包。
- [x] 默认开仓必须满足趋势方向环境和对应方向 MACD 交叉。
- [x] `min_entry_score`、`macd_zero_threshold`、`require_trend_alignment`、`require_macd_cross` 可追溯。
- [x] long/short 对称，冲突拒绝有测试覆盖。
- [x] 信号确认为当前日线 close，成交为下一日线 open。
- [x] 每笔交易输出 `entry_score`、`entry_grade`、`satisfied_conditions`、`failed_conditions`、`scene_tags` 和 `skill_notes`。
- [x] 新后端固定任务入口可创建 v0.3.1 回测任务。
- [x] v0.3.1 报告输出 raw metrics 和 trusted excluding cross-contract metrics。
- [x] Web 报告和行情页可展示/查看 score、conditions、scene tags。
- [x] 不做 migration、实盘/模拟盘、vn.py 源码修改。

## 测试命令

```bash
git status --short
git branch --show-current
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_trend_cross_score2.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_score2of4.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_vnpy_integration.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```

## 浏览器验收

- 页面：`http://127.0.0.1:5173/backtest?report_id=<new_report_id>` 和 linked `/market`。
- 操作路径：打开报告、查看交易明细、查看 K线、创建/打开复盘 note。
- 需要观察：score/conditions/tags 展示，K线 marker 对齐，console 无相关错误。

## 完成后输出要求

```markdown
## 总控目标
## 当前分支与 git 状态
## 阶段 0：计划与边界确认
## 阶段 1：v0.3.1 规则设计
## 阶段 2：v0.3.1 实现
## 阶段 3：测试结果
## 阶段 4：3 年 JM 日线回测
## 阶段 5：报告分析
## 阶段 6：Web 验收
## 新增/修改文件
## v0.2.0 / v0.3.0 是否保持不变
## v0.3.1 规则摘要
## raw metrics
## trusted excluding cross-contract metrics
## v0.2.0 vs v0.3.0 vs v0.3.1 对比
## score / condition / tag 分布结论
## 是否建议进入 v0.3.2
## 风险与后续 TODO
```

## 下一步建议

阶段 1：RQData 权限与接口能力 PoC。

- 推荐执行模式：Plan 模式。
- 建议新 Codex 会话：是。
- 需要 checkpoint：是。
- 禁止写入 `data/` 和数据库，除非下一轮 Prompt 明确允许。
- 目标：只读确认 RQData 本地环境、权限、可用接口、合约/分钟数据/交易参数字段能力，并输出后续数据链路任务设计。
