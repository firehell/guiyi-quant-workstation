# 测试与验证命令

以下命令只验证代码和本地只读行为；不授权 RQData、Canonical、生产 DB、Runtime、Scope、通知或 release 操作。

## Newow 历史恢复通用边界

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/data_foundation \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_readiness.py
```

覆盖周五夜盘首边界、未完成尾周、逐日交易所夜盘证据、来源全集身份和生命周期、局部无夜盘不得覆盖共享 Calendar，以及元数据提交结果不明时停止并独立回读。隔离工作树可显式使用既有 Python 环境；这些离线检查不代表实际历史补齐、未来 Calendar 自动扩展或浏览器验收。

## Newow 新版参考卡片定向验证

共享浏览器夹具回归（九组合解释必须通过正式响应解析器，综合上下文使用趋势身份；日/周参考卡片保留完整日期）：

```bash
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/newowProductTypes.test.ts tests/newowDetailPresentation.test.ts
env -u VITE_API_BASE_URL -u VITE_MARKET_WS_URL REAL_BACKEND=0 PLAYWRIGHT_PORT=5182 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5182 PLAYWRIGHT_CANDIDATE_PREVIEW=0 PLAYWRIGHT_SKIP_WEBSERVER= pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs
```

使用独立 worktree 和既有依赖；5182 必须空闲，不能复用其他工作区服务。正常验收不带 `--update-snapshots`；截图变更须先核对规范与实际差异。fixture 通过不代表生产历史或 Runtime 验收。

```bash
pnpm -C apps/quant-web exec node --test tests/useNewowProduct.test.ts tests/newowReferencePanel.test.ts tests/newowDetailPresentation.test.ts
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-detail-light.spec.mjs --grep 'current FLAT waiting card'
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_target_absorb_display.py \
  services/quant-api/tests/newow/test_composite_explanation.py \
  services/quant-api/tests/newow/test_page_comparator.py
```

等待卡片验证覆盖同快照当前 FLAT、空/分页历史、筛选、stale/历史窗口、跨身份与 OPEN 冲突；日期覆盖日周、同日时分与跨年夜盘。浏览器用本地 fixture，1440/390px 截图只证明显示，不证明原站新版 parity、真实数据恢复或生产启用。沿用测试默认 5182 端口，不接入生产服务。源码-only 隔离 worktree 可使用已存在的 Python 环境并显式设置上述 PYTHONPATH，避免为定向验证重新安装依赖。

## Newow 公式、参考交易与显示合同专项复核

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/newow/test_trend_band.py \
  services/quant-api/tests/newow/test_trend_band_page_v2.py \
  services/quant-api/tests/newow/test_oscillation_channel.py \
  services/quant-api/tests/newow/test_main_rise_page_v1.py \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_target_absorb_display.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test \
  tests/useNewowProduct.test.ts tests/newowReferencePanel.test.ts tests/newowDetailPresentation.test.ts \
  tests/newowProductChartPrimitives.test.ts tests/newowProductTypes.test.ts tests/NewowProductChartStage.test.ts
```

只使用现有依赖与本地测试输入；`pnpm_config_verify_deps_before_run=false` 防止新版 pnpm 在复核时自动安装依赖。
这些测试证明当前代码合同，不等于新原站版本的同输入逐值验证。可见收益舍入核查的输入、公式及限制见当前研究复核。

## Newow 固定公开快照离线逐值验证

以下命令从仓库根执行，仅使用本机已冻结文件；不重新请求外站。临时目录缺失时不能复现，不可静默用新行情替换该快照。先核对目录内 `manifest.json` 的文件与源码哈希；具体采集身份、容差和119行/18个Marker结果见[当前复核](docs/research/newow-current-review.md)。

```bash
TZ=Asia/Shanghai node /private/tmp/newow-same-input-20260909-pjncal43/replay_page.mjs
PYTHONPATH=packages/quant-core services/quant-api/.venv/bin/python /private/tmp/newow-same-input-20260909-pjncal43/compare_kernel.py
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/newow/test_trend_band_page_v2.py \
  services/quant-api/tests/newow/test_reference_trades.py
```

实跑离线比较通过；119个归一前缀检查通过；重复重放4个输出哈希一致；定向测试32 passed。比较覆盖趋势周线页面kernel及未舍入收益函数；不声称股票行情是期货completed Bar，也不证明产品API、完整参考交易投影、回撤、其他组合或Runtime通过。原始第三方响应及提取代码只保存在Git外。

## Newow 震荡60分钟固定快照差异复现

从仓库根执行，先核对下列目录的 `manifest.json` 文件/源码哈希。命令不联网，临时快照缺失时停止，不能替换成新输入。

```bash
TZ=Asia/Shanghai node /private/tmp/newow-osc60-snapshot-20260909-x56a03g5/replay_page.mjs
PYTHONPATH=packages/quant-core services/quant-api/.venv/bin/python /private/tmp/newow-osc60-snapshot-20260909-x56a03g5/compare_kernel.py
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/newow/test_oscillation_channel.py \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_reference_trades.py
```

实跑结果：比较器输出 `MISMATCH_CONFIRMED_SAME_BAR_REBUILD`，退出0表示已复现并核实差异，**不表示parity通过**；444个归一前缀、4输出哈希重放一致，73项既有合同测试通过。435对成熟通道值及共同26个Marker初始评分/价格一致；归一多4个Marker、2笔交易。源码两种灰度路径相同，原站允许重建的参数对照与归一30个Marker完全一致。详情及边界见[当前复核](docs/research/newow-current-review.md)，不执行选股或生产链。

## Newow 主升浪与目标/吸筹固定快照验证

从仓库根执行，使用同一个Git外固定公开响应集合。先核对目录内`manifest.json`；临时目录缺失时停止，不能联网补成另一快照。

```bash
TZ=Asia/Shanghai node /private/tmp/newow-mainrise-target-snapshot-20260909-rz7ib4a6/replay_mainrise.mjs
PYTHONPATH=packages/quant-core services/quant-api/.venv/bin/python \
  /private/tmp/newow-mainrise-target-snapshot-20260909-rz7ib4a6/compare_mainrise.py
TZ=Asia/Shanghai node /private/tmp/newow-mainrise-target-snapshot-20260909-rz7ib4a6/replay_target.mjs
PYTHONPATH=packages/quant-core services/quant-api/.venv/bin/python \
  /private/tmp/newow-mainrise-target-snapshot-20260909-rz7ib4a6/compare_target.py
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/newow/test_main_rise_page_v1.py \
  services/quant-api/tests/newow/test_oscillation_channel.py \
  services/quant-api/tests/newow/test_target_absorb_display.py
```

离线比较实跑通过：主升浪444根指标与全部Marker一致、444个前缀稳定、6笔未舍入配对一致；目标/吸筹日线600根与周线119根HHV10/LLV10逐项相等，三态选择、状态卡和趋势面一致。7个输出文件连续两轮SHA-256不变。比较对象明确标为外部股票页面算术输入；不证明正式期货DTO/API、previous-close activation、owner/segment、回撤、OOS或Runtime。

## Newow 综合解释 v2 固定同输入验证

从仓库根执行，仅使用Git外已冻结的公开页面、三组`batch/quote`、18份趋势/震荡多周期响应和牛哇原内核。临时目录缺失时停止，不可联网补成另一快照。原始输入和DOM哈希见目录内`manifest.json`及[当前复核](docs/research/newow-current-review.md)。

```bash
snapshot=/private/tmp/newow-composite-v2-snapshot-20260910-m7q4p9x2
test "$(shasum -a 256 "$snapshot/manifest.json" | awk '{print $1}')" = \
  6c4370142580e9b367c11d0a7980f407bff98d3ced827822cacd220a214215ff
shasum -c "$snapshot/sha256.txt"
test "$(shasum -a 256 "$snapshot/replay_composite.mjs" | awk '{print $1}')" = \
  b04d4bcd466080bb2e361c1e204cbb59977a5c9066a12ff3219037c9e12e4a91
test "$(shasum -a 256 "$snapshot/verify_and_compare.py" | awk '{print $1}')" = \
  d5c9f588ddd00534fa41a1b94d6a21910cc0f9429e5f2fc42d00962eade5a4bc
TZ=Asia/Shanghai node \
  /private/tmp/newow-composite-v2-snapshot-20260910-m7q4p9x2/replay_composite.mjs
PYTHONPATH=packages/quant-core python3 \
  /private/tmp/newow-composite-v2-snapshot-20260910-m7q4p9x2/verify_and_compare.py
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/newow/test_composite_explanation.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test \
  tests/newowExplanationPanel.test.ts tests/newowProductTypes.test.ts
```

离线原内核与独立检查通过：三个真实样本五项算术、MM1/R2、两例R3、`已清7根`逐值闭合；MM1的2/3根门槛、MM2-MM4及signalIndex降级见证通过。归一当前合同同输入0/3精确一致，确认是待版本化实现的规则差异；测试绿只证明旧合同未被本次文档任务破坏。另有固定见证证明`certExtra=-5`时页面五项82但总分77，后续实现不得隐藏该差值。

## 苏冰历史参考交易

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_subing_reference_projection.py \
  services/quant-api/tests/test_subing_reference_service.py \
  services/quant-api/tests/test_subing_reference_api.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py
pnpm -C apps/quant-web exec node --test tests/subingReference.test.ts
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/subing-reference.spec.mjs
```

上述浏览器截图使用 route-intercept fixture，只证明视觉与交互，不代表生产历史收益或自然预警。
真实历史读取、发布和 Runtime 验收单独报告；测试不授权生产数据库连接或外部写入。

## Market WebSocket 与统一详情页

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_websocket.py \
  services/quant-api/tests/data_foundation/test_market_read.py
pnpm -C apps/quant-web test
pnpm -C apps/quant-web build
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-detail.spec.mjs
```

WebSocket 验证使用 fake clients 和受控阻塞，不访问生产；浏览器使用 route fixtures。桌面与390px
截图、键盘操作用于工程验收，不能替代用户关键页面视觉审查，也不授权发布或 Runtime 切换。

## 后端

```bash
uv sync --project services/quant-api --locked
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

### 盘后每日增量、进度与每周只读审计

中断收尾的隔离验证（不连接生产，不修改现役状态）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_after_market_closeout.py \
  services/quant-api/tests/data_foundation/test_closeout_binding.py \
  services/quant-api/tests/test_captured_recovery_runtime.py
```

真实锁和只读事务另用下文同一防误连变量、精确隔离库执行
`services/quant-api/tests/data_foundation/test_after_market_closeout_postgresql.py`；未配置时 skip 不算通过。
测试包括旧次数未知、中断 health、默认只读、部分完成、窗口外损坏、额外端点、锁冲突、危险文件类型、
CAS 漂移、时钟倒退和替换后 fsync 不确定；还覆盖目标配置/实际依赖一致性、源替换、PID 变化、
shell/libpq 覆盖、第二 dotenv 来源和私有文件权限；所有 apply 只写临时状态文件。

以下定向命令覆盖 Catalog-bounded daily 规划/发布、schema-v3 进度持久化与 fail-closed health、
`operational_full_history` 审计、HTTP schema 保留、launchd 渲染/安装防护和只读状态输出。它们使用 fake provider、
临时 SQLite/Parquet/路径和复制的 shell fixture；不连接真实 RQData、production DB/Redis、Runtime 或通知服务，也不安装 LaunchAgent。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q --tb=short \
  services/quant-api/tests/data_foundation/test_daily_maintenance.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_weekly_audit.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py \
  services/quant-api/tests/data_foundation/test_runtime_promotion.py \
  services/quant-api/tests/test_runtime_entry.py \
  services/quant-api/tests/test_runtime_logging.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_captured_recovery_cli.py \
  tests/engineering/test_market_runtime_launchd.py

pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test \
  tests/runtimeStatus.test.ts tests/marketHomePageRoute.test.ts \
  tests/marketHomePresentation.test.ts tests/marketHomeResource.test.ts
env -u NO_COLOR -u FORCE_COLOR pnpm_config_verify_deps_before_run=false \
  pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-home.spec.mjs -g 'maintenance v3'
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
```

真实 PostgreSQL 只读事务与 advisory lock 合同仅允许在显式的一次性隔离数据库中验证：必须是
loopback、非 5432 端口、精确数据库名 `guiyi_canonical_isolated_test`；未设变量时 skip 不算验收通过。

```bash
GUIYI_ISOLATED_PUBLICATION_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:15447/guiyi_canonical_isolated_test' \
  PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_daily_maintenance_postgresql.py \
  services/quant-api/tests/data_foundation/test_weekly_audit_postgresql.py
```

这些工程验证不证明每周调度已安装、真实全历史无 finding、盘后自然运行耗时、release 或 Runtime promotion。
实际安装语法和前置 Gate 仅见 `deploy/README.md`。

有界 metadata fixture 与既有同步/provider/CLI 回归（全部隔离，无生产连接）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_bounded_metadata.py \
  services/quant-api/tests/data_foundation/test_metadata.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_cli.py
```

以下为用法，非外部执行授权。`targets.json` 是明确的
`[{"symbol":"au","contract":"AU2304","through":"2023-03-13"}]`；输出为普通 JSON，由 operator 保存。
fetch 和 apply 各自需要新的单次执行意图，不能在一个获准 fetch 后自动 apply。

```bash
uv run --project services/quant-api guiyi data metadata-repair --targets /absolute/targets.json
uv run --project services/quant-api guiyi data metadata-repair --phase fetch \
  --plan /absolute/plan.json --expected-plan-sha256 EXACT_PLAN_SHA256 --apply
uv run --project services/quant-api guiyi data metadata-repair --targets /absolute/targets.json \
  --classification /absolute/classification-snapshot.json --evidence-sources /absolute/evidence-sources.json
uv run --project services/quant-api guiyi data metadata-repair --targets /absolute/targets.json \
  --classification /absolute/classification-snapshot.json \
  --exchange-universes /absolute/exchange-universes.json \
  --exchange-inventory-evidence /absolute/exchange-inventory-evidence.json
uv run --project services/quant-api guiyi data metadata-repair --phase apply \
  --snapshot /absolute/snapshot.json --expected-plan-sha256 EXACT_PLAN_SHA256 \
  --expected-snapshot-sha256 EXACT_SNAPSHOT_SHA256 --apply
```

`--classification` 与 `--evidence-sources` 均为可选 plan 输入；供证列表仅含显式
`symbol/contract/date`，不扩写入范围。新 plan 如有新增 Session 请求，需要对其 hash 另行批准 fetch。
完整交易所负证据另需两份 plan 输入文件：`--exchange-universes` 内容为
`[{"exchange":"GFEX","date":"2026-09-14","products":["lc","pd","ps","pt","si"],"sources":[...]}]`，
每个 source 为 `symbol/contract/date`；`--exchange-inventory-evidence` 内容严格为
`{"identity":{"method":"all_instruments_by_type","args":[],"kwargs":{"instrument_type":"Future","market":"cn"}},"response":[...]}`。
response 必须来自已获准并持久化的未过滤完整 RQData futures inventory，不能填品种子集；plan
只读重算完整集合和所有物理来源的身份/生命周期，绑定原始响应，不执行 inventory 请求。每个输入
文件上限 16 MiB。fetch/apply 不接收上述 plan 参数，只接收已冻结 plan/snapshot 和精确 hash。
未知夜盘证据的 snapshot 为 blocked（退出 1），不能 apply。成功 apply 后旧 plan 失效，必须只读 replan，
不自动重试、覆盖或删除。已有 Session 日期只保留，不把未验证的完整性计为修复通过。

AU 已确认单键 Calendar 更正（独立于 insert-only metadata-repair）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_au_calendar_correction.py
# 仅显式本机隔离库 guiyi_calendar_isolated_test，端口不得为生产 5432；不读取 DATABASE_URL。
GUIYI_ISOLATED_CALENDAR_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:15436/guiyi_calendar_isolated_test' \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/data_foundation/test_au_calendar_correction_postgresql.py
# 真实只读连接也须在本轮授权内。输入是已保存的诊断 JSON（source_response），不是新查询。
uv run --project services/quant-api guiyi data au-calendar-correction \
  --evidence /absolute/source-response.json --expected-evidence-sha256 EXACT_FILE_SHA256
# 下面仅是用法；未取得新的单次生产写入意图时禁止执行。
uv run --project services/quant-api guiyi data au-calendar-correction \
  --evidence /absolute/source-response.json --expected-evidence-sha256 EXACT_FILE_SHA256 \
  --expected-plan-sha256 EXACT_DRY_RUN_SHA256 --apply
```

隔离验证覆盖范围/旧值/来源哈希/身份/Session 漂移、只读事务、失败回滚、提交不确定、独立读回，
PostgreSQL 验证增加真实 writer 锁和事务可见性。真实 dry-run 不执行 apply；不带 provider 重试能力。

Newow dependency/readiness 定向 fixture 验证（不连接生产数据库，不下载）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_cli.py
```

已获真实只读连接授权时，可在 exact 代码副本执行以下用法；`--as-of` 必须为本次选定的固定截止时间。

```bash
uv run --project services/quant-api guiyi data newow-readiness \
  --symbol rb --as-of 2026-09-04T08:00:00Z --max-work 10000 --timeout-seconds 300
uv run --project services/quant-api guiyi data newow-readiness \
  --universe active --as-of 2026-09-04T08:00:00Z --matrix --max-work 10000 --timeout-seconds 300
```

没有 `--apply` 或自动修复开关；symbol/universe 互斥。`max-work` 为串行枚举/依赖验证/候选规划/section
调用次数上限（1–100000），deadline 为 1–3600 秒并在 reader 分页、planner 月循环之间检查；单条 PG
查询受 statement timeout 约束，进行中的文件读取返回后才检查 deadline。审计完成退出 0，
`status=incomplete` 或异常退出 1，非法参数退出 2。退出 0 表示审计完成而非所有数据/业务 ready；
必须读取 dependencies、repair_targets、metadata_proposals、main_ready_count 和逐 case section 状态。
fixture 的 540-case 枚举不构成真实 540-case 验收。后续下载/生产数据写入仍需独立明确授权。
定向测试同时覆盖完整 warm-up scope 的 source/integrity 阻断、SQLite 原只读状态恢复及恢复失败时连接丢弃。

Newow P4 分区编排、typed API、统计截止、来源事实、快照/资源边界、旧 D1 兼容与只读保护：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_older_chart_windows.py \
  services/quant-api/tests/newow/test_historical_snapshot.py \
  services/quant-api/tests/newow/test_data_diagnostics.py \
  services/quant-api/tests/newow/test_product_source_facts.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py \
  services/quant-api/tests/newow/test_product_resource_gate.py \
  services/quant-api/tests/newow/test_product_inflight.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_product_readonly_compatibility.py \
  services/quant-api/tests/newow/test_market_newow_api.py
```

照妖镜专用绘图规则与生命周期定向验证（确定性显示输入，不代表真实行情或当前在线牛哇）：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowZhaoyaoMirrorPrimitive.test.ts tests/NewowProductChartStage.test.ts
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/newow-chart-panes.spec.mjs e2e/newow-product.spec.mjs
```

批量 Session 读取保留端点与交易日关联、缺失失败及查询数量有界：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py
```

真实性能验收须另行使用隔离开发 API 和显式只读数据连接，对相同固定历史快照采集至少五组新进程结果缓存未命中/同进程命中请求；记录 DB 数、读取/计算/序列化、字节与浏览器点击到绘制完成时间，声明未清除 OS/磁盘缓存，并比较完整稳定业务字段。不得借验收下载数据、修改 Canonical、清理系统缓存或切换现役服务。

隔离 fake MDS 的 P4 后端冷/热/长前缀复测入口（不代表浏览器或真实工作站验收）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -s \
  services/quant-api/tests/newow/test_product_performance.py
```

以上 Newow 命令只使用内存 fixture/fake MDS，不连接 RQData、production PostgreSQL/Redis、Runtime 或通知服务。

Market Home derived projection、API fallback 与 apply invalidation：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py \
  services/quant-api/tests/test_market_home_api.py \
  services/quant-api/tests/test_market_home_projection_api.py
```

这组测试只使用临时目录/fake service，验证 projection identity、strict/atomic file、API projection-hit/miss、`data update/refresh/contract-warmup --apply` 在 maintenance lease 内的失效、after-market 顺序、default-off projection activation marker 与 maintenance lease；不得以测试为理由执行真实 `guiyi data ... --apply` 或创建 marker。真实 projection-hit 性能 `<200ms` 属于后续明确授权的本地 Runtime read-only manual acceptance，不在普通 pytest 中用 timing sleep 伪造。

EMA21 10K slope 与整体退役合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_subing_retirement.py \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py
```

SuBing S1-S4 公式、同物理合约 replay、Alert dispatch/Event/notification 与 Scope activation 定向合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_config.py \
  services/quant-api/tests/test_alert_pushplus.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_subing_scope_activation.py
```

RQData session 首分钟锚点、0045 与 shadow repair 的定向合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_session_anchor_repair.py \
  services/quant-api/tests/alembic/test_session_anchor_migration.py \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_subing_scope_activation.py
```

这些测试只使用 fake provider、临时 Parquet/SQLite 与可选 isolated PostgreSQL；不会调用真实 RQData、切换
Canonical、写 production DB/Redis 或停止 Runtime。`prepare/publish --apply` 不是测试命令，分别需要新的单次
真实数据/维护授权。

Physical-contract warm-up（含 `--frequency 1d` 的 D1-only、`--frequency 1w` 的同源 D1 + W1、
`--frequency 15m` / `--frequency 60m` 的 1m dependency、空计划 scope hash 隔离、跨月日周整组发布与 fail-stop）、
同合约 Canonical + Live replay、CLI plan hash 与 projection invalidation：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py
```

该组测试仅使用 fake provider、临时 Catalog/Parquet 与临时路径。它不授权也不执行真实
`guiyi data contract-warmup --apply`；即使 dry-run 得到 plan hash，真实 RQData/Canonical apply 仍需
引用该 exact hash 的单次明确授权。

Canonical 不可变月发布的 storage、Catalog strict-read 与 manager 失败回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m "not isolated_postgresql" \
  services/quant-api/tests/data_foundation/test_storage.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py
```

真实 PostgreSQL 的提交前不可见、commit/rollback 与旧 reader 保留测试使用独立变量
`GUIYI_ISOLATED_PUBLICATION_DATABASE_URL`。运行前必须显式配置一次性隔离 PostgreSQL；仅允许
loopback、非 5432 端口与精确 database `guiyi_canonical_isolated_test`，不得使用生产连接或读取 `.env`。
测试在随机专用 schema 创建和清理测试表，不执行 production migration；变量未提供时 skip 不算验收通过。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/data_foundation/test_catalog_publication_postgresql.py
```

Isolated PostgreSQL 测试只能指向专用、空白、可销毁的数据库；未设置变量时不得运行：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic
```

0042 → 0043 → 0044 → 0045、disabled + empty-scope seed、session anchor 与 forward-only failure 的专用定向命令仍必须使用同一类隔离数据库：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py \
  services/quant-api/tests/alembic/test_subing_ths_alert_migration.py \
  services/quant-api/tests/alembic/test_session_anchor_migration.py
```

不得把 `guiyi-postgres`、production URL 或任何非空共享数据库用于 isolated PostgreSQL suite。dry-run、migration 测试与 activation 测试均不授权 production migration、Scope apply 或 Rule enable。

## Range Detector Lux V1

Range Detector 只验证 causal kernel、golden parity、v9 图表偏好、warm-up、primitive 与浏览器交互；不授权策略、Alert、数据写入或 Runtime promotion。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py

pnpm -C apps/quant-web exec node --test \
  tests/rangeDetectorLux.test.ts \
  tests/rangeDetectorGolden.test.ts \
  tests/rangeDetectorOverlayWarmup.test.ts \
  tests/rangeDetectorPrimitive.test.ts \
  tests/mainIndicators.test.ts \
  tests/kline-view-model.test.ts
```

## Web

候选只读预览的隔离 fixture Gate（不启动 8010/5174，不连接真实数据或正式 API）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -p no:cacheprovider -q \
  services/quant-api/tests/newow/test_candidate_preview.py
pnpm -C apps/quant-web exec node --test tests/candidatePreview.test.ts tests/marketSeries.test.ts tests/useNewowProduct.test.ts
PLAYWRIGHT_CANDIDATE_PREVIEW=1 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/candidate-preview.spec.mjs
```

浏览器 fixture 固定 5182，拦截业务请求并故意设置错误的旧 API/WS override，以验证隔离。
普通 dev/build 不启用预览；候选模式只供 dev server，禁止构建成 production bundle。
实际预览仅在本次明确启动/只读连接授权后，由 controller 确认干净 exact commit、共享 Catalog/Canonical
配置与无端口占用，再在同一候选代码根、沿用既有配置加载运行下面两个入口。时间值仅是用法示例，
须替换为本次选定值且两进程完全一致；不得创建第二份 Canonical 或修改 `.env`、launchd、正式服务。

```bash
GUIYI_CANDIDATE_PREVIEW=1 GUIYI_PREVIEW_AS_OF=2026-09-03T08:00:00Z \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m app.preview
GUIYI_PREVIEW_AS_OF=2026-09-03T08:00:00Z pnpm -C apps/quant-web dev:candidate
```

API 固定只绑定 `127.0.0.1:8010`，Web 固定 `127.0.0.1:5174`，端口占用直接失败。
启动后核对 `/api/preview/identity` 与横幅的 SHA/cutoff；改变代码后须停止候选进程并重新核对启动。
K线 `before` 是排他上界，牛哇保留既有 `as_of` completed 语义；首页投影/主力元数据与正式
Runtime health/当前事件不伪装成同一历史快照，各自保留响应时间戳。页面身份不匹配时不加载业务查询。
代理只允许既有两项正式 GET，其他请求返回 `PREVIEW_ROUTE_FORBIDDEN`，无 Live subscription。
停止候选进程即关闭预览；没有数据写入需要回滚，正式 Runtime 与 release Gate 不因预览通过而改变。

Newow P5 路由/偏好、typed section consumer、九组合图层、参考历史与解释面板定向回归：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowProductRoutes.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailPreferences.test.ts \
  tests/marketHomeRoute.test.ts \
  tests/marketHomePageRoute.test.ts \
  tests/marketHomeResource.test.ts \
  tests/MarketDetailPage.test.ts \
  tests/newowProductTypes.test.ts \
  tests/useNewowProduct.test.ts \
  tests/NewowProductChartStage.test.ts \
  tests/newowProductChartPrimitives.test.ts \
  tests/newowReferencePanel.test.ts \
  tests/newowExplanationPanel.test.ts \
  tests/NewowTrendChartStage.test.ts \
  tests/marketDetailController.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailShellComponents.test.ts
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

Newow P6 浏览器验收使用 tracked route-intercept fixture，覆盖九个 strategy×frequency 组合、409 单次恢复、429 不循环重试、参考分页/精确信号定位、解释 evidence-required、既有详情/Home 回归，以及桌面和 `390×844` 移动视口：

```bash
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs e2e/market-home.spec.mjs
```

全量 `test:e2e` 同样包含这些用例。route-intercept timing 只证明浏览器交互，不替代真实 MDS、真实工作站性能或页面原站 parity 验收。

SuBing Alert Rule/API/Event-backed `S↑/S↓` 与 Market Home 定向检查：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alertRuleOwnership.test.ts \
  tests/alerts.test.ts \
  tests/productCurrentAlertEvents.test.ts \
  tests/marketHomeTypes.test.ts \
  tests/marketHomeViewModel.test.ts \
  tests/marketHomeRoute.test.ts
```

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

Market Home targeted contracts、1280/1440/1920/2560 桌面与390兼容截图、60品种本地排序及三资源请求约束（受控 fixture，不连接生产）。`newow-product` fixture 严格限制默认 origin `http://127.0.0.1:5182`，与其合跑时不覆盖端口；仅首页/详情可使用独立测试端口：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketHomeTypes.test.ts \
  tests/marketHomeIcons.test.ts \
  tests/marketHomeViewModel.test.ts \
  tests/marketHomeResource.test.ts \
  tests/marketHomeWorkspace.test.ts \
  tests/marketHomePreferences.test.ts \
  tests/marketHomePresentation.test.ts \
  tests/marketHomePageRoute.test.ts \
  tests/marketHomeRoute.test.ts
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-home.spec.mjs
```

## 工程一致性与静态检查

Newow 白色详情 V2 的 MACD 只读适配、同身份图表和交互验收（内存 fixture，不连接生产）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_product_macd.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_product_readonly_compatibility.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py
pnpm -C apps/quant-web exec node --test \
  tests/newowProductTypes.test.ts tests/newowProductChartPrimitives.test.ts \
  tests/NewowProductChartStage.test.ts tests/useNewowProduct.test.ts \
  tests/newowReferencePanel.test.ts tests/newowExplanationPanel.test.ts \
  tests/newowDetailPresentation.test.ts tests/useNewowDailyQuote.test.ts
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs \
  e2e/market-home.spec.mjs e2e/market-detail.spec.mjs
```

上述 V2 测试入口已随实现提供；实际通过状态以本次命令结果为准，不代表发布或 Runtime 验收。
MACD 视觉 fixture 通过既有 Python 内核预生成，保留真实参数 hash 与同区段 Bar 输入；修改受控
输入后先去掉 `--check` 重新生成，再运行下述一致性检查与浏览器截图复核：

```bash
PYTHONPATH=packages/quant-core uv run --project services/quant-api python \
  apps/quant-web/e2e/fixtures/generate_newow_macd.py --check
```

浏览器原站观察只用于设计依据；受控截图与 API fixture 不证明真实工作站或原站完整 parity。

苏冰当日缺口、恢复水位、只读诊断及日志：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_live_recovery.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_recovery_boundary.py \
  services/quant-api/tests/test_live_recovery_guard.py \
  services/quant-api/tests/test_subing_readiness.py \
  services/quant-api/tests/test_runtime_logging.py
```

实际 Lua 测试仅接受显式 `GUIYI_TEST_REDIS_PORT` 指向一次性、无持久卷的隔离 Redis；不得填生产端口。
未配置时该项明确 skip，其余测试使用内存 provider/Redis、临时 SQLite/Parquet 与进程锁。测试不运行
现役 Runtime，不调用真实 RQData，不发送通知。

逐品种诊断命令为 `guiyi runtime subing-readiness --trading-day YYYY-MM-DD --as-of OFFSET_DATETIME`；
`as-of` 必须带时区且不晚于执行时刻。命令只读 PostgreSQL/Redis/Canonical，逐品种报告当前输入与 Scope，
非全部 ready 时退出 1；参数错误退出 2。该结果不证明 provider acceptance 或实际收件，真实连接仍须
位于用户明确授权的只读诊断范围。生产只读执行还必须使用与现役服务启动器相同的 authenticated
`REDIS_URL` 解析结果；只加载未提供该连接结果的 `project.env` 会在订阅快照读取处产生 Redis
authentication failure，此时外层的 `INPUT_DIAGNOSIS_UNAVAILABLE` 不是行情缺口或逐品种 readiness 结论。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

上述 repository-hygiene 命令只检查 Git tree、canonical identity 和安全边界，不授权 branch 删除、Issue/PR 修改、Release、Runtime 或生产写入。

项目 Codex 配置与危险 Git 前缀规则使用当前本机 CLI 做只读检查；`execpolicy check` 只解析参数，不执行命令：

```bash
codex --version
codex execpolicy check --pretty --rules .codex/rules/workflow.rules -- git push --force origin develop
codex execpolicy check --pretty --rules .codex/rules/workflow.rules -- git push --force-with-lease origin develop
codex execpolicy check --pretty --rules .codex/rules/workflow.rules -- git push -f origin develop
codex execpolicy check --pretty --rules .codex/rules/workflow.rules -- git push origin develop
codex execpolicy check --pretty --rules .codex/rules/workflow.rules -- git push origin develop --force
```

前三项必须为 `forbidden`，普通 push 与 flag 后置样例必须无匹配。该规则只覆盖列出的精确参数前缀，
不声称识别 `git -c`、绝对 executable、wrapper 或所有语义等价写法；仓库规则也不覆盖宿主安全控制。

Newow 复刻手册使用独立、锁定的文档工具环境重建：

```bash
uv sync --project tools/docs --locked
uv run --project tools/docs python scripts/docs/build_newow_replication_manual.py \
  --source docs/research/newow-v3.2.82/REPLICATION_MANUAL.md \
  --output output/pdf/newow-v3.2.82-futures-replication-manual.pdf
```

Runtime health、data audit 与 alert status 是只读入口，不能推导 Runtime promotion、自然 evidence 或外部操作授权。`guiyi runtime acknowledge-alert-notification --failure-at <exact ISO timestamp>` 是受控 Redis 写入，普通验证只运行对应 pytest，不执行该命令。


## 捕获源文件的有界 Live 恢复

代码验证在独立 worktree 的 `services/quant-api` 执行。测试使用合成 fixture、临时目录及内存 SQLite，
不读取生产配置、不调用 RQData、不写生产数据；实际 Lua 测试须显式设置 `GUIYI_TEST_REDIS_PORT`
指向本次创建、无持久卷且非 6379 的一次性 Redis，不得使用生产连接。

```bash
.venv/bin/python -m pytest tests/data_foundation/test_captured_live_recovery.py tests/data_foundation/test_live_recovery.py tests/test_live_recovery_guard.py tests/test_captured_recovery_cli.py tests/test_captured_recovery_runtime.py tests/test_alert_cli.py tests/test_subing_readiness.py tests/test_subing_ths_kernel.py -q
```

以下为人工操作语法，普通测试不得执行。CLI 默认只读，但连接生产前仍须明确只读范围。
须先部署通过审查的新 exact tag，证明 Live/Alert/After-market 同根同 commit、共享锁已启用、Live/Alert 心跳新鲜；开发 worktree
和 v1.10.3 的旧心跳不满足该 Gate。`test_captured_recovery_runtime.py` 包含 launchd 定时触发
`=> {` 与 `= {` 混合嵌套回归，验证 idle/waiting/running、字段层级、重复身份和括号不平衡拒绝。
源文件必须来自已授权查询，不能为了运行此命令临时下载。

```text
guiyi runtime recover-live-captured --trading-day YYYY-MM-DD --symbol rs --contract RS2609 --source /absolute/captured-source.json --source-sha256 SOURCE_SHA256
```

将上述完整 JSON 输出保存为计划文件后，重新核对五根目标及水位/TTL 副作用，并取得一次明确 apply
授权；下列命令不构成授权，也不会部署/切换 Runtime：

```text
guiyi runtime recover-live-captured --trading-day YYYY-MM-DD --symbol rs --contract RS2609 --source /absolute/captured-source.json --source-sha256 SOURCE_SHA256 --apply --plan /absolute/plan.json --plan-sha256 PLAN_SHA256
```

日期、两种哈希和路径均须替换为当前仍有效的精确计划值，不允许沿用已过期的 2026-09-08 候选。
源和计划读取均有 512 KiB 上限；每次至多 225 行源数据，必须恰好五根增量。
成功返回 `passed`，证明已修复的重复调用仅只读 `noop`；错误非零退出，禁止自动重试。
验收核对五根/原值、恢复水位、provider 请求为零、预算/circuit 未变，再走独立只读 readiness；
不调用历史 evaluator、不重置错误或游标、不发送测试通知，不能由恢复成功宣称 RUNTIME_READY。
