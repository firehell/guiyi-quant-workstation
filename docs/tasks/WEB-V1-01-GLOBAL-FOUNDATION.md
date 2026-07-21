# WEB-V1-01：全局交互基础与可信边界

```text
WEB_GLOBAL_FOUNDATION_READY
WEB_ERROR_REDACTION_READY
```

## 修改摘要

- `PageShell`：badges / status / error+retry / loading / empty 统一槽位
- `CapabilityBadge`：formal-research / research-only / observation-only / historical-replay / live-confirmed / rejected / unavailable
- `errorRedaction.ts` + `request.ts`：Production 不打成功日志；开发仅安全摘要；UI 错误脱敏
- `MainLayout`：`onErrorCaptured` 路由兜底 + `RouteErrorFallback`
- `NotFound` 路由；仪表盘示范 badge + safe error
- 桌面断点 1440 / 1280 / 1024 内容区适配

## 测试

- `npm test`：91 tests / 90 pass / 1 skipped
- `npm run build`：通过
- `check-secrets.sh`：通过

## 剩余页面

各业务页将在 WEB-V1-02～10 逐步接入 PageShell retry / CapabilityBadge / toSafeApiError。
