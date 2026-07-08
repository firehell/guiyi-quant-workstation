# 任务：DOC-COMPLETION-20260708

生成时间：2026-07-08
任务性质：文档完善——对齐 Stage 8.6 / Stage 9-A / 9-B1 / 9-B2 完成状态，修正过期阶段定位，补齐缺失文档，消除跨文档不一致

## 任务背景

当前代码已推进到 Stage 9-B2（企业微信单条历史回放 smoke 成功，event_id=1, HTTP 200, sent），但大量文档仍停留在 2026-07-07 的 Stage 8.5 视角。多个核心文档把已完成能力列为"未完成"，GPT 同步文件的阶段定位滞后，部分文档缺失 Stage 8.6 和 Stage 9 的新增内容。

本任务不修改任何业务代码、策略、数据资产或数据库结构，只更新文档。

## 审查范围

共 19 个文档文件需要审查，其中：

- **需更新**：14 个
- **需新增**：2 个
- **仅同步**：3 个（GPT 镜像文件）

---

## Step 1：修正核心文档阶段状态（7 个文件）

### 1.1 `README.md`

**问题**：
- "当前阶段"写 "Stage 8.5 已完成到 final Gate"
- "下一步"第 1 条写 "Stage 9：企业微信只读提醒 guarded adapter 设计 / 实现，默认不真实发送"

**修正为**：
- 当前阶段更新为 "Stage 9-B2 已完成（企业微信单条历史回放 smoke 通过）"
- "下一步"更新为 Stage 9-B 真实发送授权 / worker / scheduler、Stage 10 Web Market 策略展示增强
- "已完成功能"补充 Stage 8.6 全品种 active Gate 只读审计、Stage 9 企业微信 preview / dry-run / 受控发送

### 1.2 `docs/ARCHITECTURE.md`

**问题**：
- "当前未完成能力"第 1 条 "企业微信只读提醒 payload / guarded sender / 通知记录 / 失败重试" — 已完成
- 未提及 Stage 8.6 全品种 active Gate 审计
- 未提及 Stage 9 企业微信发送链路

**修正为**：
- "未完成能力"删除企业微信相关条目，替换为 "企业微信真实发送 worker / scheduler / 批量重试"
- "已具备能力"补充 Stage 8.6 / Stage 9-A / 9-B1 / 9-B2
- 生成时间更新为 2026-07-08

### 1.3 `docs/PROJECT_INVENTORY.md`

**问题**：
- "未完成能力"仍列 "企业微信只读提醒 payload / guarded sender / 通知记录 / 失败重试"
- 未列出 Stage 9 相关代码文件
- 生成时间 2026-07-07

**修正为**：
- "未完成能力"更新
- "已具备功能"补充 Stage 8.6 / Stage 9
- 后端 API 表补充 Stage 9 相关端点
- 生成时间更新为 2026-07-08

### 1.4 `docs/BACKTEST_ENGINE.md`

**问题**：
- "未完成"第 5 条 "signal_events 事件化" — 已完成（Stage 8）
- 未提及真实合约成本增强（手续费、保证金、强平退出）
- 未提及 Stage 8.5 actual-contract bars 试点

**修正为**：
- "未完成"删除 signal_events 条目，保留可信回测主线复核
- "当前回测能力"补充真实合约成本增强
- 补充 Stage 8.5 actual-contract bars 数据基础说明
- 生成时间更新为 2026-07-08

### 1.5 `docs/STRATEGY_CURRENT_STATE.md`

**问题**：
- "后续策略任务"第 2 条 "Stage 8 才做 signal_events 信号事件化" — 已完成
- 策略清单缺少 `SuBingEma21VnpyStrategy`（PROJECT_OVERVIEW.md 中有列出）
- 未提及 Stage 9 Gate 对策略信号的准入约束

**修正为**：
- "后续策略任务"更新为当前实际状态
- 策略清单补齐 `SuBingEma21VnpyStrategy`
- 补充 Stage 9 Gate 准入要求说明
- 生成时间更新为 2026-07-08

### 1.6 `docs/SIGNAL_EVENTS.md`

**问题**：
- Stage 8 完成后文档未更新 Stage 9-A / 9-B1 / 9-B2 的内容
- 未说明 `signal_notifications` 表扩展字段（event_id、attempt_count、retry 等）
- 未提及 Stage 9 Gate 准入逻辑的完整规则

**修正为**：
- 补充 Stage 9-A preview / dry-run adapter 说明
- 补充 Stage 9-B1 受控发送 / 通知记录 / 重试框架说明
- 补充 Stage 9-B2 历史回放事件生成说明
- 补充 `signal_notifications` 扩展字段表
- 补充 Stage 9 Gate 完整准入规则
- 生成时间更新为 2026-07-08

### 1.7 `docs/CODEX_HANDOFF.md`

**问题**：
- 生成时间 2026-07-07，但内容已更新到 9-B2 — 日期需更新
- "下一步建议"仍指向 Stage 9-B2-Retry 或 Stage 10，可保留但需确认措辞
- 必读文件列表未包含 `docs/SIGNAL_EVENTS.md`（已在其中）和 Stage 9 相关文件

**修正为**：
- 生成时间更新为 2026-07-08
- 必读文件列表补充 Stage 9 相关文档
- 确认"下一步"措辞与 NEXT_STEPS.md 一致

---

## Step 2：修正 GPT 同步文件（5 个文件）

### 2.1 `docs/gpt/CURRENT_STATE.md`

**问题**：
- "当前阶段"写 "Stage 8.5：数据主链路扩展 Gate"
- "下一步建议"写 "Stage 9-A：企业微信只读提醒 preview / dry-run adapter"
- 生成时间 2026-07-07

**修正为**：
- 当前阶段更新为 "Stage 9-B2 已完成"
- 下一步更新为 Stage 9-B 真实发送 worker / scheduler、Stage 10
- 生成时间更新为 2026-07-08

### 2.2 `docs/gpt/NEXT_STEPS.md`

**问题**：
- 阶段路线表中 Stage 9-B 状态描述需确认一致性
- "最近完成阶段"文本部分仍停留在 Stage 2 / 3 / 4 / 5 / 6 / 7 / 8，未覆盖 8.5 / 8.6 / 9-A / 9-B
- 生成时间 2026-07-07

**修正为**：
- 阶段路线表确认 Stage 9-B2 状态
- "最近完成阶段"补充 Stage 8.5 / 8.6 / 9-A / 9-B1 / 9-B2 摘要
- 生成时间更新为 2026-07-08

### 2.3 `docs/gpt/PROJECT_SNAPSHOT.md`

**问题**：
- 生成时间 2026-07-07
- "当前结论"部分未提及 Stage 8.6 / Stage 9
- "下一步"第 1 条仍指向 Stage 9

**修正为**：
- "当前结论"补充 Stage 8.6 / 9-A / 9-B1 / 9-B2
- "下一步"更新
- 生成时间更新为 2026-07-08

### 2.4 `docs/gpt/README.md`

**问题**：
- "当前结论"未提及 Stage 8.6 / Stage 9
- "下一步"第 1 条仍指向 Stage 9
- 生成时间 2026-07-07

**修正为**：
- "当前结论"补充
- "下一步"更新
- "仍需注意"更新
- 生成时间更新为 2026-07-08

### 2.5 `docs/gpt/tasks_current.md`

**问题**：
- 是 `tasks/current.md` 的镜像，需同步最新内容

**修正为**：
- 从 `tasks/current.md` 同步最新内容

---

## Step 3：新增缺失文档（2 个文件）

### 3.1 新增 `docs/STAGE9_WECHAT_DELIVERY.md`

**内容范围**：
- Stage 9 企业微信只读提醒完整设计文档
- 包含：Gate 准入规则、payload 结构、发送流程、通知记录表、重试策略、脱敏规则
- 包含：API 端点清单（preview / notification / send CLI）
- 包含：Stage 9-A / 9-B1 / 9-B2 完成状态
- 包含：安全边界（不自动下单、不暴露 webhook、observation-only）

### 3.2 新增 `docs/STAGE8_6_ACTIVE_GATE_AUDIT.md`

**内容范围**：
- Stage 8.6 全品种下载结果 active Gate 只读审计文档
- 包含：审计器设计、输入 / 输出、分层规则（active_passed / active_partial / audit_pending / failed / missing / stage9_blocked）
- 包含：审计命令、报告文件清单
- 包含：当前 smoke 摘要（90 products, active_passed=82, active_partial=8）
- 包含：安全边界（只读、不写 parquet / DB / manifest）

---

## Step 4：更新 `docs/PROJECT_OVERVIEW.md`

**问题**：
- 生成时间 2026-07-08（已较新）
- "当前阶段"需确认是否反映 9-B2
- "未完成能力"需确认是否已更新

**修正为**：
- 确认 "当前阶段" 反映 Stage 9-B2
- "已完成"部分确认包含 Stage 8.6 / 9-A / 9-B1 / 9-B2
- "下一步"表确认一致性

---

## Step 5：交叉一致性检查

完成上述步骤后，运行以下检查：

### 5.1 阶段定位一致性

所有文档中"当前阶段"描述必须一致：

```text
Stage 9-B2 已完成（企业微信单条历史回放 smoke 通过，event_id=1, HTTP 200, sent）
```

### 5.2 "未完成能力"一致性

所有文档中"未完成能力"列表必须一致，核心条目：

```text
- 企业微信真实发送 worker / scheduler / 批量重试
- 全品种下载结果审计、DB 登记核对和 active Gate 分层最终确认
- 盘后归档真实写入、worker、scheduler 和 runtime dashboard
- Web Market 策略 marker、策略详情侧栏、historical / live / signal 联动
- 阿里云 Web 托管设计与远程 health smoke
- Dashboard 真实数据接入
- 策略管理页面实用化
- Settings 持久化
- 可信回测主线复核
```

### 5.3 "下一步"一致性

所有文档中"下一步"必须与 `docs/gpt/NEXT_STEPS.md` 阶段路线表一致。

### 5.4 active 数据入口约束一致性

确认所有文档中的 active 数据入口约束文本一致：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

### 5.5 生成时间一致性

所有被修改文档的生成时间统一更新为 `2026-07-08`。

---

## 允许修改范围

```text
docs/*.md
docs/gpt/*.md
docs/gpt/tasks_current.md
tasks/doc-completion-20260708.md（本文件）
README.md
```

## 禁止修改范围

```text
所有 .py / .ts / .vue / .js 文件
所有 parquet / manifest / checksum 数据资产
所有数据库 migration / schema 文件
所有 .env / 配置文件
所有策略代码文件
scripts/ 目录下的脚本文件
AGENTS.md / CODEBUDDY.md（如需更新另开任务）
```

## 执行模式

Plan 模式优先。本任务只修改文档，不涉及代码、数据、策略或数据库。

## Gates

| Gate | 触发条件 | 动作 |
|---|---|---|
| G1 | Step 1 完成后 | 暂停，用户确认核心文档阶段状态修正 |
| G2 | Step 3 完成后 | 暂停，用户确认新增文档内容和范围 |
| G3 | Step 5 完成后 | 暂停，用户确认交叉一致性检查结果 |

## 验收标准

1. 所有 14 个需更新文档的生成时间更新为 2026-07-08
2. 所有文档中"当前阶段"统一为 Stage 9-B2 已完成
3. 所有文档中"未完成能力"列表一致，不再把已完成能力列为未完成
4. 所有文档中"下一步"与 NEXT_STEPS.md 阶段路线表一致
5. 新增 2 个文档（STAGE9_WECHAT_DELIVERY.md、STAGE8_6_ACTIVE_GATE_AUDIT.md）内容完整
6. GPT 同步文件（tasks_current.md）与 tasks/current.md 内容一致
7. 不修改任何业务代码、数据资产、数据库结构或配置文件

## 验证命令

```bash
# 确认只修改了文档文件
git diff --name-only | grep -v '\.md$' | grep -v 'tasks/' && echo "ERROR: non-doc files changed" || echo "OK: only doc files changed"

# 确认生成时间已更新
grep -rl '2026-07-07' docs/ README.md | grep -v 'DATA_UNIVERSE' && echo "WARNING: some files still have 2026-07-07" || echo "OK: dates updated"

# 确认不再有过期的"未完成"条目
grep -r '企业微信只读提醒 payload / guarded sender / 通知记录 / 失败重试' docs/ README.md && echo "WARNING: stale unfinished item found" || echo "OK: no stale items"

# 确认 GPT 同步文件一致
diff docs/gpt/tasks_current.md tasks/current.md && echo "OK: in sync" || echo "WARNING: out of sync"

# 确认 git diff 不含代码文件
git diff --check
```

## 文档清单总览

| 文件 | 操作 | Step |
|---|---|---|
| `README.md` | 更新阶段状态 | 1.1 |
| `docs/ARCHITECTURE.md` | 更新能力清单 | 1.2 |
| `docs/PROJECT_INVENTORY.md` | 更新能力 + 文件清单 | 1.3 |
| `docs/BACKTEST_ENGINE.md` | 更新未完成项 + 能力 | 1.4 |
| `docs/STRATEGY_CURRENT_STATE.md` | 更新策略任务 + 清单 | 1.5 |
| `docs/SIGNAL_EVENTS.md` | 补充 Stage 9 内容 | 1.6 |
| `docs/CODEX_HANDOFF.md` | 更新日期 + 必读列表 | 1.7 |
| `docs/gpt/CURRENT_STATE.md` | 更新阶段定位 | 2.1 |
| `docs/gpt/NEXT_STEPS.md` | 更新最近完成阶段 | 2.2 |
| `docs/gpt/PROJECT_SNAPSHOT.md` | 更新结论 + 下一步 | 2.3 |
| `docs/gpt/README.md` | 更新结论 + 下一步 | 2.4 |
| `docs/gpt/tasks_current.md` | 同步 current.md | 2.5 |
| `docs/STAGE9_WECHAT_DELIVERY.md` | 新增 | 3.1 |
| `docs/STAGE8_6_ACTIVE_GATE_AUDIT.md` | 新增 | 3.2 |
| `docs/PROJECT_OVERVIEW.md` | 确认 / 微调 | 4 |

## GPT 同步文件

完成后需同步：

- `tasks/doc-completion-20260708.md`（本文件）
- `tasks/current.md`（追加文档完善任务完成记录）
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`
- `docs/gpt/tasks_current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/ARCHITECTURE.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/PROJECT_INVENTORY.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/STAGE9_WECHAT_DELIVERY.md`（新增）
- `docs/STAGE8_6_ACTIVE_GATE_AUDIT.md`（新增）
