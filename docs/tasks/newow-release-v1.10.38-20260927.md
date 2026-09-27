# v1.10.38 日周 Newow 交互与维护收敛发布

## 候选范围

发布基线：`v1.10.37@07cdb4b7b72c1fa003d25bf2b47b3c3de127c8a4`。
本轮开始 develop：`779551f310edd67d5eb4e25120bb0599cbf5698e`。
状态：`RELEASED`。发布PR #403已合并，正式annotated tag与非草稿、非预发布GitHub Release已读回。
本轮交办为发布版本，不执行 Runtime promotion；正式运行身份保持独立记录。

## 修改汇总

- 收益窗口与主图参考标签分离；近三个月操盘记录独立于收益窗口，累计曲线日期轴、回撤与紧凑统计展示完善。
- 切换日周策略只更新相关面板，保留报价及主图上下文；计算段匹配修正，震荡突破价线作为独立显示层。
- 日周 CDV2 明示60分钟未参与，展示依据、年龄、缺失来源及价格来源；不变为策略或执行Gate。
- 独立双策略入口自动读取趋势、震荡与融合三组统计及来源记录；图形详/简、分轨标签、主导切换、背景与可见标签统计分开。
- 伙伴策略参考响应绑定自己的快照，切换取消旧请求。曲线/分页重叠记录按稳定身份精确去重；同身份内容冲突整组排除，不以后来的值覆盖。
- 删除9个不可达旧前端实现及专属测试；收敛20版 capability 校验路径，保留有效wire版本、旧后端API与错误分类；更新架构及产品导航。
- 归档当前日周状态卡核实和四分钟周期计划，仅为研究/规划，不视为已实现或周期开放。
- API、Web及锁文件发布身份一致为1.10.38；补齐突破线canonical的两个场景，未改变公式。

## 实际验证

| 命令 | 结果 |
|---|---|
| `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test` | 最终691 passed、1 skipped、0 failed |
| `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build` | vue-tsc、Vite和bundle topology通过；保留既有request.ts静/动态import提示 |
| `pnpm -C apps/quant-web exec node --test tests/newowDualChartDisplay.test.ts tests/NewowProductChartStage.test.ts tests/newowComparison.test.ts` | 最后修复25 passed |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_cross_period_prices.py services/quant-api/tests/newow/test_fusion_reference.py services/quant-api/tests/newow/test_reference_statistics.py` | 171 passed |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short tests/engineering/test_canonical_consistency.py tests/engineering/test_repository_hygiene.py` | 22 passed、1既有截图批准库存失败；相关测试与截图相对v1.10.37均无变化 |
| `openspec validate newow-product-reference-trading --type spec --strict --no-interactive` | 通过 |
| `services/quant-api/.venv/bin/python -m ruff check services/quant-api/app packages/quant-core/guiyi_quant scripts tests/engineering/test_canonical_consistency.py` | 通过 |
| `git -c core.fsmonitor=false diff --check`与变更存活文件secret scan | 通过，最终63个存活候选文件0 finding |

隔离浏览器命令（5186端口，fixture，未访问来源或更改当前5173页面）：

```bash
env -u VITE_API_BASE_URL -u VITE_MARKET_WS_URL REAL_BACKEND=0 PLAYWRIGHT_PORT=5186 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5186 PLAYWRIGHT_CANDIDATE_PREVIEW=0 PLAYWRIGHT_SKIP_WEBSERVER= pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs --grep 'owns an independent chart|missing view migrates|Free uses|Newow HTDY and Free share'
```

结果：6 passed。旧历史分页E2E仍有漂移，未宣称整套E2E通过。
额外尝试全Newow模块测试，在耗时D1–D3实验处主动中断：616 passed / KeyboardInterrupt，209.93秒；不算全模块通过，不与171定向项相加。
首次定向命令含不存在的test_decision_v2.py，未运行测试；纠正文件列表后的实际结果为上表171通过。

## Review、限制与恢复

按 requesting-code-review 技能完成独立 Review。最终复核无剩余Confirmed Issue；去重冲突、OpenSpec场景与四版本源复核通过。
收益为零费用/零滑点页面参考，普通累计、开放参考、回看理论与融合分别保持身份。
双策略可见标签统计只覆盖精确匹配的可见CLOSED样本，不等于融合全窗口收益。
固定三个月记录、普通与理论值真实浏览器交互尚需新版本部署后验收；本轮fixture不能替代现场或自然运行。
未改数据、migration、Scope、通知、策略激活、分钟周期开放或auto_order=false。
旧P9持久化面板及周审计finding仍独立未完成。

源码可按Git记录恢复；正式Runtime未切换，无本轮运行状态需要回退。未清理用户outputs或既有worktree。

## 正式发布身份与运行读回

- 候选：`dfcb8796b1b6a9f26f033bbbce6fc633c3eb84d8`。
- PR：[403](https://github.com/firehell/guiyi-quant-workstation/pull/403)，2026-09-27T04:23:42Z合并。
- 正式：`v1.10.38@18b29c985817683bf5dfd08ae3328a4762caf9b3`。main合并源码树与候选完全一致。
- Annotated tag object：`4bf676c5207dead50054da62802e5be38a03bd5a`；远端peeled commit为上述正式commit。
- [GitHub Release](https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.10.38)：isDraft=false、isPrerelease=false、targetCommitish等于正式commit；publishedAt=2026-09-27T04:24:21Z。
- develop已普通合并包含main发布commit，保留并行任务提交；发布后的文档记录另提交，不移动正式tag。

只读 `./scripts/ops/macos/local-services-status.sh`：overall=passed，API/Web HTTP200、Runtime health ok/readonly。
实际API/Web/Live/Alert以及schedule-only服务仍指向独立`runtime-v1.10.37`和`07cdb4b7`；本次未执行任何installer或服务切换。
weekly已读到旧根23项finding，截至9/24，reference worker关闭；没有将这些问题记为本版本解决。

下一步：按新版本独立执行Runtime promotion和页面读回；在该目标被交办前保持当前运行根。自然业务验收仍单独记录。

发布冻结之后，另一任务已将`3f53f9d05`测试/fixture/证据检查及`031732345`验收记录合入develop。
这些后续提交不是v1.10.38源码范围；未修改产品源码。原发布验证中的旧截图库存失败及旧分页E2E漂移，
是冻结候选上的实际结果，不能用后续develop测试修复倒填为发布候选通过。后续测试收敛记录见maintenance-convergence文档。


## 2026-09-27 owner交办 Runtime 切换

目标为已经发布的 exact tag，不部署后续 develop。新根为
`/Users/zhangzhao/Library/Application Support/GuiyiQuant/runtime-v1.10.38`，detached/clean，
HEAD=`18b29c985817683bf5dfd08ae3328a4762caf9b3`。旧 v1.10.37 root 同样 detached/clean，
HEAD=`07cdb4b7b72c1fa003d25bf2b47b3c3de127c8a4`，保留回退。两个tag之间scripts/ops与deploy无差异，
无migration或数据/Scope更改。旧根late-provider-recovery-status.json不存在，没有待消费恢复状态需要转移；不复制旧after-market/weekly结果冒充新根结果。

实际命令与结果：

- 本地 `git clone --no-hardlinks --no-checkout` 后 `checkout --detach v1.10.38`；`uv sync --frozen --project services/quant-api`及前端`install --frozen-lockfile`通过。
- exact root执行`pnpm --dir apps/quant-web build`，vue-tsc/Vite/topology通过，保留既有request.ts静/动态import提示。
- 使用既有安全通知config路径执行`install-local-services.sh --render-only`，通过。
- `run-local-service.sh market-runtime-preflight`及Market安装内部预检均passed/non_trading_interval，operational_count=60。
- `install-local-services.sh --confirm-market-runtime`成功3服务；误用不支持的`--confirm-install`只显示usage、未进行base mutation，纠正为`--confirm-load`后成功3服务；随后`--confirm-alert-runtime`成功1服务、`--confirm-weekly-audit`成功1服务。
- `local-services-status.sh`独立读回overall=passed，API/Web/Live/Alert运行；after-market/late-provider为正常schedule-only idle。六项root/commit均为新根/18b29c98，API/Web HTTP200、Runtime health=ok readonly=true；reference_worker_enabled=false，既有notification audience_count=2。
- 新根weekly_audit=missed/through unknown/findings unknown，没有新自然结果；旧根23条finding未解决。
- 正式5173浏览器reload JM D1趋势：截至9/24、报价1509、主图与MACD加载，双策略tab替代第三入口；目标1668、吸筹1474.5可见；普通74笔累计183.66、最大回撤1.27%，固定近三月列表已呈现。截图：`outputs/newow-release-v1.10.38-20260927/runtime-jm-d1.png`。这只是部署现场读回，不代表全策略/全周期交互或自然业务验收。

切换与现场readback通过；首根自然completed Bar、盘后、weekly自然结果及既有P9问题仍独立待验收，不声明RUNTIME_READY。
现场日志为`/private/tmp/guiyi-v1.10.38-before-switch.log`、`/private/tmp/guiyi-v1.10.38-after-switch.log`和`/private/tmp/guiyi-v1.10.38-runtime-build.log`。

Linked Worktrees显示的是本仓库`git worktree list`，不是Release历史。这次发布使用分支+PR403，没有新建linked release worktree；
Runtime位于Application Support的独立clone，所以不在该列表。现有validation-closeout和release-v1.10.36 worktree均未清理。
