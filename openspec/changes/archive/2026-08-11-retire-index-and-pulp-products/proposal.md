## Why

研究观察池应聚焦商品期货；股指、纸浆、玉米淀粉及部分化工/能源品种不再属于 active universe。
仅改名单无法阻止显式 CLI/API 再拉或 DB/Canonical 残留继续出现在 Market 列表，需要配置、
硬拦截与可审计清退一并收口。

## What Changes

- **BREAKING**：active universe 从 69 收口为 **60**；退役精确名单为
  `br`/`cs`/`ic`/`if`/`ih`/`im`/`lu`/`nr`/`sp`（9 码），退出 `active_products.txt` 与窗口起点表。
- 新增并维护 `retired_products.txt`，与 active 互斥。
- CLI（`update`/`refresh`/`audit`）与 `MarketDataService` / MetadataSynchronizer 对退役码精确硬拦截（`PRODUCT_RETIRED`）。
- 新增 `guiyi data retire-products`：默认 dry-run 盘点；显式 `--apply` 按依赖序硬删八表相关行并删除对应 Canonical 目录；报告 residual=0。
- 同步现行文档与 active OpenSpec 中的品种数量表述；任务合同 `GY-DATA-PRODUCT-RETIREMENT-5`。
- 生产 `--apply` **不**由本 change 自动授权，须另给范围明确的单次执行意图（已分批消耗并记入合同）。

## Capabilities

### New Capabilities

- `product-retirement`: 退役名单、精确硬拦截、`retire-products` dry-run/`--apply` 清退合同，以及 active universe 60 与 retired 互斥约束。

### Modified Capabilities

- （无主规格目录 `openspec/specs/` 可改写；universe 数量与拦截行为由本 change 的 `product-retirement` delta 定义。）

## Impact

- 配置：`data/universe/active_products.txt`、`product_window_starts.csv`、`retired_products.txt`
- 代码：`guiyi_cli/data_*`、`market_data/product_retirement.py`、maintenance / infrastructure / MarketDataService
- 文档：`STATUS.md`、`PROJECT_SOURCE.md`、`README.md`、`docs/DATA_CENTER.md`、`docs/tasks/*`、active `converge-canonical-data-foundation`
- 数据：开发/生产八表相关行与 Canonical `symbol={retired}` 目录（生产删除各需单次意图）
