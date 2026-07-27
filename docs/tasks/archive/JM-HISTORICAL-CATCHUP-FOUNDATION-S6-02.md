# JM-HISTORICAL-CATCHUP-FOUNDATION-S6-02

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | JM-HISTORICAL-CATCHUP-FOUNDATION-S6-02 |
| Work Level | L1 |
| GitHub Issue | 待创建（L1 可选） |
| Branch | feature/jm-historical-catchup-foundation-s6-02 |
| Worktree | /private/tmp/guiyi-s6-02 |
| Status | DELIVERY_READY |
| Required Env | 测试与 packet 生成均不需要真实凭据 |
| Required Mounts | 正式 packet 必须绑定 canonical data root；测试使用 tmp_path |
| Created At | 2026-07-20 |
| Owner | Codex |

## 0.1 机器可读元数据

```json
{
  "schema_version": 1,
  "task_id": "JM-HISTORICAL-CATCHUP-FOUNDATION-S6-02",
  "work_level": "L1",
  "github_issue": "待创建",
  "branch": "feature/jm-historical-catchup-foundation-s6-02",
  "worktree": "/private/tmp/guiyi-s6-02",
  "status": "DELIVERY_READY",
  "owner": "Codex",
  "allowed_paths": [
    "docs/tasks/JM-HISTORICAL-CATCHUP-FOUNDATION-S6-02.md",
    "docs/superpowers/plans/2026-07-20-jm-historical-catchup-foundation.md",
    "services/quant-api/app/services/rqdata_ingest/jm_historical_catchup.py",
    "services/quant-api/app/services/live_target_contracts.py",
    "services/quant-api/scripts/jm_historical_catchup.py",
    "services/quant-api/tests/test_jm_historical_catchup.py",
    "services/quant-api/tests/test_live_target_freshness.py"
  ],
  "forbidden_paths": [
    ".env",
    ".env.*",
    "data/raw/",
    "data/parquet/",
    "data/processed/",
    "data/manifests/",
    "data/reports/"
  ],
  "permissions": {
    "production_access_allowed": false,
    "database_write_allowed": false,
    "external_network_allowed": false,
    "push_allowed": false,
    "merge_allowed": false,
    "deploy_allowed": false,
    "trading_execution_allowed": false
  }
}
```

## 5. 目标

实现 JM-only 历史追平 foundation：动态最近完成交易日、provider finality、metadata/asset gap、versioned create-only 输出计划、hash-bound approval packet、live target freshness 和 apply 前 fail-closed 校验。本任务只实现代码、测试和 dry-run，不执行真实 RQData 或 canonical 写入。

## 6. 不做事项

- 不调用真实 RQData。
- 不写 canonical Parquet、manifest、PostgreSQL 或 Profile binding。
- 不写 live 表、SignalEvent、notification、策略、回测、报告、trade 或 order。
- 不修改其他品种，不开启 scheduler/live runtime，不发送企业微信。
- 不自动 push、merge、deploy 或 commit。

## 7. 涉及模块

允许修改仅限机器可读元数据中的 `allowed_paths`。禁止修改 `.env`、正式 `data/**`、数据库 migration、策略、回测和运行服务。

## 18. 测试清单

```bash
env PYTHONPATH=services/quant-api:packages/quant-core \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/test_jm_historical_catchup.py \
  services/quant-api/tests/test_live_target_freshness.py

env PYTHONPATH=services/quant-api:packages/quant-core \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/test_dominant_v2_incremental.py \
  services/quant-api/tests/test_profile_aware_incremental.py \
  services/quant-api/tests/test_actual_contract_bars_pilot.py \
  services/quant-api/tests/test_after_market_archive.py \
  services/quant-api/tests/test_live_runtime_scheduler.py \
  services/quant-api/tests/test_runtime_health.py

/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/ruff check \
  services/quant-api/app/services/rqdata_ingest/jm_historical_catchup.py \
  services/quant-api/app/services/live_target_contracts.py \
  services/quant-api/scripts/jm_historical_catchup.py \
  services/quant-api/tests/test_jm_historical_catchup.py \
  services/quant-api/tests/test_live_target_freshness.py

git diff --check
```

## 19. 验收标准

- 目标日由 DCE calendar、session close 和 provider finality 共同解析，缺一项即 blocked。
- packet 绑定 commit、worktree、output root、DB target、binding/metadata hash、目标日、请求范围、版本和回滚计划。
- 关键事实变化使 packet hash 或前置快照校验失败。
- gap planner 支持无缺口、单日、多日、完整周和换月分段。
- live target 对 mapping、参数和 actual `1m/5m/15m` 历史覆盖执行 required-date freshness。
- 所有输出路径 create-only；warning/failed 不允许进入 binding plan。
- dry-run 不创建 RQData client、不打开写事务、不写文件。

## 20. 风险点

- TradingCalendar 当前只到 2026-07-10；正式 packet 前必须通过 provider read-only probe 冻结目标日。
- 当前 main 有独立 canonical 文档修改；本 TASK 不合并或覆盖这些修改。
- 本 TASK 只达到 `JM_HISTORICAL_CATCHUP_IMPLEMENTED`，不声明三个 S6-03 真实 Gate。

## 21. 执行结果

- 实现纯函数 target/week/gap/request/artifact/Profile candidate planner，continuous 与 rank=1 actual 分角色、按换月区间规划。
- 实现 hash-bound S6-03 approval packet、create-only 路径、packet drift 校验和 `plan / packet / verify` 无写入 CLI。
- live target 新增显式 `required_date`，对目标日 rank=1 mapping、trading parameters 和 actual `1m/5m/15m` watermark fail-closed。
- 未调用 RQData，未连接或写 PostgreSQL，未创建 canonical 数据、manifest、Profile binding、live row、SignalEvent 或 notification。

验证结果：

```text
focused + regression pytest: 68 passed
ruff: passed
sensitive scan: 7/7 changed files clean
git diff --check: passed
```

最终代码 Gate：

```text
JM_HISTORICAL_CATCHUP_IMPLEMENTED
```

仍待 S6-03 审批和真实执行：

```text
JM_HISTORICAL_CATCHUP_READY: PENDING
JM_REFERENCE_METADATA_FRESH: PENDING
JM_LIVE_TARGET_FRESHNESS_READY: PENDING
```
