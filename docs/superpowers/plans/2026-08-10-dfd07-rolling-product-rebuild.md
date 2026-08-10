# DFD-07 滚动单品种补全实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不干扰 MR-08 关键实时验证的前提下，按单品种闭环逐步完成 DFD-07 历史 Canonical 重建，并用实际样本校准排期。

**Architecture:** 不新增代码、脚本、数据库对象或第二条维护链。每个品种只经现有 `guiyi data update|audit`、八表 Catalog、Canonical Parquet 与 `MarketDataService` 处理；写入严格单通道，准备工作严格只读。

**Tech Stack:** Python 3、现有 `guiyi` CLI、RQData、PostgreSQL 八表 Catalog、Canonical Parquet、MarketDataService。

## Global Constraints

- 固定重建水位为 `T0=2026-08-07`，当前四交易所 canary 的剩余顺序为 `ec`、`lc`。
- 每次生产 `--apply` 前都需要用户对该单一品种的一次性明确执行意图；本计划本身不构成授权。
- `update --apply`、`refresh --apply` 和盘后维护不得并发；MR-08 关键观察、历史读回或盘后维护期间不得开始品种写入。
- 不修改 `operational_products.txt`，不启用 Runtime，不执行 Live、通知或订单动作。
- 无 `--apply` 的 update/refresh 与 audit 保持零 RQData、零 PostgreSQL 写入、零 Parquet 写入。

---

### Task 1: 为 `ec` 建立只读执行前基线

**Files:**
- Create: none
- Modify: none
- Test: existing read-only CLI surfaces only

**Interfaces:**
- Consumes: `guiyi runtime status`、`guiyi data audit --symbol ec`、`guiyi data update --symbol ec --through 2026-08-07`
- Produces: `ec` 的 MR-08 检查点、当前 audit/dry-run 结果和后续单次授权所需的精确目标。

- [x] **Step 1: 确认 MR-08 处于可安全检查的状态。**

```bash
uv run --project services/quant-api guiyi runtime status
```

Expected: 返回只读 JSON；若显示 MR-08 正在关键验证、或操作者确认正处于关键实时观察，则停止，不运行后续命令。

- [x] **Step 2: 运行 `ec` scoped audit。**

```bash
uv run --project services/quant-api guiyi data audit --symbol ec
```

Expected: 当前未闭环品种可返回结构化 metadata/partition finding；命令不调用 RQData、不写入 Catalog 或 Canonical。

- [x] **Step 3: 运行固定 T0 的 `ec` dry-run。**

```bash
uv run --project services/quant-api guiyi data update --symbol ec --through 2026-08-07
```

Expected: 在元数据尚未完整时以公开 fail-closed 码停止；不得把无法生成 target 伪称为零目标或已完成。

- [x] **Step 4: 交付只读基线。**

记录 runtime 检查点、audit/dry-run JSON 中的 status、finding/错误码，以及三条命令均未带 `--apply` 的事实。不要创建任务文件、报告文件或数据库记录。

### Task 2: 在单次授权下闭环 `ec`

**Files:**
- Create: none
- Modify: none
- Test: 生产写后只读验收

**Interfaces:**
- Consumes: Task 1 基线与用户明确的单次 `ec` 执行意图。
- Produces: `ec` 的 Canonical/Catalog 更新结果，或可恢复的当前品种失败状态。

- [x] **Step 1: 取得且逐字核对 `ec` 的一次性执行意图。**

授权文字必须限定为：生产 `guiyi data update --symbol ec --through 2026-08-07 --apply`，并明确允许该次 RQData 元数据同步、生产 Catalog 与 Canonical 写入；不得包含任何其他品种、Runtime、通知或订单。

- [x] **Step 2: 在 MR-08 检查点后启动唯一一次 apply。**

```bash
uv run --project services/quant-api guiyi data update --symbol ec --through 2026-08-07 --apply
```

Expected: 进程自然结束并返回 `passed`、`partial` 或失败 JSON。若返回 `MAINTENANCE_LOCKED`，不重试；等待新的检查点与新的明确意图。

- [x] **Step 3: 记录唯一的 apply 观测。**

在终端交付中记录墙钟耗时、`planned`、`applied`、`failed`、`blocked`、`provider_requests` 与 `stop_reason`；不把部分发布或单纯分区数量称为闭环。

- [x] **Step 4: 对成功 apply 运行 audit。**

```bash
uv run --project services/quant-api guiyi data audit --symbol ec
```

Expected: `status=passed` 且 `finding_count=0`；否则停止在 `ec`，不进入 `lc`。

- [x] **Step 5: 对成功 audit 运行同 T0 NOOP 检查。**

```bash
uv run --project services/quant-api guiyi data update --symbol ec --through 2026-08-07
```

Expected: `status=noop`、`planned=0`、`provider_requests=0`；否则停止在 `ec`。

- [x] **Step 6: 做既有的七周期 MarketDataService 读回。**

使用当前已验证的读取入口，对 `1m/5m/15m/30m/60m/1d/1w` 分别检查 continuous；再从写后 rank1 map 选择已有 coverage 内的早期、近期和跨换月窗口，检查 concrete contract 与 actual_dominant。缺少 mapping、分区、coverage 或物理文件时必须 fail-closed，不得缩短窗口来通过验收。

- [x] **Step 7: 关闭或暂停 `ec`。**

仅在 Step 4 至 Step 6 全部通过时标记 `ec` 闭环；否则报告当前失败点、保留已验证分区并等待针对 `ec` 的后续决定。

### Task 3: 以相同闭环处理 `lc`，再转入最短优先队列

**Files:**
- Create: none
- Modify: none
- Test: `lc` scoped audit、fixed-T0 dry-run 与生产写后 MarketDataService 读回

**Interfaces:**
- Consumes: 完成闭环的 `ec`，以及 `lc` 自己的只读基线和一次性授权。
- Produces: 四交易所 canary 完成状态，或停在 `lc` 的显式失败状态。

- [ ] **Step 1: 确认 MR-08 处于可安全检查的状态。**

```bash
uv run --project services/quant-api guiyi runtime status
```

Expected: 返回只读 JSON；若显示 MR-08 正在关键验证、或操作者确认正处于关键实时观察，则停止，
不运行后续命令。

- [ ] **Step 2: 运行 `lc` scoped audit。**

```bash
uv run --project services/quant-api guiyi data audit --symbol lc
```

Expected: 当前未闭环品种可返回结构化 metadata/partition finding；命令不调用 RQData、不写入 Catalog
或 Canonical。

- [ ] **Step 3: 运行固定 T0 的 `lc` dry-run。**

```bash
uv run --project services/quant-api guiyi data update --symbol lc --through 2026-08-07
```

Expected: 元数据尚未完整时以公开 fail-closed 码停止；不得把无法生成 target 伪称为零目标或已完成。

- [ ] **Step 4: 交付 `lc` 的只读基线。**

记录 runtime 检查点、audit/dry-run JSON 中的 status、finding/错误码，以及三条命令均未带 `--apply`
的事实。不要创建任务文件、报告文件或数据库记录。

- [ ] **Step 5: 获得 `lc` 的独立单次意图后，执行唯一一次 apply。**

```bash
uv run --project services/quant-api guiyi data update --symbol lc --through 2026-08-07 --apply
```

Expected: 不与任何其他维护操作并发；输出为该次唯一的 `lc` 写入结果。

- [ ] **Step 6: 对成功 apply 运行 audit。**

```bash
uv run --project services/quant-api guiyi data audit --symbol lc
```

Expected: `status=passed` 且 `finding_count=0`；否则停止在 `lc`，不转入常规队列。

- [ ] **Step 7: 对成功 audit 运行同 T0 NOOP 检查。**

```bash
uv run --project services/quant-api guiyi data update --symbol lc --through 2026-08-07
```

Expected: `status=noop`、`planned=0`、`provider_requests=0`；否则停止在 `lc`。

- [ ] **Step 8: 做 `lc` 的七周期 MarketDataService 读回。**

对
`1m/5m/15m/30m/60m/1d/1w` 分别检查 continuous；再从 `lc` 写后 rank1 map 选择已有 coverage
内的早期、近期和跨换月窗口，检查 concrete contract 与 actual_dominant。任何 mapping、分区、
coverage 或物理文件缺失都必须显式失败，不得缩短窗口来通过验收。

- [ ] **Step 9: 形成第一批六个样本的排期档。**

将 J、JM、AP、AG、EC、LC 的实际 provider 请求数、apply 墙钟时间和发布分区数按终端交付汇总为短、中、长三档。只用于排序后续品种；不据此改造并发、自动重试、配置或数据模型。

- [ ] **Step 10: 常规品种循环。**

每次只选择最短优先的一个未闭环 active 品种，执行 runtime 检查点、scoped audit、fixed-T0
dry-run、一次性授权、唯一 apply、audit、NOOP 与七周期三种查询模式读回。每次闭环或失败都回到
MR-08 检查点；在 60 个品种都闭环前，不宣称 DFD-07 完成。

## Verification Summary

- 仓库实现未改动，因而不新增 pytest 或 build 验证。
- 每个真实品种的验收证据是 scoped audit、fixed-T0 dry-run 和 MarketDataService 七周期读回；真实写入前后均核对 MR-08 检查点。
- 60 个 active 品种均逐个闭环后，才运行 `guiyi data audit --universe active` 作为全域只读验收。
