# TASK-2026-07-11-001：全量历史数据资产盘点（只读审计）

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-001-data-asset-audit |
| GitHub Issue | #9 |
| Branch | codex/data-asset-audit |
| Worktree | /Volumes/扩展盘/guiyi-parallel/data-audit |
| Status | REQUIREMENT_READY |
| Baseline | main @ f29de0dd |

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

数据质量检查 / 只读审计

## 3. 参与角色

- 必须：数据工程师、测试专家、安全专家
- 不需要：前端、策略开发

## 4. 背景

Stage 8.6 全品种 Active Gate 已有 82 passed / 8 active partial（8 个 audit_pending asset）。JM 六周期 6/6 passed 与 `report_id=14` 是 V1-B 可信基线。需要独立产出全量历史数据资产盘点报告，为 P1 pending 修复提供 checklist，**本轮不做写入修复**。

## 5. 目标

1. 重跑 `stage8_6_1d_first` 与 JM 六周期 profile，输出到独立目录 `data/reports/data_audit_20260711/`。
2. 产出人类可读盘点 Markdown：8 pending 逐项根因、修复路径、是否阻塞 JM V1-B、Stage 9 阻塞说明。
3. 汇总 manifest / processed summary / DB 登记 / canonical parquet 分层一致性。

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
uv run --project services/quant-api pytest services/quant-api/tests/test_full_universe_active_gate.py -q
git diff --check
```

- [ ] stage8_6 审计 CLI 成功
- [ ] 输出目录含 matrix/summary CSV/MD
- [ ] DATA_ASSET_INVENTORY.md 含 8 pending 逐项

## 19. 验收标准

- `data/reports/data_audit_20260711/` 存在且可复现
- 8 pending 品种与 asset 类型与 `docs/DATA_CENTER.md` 一致
- 未修改 services/ 与 data/processed/
- JM 六周期仍标注 6/6 passed

## 20. 风险点

- 误将 audit 脚本当修复工具写入 DB
- 覆盖既有 `data/reports/stage8_6_*`（必须用独立子目录）

## 21. 交付记录

- 状态流转：REQUIREMENT_READY → PLAN_READY → APPROVED_DEV → DELIVERY_READY
- 合并目标：main（在 web-indicators 之后、htdy 之前）
