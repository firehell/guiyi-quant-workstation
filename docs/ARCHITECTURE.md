# 归一量化 Active Architecture

本文件只描述当前 active 模块和消费者依赖；产品边界见 `PROJECT_SOURCE.md`，业务公式见 deep canonical，当前部署与 Gate 见 `STATUS.md`。

## Dependency graph

```mermaid
flowchart LR
  RQ[RQData] --> HDM[HistoricalDataManager<br/>staging + validation]
  HDM --> CP[Canonical Parquet]
  CP --> CAT[八表 Catalog]
  CAT --> MCM[MainContractMap rank1]
  CP --> MDS[MarketDataService]
  CAT --> MDS
  MCM --> MDS

  ACTIVE[active_products.txt<br/>research capability] --> MARKET[Market API / Radar / Kline]
  MDS --> MARKET
  MARKET --> WEB[Market Web<br/>/market + /market/chart]

  MDS --> SF[SuBing Factor / Signal /<br/>Calibration / Lifecycle]
  SF --> DAILY[Daily Context artifact]
  SF --> CURRENT[Current Signal State]
  SF --> SSP[SuBing Strategy V1<br/>15m Historical Projection]
  DAILY --> MARKET
  CURRENT --> MARKET
  SSP --> MARKET

  MDS --> JDJ[JDJ 1m reference replay]
  JDJ --> MARKET
  MDS --> N[N Structure range bands]
  N --> MARKET

  SRC[research sources +<br/>candidate/policy/protocol/profile] --> CV[Candidate Validation]
  MDS --> CV
  CV --> ROB[Candidate Robustness]
  CV --> RCLI[research CLI]
  ROB --> RCLI

  OPS[operational_products.txt<br/>Runtime authorization] --> MR[Market Runtime]
  MR --> LIVE[Redis completed Live overlay]
  MR --> EOD[after-market Canonical update]
  EOD --> CP

  LIVE --> AE[Alert evaluators]
  EOD --> AE
  SF --> AE
  RULE[alert_rules + distinct Scope authorities] --> AE
  AE --> EVENT[alert_events]
  EVENT --> PUSH[one-shot PushPlus]
  EVENT --> WEB
```

## Consumer boundaries

- `MarketDataService` is the only Historical Bar reader for Market, SuBing, JDJ, N Structure and validation services. `actual_dominant` is resolved only through `MainContractMap rank=1`; incomplete identity, coverage or physical readability fails closed.
- Web consumes typed Market APIs. It may compose Daily Context, Current Signal State, Formal Event and Historical projections, but does not calculate strategy formulas or mutate Scope.
- SuBing Strategy V1 and JDJ replay are deterministic Historical read models. Their output has Web/test consumers only; no DB, Redis, Alert, Runtime or order consumer.
- Candidate Validation feeds Candidate Robustness through source-specific contracts. Policy/protocol/profile files remain explicit inputs; neither service is a Runtime evaluator or automatic promotion path.
- Market Runtime reads only `operational_products.txt`; research/API capability reads `active_products.txt`. Their current equality, if any, does not create one authority.
- Alert is independent from the Market Catalog. HTDY uses `scope_product_frequencies`; SuBing uses `scope_products`. Event persistence precedes at most one transport attempt.

## Preserved seams

Canonical/Catalog, `DatasetKey`, Trading Calendar/Session, `MainContractMap`, Live/Historical isolation, Alert Application Domain and Runtime authorization remain separate modules. Alembic migrations are schema lineage and are not active application dependencies once their domains retire.
