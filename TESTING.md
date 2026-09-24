# 测试与验证命令

以下命令区分隔离测试、现场只读和受控操作用法；示例本身不授予生产操作权限。
授权统一按 `AGENTS.md`：任务内只读诊断和隔离开发预览自主执行；真实 provider、生产写入、发布与 Runtime
须在明确任务/批次范围内。有效授权可跨会话恢复；批次内不逐命令审批，exact hash、锁和质量校验保持不变。

## 开盘恢复队列与预警合约身份

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/data_foundation/test_live_recovery.py \
  services/quant-api/tests/data_foundation/test_live_recovery_queue.py \
  services/quant-api/tests/data_foundation/test_live_recovery_concurrency.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_recovery_boundary.py \
  services/quant-api/tests/test_subing_readiness.py \
  services/quant-api/tests/test_live_recovery_guard.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_runtime_health.py
```

使用仓库自有合成fixture和假时钟验证60品种/45缺口慢队列、新鲜轮次收敛、过期预算不变、
真实尝试超时仍计数及恢复前旧cutoff不具备通知资格。typed Live读取覆盖错误/缺失合约、错误交易日、
重复端点、截止点边界与合法跨历史owner。不得依赖生产数据或Git外审计文件，也不使用真实等待模拟延迟。
Lua项仅按下文`GUIYI_TEST_REDIS_PORT`规则使用本次新建的非6379、无持久卷一次性Redis；未配置时skip不算通过。

活动 Session 组使用线程事件选择确定性交错及真实文件锁，验证 JM5m/JM15m/RB60m/RB15m 正常通知资格、
一致追加后剩余缺口恢复、全部补齐不推进水位、原事实漂移拒绝、busy pending 与跨品种继续、正常 flush 后调度。
异常组覆盖 pending/provider 两个 flush 位置的锁获取失败，以及三条调度路径的 authority/worker 失败，
确认统一不可用、保留 pending 和健康 provider、不误触发重连。
释放故障使用真实文件锁和定点 OS 错误，覆盖 pending/provider/cooldown/BREAK、close 实际关闭前后报错，
在测试手工清理 fd 之前验证锁可再入、重复 Bar 不发布及下一分钟继续写入；独立锁测试还覆盖 unlock 失败仍关闭。
同一组默认运行内存 Redis；显式配置专用 Redis 时还会运行真实 Lua 版本，只清理该一次性实例的测试 DB 9。
既有 Lua 原子性测试仍在最终重读后注入变更，验证 CAS 不会容忍提交前的再次漂移。

```bash
GUIYI_TEST_REDIS_PORT=<专用非6379端口> PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/data_foundation/test_live_recovery_concurrency.py \
  services/quant-api/tests/data_foundation/test_live_recovery.py::test_lua_atomic_commit_and_concurrent_live_conflict_on_isolated_redis \
  services/quant-api/tests/test_live_recovery_guard.py
```


## Newow 初始无入场 CLEAR v2（实施验收）

以下组验证已实现的 `INITIAL_CLEAR_NO_ENTRY` v2 合同；离线通过不替代固定 PT 截点的生产只读验收 Gate。
在本任务隔离树中执行，Python/Node 使用已有环境；依赖路径若不同，先确认解释器和本树源码导入身份。

Core/投影 RED→GREEN 与公式金样：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_product_contracts.py \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_reference_statistics.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py \
  services/quant-api/tests/newow/test_main_rise_page_v1.py
```

API、token/cursor、旧入口兼容：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py \
  services/quant-api/tests/newow/test_product_readonly_compatibility.py \
  services/quant-api/tests/newow/test_older_chart_windows.py \
  services/quant-api/tests/newow/test_historical_snapshot.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/newowProductTypes.test.ts tests/newowProductChartPrimitives.test.ts tests/NewowProductChartStage.test.ts tests/useNewowProduct.test.ts tests/newowReferencePanel.test.ts
```

共享 v2 迁移后的模块回归和静态检查：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow tests/engineering/test_repository_hygiene.py tests/engineering/test_canonical_consistency.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Ruff/Mypy 沿用下方 Newow Core/API 专项配置，限实际修改的生产模块；不降低现有检查规则。
浏览器执行本文件“Newow 新版参考卡片定向验证”的三个 fixture E2E（product/detail-light/chart-panes），
加上本功能新用例；仅使用空闲隔离端口，正常验收不带 `--update-snapshots`。明确核验 Marker 点击后可见
“清仓（无入场）”、详情解释、零交易空态、后续真实交易定位与旧响应失效。

以下现场命令仅在当前任务的真实只读连接获准后执行；固定已冻结截点，不调用 provider、不提供修复开关：

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/guiyi data newow-readiness \
  --symbol pt --frequency 1w --as-of 2026-09-13T06:36:13+00:00 --matrix --max-work 10000 --timeout-seconds 300
```

验收检查 main 3/3 READY、main_rise chart/reference 无 pairing failure、新资格 CLEAR 与零伪造交易；
通过既有 MDS/product service 的有界只读结果补齐 CLI 未公开的 Action/Trade 证据。provider_requests/writes
必须为 0，explanation 继续 UNOPENED，comparator 正常样本不足独立披露。不能用报告 exit 0 替代逐项判定。
此前两笔 PT apply 不重跑；权限不足时保留现场 Gate，继续完成离线工程验收。

## Newow 周线剩余工程收口

确定性验收脚本只有两个模式：`summary` 只离线读取显式完整 JSON 和冻结 scope；`pt` 只在一个
`readonly_transaction` 中读取固定 `pt/main_rise/1w` chart 与同 snapshot reference。两者均无 provider、
repair、apply 或通知能力。先验证 parser 与离线行为：

```bash
PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python \
  scripts/newow_weekly_acceptance.py --help
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_weekly_acceptance.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py \
  services/quant-api/tests/newow/test_product_readonly_compatibility.py
PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python \
  scripts/newow_weekly_acceptance.py summary \
  --report /absolute/full-readiness.json \
  --scope data/universe/operational_products.txt \
  --expected-as-of 2026-09-13T06:36:13+00:00
```

以下是任务范围内可自主执行的生产只读现场命令，不构成写入、重试或 Runtime 授权。完整报告 stdout 必须保存到
本任务新的显式 evidence 文件；summary 只读取该同一文件，不得用 `--compact` 再查询一次。维护锁忙、现场失败、
预算耗尽或代码修复后均停止，不循环复跑。

```bash
PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python \
  scripts/newow_weekly_acceptance.py pt
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/guiyi \
  data newow-readiness --universe operational --frequency 1w --frequency 1d --matrix \
  --as-of 2026-09-13T06:36:13+00:00 --max-work 100000 --timeout-seconds 1800
```

## Newow 日线候选工程（仅 1d 开放，1w/60m 为 UNOPENED）

以下组验证日版 capability v2、恢复器严格单频 1d、跨频 plan/hash 隔离、close 与 settlement 分离。
不授权 RQData 下载、Canonical 写入或 Runtime。真实 D1 总包 prepare/apply 仍走独立 Gate。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_candidate_preview.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/newow/test_weekly_acceptance.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py \
  services/quant-api/tests/newow/test_weekly_recovery_campaign.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py::test_rqdata_daily_keeps_close_independent_from_settlement \
  services/quant-api/tests/data_foundation/test_infrastructure.py::test_rqdata_daily_rejects_partial_or_traded_zero_ohl \
  services/quant-api/tests/data_foundation/test_infrastructure.py::test_rqdata_daily_adapter_uses_exchange_daily_zero_trade_ohlc
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test \
  tests/newowProductTypes.test.ts tests/newowCapabilities.test.ts tests/newowProductRoutes.test.ts
```

D1 只读差量必须绑定 private Canonical 根；完整原生 report 才是 campaign prepare 依据，compact 不得裁剪缺 authority 的清单。

UI 依赖整合后的完整 Web 验收：

```bash
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
env -u NO_COLOR -u FORCE_COLOR pnpm_config_verify_deps_before_run=false \
  pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs e2e/newow-product.spec.mjs \
  e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs
```

脚本 exit 0 只证明 PT 合同检查或完整 JSON 结构/计数校验通过；`audit_complete`、180 case 覆盖、
chart/reference 联合 READY 与真实页面回读仍分别报告，不因 known gap、WARMING、NOT_APPLICABLE 或
UNOPENED 被改写为全 READY。

## 首页返回恢复、消息与分钟行情

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/test_alert_history_api.py \
  services/quant-api/tests/data_foundation/test_market_home_live.py \
  services/quant-api/tests/data_foundation/test_market_home_live_websocket.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_market_pagination.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
env -u VITE_API_BASE_URL -u VITE_MARKET_WS_URL REAL_BACKEND=0 \
  PLAYWRIGHT_PORT=5182 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5182 \
  PLAYWRIGHT_CANDIDATE_PREVIEW=0 PLAYWRIGHT_SKIP_WEBSERVER= \
  pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs e2e/market-home.spec.mjs
```

后端使用 fake Redis、临时数据库与测试 Bar，验证固定 operational 批量订阅、先订阅后快照、
同合约昨收、缺失/零基准、收盘保持、乱序与身份 reset、同日恢复、资源释放及历史消息稳定分页。
Web 验证返回保留列表和位置、有效快照不重复加载、过期后台刷新、消息查询与独立错误、SVG/键盘
导航及单连接 overlay。浏览器 fixture 只证明代码行为；生产收件、自然 completed 1m、休市真实
数据与 Runtime 版本仍需独立读回。不得把当前正式 API 尚未提供的新端点用模拟数据补成可用。

共享依赖的隔离 worktree 可以使用既有 Python 环境并显式设置本树 PYTHONPATH，不提交环境 symlink。
5182 必须空闲，禁止复用其他工作区服务。新行情只读连接与本地开发服务不授权启动 provider、
修改 production Scope、发送通知或切换正式 Runtime。

## Newow 历史恢复通用边界

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/data_foundation \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py
```

覆盖周五夜盘首边界、未完成尾周、逐日交易所夜盘证据、来源全集身份和生命周期、局部无夜盘不得覆盖共享 Calendar，以及元数据提交结果不明时停止并独立回读。隔离工作树可显式使用既有 Python 环境；这些离线检查不代表实际历史补齐、未来 Calendar 自动扩展或浏览器验收。
`newow-readiness --universe operational --frequency 1w` 只审计周版及其 D1 companion；`--compact`
只生成 Gate 索引，默认完整结果仍用于逐 dependency 与原生 plan 核对。真实 Catalog/Canonical 只读审计在任务范围内自主执行，且即使结果为 `audited` 也不授权任何 `--apply`。

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
真实历史读取、发布和 Runtime 验收单独报告；生产只读诊断按任务范围自主执行，测试不授权外部写入。

## Unified Reference Trading P3 仓储

纯 DTO、严格 seed/checkpoint、原子批次和内部快照测试可在无外部服务时运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading \
  services/quant-api/tests/alembic/test_reference_trading_migration.py \
  -m 'not isolated_postgresql'
```

真实行锁、双 writer、故障回滚、NUMERIC 与 migration DDL 必须在本任务专用空白可销毁 PostgreSQL 运行；
沿用下文 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` guard，变量缺失导致的 skip 不算 P3 验收通过：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/isolated_test_db' \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading/test_repository_postgresql.py \
  services/quant-api/tests/alembic/test_reference_trading_migration.py \
  -m isolated_postgresql
```

这两组测试不加载生产 `.env`，不执行生产 migration，不创建 enabled stream，也不连接 RQData、Canonical、
Redis、通知或 Runtime。

## Unified Reference Trading P4 历史构建

P4 的严格 plan、MDS typed input、candidate build/resume、append/rebuild、边界事件、CLI 和临时
Canonical/Catalog/MDS 接线使用：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading -m 'not isolated_postgresql'
```

该入口覆盖重叠 owner warm-up、无物理 Bar 的 rollover/PRICE_UNAVAILABLE boundary、跨包 OPEN、伪造 resume
位置、同分区追加、旧 OHLCV 修订、未知 commit/publish readback、任务级单调 elapsed budget，以及 9 个 Newow
和 4 个 SuBing 策略周期的临时真实 MDS 读取。真正 PostgreSQL 的并发、事务与 migration 仍必须使用上一节
`GUIYI_ISOLATED_MIGRATION_DATABASE_URL` 入口；环境变量缺失导致的 skip 不算通过。所有 P4 测试均不授权或执行
生产 migration/bootstrap、Canonical/provider 写入、HTTP/Web、worker、通知或 Runtime。

## Unified Reference Trading P8 隔离验收

先核对测试工作树、`develop` 基线及专用一次性依赖。P8 PostgreSQL 必须是新建空白可销毁实例、
loopback 非 5432 端口和独立 `guiyi_reference_isolated_test` 数据库；Redis 必须是无持久卷的
loopback 非 6379 实例。不得读取生产 `.env`、复用现役 5432/6379 或把 skip 计为通过。
真实 PostgreSQL 测试各自在随机 schema 建表并仅删除自己的 schema。

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading/test_historical_integration.py \
  services/quant-api/tests/reference_trading/test_newow_worker_recovery.py \
  services/quant-api/tests/reference_trading/test_forward_capacity_postgresql.py \
  services/quant-api/tests/reference_trading/test_forward_query.py \
  services/quant-api/tests/reference_trading/test_query_capacity_postgresql.py \
  services/quant-api/tests/reference_trading/test_repository_postgresql.py \
  services/quant-api/tests/reference_trading/test_query_postgresql.py \
  services/quant-api/tests/alembic/test_reference_trading_migration.py \
  services/quant-api/tests/alembic/test_reference_forward_migration.py \
  -m isolated_postgresql
GUIYI_ISOLATED_REDIS_URL='redis://127.0.0.1:PORT/0' \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading/test_live_wake.py
```

真实存储 pipeline/recovery、60/300 条 fixture 流、300 条临时 Canonical→Catalog→MDS 流和 synthetic 100/1000/10000 行查询工具只接受独立测试库、
loopback 非 5432 端口、无 libpq 环境路由覆盖和临时目录输出。每次启动五个独立进程；
`historical_13_streams` 与 `forward_recovery` 耗时不代表 60/300 流容量，
`query_*` 行是直接构建的查询负载，不代表策略计算结果。原始 JSON、缺口和固定目标见
`docs/tasks/unified-reference-trading-p8/acceptance.md`。

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  services/quant-api/.venv/bin/python scripts/reference_trading_benchmark.py \
  --case historical_13_streams --repeats 5 --timeout-seconds 120
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  services/quant-api/.venv/bin/python scripts/reference_trading_benchmark.py \
  --case forward_recovery --repeats 5 --timeout-seconds 120
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  services/quant-api/.venv/bin/python scripts/reference_trading_benchmark.py \
  --case query_10000 --repeats 5 --timeout-seconds 180
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  services/quant-api/.venv/bin/python scripts/reference_trading_benchmark.py \
  --case stream_300_mds --repeats 5 --timeout-seconds 120
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  services/quant-api/.venv/bin/python scripts/reference_trading_benchmark.py \
  --case query_real_rebuild_10000 --repeats 5 --timeout-seconds 300
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/guiyi_reference_isolated_test' \
  services/quant-api/.venv/bin/python -m pytest -q -s -m isolated_postgresql \
  services/quant-api/tests/reference_trading/test_forward_capacity_postgresql.py::test_postgresql_300_mds_same_process_rss_soak
```

同一入口还接受 `--case query_100` 和 `--case query_1000`，分别保存对应 JSON。
`--case stream_60` 和 `--case stream_300` 分别测量 typed capture 持久化及真实 kernel worker
投影；它们不测 60/300 条真实 MDS 行情采集。D1/W1 有界增量的逐值与最多四个物理
分区断言在 `test_historical_integration.py`，含 45 天过期窗口拒绝和未完成日不读取。
`--case stream_300_mds` 对每条流读取临时 Canonical 经 Catalog/rank-1/MDS 的页面，
HTDY 再读取 32 Bar 上下文；其测试适配器把历史夹具包装成完成观察，不能替代真实 Live/Runtime 验收。
`query_real_rebuild_10000` 用真实策略输出、修改价格后的第二版、旧 cutoff 和每轮 100 次热查询检验查询容量；
同进程浸泡在五个独立临时 schema 中重复等量 300 流，记录每轮回收后的 RSS。

真实浏览器验收只连接上述一次性 PostgreSQL 测试库。先在单独终端运行
`PYTHONPATH=.:services/quant-api:services/quant-api/tests:packages/quant-core`
加上同一 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`，执行
`services/quant-api/.venv/bin/python scripts/reference_trading_browser_fixture.py`；
再运行 `pnpm -C apps/quant-web exec vite --config vite.p8.config.ts`，用真实浏览器打开
`http://127.0.0.1:5178/p8-reference-acceptance.html`。此页面挂载实际
`ReferenceTradePanel` 并经 Vite proxy 请求实际 FastAPI 和隔离 PostgreSQL，未拦截 API；
组件页用于组件/API/持久化闭环。完整 Market 路由验收改为打开
`http://127.0.0.1:5178/market/chart?symbol=rb&view=newow&frequency=1d`，按夹具日期
2026-01-05–03-27 设置 Newow 与 SuBing legacy 窗口，再切换 SuBing/HTDY 标签；
默认当前日期超出生成数据窗口时的 typed error 不算夹具内成功读回。退出两台服务后
脚本仅删除它创建的随机 schema 和临时 Canonical 文件。

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

### 牛哇周线与日线有界恢复入口

以下验证全部使用 fake provider、SQLite 和临时目录；不得把 production 下载当作测试。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/newow/test_weekly_recovery.py \
  services/quant-api/tests/newow/test_weekly_source_verify.py \
  services/quant-api/tests/newow/test_weekly_recovery_campaign.py \
  services/quant-api/tests/newow/test_recovery_partial_exception.py \
  services/quant-api/tests/newow/test_daily_recovery_verification.py \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py
uv run --project services/quant-api python -m ruff check \
  scripts/newow_weekly_recovery.py \
  scripts/newow_weekly_source_verify.py \
  scripts/newow_weekly_recovery_campaign.py \
  scripts/newow_daily_recovery_verification.py \
  scripts/newow_recovery_partial_exception.py \
  services/quant-api/app/market_data/rqdata_adapter.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/newow/test_weekly_recovery.py \
  services/quant-api/tests/newow/test_weekly_source_verify.py \
  services/quant-api/tests/newow/test_weekly_recovery_campaign.py \
  services/quant-api/tests/newow/test_recovery_partial_exception.py \
  services/quant-api/tests/newow/test_daily_recovery_verification.py \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/newow/test_readiness.py
PYTHONPATH=.:services/quant-api:packages/quant-core \
  MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports \
  services/quant-api/app/market_data/rqdata_adapter.py \
  services/quant-api/app/market_data/composition.py \
  scripts/newow_weekly_recovery.py \
  scripts/newow_weekly_source_verify.py \
  scripts/newow_weekly_recovery_campaign.py \
  scripts/newow_daily_recovery_verification.py \
  scripts/newow_recovery_partial_exception.py
```

单请求来源取证先对已冻结 prepared manifest 做零 provider 预检。`execute` 会再次校验 clean exact commit、
execution digest、配置/Canonical 身份、完整当前 plan 和 maintenance lock，最多发起一个冻结请求；收到响应后
先保存其原始响应。它不调用 manager apply，响应语义必须后续按 timestamp 离线审查：

```bash
: "${NEWOW_SOURCE_PROJECT_ENV:?set project env path}"
: "${NEWOW_SOURCE_PREPARED:?set prepared manifest path}"
: "${NEWOW_SOURCE_PREPARED_SHA256:?set prepared manifest sha256}"
: "${NEWOW_SOURCE_REQUEST_SHA256:?set exact request sha256}"
: "${NEWOW_SOURCE_OUTPUT_ROOT:?set fixed evidence root}"
: "${NEWOW_SOURCE_ATTEMPT_ID:?set one new attempt id}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_source_verify preflight \
  --project-env "$NEWOW_SOURCE_PROJECT_ENV" \
  --prepared "$NEWOW_SOURCE_PREPARED" \
  --expected-prepared-sha256 "$NEWOW_SOURCE_PREPARED_SHA256" \
  --unit-index 0 \
  --request-index 1 \
  --expected-request-sha256 "$NEWOW_SOURCE_REQUEST_SHA256" \
  --output-root "$NEWOW_SOURCE_OUTPUT_ROOT" \
  --attempt-id "$NEWOW_SOURCE_ATTEMPT_ID"
```

`execute` 是一次真实来源查询 Gate。只有 owner 对上述 prepared/request hash、固定 attempt 和 exact command
明确授权后才运行；未知结果不重试：

```bash
PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_source_verify execute \
  --project-env "$NEWOW_SOURCE_PROJECT_ENV" \
  --prepared "$NEWOW_SOURCE_PREPARED" \
  --expected-prepared-sha256 "$NEWOW_SOURCE_PREPARED_SHA256" \
  --unit-index 0 \
  --request-index 1 \
  --expected-request-sha256 "$NEWOW_SOURCE_REQUEST_SHA256" \
  --output-root "$NEWOW_SOURCE_OUTPUT_ROOT" \
  --attempt-id "$NEWOW_SOURCE_ATTEMPT_ID" \
  --execute-source-query
```

总包 CLI 保持 `prepare / apply / inspect` 三阶段。`prepare` 缺省为既有 W1；显式 `--frequency 1d`
生成独立 D1 schema，并且每个子包只含 physical contract `1d` target。下面命令依赖调用者先设置任务专用变量，仓库不记录
production 路径、hash 或 attempt 身份：

```bash
: "${NEWOW_CAMPAIGN_PROJECT_ENV:?set project env path}"
: "${NEWOW_CAMPAIGN_REPORT:?set full readiness report path}"
: "${NEWOW_CAMPAIGN_REPORT_SHA256:?set exact report sha256}"
: "${NEWOW_CAMPAIGN_OUTPUT_ROOT:?set one fixed evidence root}"
: "${NEWOW_CAMPAIGN_NAME:?set campaign name}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_recovery_campaign prepare \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --report "$NEWOW_CAMPAIGN_REPORT" \
  --expected-report-sha256 "$NEWOW_CAMPAIGN_REPORT_SHA256" \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --name "$NEWOW_CAMPAIGN_NAME"
```

冻结 D1 总包时只在上述 `prepare` 命令末尾增加 `--frequency 1d`。该动作仍是只读 prepare，不初始化
provider；其输入必须是完整、未耗尽预算、`frequency_scope=[1d]` 且 `matrix=false` 的原生 readiness
报告。W1 与 D1 的 policy、manifest、result、invocation 和 prior-isolation hash 均不可互换。

`apply` 是一次受控真实写入 Gate；只有 owner 对精确 campaign hash 和 attempt 明确授权后才运行：

需要按已批准设计隔离单元级来源质量异常时，必须在新的 `prepare` 显式加入
`--isolate-known-source-quality`；无此选项保持原有首次失败停批。当前 allowlist 仅为
`RQDATA_ZERO_OHL_INVALID`，仍须通过零提交、来源 artifact/journal 和原计划未变的完整校验。
若要避免重复下载旧尝试中已证实的来源异常，同时传入以下三个参数；不能只提供其中一部分，
也不能用手工合约名单替代原执行证据。例子只做只读准备，不代表 apply 授权：

```bash
: "${NEWOW_PRIOR_CAMPAIGN:?set prior campaign manifest path}"
: "${NEWOW_PRIOR_CAMPAIGN_SHA256:?set prior campaign sha256}"
: "${NEWOW_PRIOR_ATTEMPT:?set prior attempt path}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_recovery_campaign prepare \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --report "$NEWOW_CAMPAIGN_REPORT" \
  --expected-report-sha256 "$NEWOW_CAMPAIGN_REPORT_SHA256" \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --name "$NEWOW_CAMPAIGN_NAME" \
  --isolate-known-source-quality \
  --prior-campaign "$NEWOW_PRIOR_CAMPAIGN" \
  --expected-prior-campaign-sha256 "$NEWOW_PRIOR_CAMPAIGN_SHA256" \
  --prior-attempt "$NEWOW_PRIOR_ATTEMPT"
```

若异常只由一次独立 source-only 查询证明、并无可复用的旧 campaign/attempt，则必须改为传入完整的
source-only prepared、attempt、单元索引、请求索引和请求 hash。prepare 会重新验证 invocation、journal、
保存响应、失败分类、零写入约束，并用当前原生 adapter 逐行重放 allowlist 异常；任一 artifact 漂移都会
在创建子包前失败。该证据只隔离一个与当前完整 audit 精确同 identity/plan 的单元：

source-only 导入时，`attempt` 必须与落盘 outcome 的 canonical JSON 完全一致；请求上限、重试数和
Canonical/数据库写入数必须是 JSON integer，布尔值或浮点数即使数值相等也拒绝。原生零提交重规划的
`target_windows` 同样按 canonical JSON 比较，以兼容进程内 tuple 与落盘 JSON list 的容器差异，同时继续
逐字段约束 dataset、窗口、计数和值；隔离证据失败时只持久化固定的
`SOURCE_ISOLATION_EVIDENCE_FAILED` 或 `SOURCE_ISOLATION_READBACK_FAILED`，不写入异常原文。

```bash
: "${NEWOW_SOURCE_PREPARED:?set exact source-only prepared path}"
: "${NEWOW_SOURCE_PREPARED_SHA256:?set exact source-only prepared sha256}"
: "${NEWOW_SOURCE_ATTEMPT:?set completed source-only attempt path}"
: "${NEWOW_SOURCE_UNIT_INDEX:?set zero-based unit index}"
: "${NEWOW_SOURCE_REQUEST_INDEX:?set zero-based request index}"
: "${NEWOW_SOURCE_REQUEST_SHA256:?set exact source request sha256}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_recovery_campaign prepare \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --report "$NEWOW_CAMPAIGN_REPORT" \
  --expected-report-sha256 "$NEWOW_CAMPAIGN_REPORT_SHA256" \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --name "$NEWOW_CAMPAIGN_NAME" \
  --isolate-known-source-quality \
  --source-only-prepared "$NEWOW_SOURCE_PREPARED" \
  --expected-source-only-prepared-sha256 "$NEWOW_SOURCE_PREPARED_SHA256" \
  --source-only-attempt "$NEWOW_SOURCE_ATTEMPT" \
  --source-only-unit-index "$NEWOW_SOURCE_UNIT_INDEX" \
  --source-only-request-index "$NEWOW_SOURCE_REQUEST_INDEX" \
  --expected-source-only-request-sha256 "$NEWOW_SOURCE_REQUEST_SHA256"
```

上述 source-only 导入仍为 W1 专用；D1 prepare 对其任一参数 fail-closed，只允许复核同 profile D1
campaign 中已完整证明的零提交隔离，不自动跨 W1 导入来源证据。

若上次 W1 apply 在部分提交后命中权威来源 `RQDATA_ZERO_OHL_INVALID`，不得把该单元记为
zero-commit isolation 或 success。prepare 从显式失败 attempt 自动派生
`prior_partial_source_exceptions`；该单元仍计入未完成分母，不进入 executable ordinary
units，也不伪装 `DATA_READY`。prepare 会重放已保存来源响应、核验已提交月份的 Catalog /
Parquet / MDS 读回，并要求当前 fresh replan 是扣除已提交目标后的严格子集。不得手写合约排除名单，
也不得初始化 provider：

```bash
: "${NEWOW_PARTIAL_EXCEPTION_ATTEMPT:?set the failed W1 apply attempt directory}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_recovery_campaign prepare \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --report "$NEWOW_CAMPAIGN_REPORT" \
  --expected-report-sha256 "$NEWOW_CAMPAIGN_REPORT_SHA256" \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --name "$NEWOW_CAMPAIGN_NAME" \
  --isolate-known-source-quality \
  --partial-source-exception-attempt "$NEWOW_PARTIAL_EXCEPTION_ATTEMPT"
```

D1 不接受 `--partial-source-exception-attempt`，也拒绝从 prior campaign 间接携带 W1 partial receipt；
日线任一部分提交、commit unknown 或读回不明都停批，并在新的完整只读审计后另行冻结剩余范围。

新策略和旧来源排除证据均进入新 manifest hash，apply 不接受临时覆盖策略。隔离对象继续计入未完成分母；
额度、网络、锁冲突、身份漂移、提交未知、读回/清理或证据失败仍全局停止。真实 apply 命令如下：

```bash
: "${NEWOW_CAMPAIGN_SHA256:?set exact campaign sha256}"
: "${NEWOW_CAMPAIGN_ATTEMPT_ID:?set one new attempt id}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_recovery_campaign apply \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --campaign "$NEWOW_CAMPAIGN_OUTPUT_ROOT/$NEWOW_CAMPAIGN_NAME.prepare.json" \
  --expected-campaign-sha256 "$NEWOW_CAMPAIGN_SHA256" \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --attempt-id "$NEWOW_CAMPAIGN_ATTEMPT_ID" \
  --apply

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_weekly_recovery_campaign inspect \
  --attempt "$NEWOW_CAMPAIGN_OUTPUT_ROOT/$NEWOW_CAMPAIGN_ATTEMPT_ID"
```

D1 apply 会先保留 `campaign-execution.json`，再启动独立只读验证进程；验证先将该摘要重新绑定
`campaign-started`、`campaign-result`、逐批 terminal、native invocation/result 与 child hash，随后固定相同
`as_of`，对所有已处理的 passed、zero-commit isolation、known failed 和 unknown 单元重做分类保持的 D1
replan（只跳过明确 unattempted），并对完整 operational 品种运行 `matrix=false` 的 D1 readiness。验证还会
逐一以同一 `as_of` 和 snapshot token 比较 60 个品种默认 Chart/Comparator 的 D1 窗口、owner 与 replay
prefix；该运行证据缺失或不一致时不能输出 verified。验证失败、超时
或结果保存失败不改写执行结算，也不会重试、恢复或再次 apply；退出 0 仅表示执行结算明确、普通单元
全部完成且冻结 consumer 输入完整可用。后续只读重验可使用同一精确 campaign/execution hash 和新的
observation id，不覆盖旧观察：

```bash
: "${NEWOW_D1_CAMPAIGN:?set exact D1 campaign path}"
: "${NEWOW_D1_CAMPAIGN_SHA256:?set exact D1 campaign sha256}"
: "${NEWOW_D1_EXECUTION:?set exact campaign execution path}"
: "${NEWOW_D1_EXECUTION_SHA256:?set exact campaign execution sha256}"
: "${NEWOW_D1_VERIFICATION_ID:?set one new observation id}"

PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_daily_recovery_verification \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --campaign "$NEWOW_D1_CAMPAIGN" \
  --expected-campaign-sha256 "$NEWOW_D1_CAMPAIGN_SHA256" \
  --execution "$NEWOW_D1_EXECUTION" \
  --expected-execution-sha256 "$NEWOW_D1_EXECUTION_SHA256" \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --observation-id "$NEWOW_D1_VERIFICATION_ID"
```

若已校验的 D1 prepare 本身为 `status=completed`、普通分母为 0 且没有 child batch，不创建空
`campaign-execution.json`。使用同一完整 campaign hash 走显式 `not_required` 路径，仍执行完整 operational
D1 audit 与 Comparator 证明；对此 campaign 调用 `apply` 会在创建 attempt 前以
`D1_EXECUTION_NOT_REQUIRED` 拒绝：

```bash
PYTHONPATH=.:services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m scripts.newow_daily_recovery_verification \
  --project-env "$NEWOW_CAMPAIGN_PROJECT_ENV" \
  --campaign "$NEWOW_D1_CAMPAIGN" \
  --expected-campaign-sha256 "$NEWOW_D1_CAMPAIGN_SHA256" \
  --execution-not-required \
  --output-root "$NEWOW_CAMPAIGN_OUTPUT_ROOT" \
  --observation-id "$NEWOW_D1_VERIFICATION_ID"
```

验证器内部审计 deadline 固定 300 秒，父进程等待上限固定 330 秒，为结果关闭、校验与落盘保留有界余量。
父进程分别记录 timeout、非 0/1 进程码、缺失结果、空结果和损坏 JSON；这些状态都不改写已保存的执行终态，
不自动 retry。`verification.json` 与 `summary.md` 都先完整写入并 fsync 临时文件，再以原子 no-replace
发布到最终路径；并发同名目标会拒绝而不会覆盖。
正式 JSON 发布后立即结构化回读。测试入口：

```bash
PYTHONPATH=services/quant-api:. services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/newow/test_daily_recovery_verification.py \
  services/quant-api/tests/newow/test_weekly_recovery_campaign.py
```

以上 D1 `apply` 示例以及任何真实重验前的本地生产事实读取仍受各自精确 Gate 约束；本节测试命令
只使用 fake provider、SQLite 和临时目录，不证明现场数据已完成或 public D1 已开放。

`prepare` 只读读取锁定配置、Catalog、Calendar/Session 和 Canonical，要求 checkout clean 且 HEAD 精确，
输出 plan、执行代码、配置及 Canonical 根的非敏感身份；它不得初始化 provider。`apply` 同样要求 clean exact
commit，并在首次 provider 前保存绑定 prepared hash 的 invocation receipt。`apply` 是真实 RQData/Canonical/生产写入 Gate，只有
owner 对精确 prepared hash 和 attempt 明确给出一次执行意图后才可运行。默认任何失败或 unknown 都停止；
仅新 prepare 显式冻结的来源隔离策略允许在证据充分时继续独立单元，所有路径均不自动重试。
prepared 与 attempt 默认只写入已忽略的 `outputs/newow-weekly-recovery-attempts/`；除该专用 evidence 根外，
任何 tracked 或 untracked checkout 变化都会使 clean exact commit 门禁失败。

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
schema v5 另覆盖已停止的同日运行、缺失 snapshot 的未核验摘要、两读分类/内容竞争、非法 snapshot
拒绝，以及自然运行承接摘要但不继承成功；下文 promotion 和 Web 测试验证原通过条件与公开展示。

以下定向命令覆盖 Catalog-bounded daily 规划/发布、schema-v3 进度持久化与 fail-closed health、
`operational_full_history` 审计、HTTP schema 保留、launchd 渲染/安装防护和只读状态输出。它们使用 fake provider、
临时 SQLite/Parquet/路径和复制的 shell fixture；不连接真实 RQData、production DB/Redis、Runtime 或通知服务，也不安装 LaunchAgent。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q --tb=short \
  services/quant-api/tests/data_foundation/test_daily_maintenance.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_weekly_audit.py \
  services/quant-api/tests/data_foundation/test_weekly_audit_ownership.py \
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

周检状态归属测试使用 Pipe 屏障控制真实跨进程 A/B 交错，覆盖取维护锁前、审计中、终态发布及 lease 释放；
验证竞争者不覆盖、旧成功被新独占 busy/failed 替换、进程中断/退出、guard 和状态写入故障，以及可选 health 不改变 overall。
它只创建临时状态/锁文件，不安装或启动实际周检服务。

这些工程验证不证明每周调度已安装、真实全历史无 finding、盘后自然运行耗时、release 或 Runtime promotion。
实际安装语法和前置 Gate 仅见 `deploy/README.md`。

有界 metadata fixture 与既有同步/provider/CLI 回归（全部隔离，无生产连接）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_bounded_metadata.py \
  services/quant-api/tests/data_foundation/test_metadata.py \
  services/quant-api/tests/data_foundation/test_historical_session_preservation.py \
  services/quant-api/tests/data_foundation/test_historical_session_window.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_cli.py
```

以下为用法，非外部执行授权。`targets.json` 是明确的
`[{"symbol":"au","contract":"AU2304","through":"2023-03-13"}]`；输出为普通 JSON，由 operator 保存。
fetch 和 apply 均须明确包含在任务/批次授权中，可一次批准；仅批准 fetch 不等于批准 apply。

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
`symbol/contract/date`，不扩写入范围。新 plan 如有新增 Session 请求，须核对仍在授权范围与预算内并使用新 hash；超出范围才申请批准。
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
# 任务范围内真实只读连接自主执行。输入是已保存的诊断 JSON（source_response），不是新查询。
uv run --project services/quant-api guiyi data au-calendar-correction \
  --evidence /absolute/source-response.json --expected-evidence-sha256 EXACT_FILE_SHA256
# 下面仅是用法；未取得覆盖该操作的有效生产写入授权时禁止执行。
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

任务范围内可自主在 exact 代码副本执行以下只读用法；`--as-of` 必须为本次选定的固定截止时间。

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

单 API worker 部署契约回归（真实 loopback socket + 隔离 fake MDS，不接触生产数据）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_alert_runtime_launchd.py \
  services/quant-api/tests/newow/test_product_socket_http.py
./scripts/ops/macos/install-local-services.sh --render-only
```

需允许本机 loopback bind；EPERM 是宿主执行限制，不得跳过后宣称通过。测试执行真实 launcher 验证
单 worker 与 `WEB_CONCURRENCY`，并通过正式应用路由验证四个独立连接的 token、参考记录、副图、两种主图
分页和历史定位，另验证两个进程计算相同事实仍拒绝彼此 token，以及重启后的旧 token/cursor 失效。
已有缓存、门禁和去重测试继续覆盖 TTL、淘汰、共同事实修订、取消及 429；socket fixture 不证明工作站数据验收。
真实验收使用隔离只读 API、固定品种/截点/窗口与真实 MDS，分别验证浏览器操作和正式 `/health`。
至少五组新进程冷请求/同进程热请求；重型 reference/comparator 实际运行期间，health 与普通行情各至少
100 次重叠采样，要求 p95 分别不超过 1 秒/3 秒且无超时。记录空闲对比、最大延迟、错误、输入身份与
进程身份；不清除 OS/磁盘缓存。失败保持阻塞，不增加业务重试或降低快照校验。发布后现场进程和请求链路
仍须独立验收，不能以 render-only 或候选预览代替 Runtime promotion。

本次黄金固定截点实测的结果、逐请求计时、真实计算区间、截图与冻结脚本保存在
`outputs/newow-single-worker-20260911/`。这些脚本是本次工作站证据，不是新增正式服务入口；
其中 `serve.py` 用正式路由加只读 DB/GET 白名单（8011）或复用既有 `app.preview`（8010）。
需要复验时先确认脚本内固定配置根、数据范围、端口空闲和精确代码与本次意图匹配，再从候选根运行：

```bash
mkdir -p .run/single-worker
cp outputs/newow-single-worker-20260911/{serve.py,measure.py,browser_acceptance.cjs,auxiliary_browser.cjs} .run/single-worker/
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api python .run/single-worker/measure.py
```

`measure.py` 负责五个自建 API 进程的启动与回收；不控制现役服务。浏览器脚本须在同 commit 的上述
候选预览 API/Web 启动后运行，结束后关闭自建预览。不得把旧证据覆盖为新候选通过，也不得把自建预览
停机当作 Runtime 操作。命令失败后先保留结果并定位；不得借复验下载、补数或更改生产配置。

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

这组测试只使用临时目录/fake service，验证 projection identity、strict/atomic file、API projection-hit/miss、`data update/refresh/contract-warmup --apply` 在 maintenance lease 内的失效、after-market 顺序、default-off projection activation marker 与 maintenance lease；不得以测试为理由执行真实 `guiyi data ... --apply` 或创建 marker。真实 projection-hit 性能 `<200ms` 属于单独取证的本地 Runtime read-only manual acceptance，不在普通 pytest 中用 timing sleep 伪造。

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
  services/quant-api/tests/test_runtime_logging.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_subing_scope_activation.py
```

其中 MarketRead/Alert 组还固定验证 HTDY 5m/15m/60m 的 Calendar/Session/owner 完整性、窗口数量足够但中间
缺 Bar 时 kernel/Event/sender 均不运行、SuBing failed cutoff 的 typed skip 不清健康、迟到旧合约不倒退，
以及 guard enter/exit 与内部 DB/status/evaluator 失败的日志分类。Event 查询的可选周期筛选、Rule 支持周期拒绝及省略参数兼容也在此组验证；通知诊断必须通过真实临时日志 formatter 验证固定码与身份落盘，禁止只断言 LogRecord extra。
Event persistence 失败后的同 Bar 不重试；
只有下一次真实成功评价才可清当前错误，并保留历史失败时间。

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
Canonical、写 production DB/Redis 或停止 Runtime。`prepare/publish --apply` 不是测试命令，均须纳入明确的
真实数据/维护任务或批次授权。

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
在有效任务/批次授权内核对并使用该 exact hash。

Runtime-bound daily recovery 的显式 P60/fixed-through 请求、稳定 target-window hash、maintenance lease 内
identity/CAS 重检、相同端点/数量下的内部 expected/missing 时间戳漂移、hash 与执行共用同一冻结计划、目标
Runtime provider 配置绑定、projection 顺序、唯一 stdout 终态 JSON、单次 provider 失败、正式 Catalog/MDS
读回与 NDJSON 进度：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_daily_recovery_cli.py \
  services/quant-api/tests/data_foundation/test_daily_maintenance.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/data_foundation/test_closeout_binding.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py
```

此组覆盖 PD/PT 上市首日的交易日下界：不要求上市前一天的 Session，保留首个合法交易日的前一自然日晚盘，
未收盘不返回；合法区间内 Calendar、Session 或夜盘前交易日锚点缺失仍失败关闭。


该组测试只使用 Runtime/context doubles、fake provider、SQLite 与临时 Parquet；不会连接真实 RQData、生产
PostgreSQL/Redis，或修改现场 Canonical、status、projection、Runtime 和调度。真实
`daily-recovery --apply` 仍必须绑定当前 Runtime/status、dry-run exact plan hash 与一次明确生产写入意图。

schema-v5 compatible recovery 的只读绑定、候选 commit/tree、operational hash/count、`last_interruption`
保留、配置脱敏、独立 expected terminal SHA、受信 account HOME、stopped status authority、first-install
status residue 拒绝、launchd error/label reappearance、真实 schema-v5 `RuntimeDataBinding` 的四服务/config/
heartbeat/recheck、公开 daily/current-day 入口的 stopped success 与 drift/error fail-closed、promotion 四
predicate 保留、after-market→Live 安装顺序，以及部分安装失败后 candidate 逆序停服、旧 launcher/rotator/
plist/loaded-state 精确恢复、loaded 进程 root/commit/arguments/working-directory/environment 读回、真实旧
schema-v5 terminal + expected SHA + `RuntimeDataBinding` 的第二次 authority/public preflight、load 前 mutation
失败统一恢复、post-commit cleanup unknown 的 committed/no-retry 语义，以及 marker/unknown 显式 blocked 合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_closeout_binding.py \
  services/quant-api/tests/data_foundation/test_after_market_closeout.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/data_foundation/test_runtime_status_authority.py \
  services/quant-api/tests/data_foundation/test_runtime_promotion.py \
  services/quant-api/tests/test_captured_recovery_runtime.py \
  tests/engineering/test_market_runtime_launchd.py
```

测试只使用临时 root、合成状态/配置与 fake launchctl；不读取现场配置，不连接 provider、生产 DB/Redis，
不写现场 Canonical/status，也不执行安装或 Runtime mutation。`compatible-recovery-proof` 的
`recovery_ready=false` 是有意保留的发布与执行 Gate；render-only/fixture 通过不能生成可用恢复 root。

Runtime-bound current-day metadata recovery 的严格 snapshot codec/hash、P60 64 次应用层 fake API 调用、
capture/plan/apply provider 隔离、Calendar/Session/rank1 exact diff、下一交易日 insert、warm-up/窗口外保留、
maintenance lease、Runtime/plan drift、rollback、commit outcome unknown 与自然同步回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_current_day_metadata_recovery.py \
  services/quant-api/tests/data_foundation/test_metadata.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/data_foundation/test_closeout_binding.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_historical_session_preservation.py
```

该组测试仅使用 fake API、Runtime/context doubles、SQLite 与临时路径；不连接真实 RQData、生产
PostgreSQL/Redis，不写现场 Canonical/status/Runtime。真实 capture、metadata apply 各自需要绑定 exact
Runtime/status/日期及相应 source/plan hash 的一次明确意图；capture 意图不授权后续数据库写入。

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
  services/quant-api/tests/newow/test_candidate_preview.py \
  services/quant-api/tests/test_subing_reference.py
pnpm -C apps/quant-web exec node --test tests/candidatePreview.test.ts tests/marketSeries.test.ts tests/useNewowProduct.test.ts
PLAYWRIGHT_CANDIDATE_PREVIEW=1 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/candidate-preview.spec.mjs
```

浏览器 fixture 固定 5182，拦截业务请求并故意设置错误的旧 API/WS override，以验证隔离。
普通 dev/build 不启用预览；候选模式只供 dev server，禁止构建成 production bundle。
任务需要的隔离只读预览可自主启动，由 controller 确认干净 exact commit、共享 Catalog/Canonical
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
代理只允许显式列出的只读业务 GET（包括 Newow capability 与 SuBing 历史 reference）及两项正式状态 GET，其他请求返回
`PREVIEW_ROUTE_FORBIDDEN`，无 Live subscription。
停止候选进程即关闭预览；没有数据写入需要回滚，正式 Runtime 与 release Gate 不因预览通过而改变。

Market Web 发布前真实只读候选验收在 API 8010 与 Web 5174 身份核对通过后运行。它覆盖 60 品种首页、
真实 AU/JM Newow 与 SuBing reference、周线最近完整区间动作、密集 callout 桌面/移动/全屏边界；不得把
fixture 结果计作真实数据通过：

```bash
REAL_BACKEND=1 PLAYWRIGHT_SKIP_WEBSERVER=1 \
  PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 \
  pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-pre-release-readonly.spec.mjs
```

Newow P5 路由/偏好、typed section consumer、九组合图层、参考历史与解释面板定向回归：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowProductRoutes.test.ts \
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
  tests/useHtdyAlertFacts.test.ts \
  tests/useSubingAlertFacts.test.ts \
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

Newow 趋势通道圆点使用仓库内冻结 30-Bar fixture，同时校验 Python Decimal Core 与独立 JavaScript
HHV10/LLV10 序列；Core/API/Web 测试覆盖部分窗口、孤立 Bar、owner 重置、缺值、分页 prefix、
价格坐标、颜色、半径与身份清理：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_oscillation_channel.py \
  services/quant-api/tests/newow/test_trend_channel_display.py \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test \
  tests/newowTrendChannelParity.test.ts tests/newowProductTypes.test.ts \
  tests/newowProductChartPrimitives.test.ts tests/NewowProductChartStage.test.ts \
  tests/useNewowProduct.test.ts
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs
```

冻结 fixture 记录 v3.2.82 两份源码 SHA-256 与 30 组逐值输出；测试本身不读取 Git 外冻结包、不联网、
不连接 MDS/RQData/production DB/Redis/Runtime/通知。五档视觉基线为 1280、1440、1920、2560 与 390。

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

预警审查补充回归固定 HTDY 与苏冰输入合同分离、canonical 零评价/状态失败发送边界，以及周一
60 个冻结身份与 45 个夜盘目标经真实 Session authority、fake SDK 的正式 adapter、`recover_product`、
隔离 Redis 聚合和 MarketRead 的组合链：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_live_recovery.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/test_alert_recovery_boundary.py \
  services/quant-api/tests/test_live_recovery_guard.py
```

组合回归默认不会连接 Redis；实际 Lua 原子提交仍须按下方合同给 `GUIYI_TEST_REDIS_PORT` 配置本次创建、
非 6379、无持久卷的一次性实例，并只单独运行对应测试。未配置造成的 skip 不计为 Lua Gate 通过。

逐品种诊断命令为 `guiyi runtime subing-readiness --trading-day YYYY-MM-DD --as-of OFFSET_DATETIME`；
`as-of` 必须带时区且不晚于执行时刻。命令只读 PostgreSQL/Redis/Canonical，逐品种报告当前输入与 Scope，
非全部 ready 时退出 1；参数错误退出 2。该结果不证明 provider acceptance 或实际收件，真实连接仍须
位于当前任务的只读诊断范围。生产只读执行还必须使用与现役服务启动器相同的 authenticated
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


## 首页慢请求、目录独立与恢复回归

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/data_foundation/test_market_pagination.py services/quant-api/tests/data_foundation/test_market_home_overview.py services/quant-api/tests/data_foundation/test_market_home_projection.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/marketHomeResource.test.ts tests/marketHomePageRoute.test.ts
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-home.spec.mjs
```

隔离回归覆盖 W1 同周日历查询次数、下一次读取看到日历变更、分页/缺失映射语义，及慢/失败/零行 overview
下黄金和焦煤的独立搜索与消息筛选。可见页恢复覆盖成功缓存 TTL、失败重读、并发去重和旧响应隔离。
这些测试不启用生产投影，不下载行情，不写生产数据库或切换 Runtime。
