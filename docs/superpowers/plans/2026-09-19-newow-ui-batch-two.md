# 牛哇第二批：参考记录阅读与定位闭环

**Goal:** 完善参考交易详情、图表定位与返回、宽内容布局、局部视觉一致性。

**Architecture:** 延用现有 ReferencePanel、Workspace、精确定位 resolver 与 dialog；仅扩展展示状态及用户触发的定位事件。既有服务端统计和身份合同不变。

**Tech Stack:** Vue、TypeScript、现有 CSS tokens、Node test、Playwright，无新增依赖。

**Spec:** 用户已认可的第二批四项视觉交互范围，设计和验收见本文。执行使用 executing-plans；沿用原 terra / medium 会话，不创建重复任务。

## 开工基线与前置检查

基线 develop `dbaef4324`，包含第一批修复 `b05e0329d`。主会话复跑杯柄、日期、参考面板、比较排序四文件，18/18通过；原会话报告完整Web647通过1跳过、build通过、Newow E2E61通过。这不是生产或Runtime验收。

- [ ] 在原会话核对 branch/worktree/HEAD/diff，保留无关修改。补充第一批修复的独立Review：重点杯柄响应与原副图隔离、窗口选中态、异步切身份；确认P1/P2清零再开始第二批代码。发现未收口项先修复，不以第二批掩盖。
- [ ] 两份 `2026-09-19-unified-reference-trading-*` 文档是其他任务，不修改、不暂存；若该任务已改同文件，基于最新develop协调，不实施后台持久化/增量计算设计。

## 设计与边界

参照 `docs/research/newow-v3.2.82/screenshots/20260918/600519-composite.png` 的紧凑记录、红绿数字、浅底卡片与分层说明；定位与返回是归一增强，不宣称原站完全一致。继续使用第一批已实现的宽版弹窗，不重新做一套。

- 参考交易仍为非账户、零费用/零滑点页面事实，不新算收益、目标、手数、年化或曲线。
- 不改策略、合约映射、行情链路、API统计合同、开放周期、发布或Runtime。
- 不删除技术证据；将其折叠为第二层。中断不是清仓，估值不是成交。
- 不恢复退役能力；W1等严格服从当前capabilities，不硬编码成旧D1-only或新全开放。
- 不覆盖全站主题，不新增暗色模式开关；仅遵循项目已有主题合同和tokens。

## Task 1：参考交易详情分层

文件：`apps/quant-web/src/components/market/detail/newow/NewowReferencePanel.vue`、必要时同目录新增 `NewowReferenceTradeDetails.vue`；测试 `apps/quant-web/tests/newowReferencePanel.test.ts`。

- [ ] 先增加组件行为测试：CLOSED显示建仓/清仓；OPEN显示建仓/估值；中断显示原因和最后有效估值，不出现虚构清仓；initial保持原来源语义；所有收益仍等于输入字段。
- [ ] 详情按“参考建仓 / 参考清仓 / 参考估值 / 中断说明”有条件分组，每组价格优先、日期次之。只渲染适用组，不用一串横线填满空字段；无法取得事实时明确不可用。
- [ ] 技术身份、版本和Hint原始字段放底部来源折叠，保留原精确ID及已加载Hint可用性。展开/筛选/分页不重算统计，不产生额外行情请求。
- [ ] 测试详情展开收起、筛选后恢复、分页稳定ID及键盘操作；通过后提交。

## Task 2：精确定位反馈及返回原记录

文件：`NewowProductWorkspace.vue`、`NewowReferencePanel.vue`、`apps/quant-web/src/utils/newowProductViewModel.ts`；测试 `newowReferencePanel.test.ts` 和 `apps/quant-web/e2e/newow-product.spec.mjs`。

- [ ] 沿用 `resolveNewowReferenceLocate`，扩展可选定位端点 `entry | exit`，默认entry保留现有调用。清仓必须有服务端exit_signal_id、exit_bar_end、exit_trading_day；字段缺失禁用并说明，不能推断。
- [ ] 先写用例：entry/exit已加载、需加载历史窗口、缺ID、无清仓、跨快照、同Bar不同signal、物理合约不符。精确匹配除signal/date外校验既有物理合约/segment身份，失败不跳相邻Bar。
- [ ] UI将“定位图表”明确为“定位建仓”；只有完整清仓事实提供“定位清仓”。点击显示该记录定位中，成功说明合约/动作/日期，失败保留记录和原因。
- [ ] 将定位上下文绑定 identityKey、快照与请求序号，任何await后重新校验；快速点击两条记录仅最后一次生效，切品种/策略/周期/快照立即作废。不得用全局布尔loading作为唯一竞态保护。
- [ ] 图表附近显示“返回原记录”，使用稳定reference_trade_id恢复该卡片滚动和键盘焦点，不按数组序号。筛选隐藏/记录不在当前页时不擅自无限加载或改筛选，提示原因并返回记录区域。
- [ ] 返回只恢复列表阅读位置，不自动改统计窗口、不声称恢复原图表窗口。点击定位后只有真正收到精确focus回读才宣称定位成功；如果现有图表回读无法支持，完善该局部事件，不猜成功。
- [ ] 加E2E覆盖两次定位乱序、定位中切身份、清仓不可定位、返回焦点、筛选后返回；通过后提交。

## Task 3：宽内容与移动端细化

文件：`NewowDetailDialog.vue`、`NewowExplanationPanel.vue`、`NewowReferencePanel.vue`及其局部详情组件。

- [ ] 复用现有wide属性。普通解释紧凑，比较器/多字段证据宽版；不再扩大所有弹窗。长ID可断行，数字不截掉正负号/单位，列表来源折叠不撑宽页面。
- [ ] 390px窗口下详情单列，比较卡单/双列；1440px合理多列。宽表不能靠把字挤成竖列维持布局；已提供卡片时手机可隐藏重复表但不得丢字段。
- [ ] E2E断言390px页面无水平溢出，弹窗内部可滚动，Escape/Tab/关闭后焦点正确；保留对长ID、负数、暂无值的fixture。

## Task 4：局部颜色与主题统一

文件：上述Newow组件；复用 `apps/quant-web/src/styles/tokens.css` 与既有主题入口，不修改全局业务色含义。

- [ ] 将本批涉及的硬编码背景/边框/说明色替换为已有等义token；必要的新token局限Newow容器，不搭建新主题框架。
- [ ] 保持上涨红、下跌绿、当前选择橙、空仓蓝、中断有文字及图标；零/未知不等价。状态不只依赖颜色，焦点ring可见。
- [ ] 逐张查看桌面1440和手机390的记录展开、建仓/清仓定位、返回、宽弹窗截图，对照原站信息层级。只验证项目已有主题，不宣称未支持主题已适配。

## Review Focus 与交付

必须验证：中断误作清仓（Task1）、同Bar错信号/跨合约（Task2）、迟到响应导致错焦点（Task2）、返回目标被筛选移除（Task2）、长ID和键盘弹窗（Task3）。

- [ ] 定向测试先RED后GREEN；新增真实行为断言，源码文案正则不算交互验收。
- [ ] 运行 Web test/build 和以下三组完整E2E，不只刷新截图基线：

```sh
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
env -u NO_COLOR -u FORCE_COLOR pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs
git diff --check
```

- [ ] 为新增异步定位和身份校验完成独立Review，P1/P2清零。基线失败需同基线证据，不直接归为既有。
- [ ] 将代表性fixture截图和“原站/实现/有意差异”更新到现有implementation-ui目录，标明日期/commit/fixture。更新CURRENT_AUDIT和手册，仅声明实际完成的四项；不重复宣称完整算法复刻。
- [ ] 自审、精确暂存、commit/push、核对最新develop并重测冲突影响，满足Gate后集成。没有main/tag/release、生产数据或Runtime授权。
- [ ] 最终交付四项结果、第一批Review收尾结论、测试输出、截图链接、提交和未完成Gate；完成报告不能以下一批代替本批未完项。
