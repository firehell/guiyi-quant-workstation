# DATA-PROFILE-ROLLOUT-APPLY-008B

状态：`COMPLETED / PROFILE_ACTIVE_BINDINGS_VERIFIED`

B2-08A candidate SHA-256 固定为 `639009e89a8c5424c7de8281f059e296495595bc75c1abe939c19d461deba59b`。265 个 current 中 241 个需要变更、24 个保持不变；660 个 blocked 均未进入 apply。

受控批次：

```text
profile-rollout-pilot-008b-001              15
profile-rollout-pilot-new-identity-008b-002  1
profile-rollout-intraday-008b-003           85
profile-rollout-long-horizon-008b-004      140
```

Pilot 完成 apply、verify、Golden Query、15 行 rollback 和再次 apply。JM2605 新 identity 完成 apply、restore-absent rollback 和再次 apply。最终 265/265 active 指向 current candidate，duplicate active 为 0，8 条 Golden Query 全部通过。

写入范围仅为 `profile_active_bindings`。MarketDataFile、DataQualityReport、DataProfile、四个 live 表和 report 14 的 before/after 内容摘要一致；未写 Parquet/manifest，未调用 RQData，未修改 quality/data_role。

正式证据：`data/reports/full_history_audit_v2_20260710/profile_rollout_008b/`。长期状态仍为 `DATA_LAYER_REAUDIT_REQUIRED`。
