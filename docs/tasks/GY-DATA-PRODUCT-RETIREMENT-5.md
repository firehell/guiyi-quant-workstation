# GY-DATA-PRODUCT-RETIREMENT-5：多品种退役收口

更新时间：2026-08-09  
Disposition：`historical_fact`

## 范围

从 active universe 彻底退役以下品种（小写精确匹配）：

| 代码 | 名称 |
|---|---|
| `ic` | 中证500股指 |
| `if` | 沪深300股指 |
| `ih` | 上证50股指 |
| `im` | 中证1000股指 |
| `sp` | 纸浆 |
| `cs` | 玉米淀粉 |
| `br` | 丁二烯橡胶 |
| `nr` | 20号胶 |
| `lu` | 低硫燃料油 |

Active universe：**60**。退役名单：`data/universe/retired_products.txt`（9 码）。

## 仓库合同（已落地）

- 配置：`active_products.txt` / `product_window_starts.csv` / `retired_products.txt`
- 硬拦截：CLI 与 MarketDataService / MetadataSynchronizer；公开码 `PRODUCT_RETIRED`
- 清退：`guiyi data retire-products`（默认 dry-run；`--apply` 硬删八表相关行 + Canonical 目录）
- OpenSpec change：`retire-index-and-pulp-products`

## 已执行生产清退（单次意图已消耗）

在用户明确意图下，对生产 PostgreSQL + 正式 Canonical 根多次执行
`guiyi data retire-products --apply`，覆盖上表九码。最近一次清退 `br/nr/lu` 时删除前
instruments=3、contracts=228；Canonical=0；事后 residual=0；`--symbol br` → `PRODUCT_RETIRED`。
相关意图已消耗；再次生产 mutation 须新的单次意图。本文档不再构成后续删除授权。

## 明确不做

- 不删除 `exchanges` / `trading_calendars`
- 不改八表 schema / Alembic
- 不恢复旧 `data_core/product_retirement` 大框架
