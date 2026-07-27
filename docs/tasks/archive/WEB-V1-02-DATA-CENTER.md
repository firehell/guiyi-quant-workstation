# WEB-V1-02：数据中心性能与安全收口

```text
WEB_DATA_CENTER_BOUNDED
WEB_DATA_ASSET_BOUNDARY_VISIBLE
NO_PHYSICAL_PATH_EXPOSURE
```

## 变更

- 新增 `/api/v1/data/summary` 首屏计数
- coverage / download-tasks / quality-reports 支持 `paged=true` + 筛选；旧无参 list 兼容
- 默认 `include_paths=false`，`file_path` 为 null
- 前端 Tab lazy load、服务端分页、每 Tab 独立错误重试、Profile 只读 Tab

## 测试

- 前端 `npm test` / `npm run build`
- `pytest -k "data_center or coverage or profile"`
