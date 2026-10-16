# 当前看盘请求优先与收益合并读取

基线 develop `44ea394a1`；本任务分支 `codex/watch-request-priority`。
范围仅开发交付、只读诊断、独立预览与 develop 集成。不改公式、窗口、行情、研究结果或正式服务。

## 实现与取舍

- strategy-detail 复用既有耗时中间件，以 request-local collector 提供 Server-Timing。
  记录 queue/read/verify/cache/compute/replay/projection/response_encode/total；嵌套阶段不能相加。
  response_encode 是最终投影之后的 FastAPI 编码和响应构建区间，不包含压缩/网络。
  仅保留固定名称和累计毫秒，不保留输入、结果、参数、路径或跨请求数据。
- 重计算等待顺序：当前主图、所选辅助、可见收益解释、历史。运行不抢占，同级FIFO；运行/等待/超时预算不扩大。
  保留持久化参考既有独立读取额度。离场取消和共享订阅仍按现有合同；输入hash循环补取消边界。
- `reference_part=panel` 在同一次已验证结果上返回摘要、最多3条预览和所选曲线，沿用现有hash/窗口/身份。
  原 overview/curve/history 仍可独立读取，history仍为50条游标；panel不接受历史游标。
- 实施细化：切换模式也使用单个panel，因最近3条记录和页面摘要随模式改变，不能沿用旧模式预览。
  只计算当前模式的曲线，不读取所有模式；相比只读curve额外约6KB，避免另发一次摘要核验。
- 未再新增MDS跨请求缓存。现有 `load` 已有Session查询复用，MDS已有精确日线replay query key复用；
  计算后复核与新的HTTP请求仍须重新验证数据修订。此次先删除Web首次收益的重复核验，
  没有证据支持再增加会遮蔽修订检查的通用memo或扩大缓存预算。

## 验证

所有测试/构建/浏览器串行；Web单元/浏览器堆512MiB，类型/构建768MiB；浏览器单worker。
新增并发优先级、取消、组合响应一致性与请求内耗时隔离回归，先观察失败再实现。

首组真实单请求采样（运行中的8003开发服务，非P95）：JM/RB主图约579–965ms，
权威读取约365–627ms，排队小于1ms；收益缓存命中后每次核验约600ms。
组合收益响应约226KB；独立摘要6161B、曲线221727B。不同缓存冷热不能据此直接宣称速度倍数。
正式5173/8000与其他研究产物保留不变。

- 受影响后端最终357 passed；工程/合同21 passed；Ruff、类型/build/topology通过；OpenSpec strict11通过。
- Web完整1113 passed / 3 skipped；最终浏览器77项通过，无更新截图或放宽阈值。
- 真实开发4项通过：五步JM/RB切换、20次新浏览器存储、刷新、原完整收益与独立/组合响应逐值相等及桌面/390px。
- secret scan全跟踪源码及两项新增代码/测试零发现，diff检查通过；桌面与390px实际截图已查看，未更新基线。
- 独立Astra Review两项已复现并修正：非history游标在HTTP转换前拒绝；额度接纳前检查deadline。
  新增HTTP两worker交错阶段隔离、409后清理、确定性锁跨越deadline测试；增量复核无剩余确认问题，允许集成develop。
- 真实20次新浏览器存储价格P95约1492ms、最大2399ms；已有服务，并非服务冷启动P95。
  缓存返回JM价格挂载后约35ms；策略图五步为1481/1381/1905/4426/2900ms，手动刷新1380ms。
  60m策略图样本read约3520ms、queue约2ms，显示剩余主要等待在权威读取；不宣称所有策略提速。
- 独立API真实验收55秒、110次RSS采样峰值414.9MiB；五步JS堆最高48.1MiB。
  这不是整机峰值或所有场景上限，不提高既有缓存预算。
- 同一JM快照的热缓存交替3组采样，摘要+曲线独立合计1233/1548/1330ms，组合721/562/582ms；
  均逐值相等。组合226111B，独立摘要6161B+曲线221727B（未压缩）；有限样本，不作为P95或全站倍数。

实际命令（完整输出在本机 `/private/tmp/guiyi-request-priority-*.log`）：

```sh
NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web test
NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build
NODE_OPTIONS=--max-old-space-size=512 PLAYWRIGHT_PORT=5197 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/reference-split.spec.mjs e2e/chart-first-loading.spec.mjs e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-reference-curve.spec.mjs e2e/return-curve-layout.spec.mjs --workers=1
REAL_DEVELOP=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5176 PLAYWRIGHT_SKIP_WEBSERVER=1 NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/chart-first-readonly.spec.mjs e2e/multi-product-readonly.spec.mjs --workers=1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/newow/test_product_resource_gate.py services/quant-api/tests/newow/test_read_timings.py services/quant-api/tests/newow/test_newow_reference_parts.py services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_product_reader.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_product_snapshot_cache.py services/quant-api/tests/newow/test_product_inflight.py services/quant-api/tests/newow/test_replay_cache.py services/quant-api/tests/reference_trading/test_persisted_projection_cache.py services/quant-api/tests/reference_trading/test_newow_persisted_query.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider tests/engineering/test_newow_capability_contract.py tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

预览保留 `http://localhost:5176` / `127.0.0.1:8003`，本次仅重启独立开发API加载代码。
正式服务未切换，无新Redis、后台预热、数据写入、发布或通知。
