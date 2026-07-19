# Cursor → Codex 切换 Gate 审查结论

生成时间：2026-07-19T03:45:48Z  
审查基准：手册 §9「Cursor → Codex 切换 Gate」  
伴生机器可读：`data/reports/ai_handoff/cursor_to_codex_switch_gate_review.json`

## 总判

**满足切换条件，可以交给 Codex 做 X0-01。**

仅宣称：`CURSOR_TO_CODEX_SWITCH_GATE_PASSED` / 可进入 `CURSOR_WAVE_READY_FOR_CODEX_REVIEW` 后的 Codex Wave。

**不是**阶段 4 Ready，**不是** `HTDY_XMA_SEMANTICS_AUDITED`，**不是**任何正式 Codex Ready Gate。

## 冻结点

| 项 | 值 |
|---|---|
| branch | `cursor/v1-indicator-strategy-prep` |
| freeze_tip (Codex 接管点) | `b76791bf4bfa3ed0aaef048627ccca0bade1774d` |
| handoff_checkpoint | `5e1609b84a6936478ac7c52139073112168deff7` |
| 相对 handoff 额外 commit | `b76791bf` docs SHA backfill（无业务 diff） |
| working_tree | clean |
| vs origin | 0 ahead / 0 behind |

Codex 应从 **`b76791bf`** 建独立 worktree；复核范围 `origin/main...b76791bf`。

## 逐项对照

| Gate 条件 | 结论 | 证据 |
|---|---|---|
| D4-00 三项已有证据 | 通过（证据义） | 三份产物存在且 sha256 与 wave manifest 一致 |
| `CURSOR_WAVE_READY_FOR_CODEX_REVIEW` | 通过 | `tasks/current.md`、handoff、manifest、`docs/CODEX_HANDOFF.md` |
| `git diff --check` | 通过 | 本轮复验 exit 0 |
| Cursor 声明测试全部通过 | 通过（自报） | pytest 73 + report14 1 + frontend 16；本审查未重跑 |
| `forbidden_paths_touched = []` | 通过 | manifest 为空；`origin/main...HEAD` 无禁止路径命中 |
| no DB / Parquet / Profile / live writes | 通过（attestation） | wave manifest 五项 attestation=true |
| report14 regression | 通过（自报 + 资产未改） | 只读测试 pass；`jm_v1b_report14_frozen.json` 无变更 |
| handoff manifest 完整 | 通过 | Gate 表 / tests / hashes / forbidden / attestation / unresolved / Codex 首任务 |
| Cursor branch 已冻结 | 通过（轻度备注） | 干净工作区；handoff 后仅 docs SHA backfill |

## D4-00 证据 hash（本轮复算）

| 文件 | sha256 |
|---|---|
| `data/reports/indicator_contract_v1/htdy_xma_semantics.md` | `aebee9d39e2a094dfdf7bebd9da5595de50a81950515b4deeb7ff5f5ee65ba9f` |
| `data/reports/indicator_contract_v1/htdy_original_vs_strict_diff.md` | `8e816acbf235ea69e712277efbe1d26b517ef411fce920c8742f1d7429bfa842` |
| `data/reports/indicator_contract_v1/htdy_source_formula_map.csv` | `8f1d03e53eb2fec56ec03d7e51b212a9e7bbc25ae5df7ad488f90bcf8dfb9740` |
| `configs/oos/jm_v1b_report14_frozen.json` | `8f45991aae4c4db62dffd4f60e9fc3cf61abea0381b88b9cd44e938fda26f49a` |

## 必须看清（不算阻断）

1. D4-00「三项已有证据」≠ 三项 pass。仓库最终 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；禁止宣称 `HTDY_XMA_SEMANTICS_AUDITED`。
2. Cursor 测试结果为自报；Codex X0-01 必须独立复跑，不得直接采信。
3. 手册不要求 Cursor 自证：`INDICATOR_CONTRACT_READY` / `STRATEGY_VALIDATION_PROTOCOL_FROZEN` / `HTDY_STRICT_FORMAL_REPORT_READY`。

## Codex 下一入口

```text
X0-01 / CURSOR-WAVE-INDEPENDENT-REVIEW-X001
```

独立读 diff、复跑测试、检查边界，再决定：接受 / 修正后接受 / 阻断。
