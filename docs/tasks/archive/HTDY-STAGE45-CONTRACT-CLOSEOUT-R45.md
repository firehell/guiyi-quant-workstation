# HTDY-STAGE45-CONTRACT-CLOSEOUT-R45

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-STAGE45-CONTRACT-CLOSEOUT-R45 |
| Handbook Task | R45-00 / R45-01 |
| Work Level | L1 |
| GitHub Issue | 待创建（L1 可选） |
| Branch | codex/stage45-contract-closeout |
| Worktree | /private/tmp/guiyi-htdy-stage45-contract-closeout-r45 |
| Status | BLOCKED / STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT |
| Risk Level | R2 read-only data identity audit |
| Approval Scope | R45-00 baseline + R45-01 frozen-window equivalence only |
| Required Env | local canonical parquet read access |
| Required Mounts | /Volumes/扩展盘 |
| Base Commit | 2ef3abba2d6c4846b013cd5189da4366f18dcfbb |
| Created At | 2026-07-19 |
| Owner | local-user |

```json
{
  "schema_version": 1,
  "task_id": "HTDY-STAGE45-CONTRACT-CLOSEOUT-R45",
  "work_level": "L1",
  "github_issue": "待创建",
  "branch": "codex/stage45-contract-closeout",
  "worktree": "/private/tmp/guiyi-htdy-stage45-contract-closeout-r45",
  "status": "BLOCKED",
  "owner": "local-user",
  "allowed_paths": [
    "docs/tasks/HTDY-STAGE45-CONTRACT-CLOSEOUT-R45.md",
    "services/quant-api/app/backtest/htdy_stage45_closeout.py",
    "services/quant-api/scripts/htdy_stage45_closeout.py",
    "services/quant-api/tests/test_htdy_stage45_closeout_r45.py",
    "data/reports/htdy_stage45_closeout_r45/"
  ],
  "forbidden_paths": [
    ".env", ".env.*", "data/raw/", "data/parquet/", "data/processed/",
    "configs/oos/htdy_strict_validation_protocol_v1.json",
    "data/reports/htdy_trusted_backtest_candidate_x5_03/",
    "data/reports/htdy_oos_validation_x5_04/",
    "data/reports/htdy_rolling_oos_x5_05/",
    "data/reports/htdy_strategy_review_x5_06b/",
    "data/reports/htdy_stage5_acceptance_x5_07/",
    "services/quant-api/alembic/", "services/quant-api/app/models/"
  ],
  "routing": {"requested_tier": "auto", "allow_auto_escalation": true, "max_auto_escalations": 1},
  "permissions": {
    "production_access_allowed": false, "database_write_allowed": false,
    "external_network_allowed": false, "push_allowed": false, "merge_allowed": false,
    "deploy_allowed": false, "trading_execution_allowed": false
  }
}
```

## 5. 目标

1. R45-00：冻结 commit、协议/参数、report14/report15/task23、X5 packet、Profile binding 与数据身份基线。
2. R45-01：严格比较 frozen protocol 旧资产与 X5-03 新资产在冻结窗口内的逐 bar 等价性。
3. 只生成版本化、可复算、fail-closed 的文件证据；完成后停在人工检查点 A。

## 6. 不做事项

- 不修改策略、参数、protocol、report14、report15、task23 或 X5 原始证据。
- 不写 PostgreSQL、Profile binding、Parquet、manifest、live、SignalEvent、企业微信或订单。
- 不重跑策略、不调参、不翻转 `REJECTED_RESEARCH_CANDIDATE`。
- 不执行 R45-02..R45-05；不 push、merge、deploy。

## 7. 实现约束

**允许修改**：

- `docs/tasks/HTDY-STAGE45-CONTRACT-CLOSEOUT-R45.md`
- `services/quant-api/app/backtest/htdy_stage45_closeout.py`
- `services/quant-api/scripts/htdy_stage45_closeout.py`
- `services/quant-api/tests/test_htdy_stage45_closeout_r45.py`
- `data/reports/htdy_stage45_closeout_r45/`

**禁止修改**：

- `.env`、`.env.*`
- `data/raw/`、`data/parquet/`、`data/processed/`
- `configs/oos/htdy_strict_validation_protocol_v1.json`
- `data/reports/htdy_trusted_backtest_candidate_x5_03/`
- `data/reports/htdy_oos_validation_x5_04/`
- `data/reports/htdy_rolling_oos_x5_05/`
- `data/reports/htdy_strategy_review_x5_06b/`
- `data/reports/htdy_stage5_acceptance_x5_07/`

- 身份必须从 frozen protocol 与 X5-03 packet 动态读取。
- declared SHA 与 actual SHA 必须一致；文件缺失、hash 漂移、重复 datetime、缺/多 bar 或字段差异均 fail-closed。
- 共同字段逐行 exact；只允许 dtype 规范化，不允许宽松 tolerance。
- 通过 Gate 为 `HTDY_FROZEN_DATA_WINDOW_EQUIVALENT`；否则为 `STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT`。

## 18.0 自动化测试命令

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_stage45_closeout_r45.py
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_validation_protocol_c501.py \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py \
  services/quant-api/tests/test_htdy_stage5_acceptance_x507.py
uv run --project services/quant-api ruff check app/backtest/htdy_stage45_closeout.py scripts/htdy_stage45_closeout.py tests/test_htdy_stage45_closeout_r45.py
git diff --check
git status --short -- configs/oos/htdy_strict_validation_protocol_v1.json data/parquet \
  data/reports/htdy_trusted_backtest_candidate_x5_03 data/reports/htdy_oos_validation_x5_04 \
  data/reports/htdy_rolling_oos_x5_05 data/reports/htdy_strategy_review_x5_06b \
  data/reports/htdy_stage5_acceptance_x5_07
```

## 19. 验收标准

- `STAGE45_CLOSEOUT_BASELINE_READY` 基线证据可复算。
- 两份声明资产存在且文件 hash 与声明一致。
- 冻结窗口 row count、datetime 集合、first/last bar、共同字段和 ordered bar hash 可复查。
- 测试覆盖完全一致、单字段差异、缺 bar、多 bar、重复 datetime、旧文件缺失和 hash 篡改。
- 原始证据、protocol、Profile binding、Parquet 与数据库零写入。

## 20. 风险与回滚

- 文件 hash 均有效不等于窗口数据等价；正式 Gate 只能来自逐 bar 比较。
- 回滚仅删除本分支新增文件和 R45 版本化输出；无数据库或数据资产回滚。

## 21. 执行结果

### R45-00

```text
gate=STAGE45_CLOSEOUT_BASELINE_READY
source_commit=2ef3abba2d6c4846b013cd5189da4366f18dcfbb
protocol_hash=be1aca4ff14855e6c56cf6fa26addb3187b157e6f886cdbe24d152b21b9494a2
parameter_hash=84d80219d2a27d115dfdd36fe7bdf0ea41530e2fc9f2a188ec48bf9db37c2eb8
baseline_packet_hash=2cd937d4754e36f62e65ed972d633af2bd5b9d8128607af5a87c7e9cdf800efd
```

report14 consistency hash 保持 `2b16178a371a28727e0c471d6a7d68199e213ec205d838cf6634e82de428d12a`；report15/task23、binding 4945/file 71338 和 `REJECTED_RESEARCH_CANDIDATE` 均保持。

### R45-01

```text
gate=STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT
old_window_rows=19366
new_window_rows=19381
difference_count=15
first_difference=extra_in_new@2026-07-10T09:15:00
old_last_bar=2026-07-09T23:00:00
new_last_bar=2026-07-10T15:00:00
equivalence_packet_hash=142de03ada02555ce2d734e532cee097b5c23e4d91b6f92d62121b8e771b4c47
```

旧资产没有新资产缺失的 bar；新资产额外包含 2026-07-10 日盘 15 根 bar。按手册停止 R45-02..R45-05，不修改 frozen protocol，不重跑策略。

### R4501B versioned completion acceptance

`HTDY_FROZEN_DATA_WINDOW_EQUIVALENT` was accepted through `immutable_base_plus_versioned_completion`, retaining the original blocked packet unchanged. See `docs/tasks/HTDY-FROZEN-DATA-WINDOW-EQUIVALENCE-R4501B.md` and `data/reports/htdy_stage45_closeout_r45/R45_01_ACCEPTANCE.json`.

### 验证

- R45 新测试与 X5 回归：`65 passed`。
- Ruff：passed。
- `git diff --check`：passed。
- baseline/equivalence packet hash：复算通过。
- frozen protocol、Parquet、X5-03/04/05/06B/07 原始证据：无 Git 修改。
