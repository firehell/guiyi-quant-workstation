# Market 统一详情页剩余切换合同

核对日期：2026-09-09；代码基线：`0a5a49a975997c0272b3411a5c36814185d2e249`。

本文只保留尚未完成的旧页切换要求。已实现的 Shell、HTDY、Trend、SuBing 与 Newow 产品合同以
`PROJECT_SOURCE.md`、`docs/ARCHITECTURE.md` 和 active OpenSpec 为准；旧实施代码示例与调度步骤从 Git history 追溯。
当前状态集中在 `STATUS.md`。本文不授权本次审查执行页面架构改动。

## 剩余目标

完成切换后，`/market/chart` 由统一页面管理身份、视角与错误状态。必须先确定无 `view` 旧链接的
确定性迁移规则，覆盖 symbol、series_kind、contract、frequency、overlay 和 focus；不能把合法旧链接
直接丢成默认趋势日线。保留 `view=trend` 的固定 `actual_dominant + 1d` 产品兼容合同；它与
`LegacyMarketChart.vue` 旧页面是两个独立概念。

随后才能删除旧页及“返回旧版详情”入口，同时关闭其 active imports、旧路由构造器与专用偏好分支。
共享行情、指标、Event 和有效兼容测试继续保留；只有已退役路径的专用测试可随实现一起删除或替换。

## 不可破坏的产品边界

- Newow 三策略 × `1w/1d/60m` 只消费 typed API；Action、Hint、ReferenceTrade、统计与证据不串身份。
- HTDY raw retrospective 与 immutable Event 分开；苏冰正式 `S↑/S↓` 只来自 Event，独立历史参考明确标注历史重算。
- Free 无策略 Marker；Range Detector 仅研究显示。
- Event 深链只定位精确 Bar；跨品种切换清除不兼容 contract/focus；Workspace 切换不串图层、历史或披露状态。
- Rule、Scope、Runtime、Event 空/失败/不可用分别呈现，provider accepted 不写成实际送达。
- 浏览器不计算正式公式，不配对交易，不增加生产写入、Scope、通知或订单入口。

## 切换验收

1. 旧无 view 链接、显式四视角、固定 D1 trend 兼容链接、HTDY/SuBing Event 深链均有确定性转换和拒绝规则。
2. 普通首页进入 Newow 趋势日线；品种选择和恢复不再返回旧页，非法输入给明确恢复入口。
3. 单一页面控制身份；旧页、返回旧页入口及其 active references 同步删除，没有空 Tab。
4. 保留 current/reference、same-bar、physical owner、snapshot、warming、unavailable 与 repaint 边界。
5. 定向 route/controller/Marker 测试及必要 Web unit、build、Playwright、OpenSpec、secret/diff 检查通过。
6. 完成桌面/390px与键盘验收，并由用户完成关键桌面/移动端视觉审查；独立 Review 无阻塞发现后才集成 develop。

命令只看 `TESTING.md`。切换完成不代表 release 或 Runtime promotion；回滚使用 Git revert，不创建旧页副本。
