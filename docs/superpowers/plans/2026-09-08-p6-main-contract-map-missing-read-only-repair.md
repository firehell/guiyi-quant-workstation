# P6 `MAIN_CONTRACT_MAP_MISSING` Read-only Repair Plan

> 状态：`READ_ONLY_PLAN_COMPLETE / PRODUCTION_DATA_APPLY_NOT_READY`
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

同一时点，production Catalog 对全部 60 个 operational 品种都尚未发布 `2026-09-08` rank1；15 个无夜盘/该时点不 overlap 的品种没有进入上述 07:00 请求集合。

## 3. 判定：不得执行 MainContractMap production 修复

仓库合同规定：受限 metadata 同步只发布当天 rank1，正常入口位于盘后 update；不得提前发布未来主力映射。Newow 当前读取的是 Historical Canonical，权威完成日为 `2026-09-07`，不应为了读取该完成日前缀而要求 `2026-09-08` owner。

所以这 45 个目标是 reader 的窗口扩大缺陷，不是应补写的历史数据缺口。直接补写会：

1. 绕过既有盘后 metadata 发布时序；
2. 用每日临时写入掩盖确定性代码缺陷；
3. 次日再次复发；
4. 把 Historical Canonical 与当日 Live observation 边界混在一起。

以下 mutation 明确禁止：

- 直接 SQL 插入或更新 `main_contract_map`；
- 为消除 Newow 错误提前运行 current-day metadata production sync；
- 将 `guiyi data update --through 2026-09-08 --apply` 解释为本问题修复；
- 缩短 Catalog、回退 continuous、推测 physical contract；
- 在修复和验证前切换五服务。

结论：`MAIN_CONTRACT_MAP_MISSING_PRODUCTION_APPLY = REJECTED_AS_WRONG_TARGET`。本问题没有可请求的一次 production 数据授权。

## 4. 正确代码修复

### Task 1：先锁定失败测试

修改：

- `services/quant-api/tests/newow/test_product_reader.py`

新增真实时序回归：Calendar 已包含当前交易日、MainContractMap 只到上一完成日、`as_of` 位于当前日夜盘结束后但日盘完成前、coverage latest complete day 为上一日。断言：

- chart window 只消费上一完成日；
- owner-map 请求不得越过 display/performance 的最大完成日；
- 当前未完成日不进入 owners、boundaries、replay bars 或 input identity；
- completed-only、strict-before 和 prefix invariance 保持不变。

### Task 2：收窄 owner/read 边界

修改：

- `services/quant-api/app/market_data/newow/product_reader.py`

实现要求：

1. 计算唯一 `read_through = max(query.through, performance_through)`；
2. owner loader、actual-dominant day query和 owner coverage 校验使用同一 `read_through`；
3. overlap calendar 仍用于 session/as-of 判定，但未完成且大于 `read_through` 的日期不得参与 owner 完整性断言；
4. 不放宽 MDS 的缺口、冲突、physical identity 或 replay coverage Gate；
5. 不改变 page-parity 公式、Marker、收益、策略版本或参考交易语义。

### Task 3：保持 API typed fallback

当前 develop 已将底层 `MarketDataError` 脱敏映射为 `409 / NEWOW_DATA_UNAVAILABLE`。保留该 fallback，新增回归确保真正的 MDS 缺口仍 fail-closed；代码窗口修复不得把数据错误转换为成功。

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

这只是 rb 的首个失败合同，不是 P6 全矩阵的完整数据修复范围。不得仅凭该 hash 执行 apply，也不得把它与 MainContractMap 代码修复合并成一个授权。

在申请任何 production 数据授权前，必须先在代码修复后的 exact commit 上串行重放 P6 矩阵，逐个暴露并去重所有 `symbol × physical_contract × through`，对每个身份生成新的官方 dry-run 和 plan hash。授权 Packet 至少包含：

- exact code commit/tree；
- 每个 symbol/contract/effective window；
- 每个 plan SHA-256；
- direct/derived target、missing bar、provider request 计数；
- 总影响范围、quota 预算、maintenance lock、原子发布和失败恢复；
- 明确的一次 apply 顺序；任一失败停止，重试需要新授权。

## 6. 验证顺序

1. 运行新增失败测试，证明 v1.10.0 复现未完成日 owner 扩大。
2. 实施最小 reader 修复。
3. 运行 `test_product_reader.py`、Newow product/API tests 和相关 MDS/Catalog tests。
4. 对修复 commit 执行 fixed-as-of 进程内 rb 请求；预期不再出现 09-08 `MAIN_CONTRACT_MAP_MISSING`，允许准确暴露下一数据 Gate。
5. 只读生成 P6 全矩阵 physical warm-up inventory；在此之前不申请 production 数据授权。
6. 用户按完整 Packet 明确授权后，只执行一次逐项匹配的 production apply；失败不自动重试。
7. apply 后运行 `data audit`、physical replay coverage、P6 HTTP 成功矩阵及 input hash/owner/segment 一致性验证。
8. 独立 Review clean 后才准备新 Release Candidate；不得改写 `v1.10.0` tag。
9. 新 RC 只做到 release-candidate evidence。main merge、tag、GitHub Release 和五服务切换继续保持各自独立 Gate。

## 7. 验收与回滚

代码验收：

- 固定 07:00 请求不再要求未完成的 09-08 owner；
- 已完成窗口中的真实 map 缺口仍返回 typed unavailable；
- 所有直接及必要回归通过；
- diff/secret scan clean；独立 Review 无 finding。

数据验收（未来单次授权后）：

- 每个 apply identity 和 plan hash 与授权 Packet 逐字匹配；
- provider 请求数不超过 Packet；
- 无越界产品、合约、频率或日期写入；
- audit、Catalog/Parquet 完整性和 replay coverage 全部通过；
- P6 成功响应只归属新的 exact RC commit/tree。

回滚：代码通过普通 Git revert 回退；Canonical apply 使用最后有效分区和 Catalog 原子发布语义恢复。由于本计划未执行任何 production mutation，当前没有数据回滚动作。

## 8. 当前 Gate

```text
READ_ONLY_PLAN = COMPLETE
MAIN_CONTRACT_MAP_DATA_APPLY = NOT_APPLICABLE / REJECTED_AS_WRONG_TARGET
READER_CODE_FIX = READY_FOR_IMPLEMENTATION
PHYSICAL_WARMUP_PACKET = INCOMPLETE / MUST_REINVENTORY_AFTER_CODE_FIX
NEW_RELEASE_CANDIDATE = BLOCKED
RUNTIME_SWITCH = NOT_EXECUTED
```

唯一下一步：批准按本计划实施 reader 的完成日边界修复；该批准不包含任何 production 数据写入或服务切换。
