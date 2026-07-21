# WEB-V1-09：复盘 deep-link 与安全展示（关键）

```text
WEB_REVIEW_EXACT_LINEAGE_READY
WEB_REPORT_TRADE_REVIEW_ROUNDTRIP_READY
```

## 收口

- `parseReviewDeepLinkQuery` + `report_id` 过滤交易来源
- 全局 `toSafeApiError` 替代原始 detail 透传
- attachment 仅显示文件名，不暴露绝对路径
- 未保存修改提示（`*` + Alert）

## 修改

- `apps/quant-web/src/pages/review/index.vue`
