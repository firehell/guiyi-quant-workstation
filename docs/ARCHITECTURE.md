# 归一量化系统架构

更新时间：2026-08-10

## 系统定位

归一量化是本地优先、单用户的国内期货研究工作站。当前目标应用面为 Market Web、Market API、
数据 CLI 与 Canonical 历史读取。Market Runtime V1 的代码与 launchd 模板默认关闭；本地工作站已按明确请求启用严格限定为 `j/jm/ap/ag` 的有界 Runtime。不实现自动交易，`auto_order=false` 始终成立。

## 分层设计

```mermaid
flowchart TB
    subgraph Access["接入层"]
      WEB["Market Web"]
      API["Market API"]
      CLI["guiyi data update/refresh/audit"]
    end
    subgraph Application["应用层：三个深模块"]
      MS["MetadataSynchronizer"]
      HM["HistoricalDataManager"]
      MQ["MarketDataService"]
    end
    subgraph Domain["领域层"]
      DK["DatasetKey / SeriesQuery / CanonicalBar"]
      CP["月度 coverage / natural resume"]
      MM["TradingCalendar / TradingSession / MainContractMap"]
    end
    subgraph Infra["基础设施层"]
      RQ["RQData adapter"]
      PG["PostgreSQL catalog"]
      PQ["Parquet / PyArrow reader-writer"]
    end
    WEB --> API --> MQ
    CLI --> MS
    CLI --> HM
    MS --> MM
    HM --> DK
    HM --> CP
    MQ --> DK
    MQ --> MM
    MS --> RQ
    MS --> PG
    HM --> RQ
    HM --> PG
    HM --> PQ
    MQ --> PG
    MQ --> PQ
```

- 接入层只解析请求和输出结果；不实现下载、聚合、文件选择或主力判断。
- `HistoricalDataManager` 是唯一历史写应用服务；`MarketDataService` 是唯一历史读服务。
- PostgreSQL 保存八表 metadata/catalog，Parquet 保存 Bars；不引入多 provider、插件、任务中心或
  在线多版本选择器。

## 数据架构

```mermaid
flowchart LR
    RQ["RQData<br/>唯一外部事实源"] --> ST["临时 staging"]
    ST --> V["标准化 + 六项硬校验"]
    V --> DD["Canonical Direct<br/>1m / 1d / 1w"]
    DD --> AG["TradingSession 聚合"]
    AG --> DV["Canonical Derived<br/>5m / 15m / 30m / 60m"]
    DD --> CAT["八表 Catalog + 月度 Parquet"]
    DV --> CAT
    MAP["MainContractMap rank=1"] --> MDS["MarketDataService"]
    CAT --> MDS
    MDS --> CON["Market Web / 指标 / 未来研究"]
```

每 Dataset 每自然月只发布一个 `part.parquet`。文件不存在、不可读、identity 不符或 coverage 不完整
时，查询 fail-closed，维护命令将该月作为待处理目标；不以第二套状态表保存这些事实。

## 运行与授权边界

`update` 计划缺失或不完整月并自然续传；`refresh` 只重建用户指定的品种/窗口；`audit` 只读。
代码、fixture、临时目录和隔离数据库验证是普通开发。真实 RQData、正式 Canonical、生产数据库
migration 与服务启停，必须分别获得范围明确的一次性执行意图。

Market Runtime V1 分为三条明确边界的平面：Historical 继续由 `HistoricalDataManager` 发布 Canonical；
LiveMarketService 只将当日 `j/jm/ap/ag` 的 rank1 completed 1m 与本地 Derived 写入 Redis；
AfterMarketUpdater 只在 launchd 的 17:00 触发（失败最多一小时后重试一次）调用既有历史写入口。Live
永不进入 Canonical、Parquet 或 PostgreSQL。代码与模板默认关闭；只有用户明确请求在该本地工作站启用
Market Runtime V1 后，这一有界自动化才可运行，且不扩展到 release、其他 DB、通知或订单。

开发期的本地 launchd 可临时直接绑定主 `develop` 工作区，当前根和运行状态由 `STATUS.md` 记录。这只是为了快速观察，不改变 Historical/Live 边界，也不构成稳定 Runtime 版本。功能收口后的最终拓扑仍为绑定精确提交的独立 Runtime worktree。
