# 测试与验证入口

更新时间：2026-08-22

所有写入测试必须使用 `tmp_path`、临时 Canonical root 和隔离数据库；测试 URL 不得指向 Runtime 或
生产数据库。真实数据、Runtime switch 和通知不属于测试命令的隐含权限。

首次检出或锁文件变化后先联网完成一次依赖同步；后续 `--offline` 命令只依赖该
venv 与同一 cache：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

## 工程与仓库检查

```bash
python3 scripts/engineering/secret_scan.py --json
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q tests/engineering
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
git diff --check
```

Secret scan 默认只扫描 `git ls-files`，只报告文件、行号和规则类别，不输出命中内容。

## 后端与前端基线

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  pytest -q -m "not isolated_postgresql" services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/research services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

需要运行 Alembic 或 PostgreSQL 约束测试时，必须显式提供一个库名包含 `test` 或 `isolated`、且与
Runtime `DATABASE_URL` 物理身份不同的 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`。测试 guard 会以
数据库名和 OID 双重拒绝 production/Runtime 库；禁止为了让测试运行而放宽该校验。

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='<isolated-postgresql-url>' \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  pytest -q -m isolated_postgresql services/quant-api/tests
```

## 主力照妖镜 V2

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_research_cli.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
```

JM 60m sequence forensic 只读 dossier：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 \
  --symbol jm \
  --series-kind actual_dominant \
  --frequency 60m \
  --since 2026-03-10 \
  --through 2026-03-30 \
  --forensic
```

该命令只读 Historical confirmed 并把 JSON 写到 stdout；不调用 RQData，不写
Canonical、PostgreSQL、Redis 或 research-data-root。`--forensic` 只增加 balanced
profile 的逐 Bar 诊断，不改变 MarketData/V2 计算身份。

这些命令验证唯一 `main_force_mirror_v2` identity、因果 60m exact-contract 压力、
T-1 member context、不可变 snapshot 身份/覆盖/fail-closed、只读 retrospective CLI，以及 Web
`MACD | 主力照妖镜 V2` 副图。真实 member snapshot 和 retrospective matrix 不由测试执行；
这些绿灯也不授权 RQData/Canonical/DB 写入、Live/Alert/notification、Runtime、订单、
release 或策略晋升，`auto_order=false`。

## Execution Review V1

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  -m "not isolated_postgresql" \
  services/quant-api/tests/test_execution_review_contracts.py \
  services/quant-api/tests/test_execution_review_pnl.py \
  services/quant-api/tests/test_execution_review_models.py \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_execution_review_api.py \
  services/quant-api/tests/test_execution_review_reconstruction.py \
  services/quant-api/tests/test_execution_review_reconciler.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/execution-review.spec.mjs
pnpm --dir apps/quant-web build
```

这些测试覆盖 trusted-partial reference/evidence 一一对应、缺失 multiplier 的 nullable RMB 估算、
Episode snapshot、四状态工作流、reconstruction、roll estimate、stats 和 Web unavailable 展示。测试
不执行 production migration、release、Runtime switch、roll marker、Scope/notification、Canonical 或订单行为。

## SuBing Factor / Calibration / Signal Observation V1

### 无副作用实现与回归验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py::test_latest_dominant_segment_returns_current_contiguous_rank1_segment \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py::test_latest_dominant_segment_fails_closed_for_missing_map_after_known_contract \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli services/quant-api/app/alerts \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

这些命令覆盖 strict slope-only Calibration loader、exact research-only Lifecycle Policy、causal
ConfirmedPivot/Breakout/Retest 和 Lifecycle reducer、MarketDataService-only research/CLI、scoped MACD
equivalence、Signal pure core、`SubingReadService` reciprocal/lifecycle orchestration、API、Web unit/E2E、
current-rank1 segment、Historical/completed Live seam 和有效当前合约视图。测试只使用 fixture、mock、
临时目录或隔离数据库，不运行 provider、Canonical/DB/Redis 写入、Runtime switch 或通知。

`test_subing_read_service.py` 同时覆盖 current cutoff 超过 Canonical edge 时的 latest-page bootstrap、
5m/15m 非对称 edge、state 后并发发布的 strict 重读及未来 Bar 隔离；`MarketDataService` 的显式 cursor
超出 coverage 仍独立 fail-closed。`test_alert_runtime_launchd.py` 覆盖 marker-before-start、late failure
逆序 bootout、absent/existing 原子恢复，以及无法确认停止时保留 enabled marker 的 fail-closed 分支。

`guiyi research subing-calibration` 本身是只读 Historical research：只通过 `MarketDataService` 取数，
输出 stdout JSON，不直接读 provider，也不写 DB、Canonical 或 Redis，不自动 promotion。Discovery/
Validation stdout 不能作为正式 artifact；测试只验证 CLI 合同，不运行真实研究窗口。当前 accepted
intraday Calibration 仅由 Git-tracked slope-only artifact 提供，zero-distance 不参与 executable Signal。

`guiyi research subing-lifecycle` 同样只读 Historical Canonical：它通过 `MarketDataService`
按 exact trading-day Session window 与 current-rank1 segment 独立复算 research-only lifecycle
Shadow，只输出 stdout JSON。测试只验证命令、分段因果与报告合同，不运行真实当前市场观察，
也不表示正式回测、策略有效或可晋升。

`guiyi research candidate-validation` 只接受五个 Git-tracked exact Candidate 与三个
exact Protocol：SuBing 由 `SubingLifecycleResearchService`、N 由
`NStructureResearchService`、三个 JDJ Candidate 由 `JdjResearchService` 分别产生
source-specific report，只共享 rolling/prospective schedule。三条链都只输出 stdout JSON，
保持 `research_only=true` 与 `readonly=true`；测试使用 fake source 验证合同和时间边界，
不运行真实 Candidate report，也不授权 Candidate 晋升、Alert/Runtime 接入、
DB/Canonical/Redis 写入、通知或订单。N 的 retrospective 截止 `2026-08-19`，
`2026-08-20` 只是 embargo，prospective 首日是 `2026-08-21`；JDJ 的 retrospective
截止 `2026-08-20`，`2026-08-21` 是 embargo，prospective 首日是 `2026-08-24`。

## JDJ 1m Research & Candidate V1

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_jdj_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_jdj_candidate_validation_calendar.py \
  services/quant-api/tests/test_price_outcome.py \
  services/quant-api/tests/test_research_cli.py
```

该命令验证 exact Policy/Manifest/Protocol、EMA20 parity、5m N strict-before context、
三个 causal reducer、M1/M5 actual-dominant segment source、3/5/8/20 outcome、共享
10-fold schedule、calendar freeze 与 readonly CLI。测试只使用 fixture、fake source、
临时目录或隔离数据库，不运行真实 `jm` research/evidence，不写入
DB/Canonical/Redis，也不授权 evidence 生成、Candidate promotion、main/tag/release、
Runtime/Alert/通知、订单或任何盈利结论。

## N Structure V1（Historical / research-only）

### N 全链与 CLI

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_policy.py \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py \
  services/quant-api/tests/test_n_structure_segment.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/test_price_outcome.py \
  services/quant-api/tests/data_foundation/test_n_structure_research_service.py \
  services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_n_candidate_validation_policy.py \
  services/quant-api/tests/test_n_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

### 上游 SuBing zero-regression

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

这两组命令验证 `MarketDataService → ActualDominantResearchSegmentLoader →
SuBing / N` 的 Historical 链、N 的 5m/epoch/segment/prefix 因果合同、独立 source-specific
Candidate report 以及 SuBing same-day/EMA21 语义不变。`guiyi research n-structure` 与 N
Candidate Validation 只读 Historical Canonical；测试不运行真实 `jm` 数据窗口，不形成效果、
promotion、release 或 Runtime 结论，不授权数据/DB 写入、Alert/通知或订单。

## Multi-Candidate Robustness V1（Historical / research-only）

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_research_cli.py
```

该命令验证两个 frozen Candidate 的 exact Protocol、既有 causal event seam、`jm` 双向
3/5/8 Bar relationship、完整 active60 的 120-cell 保留矩阵、既有 10-fold Validation 投影与
只读 `candidate-robustness` CLI。测试不修改 Candidate、公式、参数或 prospective OOS，不运行真实
Canonical 窗口，不写 DB/Canonical/Redis，不发送通知，也不形成 rank、winner、promotion、release、
Runtime 或盈利结论。

JDJ active60 robustness 只读复算命令固定为：

```bash
uv run --offline --project services/quant-api guiyi research candidate-robustness \
  --protocol jdj_active60_robustness_v1
```

该命令只按 exact protocol 读取 Historical Canonical；不接受运行时窗口、品种、阈值、score 或 rank。

## Five-Candidate Research Dossier V1（Phase 8A / artifact-only）

exact dossier 生成命令固定为：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research candidate-dossier \
  --protocol five_candidate_research_dossier_v1
```

该命令只读七份钉住的 Git-tracked research artifact，只向 stdout 输出 deterministic JSON；
不读 `MarketDataService`，不写 DB/Canonical/Redis，不发送通知，不进入 Alert/Runtime/订单路径，
不消费 prospective OOS，也不形成 Candidate 优劣、有效性、盈利、可交易或可晋升结论。

## Five-Candidate Relationship Topology V1（Phase 8B / Historical read-only）

exact relationship topology 生成命令固定为：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research candidate-relationships \
  --protocol five_candidate_relationship_topology_v1
```

该命令只通过既有 Historical gateway 分别复算 N→JDJ
`2023-01-01..2026-08-19` 与 JDJ exact-overlap `2023-01-01..2026-08-20`，
并向 stdout 输出 deterministic JSON。正式 evidence freeze 要求同一输入连续两遍 stdout byte-identical，
完整保留 `10` 条 relationship catalog、`180` 条 dependency 和 `180` 条 overlap identity。
命令不消费 prospective OOS，不写 DB/Canonical/Redis，不发送通知，不进入 Alert/Runtime/订单路径，
不计算 proximity 或 overlap-conditioned future outcome，也不形成 Candidate 排名、有效性、盈利、
可交易或可晋升结论。

## Alert V2

### 无副作用单元、集成与工程验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification_dispatcher.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_config.py \
  services/quant-api/tests/test_alert_pushplus.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q tests/engineering

/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/ruff check \
  services/quant-api/app/alerts/notification.py \
  services/quant-api/app/alerts/notification_config.py \
  services/quant-api/app/alerts/pushplus.py \
  services/quant-api/app/alerts/notification_composition.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/schemas/runtime.py

MYPYPATH=services/quant-api:packages/quant-core \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/alerts/notification.py \
  services/quant-api/app/alerts/notification_config.py \
  services/quant-api/app/alerts/pushplus.py \
  services/quant-api/app/alerts/notification_composition.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/schemas/runtime.py

find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
find deploy/launchd -type f -name '*.plist.template' -print0 | xargs -0 -n1 plutil -lint
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

这些命令使用 fixture、tmp_path 与 fake PushPlus client，不读取或修改真实 token/Topic，不执行真实
canary/send，也不启动或切换 Alert Runtime。PushPlus transport 不新增 migration；
Alert Application Domain 仍只有 `alert_rules` 与 `alert_events` 两张表。无 Web 变更时不要求前端或 browser
验收。

全 backend 基线若包含 PostgreSQL-only 测试，仍必须按本文“后端与前端基线”的 guard 使用显式隔离测试
库；缺少隔离库只能报告环境阻塞，不得借用 Runtime/production `DATABASE_URL`。

### 独立受控外部 Gate

- 创建专用 PushPlus 消息 token 与 Topic：已完成；
- 人工核对 Topic 当前成员在 `1..4` 人边界内：当前 3 人已由用户确认，第 4 人可后续加入；
- 写入 `0700/0600` Git 外 private config：已完成，structural readback PASS；
- `owner` 与 `htdy_observers` 各一次真实 canary/send：均已完成、由 provider 接受且经用户确认实际收到，
  未重试；这两次历史 canary 不得在发布或 Runtime switch 时重复执行；
- exact HTDY Rule + Scope + audience + transport 持续边界为
  `htdy_original_15m × jm × htdy_observers × pushplus-wechat-topic`；SuBing 固定为
  `subing_entry_signal_v1 × jm × owner × pushplus-wechat`，不得从历史 canary 推导 release 或 switch；
- v1.6.5 main/release/tag 与 exact-tag Alert Runtime promotion/switch：均已完成；后续版本或再次 switch
  仍是新的独立 Gate。

这些 Gate 不能相互授权，失败或重试也需要新的明确请求。代码、fixture、render-only 或 mock 通过只证明
实现，不证明未来发布或 Runtime Gate 已授权。当前 production 为 `v1.6.5` exact Runtime，PushPlus
transport 已按两条精确 `jm` 边界启用；自然 HTDY Topic Event 与自然 SuBing owner Event 验收仍 pending。

## OpenSpec

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
```

已完成 change 只从 Git history 追溯；当前行为合同只看 `openspec/specs/`。

## Data Foundation 只读验证

```bash
uv run --project services/quant-api guiyi data update --universe active --through 2026-08-11
uv run --project services/quant-api guiyi data refresh --symbol jm --since 2024-03-01 --through 2024-03-31
uv run --project services/quant-api guiyi data audit --symbol jm --through 2026-08-11
uv run --project services/quant-api guiyi data audit --universe active --through 2026-08-11
```

无 `--apply` 的 update/refresh 只规划，audit 始终只读。任何真实 RQData、PostgreSQL 或 Canonical 写入
仍需执行前范围明确的单次意图。

## Market Runtime V1

### 无副作用验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_operational_universe.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_websocket.py

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
```

`--render-only` 不安装、重载或启用 Runtime。禁止用 fixture、手工 after-market 或旧状态冒充自然触发。

### 最终隔离 Runtime 验收

部署属于受控外部操作。取得本次明确意图后，将 Runtime worktree 固定到已验证 commit，构建 Web，安装
API 依赖并仅执行一次对应 Runtime switch。部署后至少读回：

- Runtime clean/detached 且等于批准 commit 或 release tag 的 peeled commit；
- API/Web/Live/after-market/Alert 的 launchd 根只指向该 worktree，已加载 commit 与 checkout 一致；
- `operational_products.txt` 与 active 60 完全一致，Live subscription/heartbeat 与 after-market status
  均报告同一 60 品种集合；
- API、Web、Runtime health 和实际 Market 业务字段可读；
- Historical/Live seam 保持分离，Live 不写 Parquet，`auto_order=false`。

`--confirm-market-runtime` 才会启用或重载 Market Runtime 并更新 marker。完成或失败后，本次执行意图即
消耗；重试必须取得新的明确请求。

### 18:05 自然盘后验收

不得手工执行 `guiyi data after-market` 代替 launchd 证据。自然触发后只读核对：

- launchd `runs` 增加且 `.run/after-market-status.json` 的 products 精确为 operational 60；
- `status=passed`、`attempts=1|2`，或在真实非交易日精确为 `NON_TRADING_DAY`；
- 当天 TradingSession / MainContractMap 已推进，正式 rank1 与同日 Live snapshot 一致；
- Canonical edge 与 Web Historical/Live seam 随正式发布更新，Live 从未写入 Parquet；
- intended same-day Live 清理完成，随后 Runtime health 不再因旧 Session 报 `UNKNOWN=56`。

代码、fixture、render-only 或手工命令只能证明实现，不得写成自然盘后通过。

## 最终检查

```bash
git diff --check
git status --short
```
