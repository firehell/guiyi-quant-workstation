# 文档一致性与未开放能力核对（2026-10-29）

本轮以 develop `a9a08f0db9b77daf28fd0589352a910c05b87c5e` 为审计基线，检查现役文档入口、
Web源码消费链、后端/CLI注册与显式功能开关。源码检查不证明现场启用，部署与自然验收仍看
[STATUS](../../STATUS.md)。本轮不发布、不操作账户、不修改公式或开启Runtime。

## 已修正与清理范围

- README、PROJECT_SOURCE及ARCHITECTURE补齐 reference/home CLI、独立SimNow持续宿主和只读监控边界；
  不再将“一次性CLI没有持续服务”泛化为整个项目没有持续宿主。
- STATUS追加工作树现场检查点，保留19:50“SimNow任务树暂留”的历史记录。
- 删除无Web源码消费者的旧HTDY/SuBing历史面板、旧Newow记录面板、相关独立加载器和历史标注孤岛；
  现役实时留存收益区、历史API、后台资产和共享类型保留。专属旧测试随实现删除，混合测试保留现役覆盖。
- 删除Newow投影模块中无调用的 `_reference_return` 与 `_latest_owner_mark`，保留现役Decimal收益路径；
  删除receiving_liveness中未使用的 `_validate_active` 导入。
- 历史修复脚本、冻结证据、旧版本capability合同、显式恢复入口保留；没有消费者import不自动代表脚本无用。

## 已有但未开放、受限或不易发现的能力及未实现边界

| 能力 | 源码/合同入口 | 限制与实际含义 |
|---|---|---|
| SimNow持续manage/trade | `packages/quant-core/guiyi_quant/simnow_execution/settings.py`、`supervisor.py`；[执行合同](../SIMNOW_EXECUTION.md) | 代码接受observe/manage/trade；trade启用可生成执行权限。STATUS记录现场为observe、auto_order/opening=false；本轮未重读私有配置，不能由代码声称交易已开放。 |
| SimNow有界一次性执行/人工一手往返 | `scripts/broker/simnow_controlled.py`、`simnow_manual_roundtrip.py` | 有显式execute、时间/次数/手数限制；不是Web下单入口，也不是无人值守实盘交易能力。 |
| JM Paper账户与Ledger重放 | `packages/quant-core/guiyi_quant/paper/`、`scripts/research/jm_paper.py`；[Paper合同](../PAPER_PILOT.md) | 独立离线CLI，run为历史重放；不等于持续Paper或交易Shadow。 |
| 新苏冰历史研究页 | `apps/quant-web/src/app/router.ts`、`pages/research/NewSubingPage.vue` | `/research/new-subing`已注册；Market布局隐藏侧栏，默认三Tab没有该入口，需直接URL。结果供给还依赖显式结果根。 |
| 牛哇期货双向研究模式 | `apps/quant-web/src/utils/newowFutures.ts`、`MarketDetailViewNav.vue` | `strategy_model=futures_bidir_v1`显式选择；普通URL仍默认原版。研究结果与页面参考/账户分开。 |
| 牛哇完整explanation | `services/quant-api/app/market_data/newow/product_release.py`、`NewowProductWorkspace.vue` | 完整section仍deferred；独立decision_v2和AI分析入口不能证明完整解释已经开放。 |
| 牛哇1m策略产品 | `apps/quant-web/src/utils/marketDetailRoute.ts`；[产品边界](../../PROJECT_SOURCE.md) | 通用行情/聚合输入有1m，Newow策略入口不支持1m；不能称已实现完整Newow 1m策略。 |
| Web主连 | `marketDetailRoute.ts`；[产品边界](../../PROJECT_SOURCE.md) | 页面隐藏continuous并迁移旧URL；底层行情API/内部研究能力保留。 |
| 预警管理按钮 | `MarketDetailPage.vue`、`MarketDetailTopBar.vue` | 组件保留事件，但唯一调用canManageAlert=false；页面没有Scope写入管理入口。 |
| 候选只读预览 | `apps/quant-web/src/utils/candidatePreview.ts`、`api/request.ts` | 仅VITE_CANDIDATE_PREVIEW=1时生效，限制写操作，是必要验证入口。 |
| Live recovery | `services/quant-api/app/alerts/composition.py`、`market_data/captured_recovery_runtime.py` | 默认受GUIYI_LIVE_RECOVERY_ENABLED关闭控制；本轮不从默认值推断现场设置。 |
| 每周全历史审计 | `services/quant-api/app/runtime_scheduled.py`；[部署合同](../../deploy/README.md) | 有独立安装marker和只读审计实现；STATUS保留not_run，表示尚无对应验收，不等于无代码。 |
| 牛哇通知策略管理 | `services/quant-api/app/notifications/cli.py`、`notifications/newow.py` | 独立CLI支持status/enable/disable，默认策略false且worker已接线；现场开启状态须另读回，不能据默认值下结论。 |
| Reference资产维护与首页构建 | `services/quant-api/app/guiyi_cli/main.py` | reference plan/build/advance/rebuild/resume及home build已注册，为CLI能力，未做Web写入界面；不属于废弃隐藏代码。 |

T测试1～4、主升浪位于T菜单；唐奇安默认关闭但有图层按钮；双策略对照有显式按钮；
AI分析、模拟交易监控已有产品入口。这些是收纳或按需交互，不是“有代码但未开放”。
没有证据证明独立交易Shadow Runtime已经实现；不要将修复shadow目录或Paper历史重放当作Shadow。

## 验证

- 后端定向：207 passed、1 skipped（可销毁Redis未配置，未运行其集成项）。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/newow/test_reference_trades.py services/quant-api/tests/newow/test_reference_statistics.py services/quant-api/tests/reference_trading/test_receiving_liveness.py services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/reference_trading/test_reference_cli.py
```

- 前端受影响三个测试文件：24 passed；完整单元：1212 passed、3 skipped、0 failed。
- 前端build包含capability生成校验、vue-tsc、Vite与bundle拓扑检查，全部通过；已有大于600kB chunk警告保留，未扩围重构。

```sh
NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web test
NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build
services/quant-api/.venv/bin/ruff check services/quant-api/app packages/quant-core/guiyi_quant scripts --select F401,F811,F841 --output-format concise
```

- Ruff未使用导入/变量/重定义检查通过；改动文件secret scan为0；7份导航/报告文档114个本地文件链接均存在；diff格式检查通过。
- 独立Review分别核对文档/后端删除与前端删除/保留测试：Confirmed Issue为0；运行检查已由主代理完成。
- 首次后端命令引用了不存在的test_guiyi_cli.py，未执行测试；已改用真实data_foundation/test_cli.py完成上述验证。
- 本轮仅集成develop，未发布main/tag、未切换Runtime、未打开新功能；删除代码可从本次提交前像恢复。
