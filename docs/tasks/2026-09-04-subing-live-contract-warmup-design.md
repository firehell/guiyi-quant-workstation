# SuBing Live Contract Warm-up Repair Design

日期：2026-09-04

## 状态与目标

本设计修复 `v1.9.14` production Runtime 在自然 completed 15m Bar 上暴露的两个相邻问题：

1. `MarketReadService.current_contract_replay_window()` 使用 Live cutoff 作为 physical Canonical
   分页游标。当天 Canonical 已正常停在最近完整日，而 Live cutoff 晚于该 coverage，严格
   `MarketDataService` 因此在 Live 合并前返回 `DATASET_OR_PARTITION_MISSING`。
2. PF 已在 2026-09-04 夜盘订阅 `PF2611`，但 Canonical 没有该物理合约的数据集。即使修复分页
   bootstrap，也无法按 SuBing 合同从同一物理合约上市有效期构建 MACD/EMA warm-up。

目标是让 `subing_ths_alert_15m_v1` 在 operational Scope 内只读组合“最近完整 Canonical 同物理
合约前缀 + 当日 completed Live”，并为 `PF2611` 建立可审计、可重跑的完整物理合约 warm-up。

## 不变量

- `MarketDataService` 的 Dataset、partition、coverage、physical-read 与 future-bar 校验保持严格，
  不允许 consumer 通过放宽查询合同掩盖缺口。
- `actual_dominant` 仍只由 `MainContractMap rank=1` 选择 owner；新增的非 rank1 物理合约 Bar 不会
  自动成为 `actual_dominant`。
- Historical Canonical 与 Live Redis 继续分离；Live Bar 不写入 Canonical。
- PF warm-up 只接受真实 RQData，禁止 synthetic、continuous fallback、跨合约拼接或缺口填充。
- Canonical 仍是唯一 V2 当前事实，不创建并行 data-version。
- SuBing Rule identity 保持 `subing_ths_alert_15m_v1`，公式 identity 保持
  `subing_ths_15m_v3`。本次修复让 Runtime 达到既有公式输入合同，不修改公式、seed、rounding、
  hidden filters 或 Event identity。
- 已有 Event 不修改、不删除、不回放；修复和数据维护不产生 AlertEvent 或通知。
- `auto_order=false`；本任务不增加任何订单能力。

## 设计一：Canonical + Live replay bootstrap

`MarketReadService._current_contract_history()` 的第一页 physical contract 查询改为 latest-page
bootstrap，即 `SeriesPageQuery.before=None`。分页仍由 `next_before` 向过去推进；每一页读回后只保留
满足以下边界的 Bar：

```text
after < bar_end <= decision cutoff
```

其中 `after=None` 表示不设下界。这样 Canonical 可以自然停在最近完整日，随后
`current_contract_replay_window()` 再按 `(bar_end, contract)` 严格合并当日 Live。任何 Canonical
future tail 都在进入 kernel 前排除；同一 `bar_end` 的 Canonical/Live 值不一致仍返回
`MARKET_READ_LIVE_UNAVAILABLE`。

physical 查询抛出的预期 `MarketDataError` 在 `MarketReadService` 边界转换为稳定的
`MarketReadWindowError("MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE")`。Evaluator 继续将其映射为
`ALERT_EVALUATION_FAILED`，从而留下 per-rule fail-closed 状态；未知异常继续上抛，不静默降级。

该修复不允许在 physical Dataset 缺失时仅用当日 Live 启动 kernel，因为那会丢失既有合同要求的
上市有效期前缀。

## 设计二：显式 physical-contract warm-up

新增唯一命令：

```text
guiyi data contract-warmup \
  --symbol SYMBOL \
  --contract CONTRACT \
  --through DATE \
  [--expected-plan-sha256 SHA256] \
  [--apply]
```

### 输入与计划

- `symbol` 必须是 active、非 retired 的小写品种；`contract` 必须规范化后与 Catalog `Contract`
  identity 完全一致，且属于该 symbol、provider 为 RQData。
- Catalog 必须能证明 `listed_date`、`expired_date` 及 `[listed_date, expired_date)` 有效区间。
- `through` 不得晚于该品种的最近完整交易日。实际窗口为
  `[listed_date, min(through, expired_date - 1 day)]`。
- 无 `--apply` 时只读使用 Catalog/Calendar/Session 生成七周期目标，不连接 RQData，不写 PostgreSQL、
  Redis 或 Parquet。输出必须包含 exact symbol/contract/window、direct/derived target 数、预计 Bar 数、
  `readonly=true` 和稳定 `plan_sha256`。
- `--apply` 必须同时提供 `--expected-plan-sha256`。取得 maintenance lease 后重新计算计划；hash、
  Contract identity、Calendar/Session 或目标窗口发生漂移时，在首次 RQData 请求和首次写入前拒绝。

### 数据写入

- RQData direct 频度仍为既有 `1m/1d/1w`，`5m/15m/30m/60m` 只从通过校验的同一物理合约 1m
  聚合。
- 目标只包含命令指定的一个 physical contract family。不会刷新 continuous、其他品种、其他合约或
  MainContractMap。
- 每个月分区继续使用既有 staging、schema/session/duplicate/OHLCV/coverage、row-count 与物理可读性
  校验后原子发布。跨分区失败可留下已成功的独立有效分区，并以 `partial/failed` 明确返回；后续重跑
  会按缺口幂等规划，但真实重跑需要新的单次授权。
- Apply 不修改 Rule、Scope、Runtime marker、Redis Live、Event 或 notification 状态。

### 合法的非 rank1 contract Bar

当前普通 update/audit 把 contract Dataset 的所有非映射日 Bar 当作异常并可能重写删除。为支持同物理
合约 warm-up，合同调整为：

```text
required mapped Bar ends ⊆ persisted contract Bar ends
persisted contract Bar ends ⊆ active-lifecycle valid Bar ends
```

- required mapped Bar 缺失仍失败。
- persisted extra 只有在 Contract active window、TradingCalendar 和 TradingSession 全部证明合法时才
  保留；任何越界、非 session 或 identity 冲突仍触发整分区修复或 audit finding。
- continuous Dataset 保持 exact expected equality，不应用该 superset 规则。
- 普通 update/refresh 不得删除已验证的 warm-up Bar；force refresh 若覆盖含 warm-up 的 contract
  partition，必须把既有合法 warm-up timestamps 纳入重拉目标。

这使一个 physical contract Dataset 可以保存多于 rank1 映射日的真实 Bar，但不会改变
`actual_dominant` 的选择结果。

## PF2611 production repair

本次精确目标为：

```text
symbol=pf
contract=PF2611
listed_date=2025-11-17
through=2026-09-03
frequencies=1m,5m,15m,30m,60m,1d,1w
```

流程必须是：

1. 在 release candidate 上运行 fake/temp 数据测试，不连接 production。
2. 发布 exact `v1.9.15` 后，使用 exact-tag CLI 对上述目标执行只读 plan。
3. 报告 exact targets、预计行数、provider request 数、plan hash、失败恢复和现役 Runtime 状态。
4. 取得新的、引用 exact hash 的单次授权后才执行 `--apply`；失败不自动重试。
5. Apply 后只读验证 PF2611 七周期 Catalog/Canonical、D1/W1/1m hash/coverage、15m warm-up 长度，
   并证明其它 Dataset、Rule、Scope、Event 与通知计数未变化。

现有 2026-09-03 自然 after-market 的 `LIVE_DOMINANT_MISMATCH` 保留为失败事实。本次 contract warm-up
不是自然 after-market 重试，也不得把该记录改写为 passed。

## 测试与验收

### RED regression

- 使用真实 `MarketDataService` 严格分页形态复现：Canonical coverage end 早于当天 Live cutoff 时，
  旧实现返回 `DATASET_OR_PARTITION_MISSING`。
- 修复后同一 fixture 从 latest Canonical page 启动、排除 cutoff 后 Bar、合并同合约 completed Live，
  evaluator 正常推进。

### Market read 与 Alert

- 覆盖第一页 `before=None`、多页向后分页、past cutoff、`after` cursor、同 timestamp 冲突、Dataset
  缺失稳定错误、同物理合约 rollover、warm-up、completed-only、prefix invariance 和无历史补发。
- Runtime 测试必须证明 relevant 15m evaluation failure 不会被 unrelated 1m trigger 冒充 SuBing 成功；
  per-rule 状态可用于只读验收，但不扩大 HTTP 产品面。

### Contract warm-up

- 覆盖 CLI 参数、Contract identity/lifecycle、dry-run 零 provider/零 mutation、稳定 plan hash、apply hash
  漂移、maintenance lock、RQData batch 失败、部分成功后幂等重跑、七周期 lineage、derived-only-from-1m、
  audit superset、invalid extra 与普通 refresh 保留 warm-up。
- 使用临时 Canonical/SQLite 或专用 isolated PostgreSQL；普通测试不得连接 production RQData、DB、
  Redis 或 Runtime。

### 完整验证

- SuBing/MarketRead/HistoricalDataManager/CLI/Runtime 定向 pytest。
- 完整非 isolated backend、Ruff、Mypy、engineering canonical consistency、OpenSpec strict、secret scan。
- Web 未修改时仍执行 alert contract unit/build；Playwright 按 release risk 决定是否运行并明确报告。
- 独立 Standards/Spec Review 必须无阻断 finding 后才能形成 RC。

## 文档与版本

- 同步 `openspec/specs/subing-ths-alert/spec.md`、Canonical/Historical maintenance 相关 spec、
  `PROJECT_SOURCE.md`、`docs/DATA_CENTER.md`、`TESTING.md` 和 `STATUS.md`。
- 不增加 Alembic migration，不改变 Formula/Data version。
- 候选版本为 `v1.9.15`，基于实现时最新、干净的 `develop`；当前起点
  `develop@d7ca96dfab377e58ff47f4e57ce1e39a66ffa2b0` 已包含尚未发布的 Runtime promotion guard，
  该变更属于 `v1.9.15` release diff。

## 外部 Gate

1. 设计、计划、实现、完整验证、Review 完成后合入 `develop`，形成 exact `v1.9.15` RC。
2. main merge、annotated tag 与 GitHub Release 必须取得引用 exact RC 的新授权。
3. exact-tag PF2611 warm-up dry-run 是只读 Gate；真实 RQData/Canonical apply 必须取得引用 exact
   `plan_sha256` 的新单次授权，失败不自动重试。
4. 五项 Runtime promotion 是独立 Gate，必须取得 exact tag/root/rollback 范围明确的新授权。
5. promotion 后在自然开盘只读验证：Live phase/subscription、Alert heartbeat、SuBing per-rule
   `last_evaluated_bar_at`、processing error、PF2611 contract identity、Event/transport 增量。
6. 只有自然 Candidate 产生 immutable SuBing Event 并获得一次 provider acceptance 才完成 G11；用户
   实际微信确认仍是独立 G12。不得用 synthetic、manual send、replay 或 backfill 替代。

## 明确不做

- 不全量回填所有历史 contract 的上市期数据。
- 不在 Live Runtime 内调用 RQData 修补 warm-up。
- 不允许 live-only、continuous 或上一主力合约作为 PF2611 的 kernel seed。
- 不修改 2026-09-03 after-market 失败记录，不手工运行 after-market 冒充自然验收。
- 不在本任务中改变 Scope、受众、PushPlus 配置、通知重试政策或 Web 公式。
