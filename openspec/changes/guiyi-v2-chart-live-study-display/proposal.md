# Change: Warm and update generic Web chart studies from verified market display data

## Why

Free, HTDY and SuBing charts currently initialize generic studies from the visible Canonical page. Loading an earlier page can change an EMA at the same endpoint. Completed Live candles and active candle previews have no generic study result.

## What Changes

- Give the Web chart adapter a versioned, page-independent calculation anchor and bounded warm-up.
- Extend the existing display read contract with source-tagged completed Live results and an ephemeral active result.
- Preserve the Chart Catalog, profiles, published Newow reference layers and business fact sources.

## Impact

- Affected specs: chart-indicator-system.
- Affected code: chart study API and display adapter, Web workspaces, Quant Chart presentation package when renderer changes are needed.
- Reuse MarketDataService, Market display snapshots, Compute Runtime and Quant Core. This change has no Market writer, formal strategy, account, notification or Runtime promotion scope.
