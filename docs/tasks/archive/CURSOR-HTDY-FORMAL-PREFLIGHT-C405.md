# CURSOR-HTDY-FORMAL-PREFLIGHT-C405

更新时间：2026-07-19

对应手册任务：`C4-05`（原 `D4-05`）

## 结论

状态：`COMPLETED / CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED`

生成 HTDY strict 正式报告前只读证据包：九项定向复验通过、golden 窗口 dry-run 摘要落盘、申请包草案与 report14 隔离回归说明齐备。未写 PostgreSQL、未创建 `BacktestReport`、未生成最终 `packet_hash`、未改策略算法、未做 Review/Web scaffold。

不得宣称 `HTDY_STRICT_READY_FOR_FORMAL_BACKTEST` / Stage 5 Ready。D4-00 Gate 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。

## 产物

| 路径 | 作用 |
|---|---|
| `data/reports/indicator_contract_v1/htdy_formal_preflight.md` | 九项复验矩阵 + 边界声明 + dry-run 摘要 |
| `data/reports/indicator_contract_v1/htdy_formal_apply_packet_draft.json` | 申请包草案（无 packet_hash） |
| `data/reports/indicator_contract_v1/htdy_report14_regression.md` | report14 隔离与回归命令 |

## 验证

```bash
git rev-parse HEAD
# 994799c4998087bee41dc9b2b21f059357bad8dc

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_strict_core.py \
  services/quant-api/tests/test_tdx_xma_indicator_risk.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_backtest_profile_contract.py
```

结果（2026-07-19）：**57 passed**。

Dry-run（显式 source + golden 窗口，输出 `/tmp`）：

```bash
uv run --project services/quant-api python \
  experiments/htdy_indicator/formal_backtest_candidate.py \
  --source data/parquet/canonical/bars/provider=rqdata/period=15m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_15m_20230103_20260710_v2.parquet \
  --start 2026-06-24T22:30:00 \
  --end 2026-07-09T23:00:00 \
  --output-json /tmp/htdy_formal_candidate_dry_run.json \
  --output-markdown /tmp/htdy_formal_candidate_dry_run.md
```

摘要：256 bars；trades=13；orders=26；`would_write_db=false`；`report_id_14_touched=false`。

说明：未设 `GUIYI_DATA_ROOT` 时默认路径解析 fail-closed；本轮用仓库内已存在的 lineage 文件显式 `--source`，未切换降级数据源。

## 边界

- 无 Alembic / 无 canonical DB 写入 / 无正式报告
- 无最终 `packet_hash`
- 不重开 D4-00 公式审计
- 不改 report14 配置或资产
- 不做 Review/Web scaffold（按手册 C4-05 条目范围）

## 下一入口

手册 `C5-01`（策略验证协议和冻结配置）。`CODEX_TASKS.md` 中 C4-05 起提到的 Review/Web scaffold 若仍需，应另开 Cursor 任务，不并入本证据包。
