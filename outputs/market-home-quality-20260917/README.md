# Market Home D1 质量中断修复与 60 品种复核

当前结果：用户已授权后续操作，PT/SS 补数及复验已完成，日线三策略覆盖 60/60；最新结果见 [CLOSEOUT.md](CLOSEOUT.md)。以下保留补数前诊断和当时 Gate 状态。本任务没有发布或切换 Runtime。

## 根因与修复

旧首页的 actual-dominant 口径与 physical-owner 口径不是同一历史窗口。physical-owner v2 使用普通严格读取：物理合约历史中任意权威 `PRICE_UNAVAILABLE` 会让整段读取失败，最终把 BZ、EB、PG 当成整个品种不可用。既有 Newow D1 已采用质量分段，首页尚未对应处理，不能把两个页面的 60/60 和 57/60 当成同一个验收指标。

本次新增统一 MDS 有界 D1 质量读取：以权威期望交易端点定义最多 300 根的请求范围，验证有效 Bars 与来源异常端点的并集完全覆盖该范围。异常端点占用原窗口位置，不用更早数据凑足数量。仅在最后一次来源缺价之后的连续有效段计算首页日线指标，预热不足则显式不可用。目标日自身缺价仍不提供报价。

纯历史缺失时，使用独立的一端点合同核验当天报价；该报价不能为任何日线指标补足输入。W1 缺失或来源缺价仅使周指标不可用。重复、身份、文件校验、日历或 Session 异常继续使快照失败，不能降级成正常历史不足。`physical_owner_quality_v3` 隔离旧缓存。

页面明确标注“日线报价可用”，并显示历史缺价、重新预热、日/周线历史不足；不修改 Newow 公式、ReferenceTrade、行情事实、生产配置或运行副本。

## 当前实数

- 固定完成日 2026-09-16 和 2026-09-17：日线报价均为 **60/60**，过期 0、报价不可用 0。
- 9/17 真实隔离候选自然首载：身份核对通过，DOM 与 API 均为 60/60，无水平溢出；BZ/EB/PG 有缺价披露，PT/SS 显示历史不足及不可用日线指标。
- BZ2610：2026-03-20 来源缺价；截至 9/17，中断后连续有效段 124 根。
- EB2610：2025-11-19 来源缺价；9/17 连续有效段 203 根。
- PG2610：2025-11-11、2025-12-09 来源缺价；9/17 连续有效段 189 根。
- BZ/EB/PG 三策略 × chart/reference 共 18 项均 READY。
- 全量结果：**58/60（96.67%）品种 READY**，360 项检查中 348 项 READY、12 项因 PT/SS 历史缺口阻塞。
- 全 60 结果见 `newow-all60-summary.json` 和 `newow-all60.json`。这验证三策略图表/参考读取，不是 60 品种逐页浏览器验收，也不表示实盘收益或执行准备完成。

## 剩余精确数据缺口

| 品种 | 物理合约 | 周期 | 缺失首日 | 缺失末日 | 缺失交易日 | 9/17 实有 |
|---|---|---|---|---|---|---|
| PT | PT2612 | 1d | 2025-12-15 | 2026-09-16 | 185 | 1 根 |
| SS | SS2611 | 1d | 2025-11-18 | 2026-09-16 | 204 | 1 根 |

这些是换到新主力后的物理历史前缀缺失，不能用连续主连、旧合约、当天报价或 AI 补值替代。`remaining-gaps.json` 列出全部 389 个权威缺失端点；它是只读诊断，不是可执行的已批准 prepared manifest。

拟议后续仅补上述两合约 D1，截止 9/17，最多 389 个交易日请求；先核验正式计划、再按现有维护流程下载及发布，异常停止、无自动重试、无额外品种或周期。未得到授权，未执行。

## 验证

测试代码身份：`247cc2d3adbbfac61ad3e3a842e2a681183cbdf4`。其后 `fb02c3e3b` 只提交六张经视觉核验且 E2E 通过的 PNG 基线，业务源码相同。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  ../../services/quant-api/.venv/bin/python -m pytest \
  services/quant-api/tests/data_foundation \
  services/quant-api/tests/test_market_home_api.py \
  services/quant-api/tests/test_market_home_projection_api.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_product_service.py \
  -q --tb=short -p no:cacheprovider
```

结果：1749 passed、59 skipped。新增回归覆盖完整窗口、缺失前缀/内部/尾部、目标日缺价、异常日重复/身份冲突、来源中断后预热、日周历史独立缺失、严格错误保留。

前端 `npm test`：624 passed、1 skipped；`npm run build` 通过。`PLAYWRIGHT_PORT=5193` 下 `playwright test -c apps/quant-web/playwright.config.mjs market-home.spec.mjs`：31 passed。OpenSpec 9 passed；定向 Ruff、diff check、secret scan 通过。mypy 有 11 个基线已有的 coverage Optional 类型错误，本任务未新增，不能宣称全项目类型检查通过。

独立审查已复核合并后的代码、测试和 canonical，未发现 Confirmed Issue，允许集成 develop。全量业务核验使用真实 Catalog/Canonical 只读事务，provider 请求 0、生产写入 0。预览主动禁用 Live websocket，其连接错误不作为日线失败或 Live 验收；隔离预览已结束。

## 尚未执行的外部操作

修复分支已推送到既有 origin。自动审批随后拒绝 PR 创建，理由是 GitHub 外部目的地缺少明确授权；已向用户单独请求目标 `firehell/guiyi-quant-workstation` 的 PR/develop 集成授权。

第一次 prepare 在工作树检查阶段停止，错误为 `EXECUTION_CHECKOUT_DIRTY`，未触及维护流程。后续尝试在执行前被自动审批拒绝，理由是 prepare 获取维护锁可能影响生产数据库状态；已单独请求上述两合约补数授权。没有绕过拒绝或执行 apply。

生产修复仍需受控数据批次；代码上线仍需独立 release/Runtime 授权。本次保留主工作树原有暂存文件和全部无关输出。
