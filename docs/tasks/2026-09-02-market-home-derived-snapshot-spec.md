# Market Home 盘后派生快照 Spec

状态：`SPEC_APPROVED_BY_OWNER / IMPLEMENTATION_AUTHORIZED`

日期：2026-09-02

Issue：`#315`

事实基线：`develop@fa04c5524b57a3512d7163612972099eda96e0c4`

任务车道：`Lane 3 / derived Runtime write path / code-only implementation`

## 1. 目的

Market Home 的产品设计已经稳定：首页通过三个 O(1) 只读资源展示 completed D1/W1 generic overview、Runtime health 与 current HTDY Event。当前性能问题只存在于 overview 的后端生成时机。

现有 `MarketHomeOverviewService.snapshot()` 每次请求都遍历 active universe，并对每个品种分别读取：

```text
actual_dominant D1 limit=300
actual_dominant W1 limit=80
```

当前 active universe 为 60，因此一次首页 overview 至少形成约 120 次 `MarketDataService.query_page()` 调用；每次 actual-dominant 读取还会重复经过 MainContractMap、Catalog、具体合约月分区、Parquet 解码和完整性检查。既有 benchmark 约为：

```text
cold ≈ 4.816s
warm ≈ 4.812s
```

completed D1 通常每日变化一次，W1 通常每周变化一次，因此“每次 HTTP 读取时重新生成”与事实变化频率不匹配。

本 Spec 将 Market Home overview 从常态的 read-time compute 改为极简的 update-time derived projection，同时保留现有 compute 作为 correctness fallback。

## 2. 核心结论

目标架构：

```text
RQData
→ Canonical Parquet
→ Catalog + MainContractMap
→ MarketDataService
→ MarketHomeOverviewService          唯一计算 authority
→ Market Home derived projection     性能派生，可删除、可重建
→ GET /api/v1/market/research/home-overview
→ Web
```

生成时机：

```text
after-market
→ HistoricalDataManager.update() = passed / noop
→ MarketHome projection refresh
→ same-directory temporary file
→ fsync
→ os.replace
→ .run/market-home-overview.json
```

读取时机：

```text
GET home-overview
→ 计算廉价 authority identity
→ projection identity exact match ?
   ├─ yes → 直接返回 projection payload
   └─ no  → 调用现有 MarketHomeOverviewService.snapshot()
```

API fallback 不写 snapshot。

## 3. Authority 不变量

`MarketHomeOverviewService` 仍是 completed D1/W1 overview 的唯一计算 authority。

Derived projection：

- 不是 Canonical；
- 不是 MarketDataService 替代品；
- 不拥有 MainContractMap authority；
- 不拥有 taxonomy / active universe authority；
- 不拥有策略、Alert、Runtime 或交易语义；
- 文件删除后必须可以仅通过现有 authority 完整重建；
- projection 内容与现场 compute 内容必须使用同一个 pure response mapper。

禁止形成第二套指标计算或第二套 actual-dominant 读取算法。

## 4. V1 存储合同

默认路径固定为：

```text
PROJECT_ROOT/.run/market-home-overview.json
```

原因：

1. `.run/` 已是当前项目 runtime-local、Git ignored 状态目录；
2. 与 `after-market-status.json` 一样属于可重建运行派生，而不是长期事实；
3. 不污染 `GUIYI_CANONICAL_DATA_ROOT`；
4. 不增加 Redis、PostgreSQL、Alembic、外部 derived root 或新环境变量；
5. Runtime promotion 到新 checkout 后允许文件暂时不存在，API compute fallback 保证 correctness，下一次自然 after-market 会重新生成。

V1 不保留历史 projection，只保留一个 `current` 文件。

## 5. Projection Envelope

文件必须是单个 UTF-8 JSON object：

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-02T10:00:00Z",
  "target_as_of": "2026-09-02",
  "authority_digest": "<64 lowercase hex sha256>",
  "payload": {
    "status": "ready",
    "target_as_of": "2026-09-02",
    "data_as_of": "2026-09-02",
    "freshness": "fresh",
    "active_count": 60,
    "participant_count": 60,
    "stale_count": 0,
    "unavailable_count": 0,
    "summary": {},
    "items": [],
    "sectors": []
  }
}
```

`payload` 必须严格复用现有 `MarketHomeOverviewResponse` wire contract；Decimal 继续按 Pydantic JSON 规则输出字符串，null 保持 null。

Envelope 使用 `extra="forbid"`。`generated_at` 必须是 timezone-aware datetime，仅供诊断，不参与市场事实判断。

## 6. Authority Identity

新增 `MarketHomeAuthorityIdentity`：

```text
target_as_of: date
authority_digest: sha256 hex
```

`target_as_of` 继续来自现有 `DatabaseCoverageSource.latest_complete_day(active_products)`。

`authority_digest` 精确绑定：

```text
active product 顺序
+
每个 product 的 taxonomy.name
+
每个 product 的 taxonomy.sector
```

确定性编码固定为：

```python
records = [
    {"symbol": symbol, "name": taxonomy[symbol].name, "sector": taxonomy[symbol].sector}
    for symbol in products
]
json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
sha256(encoded_utf8).hexdigest()
```

任何 active universe 数量、顺序、名称或 sector 变化都必须造成 digest 变化。

## 7. Projection 命中规则

`MarketHomeProjectionStore.load(identity)` 只有以下全部成立才返回 payload：

1. path 存在且是普通文件，不接受 symlink；
2. 文件大小 `> 0` 且 `<= 2 MiB`；
3. JSON / Pydantic strict validation 通过；
4. `schema_version == 1`；
5. `envelope.target_as_of == identity.target_as_of`；
6. `envelope.authority_digest == identity.authority_digest`；
7. `payload.target_as_of == envelope.target_as_of`；
8. `payload.data_as_of == envelope.target_as_of`。

任一不满足：视为 cache miss，不向 HTTP 泄露内部文件错误，不把旧 projection 冒充当前事实。

## 8. API 读取合同

`GET /api/v1/market/research/home-overview` 保持原 URL、response schema 和 HTTP error contract。

新路径：

```text
build MarketHomeProjection
→ service.authority_identity()
→ store.load(identity)
→ hit: return cached MarketHomeOverviewResponse
→ miss: service.snapshot() + pure mapper + return
```

### Hit

Hit 时禁止调用：

- `MarketHomeOverviewService.snapshot()`；
- `MarketDataService.query_page()`；
- `list_latest_dominants()`；
- Redis / provider / write service。

允许的廉价 identity 工作只有 active/taxonomy 已加载事实、`latest_complete_day()` 与一个小 JSON 文件读取/validation。

### Miss

Miss 时完全保留现有现场计算行为和错误语义。

API miss/fallback：

- 不创建目录；
- 不创建临时文件；
- 不更新 projection；
- 不写 Redis、DB、Canonical 或其他 runtime state。

因此 overview HTTP endpoint 仍是纯只读入口。

## 9. After-market 刷新合同

Projection refresh 只允许发生在：

```text
HistoricalDataManager.update() result.status in {"passed", "noop"}
```

顺序固定为：

```text
Canonical maintenance success/noop
→ attempt Market Home projection refresh
→ existing market:state(canonical_updated)
→ existing rank1/live reconciliation
→ existing cleanup
```

不在以下情况 refresh：

- NON_TRADING_DAY skipped；
- provider not ready；
- provider readiness error；
- HistoricalDataManager update failed/blocked；
- Canonical update 抛异常。

## 10. Projection refresh 失败语义

Projection 是性能派生，不是 Canonical maintenance 的成功条件。

如果 `service.snapshot()`、serialization、fsync 或 `os.replace()` 失败：

1. 只记录安全 warning：

```text
market_home_projection_refresh_failed exception_type=<ClassName>
```

2. 不记录异常 message、路径、SQL 或 stack detail 到公开状态；
3. 不改变已成功的 `AfterMarketResult`；
4. 不发送 PushPlus；
5. 不 retry；
6. 若旧 projection 已存在，必须保持原文件不变；
7. 后续 API 按 identity 检查，旧文件失配时自动走现场 compute。

这样 projection failure 只能造成性能退化，不能污染数据 correctness 或核心 Runtime maintenance 结论。

## 11. Atomic Publish

`MarketHomeProjectionStore.publish()` 必须：

```text
validate envelope
→ mkdir parent
→ tempfile.mkstemp(same parent)
→ UTF-8 write
→ flush
→ os.fsync
→ os.replace(temp, current)
→ finally cleanup temp
```

临时文件必须与目标文件同目录，确保 `os.replace` 的原子语义。

不得使用 append、in-place truncate 或先删除 current 再写。

## 12. Pure Response Mapper

当前 `app/api/market.py` 中从 `MarketHomeOverviewSnapshot` 到 `MarketHomeOverviewResponse` 的映射必须抽取为一个 pure function，并由：

- API compute fallback；
- after-market projection refresh；

共同调用。

不允许复制两份 response mapping。

## 13. 并发和竞态

V1 不引入锁服务、Redis mutex、线程池或文件锁。

原因：

- after-market 是单个受监督任务；
- API 只读 projection；
- atomic replace 保证 reader 只看到完整旧文件或完整新文件。

如果 projection identity 在 `authority_identity()` 与 `snapshot()` 之间发生变化，refresh 必须检测：

```text
response.target_as_of != identity.target_as_of
```

并拒绝 publish，保留旧文件。下一次自然 refresh 重试。

## 14. 性能合同

本任务不优化 compute miss 的 4.8s 路径；它只改变常态读取路径。

目标：

```text
projection store decode + strict validation < 50ms
projection-hit HTTP endpoint             < 200ms
```

以上为本地真实环境 manual acceptance 目标，不用 sleep-based unit test 伪造。

自动测试必须用行为证明 hit 不调用 expensive compute，而不是用微秒级 timing assertion。

## 15. 测试合同

### Domain / identity

必须覆盖：

- digest deterministic；
- product order 变化 → digest 变化；
- taxonomy name/sector 变化 → digest 变化；
- target_as_of 由现有 coverage authority 提供。

### Store

必须覆盖：

- publish/read round trip；
- Decimal/date wire round trip；
- missing file → miss；
- symlink → miss；
- empty/oversize/corrupt JSON → miss；
- schema/target/digest mismatch → miss；
- payload target/data_as_of mismatch → validation failure/miss；
- replace failure 保留 last-good + 清理 temp。

### API

必须覆盖：

- exact projection hit 返回 payload 且 `snapshot()` 未调用；
- miss 调用现有 compute；
- corrupt/mismatched projection 调用 compute；
- compute failure 仍映射原 409 code；
- fallback 不调用 store.publish。

### After-market

必须覆盖：

- passed refresh exactly once；
- noop refresh exactly once；
- skipped / provider not ready / update failure 不 refresh；
- projection refresh exception 不改变 passed result；
- projection refresh exception 不发送 notification；
- projection refresh 发生在 `canonical_updated` publish 之前。

## 16. Canonical / 文档同步

源码测试完成后同步：

- `DECISIONS.md`：Market Home 使用 update-time runtime-local derived projection；projection 可删除、可重建、非 authority；
- `docs/ARCHITECTURE.md`：增加 after-market → Market Home projection → overview API read 边；
- `openspec/specs/market-home-overview/spec.md`：把原“每次 endpoint 直接 compose”改为“projection hit 优先，compute fallback”，同时保持 HTTP endpoint read-only；
- `TESTING.md`：增加 targeted projection/after-market/API 测试命令。

`PROJECT_SOURCE.md` 的产品能力和用户语义不变，不因内部性能实现重复扩写。

`STATUS.md` 不修改：代码实现不等于 release、Runtime promotion 或自然 after-market evidence。

## 17. 禁止范围

本任务明确不做：

- Redis cache；
- PostgreSQL / Alembic；
- 外部 derived data root；
- background worker / queue / scheduler；
- thread pool / parallel Parquet read；
- `MarketDataService` actual-dominant 性能重构；
- 指标公式变化；
- HTDY / Alert Rule / Event / Scope / audience / transport 变化；
- Web UI 变化；
- production RQData / Canonical / DB / Redis 写入；
- 真实 after-market 执行；
- main、tag、Release、Runtime promotion。

## 18. Gate

用户已经明确授权：

```text
Spec → Plan → code/test implementation → review/fix → submit PR
```

该授权仅覆盖仓库内代码、测试、文档、task branch 和 PR。

它不授权任何真实 projection 文件在 production Runtime 中首次生成，因为那需要包含本代码的未来 Runtime promotion 和自然 after-market 运行；也不授权当前 production after-market 手工执行。

完成状态最多为：

```text
CODE_COMPLETE
TEST_COMPLETE（仅在真实命令已执行并通过时）
REVIEW_COMPLETE
EXTERNAL_GATE_PENDING
```

不得因此声明 `RELEASED` 或 `RUNTIME_READY`。