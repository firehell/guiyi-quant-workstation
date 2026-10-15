# 第一批工程收敛设计与实施记录

基线：`9bfaea867f471ac38b922730409372cab4211402`；范围为已交办的八项工程收敛，交付至 develop。

## 设计

采用现有消费者驱动的小型公共模块，不增加依赖或通用插件框架。只修复已确认的身份问题、
共享交互与绘图机制、收敛工程合同；公式、收益计算、参考交易事实及 Runtime 执行政策保持现有合同。

- 异步事实：一个 identity/generation 生命周期负责身份变化时清空、过期响应隔离、错误与销毁；
  HTDY/SuBing adapter 保留 Rule/Scope 与 Runtime 的各自验证和展示。
- 弹层：公共焦点与可重入滚动锁支撑 dialog/drawer；原生 dialog 统一管理异步 close、立即重开、
  identity 变化和卸载，业务包装保留插槽、可访问名称与皮肤。
- 曲线：纯布局函数处理有限数值、轴范围、刻度、分段与面积；共享 SVG 层负责绘制；
  各收益面板提供自身标准化点与明确日期/轴政策，保留 reference/page/fusion 统计和配对语义。
- 样式：弹层及收益图基础交互使用语义变量；page-parity 使用明确皮肤变量，保持现有视觉值。
- Runtime：服务集合放在无副作用合同模块；原模块导入同一集合，现有消费者无需改变合法服务。
- HTTP probe：两个诊断入口复用一次 curl 的状态/耗时/退出结果，保留环境诊断，离线测试不访问服务。
- 文档：STATUS 仅修正过时下一步并准确记录本批工程结果；TESTING 增加稳定入口，历史临时快照明确为证据。

## 实施与验收计划

1. [x] 异步事实：先复现 HTDY pending 旧 Scope 和错误响应身份，再抽公共生命周期，补异常/销毁/乱序回归。
2. [x] 弹层：抽公共行为，保留包装，浏览器验证 Escape、焦点、关闭立即重开、身份切换与卸载。
3. [x] 曲线：抽布局与 SVG，覆盖单日、全零、全亏损、夜盘日期和合约段断点，验证原收益数据不变。
4. [x] 样式：随弹层/曲线迁移基础 token，检查桌面与390px布局和外观。
5. [x] 验证：移除本批被抽取实现的源码正则约束，保留架构边界；以可观察行为覆盖生命周期。
6. [x] Runtime：统一服务集合，运行 bindings/handover/bootstrap/恢复/回收适用回归及独立 Review。
7. [x] HTTP：共享一次探测，离线模拟成功、HTTP失败、连接失败与部分响应，检查两个入口与 shell 语法。
8. [ ] 文档与集成：核对最新 STATUS，补稳定测试入口，运行完整 Web unit/type/build、工程检查、secret scan、
   定向浏览器及独立 Review，修正后提交、推送并集成 develop。

## Review 重点

- 身份 A 的事实不得在身份 B 请求等待期间展示；旧请求和 dispose 后结果不得提交。
- 原生 close 事件延迟到重开后到达时不得误关闭；滚动锁嵌套关闭不提前恢复滚动。
- 交易日和自然日不可互换；绘图抽取不得改变理论值、参考收益或跨合约断线。
- Runtime 集合抽取不得增加导入副作用、改变服务集合或启动服务。
- HTTP 状态、耗时和退出码必须来自同一次请求；传输失败不得报健康。

## 实际验证与交付

- `node --test apps/quant-web/tests/*.test.ts`：1128 passed、3 skipped。
- `pnpm -C apps/quant-web build`：类型、生产构建及 bundle topology passed。
- `PLAYWRIGHT_PORT=5193 pnpm test:e2e overlay-lifecycle.spec.mjs alert-facts.spec.mjs return-curve-layout.spec.mjs market-detail.spec.mjs`
  （在 Web 目录执行）：50 passed、2 failed；其中本批新增14项全部通过。
- 两个失败在未修改的最新 develop `c5deda5aa` 以 `PLAYWRIGHT_PORT=5195 pnpm test:e2e market-detail.spec.mjs --grep 'SuBing has stable|SuBing history opens'`
  原样复现：旧苏冰1440截图差2736像素，事件详情旧文案断言未包含当前“未记录”。候选与基线实际截图SHA256均为
  `8e29f05fd48ce7925bfe1138acc1cc7d41f1ae9d92bedd81b638646d58f68d27`。
  不更新截图或放宽断言；不声明完整E2E通过。
- 主树既有 Python 环境、候选工作区 `PYTHONPATH=.:services/quant-api:packages/quant-core`，
  `pytest -q -p no:cacheprovider` 选择两个 engineering 合同/卫生文件及 Runtime bindings/handover/entry/
  bootstrap/fault recovery/retention/deployment/identity/live recovery guard 与 HTTP probe：232 passed、1 skipped。
  skip 为未配置隔离Redis的bootstrap测试，不算该环境验收。
- 三个网络脚本 `bash -n`、改动Python Ruff、`git diff --check`、secret scan（0 findings）通过。
- 独立 Review 无 Confirmed Issue 或新增阻断项；另行复跑弹层10项Chrome、曲线桌面/390px两项、
  异步23项及Runtime/工具128项（1 skipped），确认收益事实算法不变。
- Fusion关闭曲线仅使用已有权威退出交易日；缺字段时显示原因并保留摘要/记录。
  FusionTrade当前不提供segment身份，关闭曲线保持以physical contract断段；holding/page保留完整区段。
- 本批交付至develop；没有执行发布、Runtime切换、通知或生产数据操作。
