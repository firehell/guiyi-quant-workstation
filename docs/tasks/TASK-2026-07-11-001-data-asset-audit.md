# TASK-2026-07-11-001：Stage 8.6 Active Gate 只读快照

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-001-data-asset-audit |
| GitHub Issue | #9 |
| Branch | codex/data-asset-audit |
| Worktree | /Volumes/扩展盘/guiyi-parallel/data-audit |
| Status | DELIVERY_READY_WITH_CLI_ENV_NOTE |
| Baseline | main @ f29de0dd |

## 1. 任务状态

DELIVERY_READY_WITH_CLI_ENV_NOTE

## 2. 任务类型

数据质量检查 / 只读审计

## 3. 参与角色

- 必须：数据工程师、测试专家、安全专家
- 不需要：前端、策略开发

## 4. 背景

Stage 8.6 全品种 Active Gate 已有 82 passed / 8 active partial（8 个 audit_pending asset）。JM 六周期 6/6 passed 与 `report_id=14` 是 V1-B 可信基线。本任务产出的是现有 Stage 8.6 active 资产只读快照，是全量历史数据资产盘点的第一阶段基线，**不代表目标年份、目标周期和参考元数据覆盖已经完成**。

本轮不做写入修复，不修 8 个 pending，不把 `1326` 资产数解释为完整覆盖率。

## 5. 目标

1. 重跑 `stage8_6_1d_first` 与 JM 六周期 profile，输出到独立目录 `data/reports/data_audit_20260711/`。
2. 产出人类可读盘点 Markdown：8 pending 逐项根因、修复路径、是否阻塞 JM V1-B、Stage 9 阻塞说明。
3. 汇总 manifest / processed summary / DB 登记 / canonical parquet 分层一致性。
4. 明确 `1326 active_passed` 是 manifest-level discovered active records，不是全量目标资产覆盖结论。

## 6. 不做事项

- 不写 DB、Parquet、RQData
- 不修复 8 pending（另开受控写入任务）
- 不修改 services 业务逻辑
- 不碰 `.env`、不自动 push/merge/deploy
- 不启动 live runtime、企业微信、信号扫描

## 7. 涉及模块

**允许修改**：

- `docs/tasks/TASK-2026-07-11-001-data-asset-audit.md`
- `tasks/current.md`
- `data/reports/data_audit_20260711/`
- `docs/gpt/CURRENT_STATE.md`（仅盘点结论段落）
- `.ai/results/TASK-2026-07-11-001-data-asset-audit/`

**禁止修改**：

- `services/` 业务逻辑
- `data/raw/`、`data/processed/` 写入
- `Alembic/`、`.env`
- `apps/`、`packages/` 策略与回测

## 8. 产品需求

- 盘点报告可让非开发人员理解 8 pending 含义与下一步
- 明确 JM V1-B 不受 8 pending 阻塞

## 9. 量化业务规则

- active 数据口径：`provider in (rqdata, local_parquet)`、`data_role=primary`、`quality_status!=failed`
- Stage 9 企业微信：90 blocked，本任务不授权发送

## 10. 数据影响

- 只读审计；默认 dry-run
- 输出 CSV/MD 到 `data/reports/data_audit_20260711/`

## 11. 技术方案

1. 运行 `scripts/rqdata_full_universe_active_gate_audit.py --profile stage8_6_1d_first`
2. 运行 JM profile：`--profile jm_main_six_period_latest`（或等效参数）
3. 可选：`scripts/rqdata_audit.py`、`scripts/rqdata_coverage_audit.py` 补充 manifest 统计
4. 编写 `data/reports/data_audit_20260711/DATA_ASSET_INVENTORY.md`

## 12. 交互视觉要求

无 Web 变更

## 13. 安全权限要求

- 不读取/写入 `.env`、RQData 凭据
- 不删除 `data/raw/` 任何文件

## 14. 开发步骤

1. Plan：只读分析现有报告与脚本
2. 重跑审计 CLI，输出到独立目录
3. 编写盘点 Markdown
4. 更新 `tasks/current.md` 本线状态

## 15. Codex Plan Prompt

```
只读 Plan。必读 AGENTS.md、docs/STAGE8_6_ACTIVE_GATE_AUDIT.md、docs/DATA_CENTER.md、docs/CODEX_HANDOFF.md。
任务：全量历史数据资产只读盘点。不得修改 services/ 或写入 data/processed/。
输出：实施步骤、报告结构、8 pending 逐项分析框架、风险与 Gate。
```

## 16. Codex Dev Prompt

```
按已批准 Plan 执行。仅修改 §7 允许路径。
重跑 stage8_6 审计到 data/reports/data_audit_20260711/，编写 DATA_ASSET_INVENTORY.md。
禁止写 DB/Parquet/RQData，禁止改 services 业务逻辑。
```

## 17. CodeBuddy 执行 Prompt

```
worktree: /Volumes/扩展盘/guiyi-parallel/data-audit
branch: codex/data-asset-audit
先 codex_plan.sh --task TASK-2026-07-11-001-data-asset-audit，用户 APPROVE 后 codex_dev.sh。
不 push/merge/deploy。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
uv run --project services/quant-api python scripts/rqdata_full_universe_active_gate_audit.py --products-file data/universe/full_products_90.txt --profile stage8_6_1d_first --output-dir data/reports/data_audit_20260711
uv run --project services/quant-api python scripts/rqdata_full_universe_active_gate_audit.py --product jm --profile jm_main_six_period_latest --output-dir data/reports/data_audit_20260711/jm_main_six_period_latest
uv run --project services/quant-api pytest services/quant-api/tests/test_full_universe_active_gate.py -q
git diff --check
```

- [x] stage8_6 direct CLI 已尝试；本 worktree 无 `.env` / `DATABASE_URL`，PostgreSQL 默认无密码连接失败
- [x] 输出目录含 matrix/summary CSV/MD；DB metadata 使用本机已运行 API readonly snapshot fallback
- [x] DATA_ASSET_INVENTORY.md 含 8 pending 逐项
- [x] JM 六周期 profile 输出到独立子目录

## 19. 验收标准

- `data/reports/data_audit_20260711/` 存在且可复现
- 8 pending 品种与 asset 类型与 `docs/DATA_CENTER.md` 一致
- 未修改 services/ 与 data/processed/
- JM 六周期仍标注 6/6 passed

## 20. 风险点

- 误将 audit 脚本当修复工具写入 DB
- 覆盖既有 `data/reports/stage8_6_*`（必须用独立子目录）

## 21. 交付记录

- 状态流转：REQUIREMENT_READY → PLAN_READY → APPROVED_DEV → DELIVERY_READY_WITH_CLI_ENV_NOTE
- 合并目标：main（在 web-indicators 之后、htdy 之前）

### 21.1 2026-07-11 Codex 交付记录

执行摘要：

- 按计划先运行 direct CLI，但当前 `data-audit` worktree 根目录无 `.env` / `DATABASE_URL`，默认连接 `127.0.0.1:5432` 报 `fe_sendauth: no password supplied`。
- 未读取 `.env`，未提取或打印 DB/RQData/Webhook 凭据。
- 使用本机已运行 API 的 readonly data-center endpoints 获取 DB metadata snapshot：
  - `/api/v1/data/coverage`
  - `/api/v1/data/quality-reports`
- manifest 与 canonical parquet 继续按当前 worktree 文件和 DuckDB 读取核对。
- 本任务仅可验收为 `Stage 8.6 Active Gate 只读快照完成`，不能验收为 `全量历史数据资产盘点完成`。

当前 snapshot 结论：

- 全品种产品层：82 `active_passed` / 8 `active_partial`。
- 当前 manifest-level discovered active records：1326 `active_passed` / 8 `audit_pending`。
- JM 最新主连六周期：6/6 `active_passed`。
- Stage 9：90 `stage9_blocked`；本任务不授权企业微信发送。

1326 口径：

- 当前矩阵共 1334 行，唯一键限定为 `product + asset_scope + contract + period + standard_path`。
- `actual_contract` 1244 行，其中 1241 passed / 3 pending。
- `dominant_main` 90 行，其中 85 passed / 5 pending。
- 当前 snapshot 全部为 `1d`，不是多周期全量覆盖。
- provider 从路径推断均为 `rqdata`。
- DuckDB row count 和 datetime boundary 已核对；checksum 未在本报告中逐文件独立证明。
- 1326 passed 记录均有 DB 登记；3 个 pending 缺 `market_data_files`；5 个 pending 是 quality warning。

新增产物：

- `data/reports/data_audit_20260711/DATA_ASSET_INVENTORY.md`
- `data/reports/data_audit_20260711/stage8_6_active_gate_matrix.csv`
- `data/reports/data_audit_20260711/stage8_6_product_summary.csv`
- `data/reports/data_audit_20260711/stage8_6_stage9_readiness.csv`
- `data/reports/data_audit_20260711/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `.ai/results/TASK-2026-07-11-001-data-asset-audit/RESULT.md`

### 21.2 下一阶段建议

合并本分支后，从最新 `main` 新开 `codex/data-target-coverage-audit`，先进入 Plan 模式设计完整目标覆盖矩阵。

预期只读输出：

- `target_asset_catalog.csv`
- `asset_physical_inventory.csv`
- `target_coverage_matrix.csv`
- `metadata_consistency_matrix.csv`
- `issue_register.csv`
- `coverage_summary.md`

下一阶段矩阵粒度为：

```text
product × contract_role × symbol/contract × period × year × status
```

覆盖范围：90 个目标产品、2020+ 主连 `1d/1w`、2023+ 主连 `1m`、2023+ 派生 `5m/15m/30m/60m/1d`、历史真实主力合约资产、`MainContractMap`、交易日历、交易时段、合约参数、manifest/checksum/DB/physical 四层一致性。
