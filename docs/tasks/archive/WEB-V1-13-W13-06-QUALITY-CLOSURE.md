# WEB-V1-13 W13-06 状态、性能、安全与可访问性 Receipt

更新时间：2026-07-22

## 结论

`WEB_SINGLE_USER_STATE_READY`

`WEB_INTERACTION_PERFORMANCE_READY`

`WEB_ERROR_REDACTION_READY`

`WEB_ACCESSIBILITY_BASELINE_READY`

`NO_SENSITIVE_WEB_EXPOSURE`

真实 PostgreSQL readonly 网络 Gate 不在本 receipt 冒充通过，继续由 W13-07 验收。

## 状态与分页

- Backtest tasks/reports、Review list/sources、Signal latest/events 均支持 `paged=true&limit&offset`，返回 `items/total/limit/offset`。
- 旧调用不带 `paged` 时仍返回原数组契约；定向测试同时覆盖旧、新响应。
- Web 列表全部改用服务端分页；分页、来源筛选和研究选择属于 URL 业务语义，滚动位置只放 `history.state`。
- localStorage 仅保留显示偏好；API/WS 临时连接覆盖迁至 `sessionStorage.guiyi_connection_overrides`。

## 安全与性能

- 启动时删除旧 `localStorage.token`/`sessionStorage.token`；Axios 请求层永久移除 Bearer 注入。
- Settings 不展示凭据，连接测试仍只调用 GET runtime health。
- Signal 列表与 event 列表用 AbortController 取消旧请求；复盘/回测/Market 使用请求序号拒绝 stale response。
- 信号任务轮询改为串行 `setTimeout`，hidden 时不请求，恢复可见时刷新；卸载时清理 timer、visibility listener、WebSocket 和 AbortController。
- 错误展示继续经过安全适配，不回显路径、query/body、token、SQL 或 traceback。

## 可访问性与响应式

- Market 四 Tab 使用原生 tablist/tab/tabpanel 语义、roving tabindex、ArrowLeft/ArrowRight/Home/End 键盘切换与 focus-visible。
- Logo、System Pulse、工作区上下文、动作区、加载和错误状态保留可访问名称。
- Browser Gate 在 1280×720 和 1440×900 检查无页面级横向溢出。

## 验证证据

```text
npm test
119 passed / 0 failed / 1 skipped

npm run build
passed

npm run test:e2e  (fresh Vite candidate)
14 passed / 0 failed

pytest: backtest task API + signal event API + review API + signal/review profile lineage
41 passed / 0 failed

ruff check (W13-06 changed Python)
passed

bash scripts/engineering/preflight.sh --json
0 failed / 2 warnings / 6 passed
warnings: step worktree dirty; data/parquet absent and not auto-created

bash scripts/engineering/check-secrets.sh
scanned_files=9155 / passed
```

Mock browser 网络审计断言没有 Authorization header；readonly 研究往返未产生 POST/PUT/PATCH/DELETE。真实环境只读审计仍待 W13-07。

## 边界

- 无 migration、无模型字段变化、无 SignalEvent 生成变化、无策略/回测/数据/Profile/Runtime Gate 变化。
- 未 push、merge、deploy，未启动 worker/scheduler，未真实发送或写真实业务数据。
