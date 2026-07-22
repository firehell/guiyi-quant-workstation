# WEB-V1-13 W13-02 Workspace Shell 验收

日期：2026-07-22

状态：`WEB_PERSONAL_WORKSPACE_SHELL_READY`

## 实现

- 侧栏按“工作 / 研究 / 系统保障”重组，所有 route path/name 保持不变。
- Batch 保留为回测中心二级入口；Settings 下沉至系统保障。
- `WorkspaceContext.vue` 只读取当前 URL 中显式存在的 symbol、contract、period、data_mode 与 contract_view，缺失字段不猜测。
- `SystemPulse.vue`、`stores/runtimePulse.ts` 统一消费 `/api/runtime/health`；Shell、Dashboard、Runtime 共享同一 Pinia 快照。
- 首次进入加载；60 秒 freshness；in-flight 去重；页面 hidden 时不刷新；恢复可见且过期时刷新；卸载时清理 timer/listener。
- Runtime 页面不再自行维护第二份 health 请求状态，手动刷新仍是只读 GET。

## 验收证据

- `workspaceShell.test.ts`：3 passed，覆盖 URL 不猜测及 Pulse 刷新决策。
- Web unit：108 passed / 1 skipped / 0 failed。
- Web build：passed。
- mock E2E：11 passed；Dashboard→Runtime 导航只产生一次 health 请求。
- 既有 Market query 规范化语义未修改。

Gate：

```text
WEB_PERSONAL_WORKSPACE_SHELL_READY
WEB_NAVIGATION_WORKFLOW_READY
WEB_SYSTEM_PULSE_READONLY_READY
```
