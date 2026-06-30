# Current Task

## Task ID

`20260629-su-bing-daily-v03-control`

## 任务名称

苏冰 JM 日线 EMA21/MACD/量能策略可信度修复、规则对齐、消融计划与 v0.3 设计。

## 背景

本轮围绕 `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily` 与 `report_id=10` 做 V1 研究闭环内的策略优化总控。`report_id=10` 只作为可信度修复、规则对齐和逐笔复盘输入，不作为参数优化目标。

## 本轮目标

- 修复低风险回测可信度字段，补齐 report 10 复盘材料，输出 rollover 审查、苏冰规则对齐、逐笔分类、条件消融计划和 v0.3 设计。
- 不静默改变 `v0.2.0-daily` 交易规则。
- 不接入自动下单、模拟盘下单或实盘逻辑。

## 允许修改范围

- `tasks/current.md`
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/`
- `services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`
- `services/quant-api/tests/test_su_bing_report_10_review_export.py`
- `scripts/export_su_bing_report_10_review_package.py`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`
- `backtests/reports/report_10_su_bing_daily_trade_review.md`
- `backtests/reports/report_10_su_bing_daily_trade_review.csv`

## 禁止修改范围

- 数据库结构 / migration：禁止，除非先暂停并输出 migration plan。
- Web：禁止。
- 实盘 / 模拟盘 / CTP / TqSdk 交易接口：禁止。
- `.env`、账号、密码、API Key、Token、license：禁止读取、写入或提交。
- 真实数据目录 `data/raw/`、`data/parquet/`、`data/processed/`：禁止写入。
- vn.py 源码：禁止。
- `v0.2.0-daily` 入场、出场、MACD 阈值、成交量规则：阶段 1-6 禁止修改。

## 执行模式

- 推荐模式：总控计划后直接执行低风险阶段。
- 原因：涉及策略、回测、报告和风控可信度，必须按阶段和 Gate 推进。
- 是否允许低风险步骤自动继续：是。
- 遇到 Gate 是否必须暂停：是。

## 任务步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 测试命令 | 测试结果 | 风险记录 |
|---|---|---|---|---|---|---|---|
| 0 | done | low | 总控计划与分支初始化 | `tasks/current.md` | `git status --short`; `git branch --show-current` | 当前分支 `feature/su-bing-daily-v03-control` | 从 `main` 创建功能分支后执行 |
| 1 | done | low | 修复 holding_bars 与 trade duration 导出 | 策略包、导出脚本、相关测试、report 10 导出 | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`; `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py`; export script | `7 passed`; `4 passed`; report 10 导出成功 | 未改入场、出场、MACD、成交量或收益规则；旧 report 持久化值仍记录为 0 |
| 2 | done | medium | report 10 rollover 审查 | `docs/strategy_specs/.../REPORT_10_ROLLOVER_AUDIT.md` | 文档审查 | 已输出 SB-JM-D-3 `untrusted_cross_contract_pnl` | P0 保持打开，不实现 rollover-safe 到 v0.2 baseline |
| 3 | done | low | 苏冰规则提取与对齐 | `docs/strategy_specs/.../SU_BING_SKILL_RULES_EXTRACT.md`; `SKILL_ALIGNMENT_REVIEW.md` | 文档审查 | 已输出规则候选和 match_status | 不复制课程原文，不编造阈值 |
| 4 | done | low | report 10 逐笔分类与 baseline findings | `REPORT_10_SKILL_TRADE_CLASSIFICATION.md`; `V0_2_BASELINE_FINDINGS.md` | 文档审查 | 7 笔交易已分类 | 7 笔样本只做复盘归因 |
| 5 | done | low | 条件消融计划 | `CONDITION_ABLATION_PLAN.md` | 文档审查 | 已输出计划 | P0 未解除前不做收益消融结论 |
| 6 | done | medium | v0.3 日线策略设计 | `V0_3_DAILY_STRATEGY_DESIGN.md` | 文档审查 | 已输出设计 | 仅设计，不默认实现 |
| 7 | blocked | high | v0.3 实现条件判断 | 待确认 | 待确认 | 未执行实现 | SB-JM-D-3 跨合约 PnL 仍不可信，缺少日线 rollover-safe 新版本或排除后新报告 |
| 8 | done | low | report 10 cross-contract exclusion 可信报告 | 导出脚本、相关测试、策略 spec 文档、trusted CSV | `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py`; `uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`; `uv run --project services/quant-api pytest -q services/quant-api/tests/test_vnpy_integration.py`; `uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py`; `uv run --project services/quant-api ruff check .` | `6 passed`; `7 passed`; `14 passed`; `13 passed`; `All checks passed!` | 不改 v0.2.0-daily 策略行为；只生成 trade-level trusted metrics；forced rollover-safe 仍需正式合约级日线数据标准化 |

## Gates

| Gate | 触发条件 | 暂停时必须报告 |
|---|---|---|
| Gate 0 | 仍在 `main` 且准备改文件 | 当前分支、工作区状态、建议分支 |
| Gate 1 | 工作区出现非本轮未提交改动 | 改动文件、是否相关、继续风险 |
| Gate 2 | 需要 migration、Web 改动、实盘/模拟盘接口、凭据读取或真实数据目录写入 | 触发原因、拟修改文件、风险和确认问题 |
| Gate 3 | 主连跨合约 PnL 不可信且无 rollover-safe 处理 | 当前完成情况、受影响交易、后续方案 |
| Gate 4 | 测试失败 | 失败命令、错误摘要、拟修文件 |

## 验收标准

- [x] `holding_bars` 不再在 report 10 导出中全部为 0。
- [x] `v0.2.0-daily` 入场、出场、MACD、成交量规则未改变。
- [x] 输出 `REPORT_10_ROLLOVER_AUDIT.md`。
- [x] 输出 `SU_BING_SKILL_RULES_EXTRACT.md` 或明确无可用原文，并输出 `SKILL_ALIGNMENT_REVIEW.md`。
- [x] 输出 7 笔交易分类和 `V0_2_BASELINE_FINDINGS.md`。
- [x] 输出 `CONDITION_ABLATION_PLAN.md`。
- [x] 输出 `V0_3_DAILY_STRATEGY_DESIGN.md`。
- [x] 若 v0.3 条件不满足，明确阻塞项，不实现。
- [x] 输出 report 10 排除跨合约交易后的 trusted metrics。
- [x] 明确 forced rollover-safe 因正式合约级日线数据未标准化而阻塞。

## 测试命令

```bash
git status --short
git branch --show-current
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_vnpy_integration.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py
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
## 本轮目标
## 修改摘要
## 变更文件
## 运行方式
## 测试命令
## 测试结果
## 验收标准对照
## 风险与后续 TODO
```
