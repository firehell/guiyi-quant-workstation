# TASK-WEB-B1-DECISION-COMPRESSION-20260822

状态：READY_FOR_IMPLEMENTATION

日期：2026-08-22

原始代码基线：`develop@2d2cbca0b8cf765523bcd260565e94a53afa5238`

设计：`docs/superpowers/specs/2026-08-22-market-b1-decision-compression-design.md`

实施计划：`docs/superpowers/plans/2026-08-22-market-b1-decision-compression.md`

## 1. 任务目的

把 Market Web 从“信息展览”收敛为个人量化工作站的决策漏斗：

```text
首页：优先检查 0~3
→ 详情页：5~10 秒完成品种验证
→ Alert：正式 Event 打断
→ Execution Review：人工处理 / 复盘
```

本任务只做 Web 信息架构和确定性 view projection，不建设新的机会系统。

## 2. 价值 Gate

本任务只有四个允许的价值目标：

```text
减少主动遍历 60 品种的时间
减少首页视觉与逻辑判断负担
提高正式 Event / 研究观察的认知分层一致性
保留并更容易使用现有 Alert / Execution Review 证据链
```

如果实现需要 Opportunity domain、后端 ranking、策略统一 adapter 或新持久化才能成立，应立即停止并报告设计偏移。

## 3. Scope

### 允许

```text
现有 Market Radar D1 facts
现有 Product Research D1/W1 facts
现有 SuBing / HTDY Web observation
现有 Alert current events / rules
现有 Execution Review event-states
Vue view projection / UI layout / disclosure
Web unit / E2E / build
```

### 禁止

```text
Radar backend 新字段
全市场 W1 新扫描
OpportunityService / OpportunityModel
综合分 / 概率 / winner / 最佳机会
SuBing/N/JDJ/MFM 统一机会 adapter
策略公式 / Candidate / Research protocol 修改
MarketDataService / Canonical / Redis / DB / migration
Alert Rule / Scope / notification / Runtime 修改
main / tag / release / Runtime promotion
订单 / 自动交易
```

## 4. 文件白名单

生产代码只允许：

```text
apps/quant-web/**
```

文档允许：

```text
docs/superpowers/specs/2026-08-22-market-b1-decision-compression-design.md
docs/superpowers/plans/2026-08-22-market-b1-decision-compression.md
docs/tasks/TASK-WEB-B1-DECISION-COMPRESSION-20260822.md
```

任何需要突破白名单的实现必须停止并报告。

## 5. 固定产品合同

### 首页

```text
需要处理
优先检查 0~3
展开全市场研究
```

Focus 只使用现有 D1 Radar `reason_codes`：

```text
多头：ema21_up + 至少一个 price_move_up / volume_expansion / oi_increase
空头：ema21_down + 至少一个 price_move_down / volume_expansion / oi_increase
```

不计算综合分。

排序固定：

```text
支持原因数量
→ 增仓
→ 放量
→ 方向价格变化
→ 成交额
→ symbol
```

`degraded` 不产生 Top3；`pending_after_market` 明确 `data_as_of`。

### 详情页

默认检查顺序固定：

```text
1. 现在
2. 市场背景
3. 当前观察
4. 位置 / 参与
5. 提醒
6. 更多研究
```

其中：

```text
正式 Event = AlertEvent
研究观察 = current SuBing / HTDY
Research only = SuBing Lifecycle V2
```

三者不得互相替代。

## 6. Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Terra
- 推理强度：中
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：新 task worktree
- 人工 Gate：独立 Review

### Worktree

```text
branch: feat/web-b1-decision-compression
from: develop
integrate to: develop
允许自动 task → develop: 是，但必须先通过 Task 4 独立 Review
PR: 可选；遵循当时仓库正式流程
main/tag/runtime: 禁止触及
cleanup: 确认 commits 已进入 develop 后清理 task worktree 和已合并 branch
```

Tasks 1~4 是同一个 Web feature 的 TDD checkpoints，使用同一 task branch/worktree，不为机械步骤创建多套 branch。

## 7. Task 拆分

### Task 1 — 首页 Focus / 全市场研究折叠

必须完成：

```text
marketFocus.ts pure qualification + ordering
MarketFocusList.vue
0~3 Focus
0 个合法状态
current / pending / degraded freshness
原 Summary / Scatter / Attention / DetailTable 默认折叠但可访问
首页正式事项仍在最前
无新 route / backend
```

完成测试：

```text
marketFocus.test.ts
market-radar.spec.mjs
homepage portion of market-research.spec.mjs
Web build
```

### Task 2 — 详情页“当前检查栏”

必须完成：

```text
productCheck.ts pure view helper
ProductCheckSidebar.vue
getEventStates 复用
现在 = AlertEvent / Execution Review state
市场背景 = W1 + D1
当前观察 = selected overlay only
Lifecycle Research-only 明确
位置/参与 = 20日位置 / 量比 / OI / ATR
提醒开关只出现一次
更多研究默认关闭
Subing error/loading 不清空 Kline
```

完成测试：

```text
productCheck.test.ts
market-research.spec.mjs
alert-v1.spec.mjs
Web build
```

### Task 3 — Toolbar / Status / 深度研究降噪

必须完成：

```text
EMA + 指定合约收进“图表设置”
周期 / Overlay 仍是一等控制
identity card 压成状态行
正常状态安静、异常突出
Price / Volume / OI 移入更多研究
窄屏入口改为“检查”但不强制 localStorage migration
旧重复组件 zero-reference 后再删除
```

完成测试：

```text
Web unit
market-research / market-radar / alert-v1 E2E
Web build
```

### Task 4 — Cross-page acceptance / Review / integration

必须完成：

```text
/market -> Focus -> /market/chart cross-page journey
1440x900 / 1280x720 / 1024x768 无横向溢出
1024 下检查 Drawer 可访问
full Web unit
full Playwright
build
secret scan
diff check
forbidden-scope audit
独立 Review Critical=0 Important=0
```

Review 结论只能：

```text
允许集成 develop
要求修正后再集成
```

## 8. 关键验收语句

### 首页完成后用户应能在 5 秒内回答

```text
现在有没有待处理正式事项？
如果没有，我先检查哪 0~3 个品种？
其余全市场研究是否可以先不看？
```

### 详情完成后用户应能在 5~10 秒内回答

```text
现在是否有正式 Event？
周线 / 日线是否支持？
当前 Overlay 在什么阶段？
位置 / 量价参与是否值得继续观察？
```

默认验证态不需要展开 Factor / Lifecycle 详细表、今日历史记录或 Price / Volume / OI。

## 9. 验收命令

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

范围审计：

```bash
git diff --name-only develop...HEAD
rg -n "Opportunity(Service|Model)|opportunity_score|综合分|最佳机会|推荐交易" apps/quant-web/src
```

## 10. Codex 开工 Prompt

```text
请先阅读 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`，以及：

- `docs/superpowers/specs/2026-08-22-market-b1-decision-compression-design.md`
- `docs/superpowers/plans/2026-08-22-market-b1-decision-compression.md`
- `docs/tasks/TASK-WEB-B1-DECISION-COMPRESSION-20260822.md`

本任务为 Lane 2，Terra，中推理，Plan-then-execute。

目标：
完成 Market B1 Decision Compression，严格按 implementation plan 的 Task 1 → Task 4 顺序执行。

工作区：
从最新 `develop` 创建 `feat/web-b1-decision-compression` 独立 task branch/worktree。
不得修改 main/runtime worktree。

核心边界：
1. 首页只用现有 D1 Radar facts 生成 0~3 个“优先检查”；
2. 详情页负责 W1/D1/当前 Overlay/位置参与的验证；
3. 正式 Event 只认 AlertEvent；Lifecycle 保持 Research only；
4. 不改后端、策略、Alert、DB、Runtime；
5. 不建立 Opportunity domain，不做综合分或 winner；
6. 所有旧研究能力只降级视觉权重，不因重构丢失。

验收：
执行 Task 1~4 指定测试，最终 full Web unit + full Playwright + build + secret scan + diff check 全绿；完成独立 Review，Critical=0、Important=0。

完成流转：
通过后按仓库正式流程完成 task branch → develop，并在确认提交进入 develop 后清理临时 worktree/branch。
不得发布 main/tag，不得 Runtime promotion。

完成后输出：
修改摘要、Task 1~4 完成状态、测试结果、独立 Review 结论、集成/清理结果、风险与未完成项。
```

## 11. 最终允许结论

实现阶段最终只允许：

```text
允许继续实现
要求修正后再集成
允许集成 develop
阻塞
```

本任务不产生：

```text
允许发布 main/tag
允许 Runtime promotion
```
