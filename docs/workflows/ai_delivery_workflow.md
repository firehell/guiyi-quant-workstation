# AI 半自动交付流程 SOP

> 提炼自：`STATION_CONFIG.md` §15–23（归一量化产品与交付工作站 Final v1.0）
> 配套：`STATE_MACHINE_TICKET.md`（10 状态机）、`COLLAB_PROTOCOL.md`（四方协作）、`TASK_TEMPLATE.md`（21 字段）
> 适用范围：WorkBuddy → CodeBuddy → Codex CLI 半自动开发闭环（想法 → 任务单 → plan → dev → 测试 → 交付 → merge）

---

## 0. 总原则（铁律，无条件生效）

1. 先 plan，后开发。
2. plan 只读。
3. dev 仅允许 workspace-write。
4. 不允许自动 push。
5. 不允许自动 merge。
6. 不允许自动 deploy。
7. 不允许修改 `.env` / token / webhook / 密钥。
8. 不允许删除数据。
9. 不允许启动自动交易。

任何脚本 / 角色违反以上任一条，立即中止并回报用户与安全专家。

---

## 1. 流程总览

```text
你 ──想法──▶ WorkBuddy ──命令1 任务单──▶ [REQUIREMENT_READY / PLAN_READY]
你 ──确认──▶ WorkBuddy ──命令11 Codex Plan Prompt──▶ CodeBuddy
CodeBuddy ──codex_plan.sh(只读)──▶ Codex CLI ──plan.md──▶ CodeBuddy ──回传──▶ 你
你 ──确认 plan + 确认开发──▶ WorkBuddy ──命令10/12 执行/Dev Prompt──▶ CodeBuddy
CodeBuddy ──codex_dev.sh(workspace-write)──▶ Codex CLI ──改代码──▶ codex_dev 自动调 run_tests.sh
CodeBuddy ──collect_result.sh──▶ result_bundle ──回传──▶ 你 ──▶ WorkBuddy
WorkBuddy ──命令13 交付报告──▶ [DELIVERY_READY]
你 ──命令15 合并前检查──▶ WorkBuddy ──检查结论──▶ 你 ──merge/deploy──▶ [CLOSED]
```

任一环节失败 → 命令 14 失败复盘 → FAILED → REPLAN → PLAN_READY。

---

## 2. 各阶段 SOP 与人工确认点

### 阶段 A · 任务单生成（WorkBuddy，命令 1）
- 状态：`IDEA → REQUIREMENT_READY`
- 动作：按 `TASK_TEMPLATE.md` 21 字段产出任务单；必含测试清单、验收标准、风险点。
- **人工确认点**：你确认 PRD 与验收目标。
- 不生成：纯问答 / 已存在未关闭同意图任务单。

### 阶段 B · Plan（CodeBuddy，命令 11）
- 状态：`PLAN_READY → APPROVED_DEV`
- 动作：`codex_plan.sh --task <ID>` 以**只读**模式调 Codex，产出 `scripts/ai/.out/<ID>/plan.md`。
- 护栏：不写业务代码、不 commit、不 push。
- **人工确认点**：**你审阅并批准 plan**（批准即进入 APPROVED_DEV）。

### 阶段 C · Dev（CodeBuddy，命令 12）
- 状态：`APPROVED_DEV → CODING → TESTING`
- 动作：`codex_dev.sh --task <ID> --plan <plan>` 调 Codex 开发；完成后自动 `run_tests.sh --scope all`。
- 护栏（硬约束）：不碰 `.env`/密钥；不 push/merge/deploy；不删数据；默认 dry-run；真实发送需 `--run-send --confirm-observation-only` 且你授权。
- **人工确认点**：真实写入 / 发送 / 外部动作需你显式授权。

### 阶段 D · 测试（CodeBuddy，命令 8 类）
- 状态：`TESTING`
- 动作：`run_tests.sh` 跑 pytest；日志脱敏过滤 `webhook|token|password|secret`。
- 护栏：默认 dry-run / mock webhook；`--real` 需人工确认。
- **人工确认点**：重大阻塞需知会你；真实 smoke 需授权。

### 阶段 E · 结果收集（CodeBuddy）
- 动作：`collect_result.sh --task <ID>` 生成 `result_bundle.md`，敏感字段脱敏为 `[REDACTED]`。
- 护栏：不 push；不写密钥。

### 阶段 F · 交付摘要（CodeBuddy）
- 动作：`make_delivery_summary.sh --task <ID> --bundle <result_bundle>` 生成 `delivery_summary.md`（结构见 UX_VISUAL_SPEC §3）。
- 护栏：不含任何密钥。

### 阶段 G · 交付报告（WorkBuddy，命令 13）
- 状态：`TESTING pass → DELIVERY_READY`
- 动作：交付专家按《交付测试结论模板》产出报告；状态建议 `DELIVERY_READY`。
- **人工确认点**：你最终 review、merge、deploy（WorkBuddy 不代执行）。

### 阶段 H · 合并前检查（WorkBuddy，命令 15）
- 动作：`git diff --check` / 测试通过 / 无敏感泄露 核查。
- **人工确认点**：你执行 merge / deploy。

---

## 3. 失败处理（命令 14）

```text
run_tests.sh 退出非 0
  → CodeBuddy 调 collect_result.sh 收集失败日志
  → 回传你 + WorkBuddy（附失败摘要）
  → WorkBuddy 出《失败复盘报告》：根因分类 / 影响 / REPLAN 方向 / 回归用例 / 验收标准 / 风险点
  → 状态：FAILED →（你确认）→ REPLAN → PLAN_READY
  → 修复后重走：单元→集成→数据/策略/告警→回归
  → P0 红线级（自动交易/误发/密钥泄露/active 污染）：立即止损 + 安全专家一票否决，不自动恢复
```

---

## 4. 脚本清单（scripts/ai/）

| 脚本 | 契约 | 模式 |
|------|------|------|
| `codex_plan.sh` | COLLAB §6 / §11 | 只读 plan |
| `codex_dev.sh` | COLLAB §7 / §12 | workspace-write + 自动测试 |
| `run_tests.sh` | COLLAB §8 | dry-run 默认，日志脱敏 |
| `collect_result.sh` | COLLAB §9 | 脱敏汇总 |
| `make_delivery_summary.sh` | TASK §11 / UX §3 | 交付摘要 |

本地产物统一落 `scripts/ai/.out/<task-id>/`（已加入 `.gitignore`，不入库）。

---

## 5. 状态门与人工确认速查

| 状态 | 必须人工确认 | 可代执行方 |
|------|------------|-----------|
| REQUIREMENT_READY | 确认 PRD | WorkBuddy |
| PLAN_READY | **批准 plan** | CodeBuddy 调 Codex 只读 |
| APPROVED_DEV | review Prompt | CodeBuddy 准备入口 |
| CODING | 真实写入/发送授权 | CodeBuddy 调 Codex |
| TESTING | 真实 smoke 授权 | CodeBuddy 跑测试 |
| DELIVERY_READY | **最终 review / merge / deploy** | WorkBuddy 出报告 |
| FAILED | 回滚/重规划/放弃决策 | CodeBuddy 回滚（授权后） |

---

> 本 SOP 与工作站基线 Baseline v1.0（2026-07-09）严格一致。任何流程调整须经你确认并更新 `STATION_CONFIG.md`。
