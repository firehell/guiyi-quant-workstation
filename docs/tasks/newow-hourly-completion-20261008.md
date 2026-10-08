# 牛哇60m完整功能与60品种发布

用户明确交办实现、develop集成、minor发布及正式运行树切换。范围固定截至2026-09-24T07:00:00.000001Z；不重跑已闭环分钟维护。1m页面、分钟主升浪、持续分钟更新及reference worker保持关闭，不新增通知、受众或交易。承接v1.12.1：苏冰只保存信号/Event，HTDY既有通知保持，auto_order=false。

## 候选实现和验证

- capability v31正式纳入PP，60品种四分钟周期趋势/震荡/双策略；AI response v2返回W1/D1/60m六组合，窗口起点分别2024-06-01、2025-09-01、2026-04-01。
- opt-in CDV2统一历史as_of，小时趋势/震荡事实、计龄、原权重、方向/确定性评分和第一行动原则参与；缺失/预热/异owner显式不可用。分钟不调用MAIN_RISE，J风险不以日周替代。
- 同合约60m当前Close与D1/W1通道目标/吸筹展示；日周路径仍为背景，杯柄仅D1。震荡状态卡采用27格三周期解释；版本guiyi_newow_status_card_hourly_v2，独立于策略状态与CDV2仓位参考强度。
- AI采纳只切图表策略/周期；page-parity、段末参考估值、五窗口理论比较及账户事实独立。五窗口比较入口仅震荡显示，前端接受显式Canonical V1身份并继续拒绝跨频V2。

实际验证命令保存在本任务outputs/newow-hourly-20261008。最终后端限定风险范围pytest661 passed/1既有skip（reader/service/API/cache/CDV2/AI/cross-period/comparator/candidate-preview及工程一致性）；Newow Node测试390 passed；vue-tsc、Vite build与bundle topology通过，OpenSpec10通过，Ruff、uv offline lock、diff/secret通过。扩展全Newow测试因两个旧PP关闭断言失败后中断：756 passed/2failed，原日志保留；更新范围断言后完整运行受影响定向集合，不声称全Newow套件通过。

真实候选API：capability60/60，60品种×趋势/震荡小时决策120/120 HTTP200；240小时事实ready，4项日周预热/owner不足明确保留，每个源bar_end不晚于共同截止。PP四分钟周期×两基础图表8/8，均500bar，正式入口无preview扩权。Chrome真实读取PP60m综合决策/目标价/状态，六卡AI推荐60m，从D1采纳切60m，五窗口比较器与双策略依赖；报价不可用保持，不冒充Live行情。

## 源码与独立Review

原冻结四组合oracle保持不变。当前公开整页v3.3.79 SHA256 3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d；共享strategy-calc JS仍a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e。只独立提取scoreCombos（d9cb5044e8b797558a091f1647fe4bebc942729b822457a254eee0da1733d2c2）及历史AI_ADVICE_MATRIX（661da186d387bf553bc17b37bee5fbc1e1a5649a4b2312da4cb0704cb41e7ae6）；未采用新页面测试策略或新版决策语义，不把新整页称旧冻结源码。可重现入口tools/build_newow_hourly_oracle.mjs，4个case均6项，覆盖不足三笔、低样本、零回撤、稳定同分；27格逐值对照通过。

独立Review先发现小时颜色/推荐序号两P2、六组合oracle仍四项P1，均修复并复核；允许集成develop。真实比较器暴露V1前端身份拒绝，RED后修正并真实复验。旧OpenSpec要求段位置错误已修正。所有失败证据保留，未改数据或削弱评分。

## 发布与运行

候选08ef5e4a0通过独立Review后集成develop；PR #412发布v1.13.0@6dc0b81e11450262b5cbb39090c4aa1c85ab138e。annotated tag、peeled commit、远端main及非草稿GitHub Release exact读回一致，发布完整树与候选相同。candidate-binding与delivery-binding分别记录原验证和发布运行身份；代码相同不冒充自然业务相同。

正式根`.worktrees/release-v1.13.0` detached/clean，独立复制依赖并重绑定editable/bin路径，实际typecheck/build/bundle topology通过。render-only与preflight snapshot_ready60/60；base安装exit0。首次Market在mutation前因旧root缺after-market.lock失败，通用错误为AFTER_MARKET_HISTORY_INVALID；原history内容与retain只读独立通过，_guard_fd明确FileNotFoundError。使用既有after_market_recovery_guard初始化空协调锁后，原安装器重新持锁/preflight通过，并按合同实际保留历史到新树；Market、Alert及既有weekly各exit0。不是整个恢复过程只读，不运行自然job，不修改旧history/status，不盲重试。

七应用installed/loaded root/commit一致，实际API1.13.0与Web200；capability v31/60，60品种Alert Rule/Scope前后JSON完全相同。苏冰notification_enabled=false、信号/Event保留，HTDY既有发送保持，原受众与auto_order=false保持。真实正式Chrome PP60m综合决策与六卡AI已读回。

新Runtime health degraded：午休BREAK中Live/Alert coverage unverified，heartbeat新鲜、Alert processing=ok；Live last_bar_at=null。自然completed Live、盘后与weekly验收PARTIAL，不声明RUNTIME_READY、不新增monitor或手工运行job制造证据。schedule-only not_running和weekly not_run不作为业务失败。既有BZ/EG/weekly数据缺口与page-parity不可执行边界保留。

旧v1.12.1 clean、installed/进程引用0；13份.run JSON/plist/marker按SHA保存后non-force移除。候选API8011/Web5178退出；正式root保持exact tag。候选浏览器HMR取消、heavy429、加载态原图、错误selector及比较器身份失败均封存；最终受影响实际读取通过。前轮宿主审批超时未执行的公开下载/候选启动记录保留，本轮恢复后连续完成，不计为数据维护attempt。

最终状态RELEASED；运行切换/页面范围读回通过，独立Review确认；自然验收PARTIAL。唯一最小下一步：只读验收新版本下一次自然completed Live及既有自然业务，不启动新任务、通知或交易。

实际验证入口：
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow/test_candidate_preview.py services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_product_reader.py services/quant-api/tests/newow/test_product_snapshot_cache.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_cdv2.py services/quant-api/tests/newow/test_cdv2_presentation.py services/quant-api/tests/newow/test_ai_analysis.py services/quant-api/tests/newow/test_cross_period_prices.py services/quant-api/tests/newow/test_page_comparator.py tests/engineering/test_repository_hygiene.py tests/engineering/test_canonical_consistency.py
node --test apps/quant-web/tests/newow*.test.ts apps/quant-web/tests/Newow*.test.ts apps/quant-web/tests/useNewow*.test.ts
node apps/quant-web/node_modules/vue-tsc/bin/vue-tsc.js -b apps/quant-web/tsconfig.json
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
```
正式build在发布树apps/quant-web执行`node node_modules/vite/bin/vite.js build`与`node scripts/checkProductionBundleTopology.mjs dist`。实际Python为现有venv，Node为/opt/homebrew/bin/node；uv lock使用可写/tmp cache。所有实际输出在`outputs/newow-hourly-20261008/`，不声称中断的全Newow套件通过。
