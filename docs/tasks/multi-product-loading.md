# 多品种看盘与收益接口优化

基线 develop `7ea6a0dca`。范围为 owner 已批准的看盘与收益读取优化，仅开发交付和独立预览。
不修改公式、统计窗口、行情事实、历史研究资产或正式 Runtime；所有无关未跟踪产物保留。

## 实现

- 当前请求先完成 MDS 权威核验，再按完整 kernel 输入/生命周期/中断/公式/profile/质量政策复用纯 replay。
  新截止时间保留独立快照与请求身份；共享计算使用所有订阅者的取消状态，不让离开的 leader 取消 follower。
  纯计算、完整参考与模式投影共用现有 SnapshotCache 容量，未扩大预算。
- 价格缓存保持内存8MiB、磁盘32MiB、最长7天。IndexedDB 每次原子事务按键读取价格与紧凑 LRU 元数据，
  跨标签页不覆盖旧索引；超时 abort 事务并阻止迟到写入。一次升级丢弃可重建旧详情价格缓存，不触及事实数据。
- `/market/product-directory` 只含名称、交易所、板块与品种；ETag及24小时展示缓存与当前主力映射分离。
  D1 表头使用当前已验证主图价格，分钟/W1保留独立D1事实读取；跨物理合约不计算虚假涨跌。
- GET保持2并发，等待队列依次优先当前价格/主图、所选辅助、可见收益解释、追加历史；离场撤销旧订阅。
  主图、辅助和解释的未缓存计算也加入既有单重计算预算，价格读取独立。
- `strategy-detail?section=reference` 的 Web 入口显式读取 `reference_part=overview|curve|history` 与 `reference_mode`。
  overview最近3笔，history固定50条游标，不重复摘要与曲线；三者绑定snapshot/window/result_hash。
  mode区分页面普通/理论、已完成、含浮动及融合；未选派生不执行，legacy内部完整消费者合同保留。
- 完整结果产生指标和年化，绘图最多2000原始点，保留端点、极值、空洞/物理及计算区段边界，不插值。
  边界无法容纳则明确不可绘制；孤立原始点可见，不跨合约连线。页面回撤按真实来源声明百分点或单笔损失。
- 分钟参考记录沿原源端窗口；融合保留独立近一年记录窗，`record_since/records_window_limited`明确覆盖。
  页面记录按所选完整页面投影窗口。Web记录累积上限300，达到上限不冒充服务端终页或完整统计。
  双策略完整统计由用户显式读取并核对范围、membership及数量；默认不遍历全部历史。
- 模式/窗口/快照变化即使面板隐藏也清除旧内容与选中记录。已删除无生产消费者的三套旧收益面板和旧最近记录控制器。

长期约束更新于现有 market-home-overview 与 newow-product-reference-trading OpenSpec，未建立另一套公式手册。

## 验证记录

测试、构建和浏览器严格串行；Web单元并发1、浏览器单worker，Node单元/浏览器堆512MiB、类型/构建768MiB。

- 最终完整Web单元：1112 passed / 3 skipped；追加分包参数定向7 passed。
- 受影响后端：578 passed；两项本地HTTP socket用例在沙箱外受控运行2 passed。
  中间全目录试跑暴露的初始化/旧fixture问题已修复，最终定向覆盖相关失败路径；不宣称后端全仓通过。
- 年化运算顺序与无status空洞抽样追加回归：75 passed及10 passed。
- 工程/合同32 passed；类型/build/topology通过；OpenSpec strict 11通过；Ruff通过。
- 独立Review确认项及缓存原子性、融合依赖、尾部缺口风险已修复并回读，无剩余确认问题。
- 最终受影响浏览器96项无截图更新通过；真实开发4项通过（五步切换、20次新存储、手动刷新、收益分包逐值对照及桌面/390px）。
- 截图经桌面、390px及真实JM人工查看后才更新，原maxDiffPixels=500未放宽。

实际核心命令：

```sh
NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web test
NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build
NODE_OPTIONS=--max-old-space-size=512 PLAYWRIGHT_PORT=5197 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/detail-price-persistence.spec.mjs e2e/reference-split.spec.mjs e2e/chart-first-loading.spec.mjs e2e/newow-reference-curve.spec.mjs e2e/return-curve-layout.spec.mjs e2e/newow-ui-nine.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-product.spec.mjs e2e/ui-unification.spec.mjs --workers=1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/newow/test_replay_cache.py services/quant-api/tests/newow/test_newow_reference_parts.py services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_page_performance.py services/quant-api/tests/newow/test_page_performance_adapter.py services/quant-api/tests/newow/test_home_cards.py services/quant-api/tests/newow/test_weekly_acceptance.py services/quant-api/tests/newow/test_experiments.py services/quant-api/tests/newow/test_product_socket_http.py services/quant-api/tests/newow/test_p0_acceptance.py services/quant-api/tests/newow/test_product_snapshot_cache.py services/quant-api/tests/newow/test_product_resource_gate.py services/quant-api/tests/newow/test_product_inflight.py services/quant-api/tests/reference_trading/test_persisted_projection_cache.py services/quant-api/tests/reference_trading/test_newow_persisted_query.py services/quant-api/tests/reference_trading/test_newow_fusion_historical.py services/quant-api/tests/reference_trading/test_newow_fusion_forward.py services/quant-api/tests/test_market_home_api.py services/quant-api/tests/data_foundation/test_catalog_and_service.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

## 真实开发预览与测量

独立Web/API：`http://localhost:5176` / `127.0.0.1:8003`，根develop源码，单API worker。
正式5173/8000和既有5175/8002均未切换。初次GET采样：目录60品种约48ms；JM日线主图约685ms。

真实JM完整旧响应与三个分包逐值比较通过，收益/胜率/回撤不变：

| 未压缩响应 | 字节 | 单次耗时 |
|---|---:|---:|
| 原完整参考 | 886772 | 本例仅作数值对照 |
| overview | 6161 | 1901ms |
| 所选curve | 221727 | 796ms |
| history | 9263 | 572ms |

这是运行中开发服务的有限样本，不是性能倍数或P95结论。
本轮后端大目录测试进程只读采样约56MiB RSS/单核运行，不是整机峰值证明。
最终20次新浏览器存储价格P95约1372ms、最大1443ms，已有开发服务，并非服务冷启动P95。

| 操作 | 价格可见（导航起 / 挂载后） | 正式图可见 | JS堆 |
|---|---:|---:|---:|
| JM日线震荡 | 814 / 503ms | 1547ms | 30.0MiB |
| RB日线震荡 | 650 / 565ms | 1379ms | 35.6MiB |
| 返回JM缓存 | 112 / 30ms | 1904ms | 31.0MiB |
| JM60分钟 | 335 / 243ms | 5429ms | 29.5MiB |
| JM日线趋势 | 114 / 36ms | 4424ms | 29.7MiB |
| 手动刷新 | 保留价格 | 1889ms | 33.4MiB |

20次新存储浏览器JS堆最高约33.9MiB；独立API60秒/60样本RSS峰值约370MiB，
不是整机峰值或所有场景上限。分钟/趋势正式图仍有4–5秒样本，不声称所有策略重任务变快。
截图基线只按已确认变化更新，最终不带update复验96项通过。

最终状态：CODE_COMPLETE、TEST_COMPLETE、REVIEW_COMPLETE；允许集成develop。
无正式发布或Runtime切换。新增静态目录、分包及缓存均为代码交付，不以此宣称数据或Runtime就绪。

真实验收命令：

```sh
REAL_DEVELOP=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5176 PLAYWRIGHT_SKIP_WEBSERVER=1 NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/chart-first-readonly.spec.mjs e2e/multi-product-readonly.spec.mjs --workers=1
```
