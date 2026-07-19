# Cursor Wave 统一交接包

生成时间：2026-07-19  
状态目标（仅此）：`CURSOR_WAVE_READY_FOR_CODEX_REVIEW`

**不是**阶段 4 Ready，**不是**任何正式 Codex Gate，**不是** `INDICATOR_REGISTRY_V1_READY` / `STRATEGY_REVIEW_CLOSED_LOOP_READY` / `JM_LIVE_ARCHIVE_OBSERVATION_READY` / `HTDY_STRICT_READY_FOR_FORMAL_BACKTEST`。

机器可读伴生文件：[cursor_wave_manifest.json](./cursor_wave_manifest.json)

---

## 1. Wave 结论

Cursor Wave（C0-01 → C6-07A）已按手册完成契约/盘点/低风险预构建；定向测试与禁止范围审计通过；本包为 Cursor → Codex 单次交接入口。

Codex **首任务锁定**：手册 **X0-01**（`CURSOR-WAVE-INDEPENDENT-REVIEW-X001`）——独立复核，不得信任 Cursor 自报。

---

## 2. 分支 / commits / 相对 main 范围

| 项 | 值 |
|---|---|
| branch | `cursor/v1-indicator-strategy-prep` |
| origin/main | `36185303f39fef8ba04693b6c55f1ff40cb4b2d9` |
| pre-handoff HEAD | `65c927198abd5f7c25398a26041b5960d7d38257` |
| checkpoint HEAD | `5e1609b84a6936478ac7c52139073112168deff7` |
| D4-00 source freeze | `fe05f5419fa28476d719baccb1b9406c76a286bf` |

相对 `origin/main...pre-handoff`：约 80 个文件（完整列表见 manifest `modified_files`）。  
本交接 commit 额外纳入本目录交接包与任务文档更新。

本地 checkpoint **不** push、**不** merge `main`。

---

## 3. 任务 Gate 表（全部 provisional）

| Task | 文档 | Cursor Gate（provisional） |
|---|---|---|
| C0-01 | `docs/tasks/CURSOR-CANONICAL-SYNC-C001.md` | `CURSOR_CANONICAL_SYNC_PREPARED` |
| C4-01 | `docs/tasks/CURSOR-INDICATOR-CALLER-INVENTORY-C401.md` | `CURSOR_INDICATOR_CALLERS_AUDITED` |
| C4-02 | `docs/tasks/CURSOR-INDICATOR-REGISTRY-C402.md` | `CURSOR_INDICATOR_REGISTRY_IMPLEMENTED` |
| C4-03 | `docs/tasks/CURSOR-FIRST-FORMAL-CALLER-C403.md` | `NO_FORMAL_INDICATOR_CALLER_MIGRATION_REQUIRED` |
| C4-04 | `docs/tasks/CURSOR-STRATEGY-INDICATOR-POLICY-C404.md` | `CURSOR_STRATEGY_INDICATOR_POLICY_IMPLEMENTED` |
| C4-05 | `docs/tasks/CURSOR-HTDY-FORMAL-PREFLIGHT-C405.md` | `CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED` |
| C5-01 | `docs/tasks/CURSOR-HTDY-VALIDATION-PROTOCOL-C501.md` | `CURSOR_VALIDATION_PROTOCOL_PREPARED` |
| C5-06A | `docs/tasks/CURSOR-REVIEW-FOUNDATION-C506A.md` | `CURSOR_REVIEW_FOUNDATION_PREPARED` |
| C6-07A | `docs/tasks/CURSOR-LIVE-ARCHIVE-OBSERVATION-FOUNDATION-C607A.md` | `CURSOR_RUNTIME_OBSERVATION_FOUNDATION_PREPARED` |
| C-HANDOFF | `docs/tasks/CURSOR-WAVE-HANDOFF-C999.md` | `CURSOR_WAVE_READY_FOR_CODEX_REVIEW` |

诚实保留：`HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`（D4-00 最终 Gate；证据确认 ≠ pass）。

---

## 4. 测试命令与结果

### 4.1 `git diff --check`

结果：pass（exit 0）

### 4.2 定向 pytest 全集

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_strict_core.py \
  services/quant-api/tests/test_tdx_xma_indicator_risk.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_backtest_profile_contract.py \
  services/quant-api/tests/test_htdy_validation_protocol_c501.py \
  services/quant-api/tests/test_review_foundation_c506a.py \
  services/quant-api/tests/test_market_runtime_foundation_c607a.py
```

结果：**73 passed** in 2.19s

### 4.3 report14 只读回归

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py::test_report14_style_read_path_does_not_invent_registry_policy
```

结果：**1 passed**；`configs/oos/jm_v1b_report14_frozen.json` 未被本 Wave 修改（sha256 见 manifest）。

### 4.4 前端定向测试

```bash
cd apps/quant-web && node --test \
  tests/reviewFoundation.test.ts \
  tests/reviewDeepLink.test.ts \
  tests/marketRuntimeObservation.test.ts
```

结果：**16 passed** / 0 failed（3 suites）

---

## 5. 禁止范围审计与 attestation

扫描相对 `origin/main` 变更文件关键字：`alembic/`、`migrations/`、`data/raw/`、canonical parquet 写入、`.env`、`profile_binding` 写路径、`launchd`、SignalEvent/企业微信发送、order submit。

**结论：`forbidden_paths_touched = []`，审计 PASS。**

### 允许说明（非违规）

C6-07A 修改 `services/quant-api/app/services/live_target_contracts.py`：只读 **path strip**（`historical_coverage.file_path=None` + `sanitize_live_targets_payload`）。属观察契约脱敏，**不是** live 启停、DB/T3 写入或下单。

### Attestation

| 项 | 值 |
|---|---|
| no DB write | true |
| no parquet write | true |
| no profile_binding write | true |
| no live write/start | true |
| no push / no merge | true（本交接仅本地 checkpoint） |

---

## 6. Hash 证据（摘要）

| 产物 | sha256（前 16） |
|---|---|
| `htdy_xma_semantics.md` | `aebee9d39e2a094d…` |
| `htdy_original_vs_strict_diff.md` | `8e816acbf235ea69…` |
| `htdy_source_formula_map.csv` | `8f1d03e53eb2fec5…` |
| `caller_inventory.csv` | `3ee695855827318e…` |
| `policy_matrix.csv` | `1abc608f532ef686…` |
| `jm_v1b_report14_frozen.json` | `8f45991aae4c4db6…` |
| `htdy_strict_validation_protocol_v1.json` | `f9ef6961cb3f08f2…` |

完整摘要见 `cursor_wave_manifest.json` 的 `d4_00_artifact_hashes` / `indicator_output_hashes`。

---

## 7. unresolved / provisional 清单

1. `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`（D4-00）
2. 全部 `CURSOR_*` Gate 均为 provisional，非正式 Codex Ready
3. C4-05 申请包草案无 `packet_hash`、无 BacktestReport
4. C5-01 `freeze_status=protocol_prepared_not_final_frozen`
5. C5-06A / C6-07A gap：未宣称 closed-loop / JM Live Archive Ready
6. C4-03 真迁移延期

---

## 8. Codex 首任务

```text
X0-01 / CURSOR-WAVE-INDEPENDENT-REVIEW-X001
```

要求：独立复核本交接包与分支 diff；不信任 Cursor 自报；不得把 provisional 写成正式阶段 Gate。

---

## 9. 明确边界

- **仅宣称**：`CURSOR_WAVE_READY_FOR_CODEX_REVIEW`
- **不宣称**：阶段 4 Ready / 正式指标 Registry Ready / 策略复盘闭环 Ready / JM Live Archive Ready / HTDY 正式回测资格
- **不做**：本包生成过程未写 DB/Parquet、未启 live、未调 RQData、未改 D4-00 审计结论、未 push/merge
