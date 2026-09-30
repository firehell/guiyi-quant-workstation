# RB 分钟历史产品闭环

2026-09-28：本轮分钟显示、指标与牛哇策略范围调整为 **5m/15m/30m/60m**；1m 保留可信聚合输入，Newow 1m 页面、策略产品、构建与 readiness 留待独立版本。通用 Market/HTDY 1m 与既有保存资产兼容保留。仅 RB 趋势、震荡、独立双策略，固定分母 12；主升浪分钟、其他品种及实时观察不在本轮。

## 已完成与身份

RB 分钟 **source → assets → API → browser → 视觉审核 12/12 PASS**，高风险代码、维护与真实证据已独立复核。D1/W1 初屏、全部已完成曲线、近一年记录、辅助与周期返回的六个模式已完成兼容性回归；周线趋势转折不足 120 根的 WARMING 原样保留。D1 更早主图分页的既有缺陷单列，不计为通过。

- 起点 develop `00cea970e7e87295ddcc89f7937a34430fb64b11`；冻结业务实现 `82a27a322e3b53631aa40b9f087d69ec7086a9e3`。
- 独立树 `/Volumes/扩展盘/worktree/rb-minute-closeout/guiyi-quant-workstation`；候选 API `http://127.0.0.1:8010`、Web `http://127.0.0.1:5174`，只读、固定 as_of、无 realtime。
- 历史统计 2023-01-01..2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`；分钟近一年记录下界 2025-09-25。
- API identity 与 Web 编译模块分别验证 SHA；Web `/api/preview/identity` 只是 API proxy，不算独立 Web 证明。
- 已保留 root 原有 1m/30m warmup 文档及测试修正 `da3dec2f8`，集成 `a15ab71f0`；相对冻结候选仅增加空计划 hash 的 1m/5m 测试覆盖，生产源码一致。STATUS 与原路线图其他未提交修改保持。

## 数据与资产

12 个 rank1 physical owner：RB2305、RB2310、RB2401、RB2405、RB2410、RB2501、RB2505、RB2510、RB2601、RB2605、RB2610、RB2701。

5m 缺口以每个 owner 有效末日独立 hash plan 执行，仅派生维护：**95 个 target 成功、0 provider、0 失败/阻塞**；1m 来源未修改，15m/30m/60m 未重写。精确旧文件与前像、维护锁、单次 attempt、质量及独立零缺口 readback 保存。重算同物理合约完整 Session `(start,end]` 前缀，包含上市预热：**140 个 contract-month 全量 Decimal OHLCV/turnover/OI 一致**。早期 129 月读回漏掉预热月份，原输出保留，后续 140 月独立只读复核补齐；未重复生产写入。

5m 新建两基础流与一融合流，15m/30m/60m 九条既有流按 source/hash/revision/generation 复用。全部 **12 READY、computed_through=2026-09-24T07:00:00+00:00、disabled、generation=0**。资产仅在既有 `newow_intraday_pilot_20260927` 隔离 schema；没有 migration、正式消费者切换或 worker enable。

## API 与真实页面

| 周期 | 趋势 | 震荡 | 独立双策略 |
| --- | --- | --- | --- |
| 5m | PASS | PASS | PASS |
| 15m | PASS | PASS | PASS |
| 30m | PASS | PASS | PASS |
| 60m | PASS | PASS | PASS |

152 个实际 API GET 全部 HTTP200；检查主图 completed physical bars、共同行情字段、snapshot/source/hash、全窗统计曲线、近年记录、主图和参考游标、融合独立身份与两基础来源、辅助指标。scope capability v25 为 5m/15m/30m/60m/1d/1w；旧 Newow 1m 请求 HTTP409 `NEWOW_FREQUENCY_NOT_OPEN` 仅是关闭边界验证，不是 1m 产品验收。

真实 Chrome 12 组合、322 个响应：主图、记录、参考曲线、五项辅助、周期/策略离开返回、无错误检查通过；24 张 main/full-curve 原始分辨率截图由主代理 root 逐张视觉审阅。完整曲线补拍与辅助工具栏独立 DOM/命中/截图读回保留，未用最初截图不完整处冒充视觉通过。浏览器同日分页 **4 PASS、3 无下一页、5 实际跨日 NA**；API 同日分页也只有实际同日样本计入。NA 不改为 PASS。

实际 pending 请求切换取消、0.25 秒客户端超时、返回 5m HTTP200 恢复通过；旧 5m snapshot 用在 15m 的主图及记录分别 HTTP409 `NEWOW_SNAPSHOT_GENERATION_CONFLICT`，重新读取 15m 同身份主图/记录恢复。最初观察器漏掉 5m 的失败 attempt 原样保留，修正的是验收 helper，没有伪造响应。

分钟仅支持既有已完成交易累计曲线，逐 Bar 持有过程在 UI 明确不可用；OPEN 浮动、换月中断与已完成收益分离。本轮没有新增该参考模型、因果撮合、OOS 或账户语义。页面参考零成本收益不能称为账户/可执行收益。

## 日周兼容性与既有缺陷

独立 legacy 回归六个真实页面分别读取固定候选与截止：主图非空、ready、completed/physical/source、严格端点顺序与截止，全部已完成累计曲线、近一年记录精确投影、MACD/趋势转折及 60m 离开返回、无请求/页面/解析错误均核对；主代理 root 审阅十二张日周截图。W1 趋势转折 `NEWOW_TREND_REVERSAL_WARMING` 明确披露，不伪造 READY。初始分钟验收 helper 不适配 legacy 记录窗口及持有曲线模式的失败输出保留；新 helper 经独立复核收紧空 bars、陈旧截止误通过检查，离线复算原真实观察，不冒充又一轮浏览器运行。

**既有 D1 加载更早主图仍失败**：HTTP200 的 `chart.price_reference.as_of=2024-09-02T07:00:00Z` 与 generation `meta.as_of=2026-09-24T07:00:00.000001Z` 不一致，前端 `NEWOW_RESPONSE_INVALID` 后清空依赖。baseline `00cea970e` 与 `82a27a322` 对同一实际 body 都拒绝相同字段；normalizer、价格 projector 及后端关键分支一致，证明不是本轮 5m 枚举扩展引入。该项属于既有日线合同缺陷，未在本轮分钟范围修复，也未被改为分页通过；证据 `api/d1-older-price-reference-diagnosis.json`、真实 body 和 browser/d1-pagination-debug。

## 实际验证

实际测试输出保存于 `outputs/rb-minute-closeout-20260928/tests/`，关键入口如下：

- 后端 `pytest` product_service/reader/contracts/intraday_pilot/candidate_preview + historical_planning：456 passed；数据 manager/readiness/aggregation：278 passed；reference planning/driver/fusion/input/persisted：73 passed。以上集合存在重叠，不合计为唯一测试总数。
- Web `node --test tests/newow*.test.ts tests/useNewow*.test.ts tests/NewowProductChartStage.test.ts`：351 passed；Market/偏好/路由/capability 定向：52 passed；`npm run build`（vue-tsc/Vite/拓扑）通过。
- 维护脚本 9 passed；独立后端 389、最终兼容性 208 检查通过；Ruff、两份 OpenSpec、diff 与 secret scan（0 finding）通过。
- develop 集成后上述受影响后端与数据集合合并运行：**693 passed in 11.02s**，包括八种空计划 scope hash 相互隔离。
- 原宽 Newow/reference 套件 2559 passed / 48 skipped / 3 failed。两个旧 5m-invalid fixture 和一个既有保存 1m admission 回归已前向修复，456 定向覆盖全部三项；宽套件未在修复后重跑，不宣称全套绿色。

## 证据入口与边界

`outputs/rb-minute-closeout-20260928/` 保留 source-assets-final、final-asset-admission、5m-maintenance-progress、aggregation-full-prefix-readback、api/summary、browser/matrix、取消/快照恢复、完整曲线与实际日周回归记录。初始/失败/未审阅观察不改写，最终 browser/matrix 单独记录 root 视觉审核。原黑色批次输出保持原身份，不能把本次 RB 结果扩展为其他品种通过。

本轮未发布 main/tag/release、未切换正式 Runtime；正式 v1.10.39 的分钟开关仍关闭。候选历史服务保持有界本地预览，未开启 reference worker、观察 Scope、通知、订单、Shadow 或策略晋升。`auto_order=false` 不变。正式发布、实时启用及其他品种仍需各自证据，不能以 develop 集成替代。

本轮 RB 四派生分钟历史候选验收完成，允许集成 develop，已集成。唯一最小下一步为按同一四周期范围推进 HC；本轮不自动扩展。
