# HTDY vs Report 14 隔离回归（C4-05）

生成时间：2026-07-19T03:09:57Z
任务：`CURSOR-HTDY-FORMAL-PREFLIGHT-C405`
`source_commit`：`994799c4998087bee41dc9b2b21f059357bad8dc`

## 1. 结论

```text
HTDY_PREFLIGHT_REPORT14_ISOLATION_HELD
```

本轮 HTDY strict formal preflight **未读取以写入、未复用、未覆盖、未修复、未删除** `report_id=14`。
JM V1-B report14 继续仅作为 Stage 13 历史可信基线；HTDY 若未来写入，只能新建独立 report。

本文件不宣称 HTDY 正式报告资格，也不重跑改写 report14 资产。

## 2. 本轮未触碰证据

| 检查 | 结果 |
|---|---|
| `configs/oos/jm_v1b_report14_frozen.json` | `git status` 无变更 |
| `configs/data_profiles/intraday_research_v1.json` 中 `report_14_reference` | 本轮未修改 |
| HTDY dry-run gate | `report_id_14_touched=false`；`would_write_db=false`；`would_create_backtest_report=false` |
| C4-04 读路径 | report14 风格无 snapshot → `legacy_policy_unavailable`，禁止用当前 Registry 臆造 policy |

冻结配置锚点：

- `configs/oos/jm_v1b_report14_frozen.json` → `baseline_report_id: 14`
- Profile 文档字段：`configs/data_profiles/intraday_research_v1.json` → `report_14_reference`

历史 MD5 对照（只读引用既有 Gate 证据，本轮不重算改写）：消费者最终 Gate 曾记录 report14 内容 MD5=`ae807ef77f7d9a4ce3067996558b57e8`（见 `data/reports/consumer_golden_query_final_gate_20260718_rerun/` 类证据）。C4-05 未打开或重写该报告行。

## 3. 定向回归命令

最小隔离回归：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py::test_report14_style_read_path_does_not_invent_registry_policy \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py::test_normalized_result_can_be_persisted_and_passes_trust_audit
```

本轮已包含在完整定向套件中：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_backtest_profile_contract.py
```

结果（整套 C4-05 定向）：**57 passed**。

工作区冻结配置抽查：

```bash
git status --short -- \
  configs/oos/jm_v1b_report14_frozen.json \
  configs/data_profiles/intraday_research_v1.json
```

期望：无输出（本轮干净）。

可选（未来正式写入 HTDY 报告后，仍不应用于改 report14）：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_backtest_trust_audit.py
uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id <NEW_HTDY_REPORT_ID>
```

## 4. 隔离语义

| 对象 | HTDY C4-05 / 未来写入 | report_id=14 |
|---|---|---|
| 角色 | strict formal candidate / 独立新报告 | JM V1-B 历史可信基线 |
| policy | 强制 `huotian_dayou_strict_v1` snapshot | 无 snapshot → legacy unavailable |
| Profile | 草案绑定 `intraday_research_v1` | 同 Profile 族内只读参考，不作 HTDY 写入目标 |
| 本轮动作 | 只读 pytest + /tmp dry-run | 零写入 |

## 5. 风险与后续

- 若 Codex Wave 获批写 HTDY 报告，必须新建 report id；写入后立刻 trust audit。
- 任何触及 report14 行或 `jm_v1b_report14_frozen.json` 的变更都属于范围外，应单独 Gate。
- D4-00 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` 与 report14 隔离相互独立：解除前者不得隐含修改后者。
