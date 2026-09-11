## Why

Newow `failConflict` 清空页面结果，但未取消关联请求或推进 section generation。已复现：chart 共享 Bar 冲突后，晚到的 explanation 响应重新填回数据，使冲突页面呈现来自旧快照的解释。

## What Changes

- 在 composable 内统一“使请求过期、取消、清除数据及导航状态”的局部操作。
- 明确不同冲突和切换的影响范围，阻止晚到成功、异常及 finally 污染新状态。
- 保留同 token 的合法跨 chart 窗口导航、严格同窗口分页、最多一次 409 重建及 429 不重试。
- 增加可控制 Promise 顺序的回归及隔离页面验证，不引入通用前端请求框架。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `newow-product-reference-trading`：落实冲突失效时取消在途请求并阻止晚到响应的现有合同。

## Impact

主要涉及 `apps/quant-web/src/composables/useNewowProduct.ts`、其 unit test 与现有 `e2e/newow-product.spec.mjs`。API schema、策略公式、token 服务端语义不变。

本 change 已完成实现与独立 Review。定向测试及新增浏览器回归通过；完整浏览器文件仍有两项精确复现的既有失败，不声明完整浏览器 Gate 通过。验证使用固定 fixture 和隔离页面，不代表生产行情或 Runtime 验收。
