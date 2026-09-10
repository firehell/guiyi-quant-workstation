## 1. 定向复现（RED）

- [ ] 1.1 从实施时干净 develop 建立独立任务工作区，核对当前 composable 和 active Newow spec；不得合入其他优化。
- [ ] 1.2 在 `apps/quant-web/tests/useNewowProduct.test.ts` 使用 controlled Promise 构造 chart 冲突后 explanation 晚到的回归，记录原实现失败；同时覆盖忽略 abort 与晚到 reject。
- [ ] 1.3 添加失效范围矩阵、旧 finally/新请求、旧 token/cache、分页和 current-window 状态断言；保留同 token 跨窗、409 一次重建与 429 不重试保护测试。

## 2. 局部实现（GREEN）

- [ ] 2.1 在 `apps/quant-web/src/composables/useNewowProduct.ts` 提取私有 section 失效操作，并让冲突、token、chart generation、reset 等相关清理入口复用；显式区分普通失效与当前一次重建的保留请求模式。
- [ ] 2.2 按设计的范围矩阵调用，先计算匹配集合再清理；检查主要冲突不遗留可被 compatibleToken 选中的其他资源。
- [ ] 2.3 运行 composable、API、类型、reference/explanation 相关测试；确认未改变服务端兼容合同及请求重试上限。

```bash
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/useNewowProduct.test.ts tests/newowApi.test.ts tests/newowProductTypes.test.ts tests/newowReferencePanel.test.ts tests/newowExplanationPanel.test.ts
pnpm --dir apps/quant-web build
```

## 3. 页面与工程验收

- [ ] 3.1 在 `apps/quant-web/e2e/newow-product.spec.mjs` 增加受控响应顺序案例；按 `TESTING.md` 在隔离 5182 执行固定 fixture，记录冲突不恢复旧解释、重新加载可恢复及合法导航保持 reference 的页面结果。
- [ ] 3.2 独立 Review 并发交错和清理范围；完成 diff、secret 与 OpenSpec 检查，修正反馈后再集成。
- [ ] 3.3 交付实际命令和结果，明确 fixture browser acceptance 与生产/Runtime 验收边界；实现完成前保持任务未完成状态，不提前改写 STATUS。

隔离页面命令（执行前确认无外部后端环境覆盖；不复用他人服务）：

```bash
REAL_BACKEND=0 PLAYWRIGHT_PORT=5182 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5182 PLAYWRIGHT_CANDIDATE_PREVIEW=0 PLAYWRIGHT_SKIP_WEBSERVER= pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs
```
