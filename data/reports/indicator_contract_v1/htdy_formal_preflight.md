# HTDY Strict Formal Preflight（C4-05）

生成时间：2026-07-19T03:09:57Z
任务：`CURSOR-HTDY-FORMAL-PREFLIGHT-C405`（手册 `C4-05` / 原 `D4-05`）
状态：`CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED`

`source_commit`：`994799c4998087bee41dc9b2b21f059357bad8dc`
分支：`cursor/v1-indicator-strategy-prep`

## 1. 边界声明

本证据包是 **只读 preflight**，用途是复验 HTDY strict formal candidate 进入正式报告写入前的契约与回归面。

**本包不构成正式报告资格。** 不得据此宣称：

- `HTDY_STRICT_READY_FOR_FORMAL_BACKTEST`
- `HTDY_XMA_SEMANTICS_AUDITED`
- Stage 5 Ready / Codex Ready Gate
- 可直接创建 `BacktestReport`

后续若写入独立报告：必须用户单独批准 → Codex Wave 执行 → 立刻 trust audit；且 **禁止** 复用/覆盖/修复/删除 `report_id=14`。

本轮未写 PostgreSQL、未创建 BacktestTask/BacktestReport、未生成最终 `packet_hash`、未改策略数值算法、未触碰 live / scanner / 企业微信。

## 2. D4-00 只读引用（不重开审计）

| 产物 | 路径 |
|---|---|
| XMA 语义 | `data/reports/indicator_contract_v1/htdy_xma_semantics.md` |
| original vs strict | `data/reports/indicator_contract_v1/htdy_original_vs_strict_diff.md` |
| 公式映射 | `data/reports/indicator_contract_v1/htdy_source_formula_map.csv` |

诚实 Gate（保持不变）：

```text
HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED
```

已确认可复用结论：

- 通达信 `XMA` 为未来函数；original/Web 会重绘。
- strict 使用 double trailing EMA 因果改写；有 future-tail / prefix-batch 回归。
- XMA(6) / VAR23 内层 oracle 与部分 provenance 仍未关闭 → 不得解除 unresolved Gate。

## 3. 定向复验矩阵

命令（2026-07-19，无 canonical DB 写入）：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_strict_core.py \
  services/quant-api/tests/test_tdx_xma_indicator_risk.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_backtest_profile_contract.py
```

结果：**57 passed**（1.88s）

| # | 复验项 | 结果 | 主要证据 |
|---|---|---|---|
| 1 | future-tail perturbation | PASS | `test_htdy_strict_future_tail_does_not_repaint_history`；`test_strict_candidate_future_tail_does_not_repaint_prior_outputs` |
| 2 | no centered XMA | PASS | `test_tdx_xma_indicator_risk` 证明 centered/XMA 会读未来并重绘；strict 路径不走该实现 |
| 3 | historical confirmed values 不随未来尾部变化 | PASS | strict core future-tail + append/batch 一致性 |
| 4 | 当前 bar 收盘确认 | PASS | `confirmed_only=true`；formal candidate signal-on-close 断言 |
| 5 | 最早 next bar open fill | PASS | `test_entry_signal_fills_next_bar_open_with_slippage`；`fill_policy=signal_on_close_fill_next_bar_open` |
| 6 | strict policy snapshot 可序列化 | PASS | `test_htdy_strict_snapshot_binds_strict_v1_and_rejects_original`；本轮生成 snapshot 见申请包草案 |
| 7 | BacktestService 可消费 normalized payload | PASS | `test_normalized_result_can_be_persisted_and_passes_trust_audit`（内存库；`would_write_db=false`） |
| 8 | 不接受客户端任意本地 path | PASS | `test_formal_request_forbids_client_paths_and_quality_metadata` 等 profile contract 用例 |
| 9 | report 14 完全隔离 | PASS | 见 `htdy_report14_regression.md`；dry-run `report_id_14_touched=false` |

补充规则回归（同套件内，已 PASS）：stop/TP 同 bar 优先级、time exit bar 8、conflict skip、reverse 不平反、missing cost fail-closed。

## 4. 只读 dry-run 摘要

默认无 `GUIYI_DATA_ROOT` 时，CLI 解析候选路径失败（fail-closed，未切换降级源）。
本轮显式指向仓库内已存在的 golden lineage 文件，并限制为 golden sample 窗口（避免全窗口超时）：

```bash
uv run --project services/quant-api python \
  experiments/htdy_indicator/formal_backtest_candidate.py \
  --source data/parquet/canonical/bars/provider=rqdata/period=15m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_15m_20230103_20260710_v2.parquet \
  --start 2026-06-24T22:30:00 \
  --end 2026-07-09T23:00:00 \
  --output-json /tmp/htdy_formal_candidate_dry_run.json \
  --output-markdown /tmp/htdy_formal_candidate_dry_run.md
```

| 字段 | 值 |
|---|---|
| window | `2026-06-24T22:30:00` → `2026-07-09T23:00:00` |
| row_count | 256 |
| source_file_sha256 | `7161c515379db31f46cf115cc1cbeb7f487ce774ff8c1ab5d86a77af727bc70c` |
| input_sha256 | `8d9a63c328288b75d0e493b0ba71d1e5d36b8563df57226bdef147e02dba863c` |
| lineage | rqdata / primary / passed / jm / jm.MAIN / 15m |
| trade_count | 13 |
| order_count | 26 |
| execution_event_count | 26 |
| `would_write_db` | false |
| `would_create_backtest_report` | false |
| `report_id_14_touched` | false |
| `requires_user_confirmation_before_report_write` | true |

`/tmp` 产物仅作本机临时证据，未写入 canonical DB，未归档为正式报告。

## 5. Profile / Policy / Cost 绑定摘要

| 字段 | 值 |
|---|---|
| profile_id（草案） | `intraday_research_v1` |
| strategy_code | `huotian_dayou_strict` |
| strategy_version | `v0.1.0-backtest-candidate` |
| formal_policy_ids | `huotian_dayou_strict_v1` |
| confirmed_only | true |
| execution_timing | `next_bar_open` |
| cost_model_version | `cost_model_v1_rate_slippage_size` |
| parameter_hash | `84d80219d2a27d115dfdd36fe7bdf0ea41530e2fc9f2a188ec48bf9db37c2eb8` |

完整申请包草案见：`htdy_formal_apply_packet_draft.json`（**无** `packet_hash`）。

## 6. 相关规格与实现锚点

- `docs/strategy_specs/htdy/STRICT_V1_SPEC.md`
- `docs/strategy_specs/htdy/FORMAL_BACKTEST_CANDIDATE_PLAN.md`
- `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/`
- `packages/quant-core/guiyi_quant/strategies/indicator_policy.py`
- `experiments/htdy_indicator/formal_backtest_candidate.py`
- C4-02 Registry / C4-04 policy：`docs/tasks/CURSOR-STRATEGY-INDICATOR-POLICY-C404.md`

## 7. 结论

```text
CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED
```

九项定向复验通过；golden 窗口只读 dry-run 可产出 normalized payload 且声明不写 DB、不碰 report14。
**仍不是**正式报告准入；D4-00 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。
