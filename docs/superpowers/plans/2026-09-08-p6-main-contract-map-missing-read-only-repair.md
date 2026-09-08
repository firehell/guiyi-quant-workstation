# P6 `MAIN_CONTRACT_MAP_MISSING` Read-only Repair Plan

> 状态：`READ_ONLY_PLAN_CORRECTED / READER_FIX_REJECTED_BY_EXISTING_CONTRACT`
>
> 本计划只冻结诊断、目标和 Gate。它不授权 RQData 请求、PostgreSQL/Canonical/Parquet/Redis 写入、Runtime 切换、main merge、tag 或 release。

## 1. 固定身份与复现请求

- 已发布基线：`v1.10.0@f8f7d91765122c33cf5e82ed425b6c44f41ad0b1`
- 已发布 tree：`ccb8f27a1a51e09602a4734c032918f063aa4df2`
- 计划输入 develop：`00c5691c118cc4c87ea8b833d78309001ba339e2`
- 计划输入 develop tree：`a575b8b370ac66c9e830e55f6c6d88fe6c60bfe7`
- 冻结请求：`series_kind=actual_dominant`、`as_of=2026-09-08T07:00:00+08:00`
- 代表请求：`rb × trend × 60m × chart × chart_limit=500`
- v1.10.0 HTTP 结果：`500 / NEWOW_INTERNAL_ERROR`
- 同 exact release 进程内原始错误：`MarketDataError(MAIN_CONTRACT_MAP_MISSING)`
- provider 请求：`0`
- production 写入：PostgreSQL `0`、Canonical `0`、Parquet `0`、Redis `0`

## 2. 精确 `MAIN_CONTRACT_MAP_MISSING` 目标

### 2.1 已完成数据窗口

对 60 个 operational 品种的 `1w/1d/60m` chart 和 reference 已完成窗口审计到 `2026-09-07`：

- 缺失 owner-map 身份：`0`
- 空集合 SHA-256：`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

因此，已完成历史窗口不存在可执行的 `MainContractMap` 补写目标。

### 2.2 触发错误的未完成日

`NewowProductReader.load()` 将 overlap calendar 的最后一天传给 owner loader。对有夜盘的品种，07:00 时该值为尚未完成的 `2026-09-08`，而 display/performance 的权威完成日仍为 `2026-09-07`。

以 rb 为例，实际 owner 请求为：

```text
rb | 2026-03-10..2026-09-08 | missing=2026-09-08
```

60 品种 × 3 周期扫描结果：

- request gap：`135`
- 去重 product × trade_date：`45`
- request identity SHA-256：`ec789509822ffdb9d8ca53ae12df1f42b10e1f13769c7753c6d0ffab8ed9ac38`
- unique target SHA-256：`27370177d8ac98deddefd5934d47a9eefdde752f16e07952369ce58f33a3ef12`

去重集合为：

```text
a, ag, al, ao, au, b, bu, bz, c, cf, cu, eb, eg, fg, fu,
hc, i, j, jm, l, m, ma, ni, oi, p, pb, pf, pg, pl, pp,
pr, px, rb, rm, ru, sa, sc, sh, sn, sr, ss, ta, v, y, zn
× 2026-09-08
```

同一时点，production Catalog 对全部 60 个 operational 品种都尚未发布 `2026-09-08` rank1；其余 15 个品种在该固定时点没有把 09-08 纳入 overlap owner 请求。

## 3. 更正判定：reader 不得收窄 owner 边界

首次计划错误地把 `days[-1]` 解释为窗口扩大缺陷。TDD 的 RED 用例虽然精确复现了该行为，但最小实现随后使四个既有 owner/rollover 合同失败：

```text
test_only_effective_owners_can_prove_rollover_without_next_weekly_bar × 2
test_night_session_boundary_uses_next_trading_day_without_natural_date_guess
test_request_end_is_not_rollover_but_later_effective_mapping_is
```

这些测试和 Newow canonical 共同要求：display/performance 可以截止在更早的 completed Bar，但 owners 必须保留截至 `as_of` 已生效的权威换月边界；否则旧 owner 的 OPEN 参考交易可能漏掉 `ROLLOVER_INTERRUPTED`，相同 query cutoff 的 segment identity 也会被错误改变。

因此，以下拟议改动已被拒绝且没有提交：

- 不把 owner loader 收窄到 `max(query.through, performance_through)`；
- 不从 owner coverage 中删除与 `as_of` 重叠的下一交易日；
- 不把缺少权威 current owner 降级成历史成功响应。

恢复原实现后，`test_product_reader.py` 为 `86 passed`，worktree 无源码修改。

结论：`READER_COMPLETED_DAY_BOUNDARY_FIX = INVALID / CONTRACT_REGRESSION`。现有 reader 的 fail-closed 行为必须保留。

## 4. 当前 MainContractMap 状态与合法处理

production 的自然盘后状态为：

```text
last_run.trading_day=2026-09-07
last_run.status=passed
last_run.attempts=1
started_at=2026-09-07T18:05:06.856229+08:00
finished_at=2026-09-07T19:30:30.071088+08:00
last_successful_trading_day=2026-09-07
```

当前日 `2026-09-08` 对全部 60 个 operational 品种都没有 rank1 行；这是现有盘后发布水位，而不是 09-07 及以前的历史缺口。45 个冻结请求在 07:00 已进入 09-08 owner 时段，所以按权威 identity 合同返回 unavailable。

合法处理顺序：

1. 推荐等待 `2026-09-08 18:05` 的自然盘后任务发布 09-08 metadata/Canonical，再做只读 readback；自然任务结果未知前不得预报成功。
2. 如果必须在自然盘后前手工同步，只能调用受限 `synchronize_current_day(operational-60, 2026-09-08)`；该操作会请求真实 RQData，并在一个事务内更新 09-08 至下一交易日的 Calendar、09-08/下一交易日 Session、以及恰好 60 个 09-08 rank1。它没有公开 dry-run CLI，当前也没有单次 production 授权，因此不得执行。
3. 禁止直接 SQL、推测合约、从 Redis subscription snapshot 回填 Catalog、回退 continuous 或用 `data update --through 2026-09-08 --apply` 冒充 metadata-only 修复。
4. 当前 develop 已将底层 `MarketDataError` 脱敏映射为 `409 / NEWOW_DATA_UNAVAILABLE`；该 fallback 应保留，但它不补数据、不改变 owner 语义。

当前最小正确动作是等待自然盘后并只读核对；若自然任务失败，再基于失败后的 exact state 生成新的手工 metadata Packet 和单次授权请求。

## 5. 被首层错误遮蔽的独立 production 数据 Gate

将 rb 请求冻结在完成日 `2026-09-07T15:00:00+08:00` 后，owner-map 错误消失，下一原始错误为：

```text
MarketDataError(CONTRACT_REPLAY_COVERAGE_UNAVAILABLE)
```

首个精确身份：

```text
rb | RB2605 | 60m | owner_end=2026-04-07
actual lifecycle prefix = 561 bars, first=2025-12-02T14:00:00Z
expected lifecycle prefix = 1509 bars, first=2025-05-15T14:00:00Z
```

官方 `contract-warmup` dry-run（无 `--apply`）结果：

```text
symbol=rb
contract=RB2605
effective_window=2025-05-16..2026-04-07
frequencies=1d,1w,1m,5m,15m,30m,60m
targets=55 (23 direct + 32 derived)
expected_bar_count=71462
missing_bar_count=61865
provider_request_count=23
plan_sha256=4312ba1e3efda03298b639a159e9f335d5ba55381d9f9199d2945451da422195
status=planned / readonly=true / applied=0 / failed=0
```

这只是 rb 的首个失败合同，不是 P6 全矩阵的完整数据修复范围。不得仅凭该 hash 执行 apply，也不得把它与 current-day metadata 同步合并成一个授权。

必须先在 09-08 MainContractMap 完整后的 exact code commit 上串行重放 P6 矩阵，逐个暴露并去重所有 `symbol × physical_contract × through`，对每个身份生成新的官方 dry-run 和 plan hash。申请 physical Canonical production 授权的 Packet 至少包含：

- exact code commit/tree；
- 每个 symbol/contract/effective window；
- 每个 plan SHA-256；
- direct/derived target、missing bar、provider request 计数；
- 总影响范围、quota 预算、maintenance lock、原子发布和失败恢复；
- 明确的一次 apply 顺序；任一失败停止，重试需要新授权。

## 6. 验证顺序

1. 保留现有 reader；`test_product_reader.py` 必须继续 `86 passed`，四个 owner/rollover 合同不得删除或改弱。
2. 09-08 自然盘后任务结束后，只读检查 status 必须为 exact `trading_day=2026-09-08 / status=passed`；失败时停止并重新计划，不手工重试。
3. 只读检查 operational 60 的 09-08 MainContractMap 必须恰好一品种一条、无缺失、重复或越界身份，并与同交易日 Live subscription snapshot 严格一致。
4. 在同一 production state 上重放 fixed-as-of rb 请求；预期不再出现 09-08 `MAIN_CONTRACT_MAP_MISSING`，允许准确暴露下一 data Gate。
5. 只读生成 P6 全矩阵 physical warm-up inventory；在完整 Packet 前不申请 physical Canonical production 授权。
6. 用户按完整 Packet 明确授权后，只执行一次逐项匹配的 physical production apply；失败不自动重试。
7. apply 后运行 `data audit`、physical replay coverage、P6 HTTP 成功矩阵及 input hash/owner/segment 一致性验证。
8. 独立 Review clean 后才准备新 Release Candidate；不得改写 `v1.10.0` tag。
9. 新 RC 只做到 release-candidate evidence。main merge、tag、GitHub Release 和五服务切换继续保持各自独立 Gate。

## 7. 验收与回滚

reader 合同验收：

- 缺少截至 `as_of` 已生效 owner 时继续 typed unavailable；
- display/performance 截止更早时，已知的后续有效 owner 和 rollover interruption 仍被保留；
- `test_product_reader.py` 全部通过且源码 diff 为空。

数据验收（未来单次授权后）：

- 每个 apply identity 和 plan hash 与授权 Packet 逐字匹配；
- provider 请求数不超过 Packet；
- 无越界产品、合约、频率或日期写入；
- audit、Catalog/Parquet 完整性和 replay coverage 全部通过；
- P6 成功响应只归属新的 exact RC commit/tree。

回滚：本轮没有 reader 源码提交，也没有 production mutation，因此当前没有代码或数据回滚动作。未来 physical Canonical apply 继续使用最后有效分区和 Catalog 原子发布语义恢复。

## 8. 当前 Gate

```text
READ_ONLY_PLAN = COMPLETE
MAIN_CONTRACT_MAP = PENDING_NATURAL_AFTER_MARKET_2026-09-08
READER_CODE_FIX = REJECTED / CONTRACT_REGRESSION
PHYSICAL_WARMUP_PACKET = INCOMPLETE / MUST_REINVENTORY_AFTER_MAIN_MAP_READBACK
NEW_RELEASE_CANDIDATE = BLOCKED
RUNTIME_SWITCH = NOT_EXECUTED
```

唯一下一步：等待 2026-09-08 自然盘后任务结束后，执行 09-08 MainContractMap 和 rb fixed-as-of 的完整只读回执；不手工触发 production mutation，不切换服务。
