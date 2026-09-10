## Context

基于 `develop@284ae9abeb2eaf045899fbebe82419360bc01560` 审查。`HistoricalDataManager._execute_apply` 已维护 `pending_minute_months`，但早期派生循环只在 `fail_stop or self._source_cache is not None` 时检查它。普通 refresh 不满足这两个条件，旧 1m 完整时派生目标提前成功并从 remaining 移除，随后来源更新不能重新触发它。

既有 `docs/DATA_CENTER.md` 已要求 refresh 先重建基础数据再重建派生数据。本方案落实此合同，不改变策略或聚合语义。

## Goals / Non-Goals

目标：每个本次更新的派生目标只能使用其依赖的本次成功发布 1m；失败时结果诚实，其他独立 family/month 保持既有可推进行为。

不做：全批次事务、数据世代数据库、通用 DAG、自动重试、历史数据修复、公式或频率扩展。历史已受影响分区如何定位和真实修复，属于后续单独只读审计及受控写入。

## Decisions

### 1. 复用现有依赖身份

依赖键保持 `(*_family(target.key), target.year, target.month)`，frequency 不属于 family；`continuous` 与 `contract` 及不同 series/physical contract 不得碰撞。

在早期派生循环中，只要该键属于 `pending_minute_months` 就延后。判断不依赖运行模式、fail_stop 或 source cache。无需增加调度对象；现有成功发布 1m 后的派生循环负责推进。

### 2. 成功发布才解除依赖

来源完成下载不足以释放派生目标，必须经过既有 validation、不可变文件发布、Catalog commit 和已有 readback 流程。失败或 quota interruption 不得回退到旧来源把依赖目标报为成功。

保留现有 `failed_families`、全局失败与 quota 结果分类；`COMMIT_OUTCOME_UNKNOWN` 仍立即停批，不自动读猜结果后继续。保留已经成功提交的其他分区，不构造跨周期回滚。可能出现“1m 已更新、派生仍旧”的明确 partial/failed 状态；本方案保证不会将其包装成全部成功，并不提供跨周期读快照。

### 3. 来源不变的独立工作继续

若本次没有更新该 family/month 的 1m，且 Canonical 来源按既有规则完整有效，仍可在 provider 下载前派生。这保留了无关 provider 配额不足时，已有可信数据仍能完成本地派生的能力。

## Alternatives considered

- 全部派生一律推迟到所有下载结束：简单但会降低独立目标在 quota interruption 前完成的机会，不采用。
- 先派生再强制重算：增加发布次数，且中间结果来源错误，不采用。
- 引入依赖图调度器：当前依赖只有固定 1m → 四种分钟周期，维护成本无收益，不采用。

## Validation

在 `test_historical_data_manager.py` 使用真实 manager、临时 store、隔离 Catalog 与 FakeProvider，先发布旧 1m 和派生数据，再令 refresh 返回不同数值的新 1m。参数化覆盖 5m/15m/30m/60m 及 continuous/contract，断言结果状态、最终逐值结果和来源 commit 早于派生发布。

保护案例包括：普通无缓存路径；既有 streaming/fail_stop 路径；同一 family 不同月份、不同 family 同月份；来源校验失败、quota 中断和 commit unknown；来源不变时，在无关 provider quota 前仍可完成派生。测试不能仅检查调用顺序或只 mock `_derive_target`，必须至少有最终 Canonical readback 的数值断言。

## Rollout and risks

从实施时最新干净 develop 基线开始，先确认本问题仍存在。无需 migration、版本 bump 或生产动作。源码回退可使用 Git revert；若未来已经真实更新数据，Git 回退不能回退 Canonical，须另行评估。

实施后独立 Review 重点核对派生目标没有被过早移除、失败分支没有解除来源依赖。通过工程验收只支持集成 develop，不证明生产历史已修正。
