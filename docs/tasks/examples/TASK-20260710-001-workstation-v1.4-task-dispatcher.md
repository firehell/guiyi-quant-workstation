# TASK-20260710-001：WORKSTATION-V1.4 单项目受控任务调度器

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-20260710-001-workstation-v1.4-task-dispatcher |
| GitHub Issue | 待创建 |
| Branch | feature/workstation-v1.3-codebuddy-daemon |
| PR | — |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-10 |
| Updated At | 2026-07-10 |
| Owner | zhangzhao |

## 1. 任务状态
REQUIREMENT_READY

## 2. 任务类型
AI 工作流优化

## 3. 参与角色
- 必须：量化架构师（状态机+门控设计）、开发负责人（脚本实现）、安全专家（护栏审查）
- 可选：QA 工程师（测试验证）
- 不需要：PM/PO（需求已明确）

## 4. 背景
V1.1-V1.2 建立了本地规程化流水线 + GitHub Issue 留痕，但流程由 WorkBuddy/CodeBuddy 外部驱动，缺少统一调度入口。存在以下问题：
- **无锁机制**：scripts/ai/ 中无任何并发保护，并发 dev 会冲突
- **双输出路径**：`scripts/ai/.out/` 和 `.ai/results/` 存放相同产物
- **无审批记录**：approve-plan 仅靠外部对话确认，无本地持久化
- **无幂等保障**：重复 plan 可能覆盖结果，重复 dev 无记录
- **无中断恢复**：pause/resume/cancel 机制缺失

## 5. 目标
1. 创建 `dispatch_task <task_id> <action>` 统一调度入口，支持 validate/plan/approve-plan/dev/test/collect/pause/resume/cancel/status 共 10 个 action
2. 实现任务锁机制（仅一个写任务同时执行）
3. 实现本地审批记录持久化（`.ai/approvals/<TASK_ID>/approval.json`）
4. 实现状态机门控：每个 action 必须通过前置 Gate 才可执行
5. 统一产物路径到 `.ai/results/<TASK_ID>/`
6. 实现 pause/resume/cancel 中断恢复机制
7. 外部操作（Issue 评论/Label 更新）默认 dry-run
8. 产出状态机文档和故障处理手册

## 6. 不做事项
- 不自动批准 Plan
- 不连续自动多任务执行
- 不自动 push/merge/deploy
- 不修改业务代码测试调度器
- 不做多项目队列
- 不接 n8n/GitHub webhook 自动触发
- 不合并 scripts/ai/.out/ 和 .ai/results/ 的现有历史产物

## 7. 涉及模块

**允许修改：**
| 文件 | 类型 |
|------|------|
| `scripts/ai/dispatch_task.sh` | 新增，核心调度入口 |
| `scripts/ai/_gate_lib.sh` | 新增，门控函数库 |
| `scripts/ai/_state_lib.sh` | 新增，状态机函数库 |
| `scripts/ai/_lock_lib.sh` | 新增，锁机制函数库 |
| `scripts/ai/_approval_lib.sh` | 新增，审批记录函数库 |
| `docs/workflows/status_machine.md` | 更新，V1.4 状态机 |
| `docs/workflows/ai_delivery_workflow.md` | 更新，补充 dispatcher SOP |
| `docs/workflows/dispatcher_fault_handling.md` | 新增，故障处理手册 |
| `CODEBUDDY.md` | 更新，增加 dispatcher 使用指引 |
| `.gitignore` | 更新，增加 .ai/approvals/ 和 .run/dispatch/ |

**禁止修改：** .env/.env.*、data/、services/、apps/、vn.py 源码、现有 scripts/ai/ 核心脚本逻辑

## 8. 产品需求

### 8.1 统一调度入口
`dispatch_task <task_id> <action> [--force] [--confirm-issue-ops]`

### 8.2 支持动作（10 个）
| Action | 描述 |
|--------|------|
| validate | 验证 TASK 合法性（G1-G4） |
| plan | 调 codex_plan.sh 产出 plan |
| approve-plan | 写审批记录，状态推进 |
| dev | 获取锁，调 codex_dev.sh |
| test | 调 run_tests.sh |
| collect | 调 collect_result.sh |
| pause | 释放锁，记录暂停点 |
| resume | 恢复到暂停前状态 |
| cancel | 释放锁，标记取消 |
| status | 只读查询 |

### 8.3 Mandatory Gates（6 个）
| Gate | 检查内容 |
|------|----------|
| G1 | TASK 文件存在 |
| G2 | 元信息格式合法（含 ## 0. 元信息 + Task ID + Status） |
| G3 | GitHub Issue 已绑定（#N 格式） |
| G4 | 当前 git 分支匹配 TASK 元信息中的 Branch |
| G5 | plan_result.md 存在 |
| G6 | approval.json 存在 + plan hash 匹配 |

### 8.4 幂等性规则
- 重复 plan：不覆盖已有结果（除非 --force）
- 重复 dev：提示已有执行记录并拒绝（除非 --force）
- 重复 test：允许，作为新一次 test attempt
- 重复 collect：不生成冲突结果包（除非 --force）
- cancel 后不能继续 dev，除非显式 resume/replan

### 8.5 任务锁
- 复用 PID 模式（参考 dev-down.sh），使用 `.run/dispatch/` 三文件组合
- 同一时间只允许一个写任务
- 不允许不同 TASK 共用结果目录
- 不允许跨分支错误执行

### 8.6 审批记录
- 本地记录审批时间、阶段和 task_id（`.ai/approvals/<TASK_ID>/approval.json`）
- 不记录敏感内容
- 审批只对当前 TASK、当前 Plan 和当前 commit 有效
- Plan 变化后旧审批自动失效（SHA256 hash 检测）

### 8.7 外部操作
- Issue 评论和 Label 更新默认 dry-run
- 必须显式传入 --confirm-issue-ops 才实际执行
- push、merge、deploy 始终不属于调度器能力

## 9. 量化业务规则
不涉及（纯工具链任务）。

## 10. 数据影响
- 无 RQData/Parquet/PostgreSQL 变更
- 新增运行时目录：`.ai/approvals/`、`.run/dispatch/`（不入库）

## 11. 技术方案

### 11.1 核心架构
1 个主脚本 + 4 个 lib 文件，子命令分发模式：

```
dispatch_task.sh
  ├── do_validate()     → Gate G1-G4 全通过
  ├── do_plan()         → Gate G1-G5 + codex_plan.sh
  ├── do_approve_plan() → Gate G1-G5 + 写审批记录
  ├── do_dev()          → Gate G1-G6 + 获取锁 + codex_dev.sh
  ├── do_test()         → Gate G1-G4 + 锁持有 + run_tests.sh
  ├── do_collect()      → Gate G1-G4 + collect_result.sh
  ├── do_pause()        → 释放锁 + 记录暂停点
  ├── do_resume()       → Gate G1-G4 + 审批有效 + 重获锁
  ├── do_cancel()       → 释放锁 + → CANCELLED
  ├── do_status()       → 只读查询
  └── (Issue同步)       → dry-run默认，--confirm-issue-ops才实际执行
```

### 11.2 锁机制
参考 `scripts/dev-down.sh` PID 模式（kill -0 + SIGTERM→SIGKILL），使用 `.run/dispatch/` 三文件组合：
- `dispatch.lock`：持有者 TASK_ID
- `dispatch.pid`：持有者 PID
- `dispatch.timestamp`：获取时间

### 11.3 审批记录格式
```json
{
  "task_id": "TASK-20260710-001-workstation-v1.4-task-dispatcher",
  "stage": "approve-plan",
  "approved_at": "2026-07-10T14:30:00",
  "plan_hash": "sha256:abc123def456...",
  "plan_file": ".ai/results/TASK-.../plan_result.md",
  "approved_by": "human",
  "commit_hash": "a1b2c3d",
  "branch": "feature/workstation-v1.3-codebuddy-daemon"
}
```

### 11.4 Plan 变更检测
审批记录绑定 plan.md 的 SHA256 hash。dev 前比对当前 hash 与审批 hash，不匹配则拒绝。

### 11.5 产物路径统一
dispatch 调用现有脚本后，将产物从 `scripts/ai/.out/` 复制到 `.ai/results/`（用 `cp -n` 不覆盖）。

### 11.6 退出码约定
| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | Gate/转换失败 |
| 2 | 参数错误 |
| 3 | 锁冲突 |
| 4 | 文件不存在 |
| 5 | 幂等拒绝（重复操作） |
| 6 | 外部操作 dry-run 提示（非错误） |

## 12. 交互视觉要求
不涉及（CLI 工具）。

## 13. 安全权限要求
- 不碰 .env/token/webhook
- 不自动 push/merge/deploy
- 外部操作默认 dry-run
- 审批记录不含敏感内容
- 退出码约定：0=成功 1=Gate失败 2=参数错误 3=锁冲突 4=文件不存在 5=幂等拒绝 6=dry-run提示

## 14. 开发步骤
1. 创建分支 `feature/workstation-v1.3-codebuddy-daemon`
2. 实现 `_gate_lib.sh`（G1-G6 6 个 Gate 函数）
3. 实现 `_state_lib.sh`（状态读取/写入/转换验证）
4. 实现 `_lock_lib.sh`（基于 .run/dispatch/ 的 PID 锁）
5. 实现 `_approval_lib.sh`（审批记录读写/Plan hash 检测）
6. 实现 `dispatch_task.sh`（10 个子命令 + Gate 串联 + Issue dry-run）
7. 统一产物路径（dispatch 调后复制到 .ai/results/）
8. 编写状态机文档更新 + 故障处理手册
9. 编写测试 fixture + 测试脚本
10. E2E drill（仅修改 workstation fixtures）
（每步标注是否需用户显式授权：步骤 6-10 需确认后才执行 dev/test/collect）

## 15. Codex Plan Prompt
```
你是 Codex，在归一量化工作站仓库中执行只读 Plan。

必读（按顺序）：
1. AGENTS.md
2. CODEBUDDY.md
3. docs/workflows/status_machine.md
4. docs/workflows/ai_delivery_workflow.md
5. docs/workflows/github_issue_trace_workflow.md
6. scripts/dev-down.sh（PID管理模式参考）
7. scripts/dev-status.sh（PID检测参考）
8. scripts/ai/codex_plan.sh、codex_dev.sh、run_tests.sh、collect_result.sh、update_issue_status.sh、comment_issue_result.sh（现有脚本契约）
9. 本任务单全文

任务：V1.4 受控任务调度器 — dispatch_task.sh

只读，不修改任何文件。输出以下 8 项：

1. 理解摘要：V1.3 基础设施分析（现有脚本契约、锁缺失、双路径、无编排）
2. 拟修改文件列表（精确路径，区分新增/修改）
3. 实现架构设计：
   a. dispatch_task.sh 的子命令分发结构（含参数解析）
   b. _gate_lib.sh 的 6 个 Gate 函数签名与逻辑
   c. _state_lib.sh 的状态读取/写入/转换验证 + 合法转换表
   d. _lock_lib.sh 的锁获取/释放/stale检测（参考 dev-down.sh PID 模式）
   e. _approval_lib.sh 的审批记录格式与 Plan 变更检测（SHA256 hash）
4. 状态转换表：正向 8 条 + 失败/中断 9 条 + 禁止 10 条
5. 幂等性规则：10 个 action 的幂等行为 + --force 行为
6. 外部操作 dry-run 方案：默认不执行 gh，--confirm-issue-ops 才执行
7. 测试 fixture 设计：3 个 fixture 任务单 + 测试脚本结构
8. 风险点与缓解措施

确认条款：
- 不触碰 data/、.env、业务代码
- 不修改现有 scripts/ai/ 核心脚本逻辑（仅新增文件）
- Issue Gate：无 Issue 不开发
- 审批铁律：无审批不 Dev
```

## 16. Codex Dev Prompt
```
你是 Codex，在归一量化工作站仓库中执行 V1.4 开发。

必读：AGENTS.md、CODEBUDDY.md、本任务单、Plan 输出。

任务：实现 V1.4 受控任务调度器（dispatch_task.sh + 4 个 lib + 文档，不碰业务代码）

允许修改：scripts/ai/dispatch_task.sh、_gate_lib.sh、_state_lib.sh、_lock_lib.sh、_approval_lib.sh、docs/workflows/、CODEBUDDY.md

禁止修改：.env、data/、services/、apps/、vn.py 源码、现有 scripts/ai/ 核心脚本逻辑

要求：
- 按开发步骤逐个创建文件
- 每个脚本 bash -n 语法验证
- 所有 Gate 有明确错误消息和退出码
- 不 push、merge、deploy
- 不自动 close Issue
- 完成后列出变更文件与测试命令
```

## 17. CodeBuddy 执行 Prompt
```
你是 CodeBuddy，在本地仓库执行 V1.4 调度器开发。

前置确认：
1. 当前分支 = feature/workstation-v1.3-codebuddy-daemon
2. Issue 已绑定（Issue Gate 通过）
3. Plan 已获人工批准

执行：
1. 按开发步骤逐个创建脚本文件
2. 每个脚本 bash -n 验证语法
3. 创建测试 fixture 目录
4. 用 fixture 执行 dispatch_task validate/status 正向/反向
5. 不 push / merge / deploy
```

## 18. 测试清单

### 18.1 状态转换正向测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T01 | validate 有效任务单 | AC1 | exit 0，输出合法 |
| T02 | plan 从 REQUIREMENT_READY | AC2 | exit 0，状态→PLAN_READY，plan.md生成 |
| T03 | approve-plan 从 PLAN_READY | AC3 | exit 0，审批记录写入，状态→APPROVED_DEV |
| T04 | dev 从 APPROVED_DEV | AC3 | exit 0，获取锁，状态→CODING |
| T05 | test 从 CODING(dev完成后) | AC2 | exit 0，状态→TESTING |
| T06 | collect 从 TESTING | AC1 | exit 0，result_bundle生成 |
| T07 | status 查询 | AC5 | exit 0，输出状态+锁+审批信息 |

### 18.2 状态转换反向测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T08 | 无TASK文件 → validate | AC2 | exit 1，报"G1: TASK文件不存在" |
| T09 | 无元信息 → validate | AC2 | exit 1，报"G2: 元信息格式不合法" |
| T10 | 无Issue绑定 → plan | AC2 | exit 1，报"G3: Issue Gate — GitHub Issue未绑定" |
| T11 | Branch不匹配 → dev | AC2 | exit 1，报"G4: Branch Gate不匹配" |
| T12 | 无Plan → dev | AC3 | exit 1，报"需先plan" |
| T13 | 无审批 → dev | AC3 | exit 1，报"G6: 审批记录不存在" |
| T14 | Plan变更 → 旧审批失效 | AC3 | exit 1，报"plan hash与审批不匹配" |
| T15 | 从PLAN_READY直接dev | AC3 | exit 1，报"需先approve-plan" |
| T16 | 从FAILED直接dev | AC3 | exit 1，报"需先replan" |

### 18.3 锁机制测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T17 | 并发锁冲突 | AC4 | 第二个dispatch exit 3，报"锁被TASK-X持有" |
| T18 | 锁stale检测 | AC5 | PID已死，自动清理锁，继续 |
| T19 | cancel释放锁 | AC5 | 锁文件删除，状态→CANCELLED |
| T20 | pause释放锁 | AC5 | 锁文件删除，状态→PAUSED |

### 18.4 中断恢复测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T21 | pause后resume | AC5 | 状态恢复到暂停前，重新获取锁 |
| T22 | cancel后resume被拒绝 | AC6 | exit 1，报"已取消，需replan" |
| T23 | resume时审批仍有效 | AC5 | 不需重新审批，直接继续dev |

### 18.5 幂等性测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T24 | 重复plan | AC6 | warn"plan已存在"，不覆盖(除非--force) |
| T25 | 重复dev | AC6 | warn"已有执行记录"，拒绝(除非--force) |
| T26 | 重复test | AC6 | 允许，作为新测试尝试 |
| T27 | 重复collect | AC6 | warn"bundle已存在"，不覆盖(除非--force) |
| T28 | cancel后继续dev | AC6 | exit 1，报"需显式resume/replan" |

### 18.6 外部操作 dry-run 测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T29 | update_issue_status 默认dry-run | AC7 | 不调gh，只打印拟执行操作 |
| T30 | comment_issue_result 默认dry-run | AC7 | 同上 |
| T31 | --confirm-issue-ops显式执行 | AC7 | 实际调gh执行 |

### 18.7 安全边界测试
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T32 | dispatch不含push/merge/deploy | AC8 | 无对应子命令 |
| T33 | 审批记录不含敏感内容 | AC7 | 只含task_id/时间/hash/阶段/commit |
| T34 | git diff --check | AC10 | 无冲突标记 |

### 18.8 E2E 演练
| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T35 | 完整E2E drill | AC10 | 仅修改workstation fixture，跑完全流程 |

## 19. 验收标准
1. 一条入口可以安全调用既有工作站脚本
2. 所有状态迁移均受 Gate 控制
3. 没有审批不能 Dev
4. 同一时间只有一个写任务
5. 中断后可以从已确认状态恢复
6. 重复命令不会造成重复开发或状态污染
7. 外部操作默认 dry-run
8. 不具备 push、merge、deploy 能力
9. 输出调度状态机文档和故障处理手册
10. 完成一次仅修改工作站 fixture 的 E2E 演练

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| P1 | 锁文件 stale（进程异常退出） | 锁含 PID + timestamp，dispatch 启动检测 PID alive |
| P1 | 状态写入与实际执行不一致 | dispatch 脚本前后原子更新状态 |
| P2 | Plan hash 检测误判 | 使用 SHA256（shasum -a 256），与审批记录绑定 hash 比较 |
| P2 | 双输出路径遗留产物 | dispatch 新调用走统一路径；旧产物不迁移 |
| P2 | 并发终端竞争 | 锁基于 PID 文件；单写入限制 |

## 21. 交付记录
- 状态流转：REQUIREMENT_READY → PLAN_READY → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → CLOSED
- 测试结论：pass / block
- 交付报告：链接/摘要
- 合并前检查：git diff --check / 测试通过 / 无敏感泄露
- 用户 review：待/已 merge/已 deploy
- 下一阶段建议：V1.5 CodeBuddy daemon 常驻
