## Why

Data Core V2 架构收口已完成，生产写链已真实跑通，但增量发布仍会制造 Catalog partition conflict、NOOP 漏掉 actual_dominant、Calendar/Session identity 不一致，以及 M2 大规模 unreadable。现在需要在不改架构的前提下把日常 `data update` 修成精确增量、可重复收敛的内核。

## What Changes

- Planner 将 Catalog 缺口物化为 **exact DataTarget**（Direct + Derived）；日常增量不再整窗重发。
- **BREAKING（CLI 语义）**: `--since` 仅作缺失检测下界；covered 窗口不再 force-refresh / 重建已有 partition。
- Apply 控制流改为 **metadata bootstrap → refreshed watermark → MainContractMap refresh → final exact plan → Direct → Derived → verify**；metadata 不再依赖初始 plan 非空。
- actual_dominant 完整性由 **MainContractMap rank=1 expected windows** 驱动（整 Dataset 不存在也必须发现）。
- Calendar/Session 最终只认实际 `exchange_code`；分迁移移除 CNFE/CZCE 隐式 fallback；writer 禁止硬编码 CNFE，并修正 `has_night_session` 无证据写 False。
- 删除已 drop 表的 stale ORM（Profile/Binding/Checkpoint）；保留 IngestRecorder 使用的 Task/File/QualityReport。
- 1w 完成根因矩阵并冻结周 watermark / 周末日 rank1 归属；根因清晰后修确认层。
- M2 将不可读/ map 问题拆成有界 `reason_code` 与 `MAPPED_CONTRACT_DATASET_MISSING`；不新建第二套 audit。
- 验收 Gate：JM → 多交易所 canary → 69 → M2=0 → **相同 `--through`** 二次 dry-run NOOP。

## Capabilities

### New Capabilities

- `historical-update-convergence`: exact missing publish、`--since` 非 refresh、metadata bootstrap 先于 final plan、MainContractMap expected actual_dominant、同 watermark 幂等 NOOP。
- `exchange-metadata-identity`: 按实际交易所 materialize/读取 Calendar 与 Session；迁移顺序与 fail-closed；退出 CNFE/CZCE 隐式 fallback。
- `weekly-bar-semantics`: 1w 完整周 watermark、continuous/actual_dominant 周归属与根因矩阵验收。
- `m2-probe-diagnostics`: SessionAligned probe 有界 outcome；map invalid vs mapped dataset missing 拆分。

### Modified Capabilities

- （无既有 `openspec/specs/` 能力需 delta；本变更为新建能力合同。正式业务 canonical 仍以 `docs/tasks/GY-DATA-CORE-V2.md` 为准，本 change 仅为 implementation delta。）

## Impact

- 代码：`target_planner.py`、`historical_update.py`、`download.py`、`aggregate.py`、`publisher.py`、`metadata_sync.py` / `composition.py`、`ingestors.py`、`historical_sessions.py`、`trading_session_clock.py`、`m2_architecture_audit.py`、`market_data_probe.py`、`models/data_center.py`。
- CLI：`guiyi data update` apply/dry-run 语义与输出字段（含 metadata watermark / refresh_required）。
- 文档：M3-00 后仅按 readback 事实更新 `STATUS.md` / `DATA_CENTER.md` / `ARCHITECTURE.md`；完成后 archive 本 change，不形成第二套长期事实源。
- 生产：代码合入不自动授权写；Metadata normalization / JM / canary / 69 各需独立 mutation 意图；只读 audit/dry-run 不授予写权限。
- 禁止：放宽 Catalog、降 M2 严格度、AD 回退 continuous、全量删 Canonical 重下、误删 IngestRecorder 三表、恢复 Profile/Binding/Hive/after-market。
