# WEB-V1-05：策略中心能力边界

```text
WEB_STRATEGY_CAPABILITY_BOUNDARY_READY
NO_REGISTRY_EQUALS_VALIDATED
```

## 裁定

- Registry 只读展示；`is_v1b` ≠ validated
- 后端 `capability_classes` 为 machine source；缺失时前端默认 `research_only`
- 「JM 扫描」统一为「历史研究扫描」
- `rejected` 候选无 live / 扫描按钮
- 全页使用 `CapabilityBadge` 按能力分区

## 修改

- `apps/quant-web/src/pages/strategy/index.vue`
- `apps/quant-web/src/utils/strategyCapability.ts`
- `apps/quant-web/src/types/dashboard.ts`
- `services/quant-api/app/services/strategy_registry.py`
- `services/quant-api/app/schemas/dashboard.py`
