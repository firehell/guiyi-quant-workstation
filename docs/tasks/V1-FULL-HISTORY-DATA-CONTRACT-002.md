# V1-FULL-HISTORY-DATA-CONTRACT-002：冻结全历史 V1 数据契约

生成时间：2026-07-16

状态：`V1_DATA_CONTRACT_FROZEN`

## 目标

为 Audit V2、Profile target-aware 选优和 formal consumers 冻结统一、可测试的 V1 全历史目标与消费边界，不把旧 2020/2023 口径继续用作最终契约。

## 冻结结论

```text
audit_end = 2026-07-10
timezone = Asia/Shanghai
continuous 1m = max(listed semantic start, authoritative provider first valid 1m)
continuous direct 1d = max(listed semantic start, provider first completed daily bar)
continuous direct 1w = provider first completed trading-week bar
derived 5m/15m/30m/60m/1d = passed 1m only
actual dominant = MainContractMap.rank=1 effective ranges, 1m/1d only
```

provider earliest evidence 缺失或不权威时必须返回 `expected_start_unresolved`。物理文件、manifest、DB metadata 和 listing metadata 各自只证明其对应层级，不得互相替代。

## 五层状态

```text
physical_coverage
registration
quality
reference_metadata
profile_eligibility
```

Market 可展示 warning 且必须暴露质量；Backtest 默认 passed-only；Signal 阻断 warning/partial；Review 只可把 warning 用于带标签展示。所有 historical formal consumer 均阻断 failed、unchecked、partial、registration missing 和 Profile ineligible。

## 历史兼容与冻结

- `DEFAULT_MINUTE_START=2023-01-03` 和 2020 universe CSV 只保留给 legacy Phase 3。
- 旧 `1853 / 34 / 45` 数字继续作为历史审计模型快照。
- `report_id=14` 只能读取和引用，禁止更新、回填、重算覆盖或替换 lineage。
- Audit V2 必须使用 `full_history_contract.py`，不得复用旧固定年份 target catalog 作为最终目标。

## 非目标

- 不盘点或填充每个品种的 authoritative provider earliest evidence。
- 不实现 Audit V2，不修改 Profile 配置或 binding。
- 不调用 RQData，不写 DB、Parquet、manifest，不修改历史报告。

## 验收

```text
V1_DATA_CONTRACT_FROZEN
DATA_LAYER_REAUDIT_REQUIRED
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```
