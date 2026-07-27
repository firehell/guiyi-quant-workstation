# WEB-V1-10：Runtime / Dashboard / Settings

```text
WEB_RUNTIME_OBSERVABILITY_READY
WEB_CONNECTION_SETTINGS_READY
```

## 收口

- Runtime：展示 `scheduler` + `archive` 专节（类型已有，消费 health）
- Settings：连接测试仅 `GET /api/runtime/health`；不显示 token
- Dashboard：`CapabilityBadge`；Registry≠validated；不硬编码漂移 Gate

## 修改

- `apps/quant-web/src/pages/runtime/index.vue`
- `apps/quant-web/src/pages/settings/index.vue`
- `apps/quant-web/src/pages/dashboard/index.vue`
