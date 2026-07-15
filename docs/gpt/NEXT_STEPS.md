# NEXT_STEPS.md

更新时间：2026-07-14

## 总原则

- 数据可信度、可追溯和可复算优先于收益和功能扩展。
- 当前不做自动交易、实盘账户、SaaS、多用户或大型重构。
- live、scheduler、数据写入、schema 和公网部署必须分阶段 Gate。
- 文档和 GPT Sources 必须来自仓库事实源，不靠聊天复述。

## 当前状态

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

当前不能宣称全品种周线从上市以来完整，不能宣称长期 live runtime ready，不能宣称企业微信自动长期发送 ready。

## P0 后续任务

1. **manifest / DB 对齐专项 Plan**
   - 输入：`data/reports/data_layer_final_audit_phase3_20260712/metadata_consistency_matrix.csv`、`data/reports/data_stage_closure/manifest_db_consistency.csv`
   - 目标：解释或修复 `metadata_gap=1853`
   - 默认先 Plan；不得直接写 DB/manifest。

2. **pre-2020 周线 34 品种缺口专项 Plan**
   - 输入：`data/reports/data_layer_final_audit_phase3_20260712/weekly_history_audit.csv`
   - 目标：逐品种区分 RQData 下限、真实上市边界、应补数据和应标记 N/A
   - 不得直接重新下载全量数据。

3. **JM T3-real 单次 live 写入 Gate**
   - 输入：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
   - 条件：JM 可交易时段 + 用户显式确认
   - 只允许 live 表和 checkpoint 写入；不包含 signal event、archive、企业微信或交易执行。

4. **真实公网安全 smoke**
   - 输入：`deploy/nginx/README.md`、`deploy/frp/README.md`
   - 验证：TLS、Basic Auth、未认证 401、5432/6379/8000/5173 不直接公网开放、FRP/Nginx 重启恢复
   - 配置模板存在不等于远端验收通过。

## P1 后续任务

1. actual contract 缺口专项 Plan。
2. OOS / walk-forward 全窗口验证。
3. Web trust audit 专项展示。
4. 公共 chunk 拆包。
5. `research_only` schema/API 语义拆分。

## GPT 上传建议

最小集合：

- `project_sources/00-INDEX.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`

完整集合：

- `project_sources/*.md`
- `project_sources/modules/*.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`

专题补充集合：

- 数据：`docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md`
- 回测：`docs/STAGE13_BACKTEST_TRUST_AUDIT.md`、`docs/BACKTEST_ENGINE.md`
- 信号：`docs/SIGNAL_EVENTS.md`、`docs/STAGE9_WECHAT_DELIVERY.md`
- live：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- 工作站：`docs/workstation/`、`docs/workflows/`
