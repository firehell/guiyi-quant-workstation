# Market Home 盘后派生快照 Spec

状态：`SPEC_APPROVED_BY_OWNER / REVIEW_AMENDED / IMPLEMENTATION_AUTHORIZED`

日期：2026-09-02

Issue：`#315`

事实基线：`develop@fa04c5524b57a3512d7163612972099eda96e0c4`

任务车道：`Lane 3 / derived data write seam / repository implementation only`

## 1. 目的

Market Home 产品设计已经稳定：首页通过三个 O(1) 只读资源展示 completed D1/W1 generic overview、Runtime health 与 current HTDY Event。当前性能问题只存在于 overview 后端的生成时机。

现有 `MarketHomeOverviewService.snapshot()` 每次请求都遍历 active universe，对每个品种分别执行：

```text
actual_dominant D1 limit=300
actual_dominant W1 limit=80
```

当前 active universe 为 60，因此一次 overview 约形成 120 次 `MarketDataService.query_page()`；每次 actual-dominant 查询继续经过 MainContractMap、Catalog、具体合约月分区、Parquet 解码和完整性检查。既有本地 benchmark：

```text
cold ≈ 4.816s
warm ≈ 4.812s
```

completed D1 通常每日变化一次，W1 通常每周变化一次。对一个 Dashboard read model 而言，“每次 HTTP 请求现场重算”与事实变化频率不匹配。

本 Spec 将常态路径改为 update-time derived projection，同时保留原现场 compute 作为 correctness fallback。

## 2. 最终架构

```text
RQData
→ HistoricalDataManager
→ Canonical Parquet + Catalog + MainContractMap
→ MarketDataService
→ MarketHomeOverviewService                唯一 overview compute authority
→ <canonical_root>/.derived/market-home-overview.json
→ GET /api/v1/market/research/home-overview
→ Web
```

API：

```text
current authority identity
→ valid projection ?
   ├─ yes → 直接返回 projection
   └─ no  → MarketHomeOverviewService.snapshot()
```

自然盘后：

```text
provider ready
→ 失效旧 projection
→ HistoricalDataManager.update(apply=True)
→ canonical_updated
→ rank1 / Live reconciliation
→ Live cleanup
→ best-effort refresh Market Home projection
→ after-market status
```

人工正式维护：

```text
guiyi data update/refresh --apply
→ 失效旧 projection
→ HistoricalDataManager action
→ 不同步重建 projection
→ API 暂时走 authoritative compute fallback
```

下一次自然 after-market 再重建 projection。

## 3. Review Amendment

首稿设计曾使用：

```text
PROJECT_ROOT/.run/market-home-overview.json
```

并仅以 `target_as_of + universe/taxonomy` 判定 freshness。提交前架构 Review 发现两个问题：

1. 同一 trading day 的 Canonical/MainContractMap 可以被合法 refresh/update；日期不变时旧 projection 会继续误命中；
2. 若 projection refresh 放在 `canonical_updated` 前，会把约 4.8 秒历史计算插入 HTDY D1/W1 Web/Alert seam 前面。

最终修正为：

- projection 跟随共享 `canonical_root`，跨 checkout/Runtime root 共享；
- 所有正式 apply 入口在 manager action 前先删除旧 projection；
- invalidation 失败在 authoritative mutation 前 fail-closed；
- after-market projection refresh 移到 `canonical_updated + reconciliation + cleanup` 全部成功之后；
- refresh 失败只导致 API compute fallback，不改变已完成的核心 maintenance 结论。

这两个 amendment 以 correctness 和现有 Alert seam 优先于缓存命中率。

## 4. Authority 不变量

`MarketHomeOverviewService` 始终是 completed D1/W1 overview 的唯一计算 authority。

Projection：

- 不是 Canonical；
- 不是 MarketDataService 替代品；
- 不拥有 MainContractMap authority；
- 不拥有 active universe / taxonomy authority；
- 不拥有策略、Alert、Runtime 或交易语义；
- 删除后必须能仅用原 authority 完整重建；
- payload 必须由与 API fallback 共用的 pure mapper 产生。

禁止创建第二套 EMA/ATR/趋势/actual-dominant 逻辑。

## 5. 存储合同

唯一默认位置：

```text
<GUIYI_CANONICAL_DATA_ROOT>/.derived/market-home-overview.json
```

未配置外部 Canonical root 时等价于：

```text
<PROJECT_ROOT>/data/parquet/canonical/.derived/market-home-overview.json
```

原因：

- 与权威 Canonical root 共享生命周期和 checkout 无关身份；
- 不污染 Catalog 的 physical Dataset taxonomy；`.derived` 不是 Bar Dataset；
- 不增加 PostgreSQL、Redis、Alembic、queue、worker 或新环境变量；
- 人工维护和 Runtime after-market 无论从哪个 checkout 执行，只要指向同一 canonical root，就操作同一 projection。

V1 只保留一个 current projection，不做历史版本、LRU 或 TTL。

自然 after-market 的 projection refresh 默认关闭。只有 owner 在独立的受控 Gate 中写入
`<PROJECT_ROOT>/.run/market-home-projection-enabled` 且内容精确为 `enabled\n` 后，factory
才装配 refresh callback；本任务不创建、修改或验证该 marker，也不生成 production projection。

## 6. Projection Envelope

单个 UTF-8 JSON object：

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

规则：

- envelope `extra="forbid"`；
- `schema_version == 1`；
- `generated_at` 必须 timezone-aware，只用于诊断；
- `authority_digest` 必须是 lowercase SHA-256 hex；
- `payload` 严格复用现有 `MarketHomeOverviewResponse`；
- Decimal wire 继续为字符串，null 保持 null；
- `payload.target_as_of == payload.data_as_of == envelope.target_as_of`。

## 7. Authority Identity

`MarketHomeAuthorityIdentity`：

```text
target_as_of
authority_digest
```

`target_as_of` 继续由 `DatabaseCoverageSource.latest_complete_day(active_products)` 提供。

`authority_digest` 精确绑定：

```text
active product 顺序
+
每个 product taxonomy.name
+
每个 product taxonomy.sector
```

确定性编码：

```python
records = [
    {"symbol": symbol, "name": taxonomy[symbol].name, "sector": taxonomy[symbol].sector}
    for symbol in products
]
json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
sha256(encoded_utf8).hexdigest()
```

Market-data source revision 不通过昂贵文件扫描加入 digest；由 §10 的 apply invalidation seam 保证任何 authoritative mutation 之前旧 projection 已不可读。

## 8. Projection Read Contract

`MarketHomeProjectionStore.load(identity)` 只有以下全部成立才返回 payload：

1. `.derived` parent 不是 symlink；
2. projection 自身不是 symlink 且是普通文件；
3. `0 < size <= 2 MiB`；
4. JSON / Pydantic validation 通过；
5. schema == 1；
6. target 与 authority digest 精确匹配；
7. payload target/data_as_of 与 envelope target 一致。

任一失败：返回 miss，不向 HTTP 泄露文件路径或解析细节。

## 9. API Contract

URL 与 response schema 不变：

```text
GET /api/v1/market/research/home-overview
```

Hit：

- 不调用 `MarketHomeOverviewService.snapshot()`；
- 不调用 `MarketDataService.query_page()`；
- 不调用 `list_latest_dominants()`；
- 不访问 Redis/provider；
- 不执行任何写入。

Miss：

- 调用现有 authoritative compute；
- 保持原 typed 409 error code；
- HTTP endpoint 不创建目录、不修复文件、不 publish projection。

因此 HTTP endpoint 始终只读。

## 10. Apply Invalidation Contract

正式 apply 写入口当前只有：

```text
guiyi data update --apply
guiyi data refresh --apply
natural after-market -> manager.update(apply=True)
```

代码搜索确认 metadata synchronization 的 active application 写入口也只由 `HistoricalDataManager` 维护链调用。

规则：

- CLI update/refresh：`run_data_command()` 在调用 manager 前 invalidates projection；
- after-market：provider readiness 通过后、manager.update 前 invalidates projection；
- dry-run/audit 不触碰 projection；
- provider readiness 未通过时不触碰 projection；
- invalidation 失败时 manager action 不得开始。

为什么必须先失效：同一日期的 MainContractMap 或 Parquet 可以被修正，`target_as_of` 不变。删除旧 projection 后，任何中途失败都只会使首页暂时回退现场 compute，不会显示旧快照。

## 11. Invalidation Path Safety

Projection path 由 `canonical_root.resolve()` 推导。

`.derived` parent 不允许为 symlink：

- read：视为 miss；
- invalidate：fail closed；
- publish：fail closed。

Projection 自身为 symlink时 read 不接受；invalidate 可安全 unlink 该 symlink 本身。

## 12. Atomic Publish

`MarketHomeProjectionStore.publish()`：

```text
validate envelope
→ mkdir .derived
→ open trusted .derived directory descriptor (O_DIRECTORY | O_NOFOLLOW)
→ create same-directory temporary file relative to that descriptor (O_EXCL | O_NOFOLLOW)
→ UTF-8 write
→ fsync temporary file
→ os.replace(temp, current, dir_fd)
→ fsync directory descriptor
→ cleanup temp
```

禁止 append、in-place truncate 或 delete-current-then-write。

写失败统一映射内部 projection error；after-market refresh 会隔离该错误。

## 13. After-market Ordering

Projection refresh 只在 `_attempt()` 已经完整返回 success 后执行，也就是：

```text
HistoricalDataManager status passed/noop
AND canonical_updated 已 publish
AND rank1/live reconciliation passed
AND cleanup passed
```

然后：

```text
try projection.refresh()
except:
    log warning(exception_type only)
    keep AfterMarketResult passed
```

Refresh failure：

- 不 retry；
- 不发 projection-specific PushPlus；
- 不更改 Alert Rule/Scope/Event；
- 不把 core maintenance 改判 failed；
- 旧 projection 已在 manager apply 前失效，因此 API 走 compute fallback。

refresh 在 compute、post-compute identity check 和 publish 的整个区间必须持有与 authoritative
apply 共用的 maintenance lease；拿不到 lease 时跳过这次 best-effort refresh。这样同日的
manual apply 不会与 refresh 交错发布 stale projection。

Invalidation failure 与 refresh failure 不同：invalidation failure 发生在 authority mutation 前，必须阻塞本次 apply，并沿 existing after-market failure contract 处理。

## 14. Pure Response Mapper

原 `app/api/market.py` 的 Snapshot → `MarketHomeOverviewResponse` 映射抽到：

```text
market_home_response(snapshot)
```

仅做 pure projection，无 I/O。

API compute fallback 和 after-market refresh 共用该 mapper；禁止复制两份 wire mapping。

## 15. 并发

V1 不引入 Redis lock、线程池或文件锁。

原因：

- authoritative maintenance 已有 maintenance lease；
- apply 前 invalidation 与 shared canonical root 避免跨 checkout stale projection；
- API 只读；
- atomic replace 保证 reader 只看到完整文件或 miss。

Projection refresh 如果 `authority_identity()` 与 `snapshot()` 之间 target day 变化，必须拒绝 publish。

## 16. 性能合同

本任务不优化 4.8s compute fallback；只把常态读路径改成小 JSON validation。

Manual acceptance 目标：

```text
projection decode + validation < 50ms
projection-hit HTTP endpoint  < 200ms
```

不得用 sleep/timing unit test伪造。自动测试通过行为断言证明 hit 没有调用 expensive compute。

## 17. 测试合同

### Identity / store

覆盖：

- digest deterministic；
- product order、taxonomy name、sector 变化 → digest 变化；
- round trip；
- Decimal/null wire 保持；
- missing/symlink/empty/oversize/corrupt → miss；
- schema/target/digest/payload identity mismatch → miss；
- parent symlink → read miss / invalidation fail；
- atomic replace failure 保持原文件并清临时文件；
- refresh target race 拒绝 publish。

### API

覆盖：

- hit 不调用 snapshot；
- miss compute 但不写；
- corrupt/mismatch compute fallback；
- typed 409 不变；
- router 只调用 projection read。

### Apply invalidation

覆盖：

- CLI update/refresh apply：manager action 前 projection 已不存在；
- CLI dry-run：projection 保留；
- symlink/失效失败：manager action 未调用；
- after-market provider not ready：不 invalidate；
- after-market manager failure：projection 保持失效，不 refresh；
- after-market success/noop：顺序 `invalidate → canonical_updated/core success → projection refresh`。

### Failure isolation

覆盖：

- projection refresh exception → AfterMarketResult 仍 passed；
- log 只含 exception type，不含 private message；
- refresh failure 不触发 notification。

## 18. Canonical / 文档同步

源码完成后同步：

- `DECISIONS.md`；
- `docs/ARCHITECTURE.md`；
- `openspec/specs/market-home-overview/spec.md`；
- `TESTING.md`。

不修改：

- `PROJECT_SOURCE.md`：用户产品语义未变化；
- `STATUS.md`：代码进入 branch/develop 不等于 release/Runtime/evidence。

## 19. 禁止范围

本任务不做：

- Redis cache；
- PostgreSQL / Alembic；
- 新外部 derived root/env；
- background worker / queue / scheduler；
- thread pool / parallel Parquet reader；
- MarketDataService 性能重构；
- 指标公式变化；
- HTDY / Alert Rule / Event / Scope / audience / transport 变化；
- Web UI 变化；
- production RQData / Canonical / DB / Redis 写入；
- 手工真实 after-market；
- main/tag/Release/Runtime promotion。

## 20. Gate

用户已明确授权：

```text
Spec → Plan → code/test implementation → review/fix → submit PR
```

该授权只覆盖仓库代码、测试、文档、task branch 和 PR。

pytest/Ruff/Mypy/OpenSpec/secret scan 与 projection-hit benchmark 必须在实际可运行的本地环境完成；未实际执行时 PR 必须明确保留 pending，不能以静态 Review 代替。

production projection 首次生成、release 与 Runtime promotion 仍是独立 Gate。
