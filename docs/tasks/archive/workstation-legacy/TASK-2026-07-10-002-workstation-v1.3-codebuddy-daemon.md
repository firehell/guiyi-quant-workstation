# TASK-2026-07-10-002：WORKSTATION-V1.3 CodeBuddy 单项目常驻控制器

> 团队：归一量化产品与交付工作站
> 状态：REQUIREMENT_READY
> 任务类型：AI 工作流优化（CodeBuddy 常驻稳定化）
> 生成：WorkBuddy（按 `STATE_MACHINE_TICKET.md` 21 字段模板 + V1.2 `## 0. 元信息` 扩展）
> 配套：STATION_CONFIG.md（Final v1.0）、COLLAB_PROTOCOL.md、SECURITY_HANDBOOK.md、MACMINI_OPS_MANUAL.md、CODEBUDDY.md
> 性质：**CodeBuddy 常驻控制器实现任务**——设计并落地单项目 daemon 进程，提供稳定在线、状态查询、任务锁、心跳和异常恢复能力。不自动调用 Codex Plan/Dev，不实现任务队列，不支持多项目。

> **状态门控说明**：本任务单当前处于 `REQUIREMENT_READY`。第 15–17 节的 Prompt 是草案，按状态机规则：Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 喂给 `codex_plan.sh` 执行（只读）；Dev Prompt 在 `APPROVED_DEV` 才启用。**WorkBuddy 本次只产出本任务单文档，不修改代码、不执行任何脚本。**

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon |
| GitHub Issue | 待创建 |
| Branch | feature/workstation-v1.3-codebuddy-daemon |
| PR | 待创建 |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-10 |
| Updated At | 2026-07-10 |
| Owner | WorkBuddy |

---

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

AI 工作流优化（CodeBuddy 常驻稳定化）
- 关联：V1.1 开发规程建立、V1.2 GitHub Issue 留痕、V1.2.1 基线收口
- 参照：TASK_MATRIX.md「12. AI 工作流优化」「13. CodeBuddy / Codex / WorkBuddy 协作优化」
- 前置依赖：V1.2.1 完成收口验收（scripts/ai/ 脚本基线稳定）
- 是否允许进入代码开发阶段：**是**（严格限定 `scripts/ai/`、`docs/operations/`、`docs/workflows/`、`CODEBUDDY.md`、`.gitignore`；不碰业务/数据/策略/配置）

## 3. 参与角色

- **必须**：
  - 项目经理 / 流程调度员（编号、状态、拆分、卡点检查）
  - 后端开发负责人（daemon 脚本设计与实现、三类 Prompt）
  - 测试专家 / QA Lead（start/stop/status/锁冲突/recovery 测试、脱敏验证）
  - 安全与权限专家（护栏自检、脱敏审核、deny-list 确认）
  - DevOps / 本地运维部署专家（PID 管理、launchd 模板、Mac mini 落地指导）
  - 交付专家（验收报告、运行手册、恢复手册、V1.3 交付报告）
- **可选**：
  - 量化架构师（评审 daemon 架构边界与项目约束）
- **不需要**：
  - 产品负责人（无新用户场景，纯基础设施）
  - 量化业务专家（非数据/行情/交易日任务）
  - 策略研究员（非策略逻辑）
  - 数据工程师（非 RQData/聚合）
  - 交互视觉专家（无 Dashboard / 页面设计）

## 4. 背景

- V1.1（工作站脚本脚手架）已完成 `scripts/ai/` 下 5 个核心脚本的落地。
- V1.2（GitHub Issue 留痕）已完成 TASK ↔ Issue 双向同步机制。
- V1.2.1（基线收口）正在进行中，完成后 scripts/ai/ 脚本将处于稳定基线。
- **当前痛点**：CodeBuddy 仍依赖人工在终端手动启动，缺少：
  - 稳定的在线状态（是否在运行？PID 是什么？）
  - 结构化状态查询（当前任务？阶段？等待审批？）
  - 写任务互斥锁（防止两个 Dev 同时进行破坏仓库）
  - 异常恢复机制（进程崩了，锁还在，怎么清理？）
- V1.3 目标：补齐 CodeBuddy 常驻能力，让 CodeBuddy 可以"启动即在线，等待指令"，为后续 V1.4+ 的自动 dispatch 和调度打下基础。

## 5. 目标

1. **设计并实现单项目 CodeBuddy 常驻控制器**：PID 管理、启动/停止/重启/状态查询、心跳
2. **实现单项目写任务锁**：同一时间最多一个可写任务，锁文件含 task_id/pid/branch/started_at，进程失效后进入 recovery 而非静默删除
3. **实现状态文件**：daemon 状态、当前 task_id、当前阶段、当前分支、最近 heartbeat、最近错误类型、是否等待审批（不含 token/webhook/敏感日志）
4. **实现命令入口**：`daemon.sh {start|stop|restart|status|heartbeat|current-task|recover}`
5. **实现结构化日志与脱敏**：日志轮转设计、敏感字段脱敏、不记录 Prompt 中的密钥和 .env 内容
6. **生成 launchd 模板、安装说明和验收脚本**：不自动写入或加载用户 LaunchAgents
7. **产出运行手册、恢复手册和 V1.3 交付报告**

## 6. 不做事项

- ❌ 不自动执行 Codex Plan / Dev（V1.3 只解决"稳定在线和等待指令"）
- ❌ 不实现任务队列
- ❌ 不自动更新 GitHub Issue
- ❌ 不发送企业微信
- ❌ 不自动 push / merge / deploy
- ❌ 不支持多项目、多仓库和多 Codex 并发
- ❌ 不支持多个写任务并发
- ❌ 不自动写入或加载用户 LaunchAgents（仅生成模板和说明）
- ❌ 不修改归一量化业务代码（`services/`、`apps/`、`packages/`、`strategies/`）
- ❌ 不修改 `data/` 下的任何文件
- ❌ 不修改 `.env` / `.env.*` / token / webhook / 密钥
- ❌ 不删除任何历史数据

## 7. 涉及模块

- **允许修改/新增**：
  - `scripts/ai/daemon.sh` — 主控制器脚本（新增）
  - `scripts/ai/lib/daemon_lib.sh` — 共享函数库（新增）
  - `scripts/ai/com.guiyi.codebuddy-daemon.plist.template` — launchd 模板（新增）
  - `scripts/ai/install_daemon_launchd.sh` — 安装说明脚本（新增）
  - `scripts/ai/verify_daemon.sh` — daemon 验收脚本（新增）
  - `scripts/ai/.daemon/` 目录（运行时产物，新增；`.gitignore` 管理）
  - `docs/operations/DAEMON_OPS_MANUAL.md` — 运行手册（新增）
  - `docs/operations/DAEMON_RECOVERY_MANUAL.md` — 恢复手册（新增）
  - `docs/tasks/examples/V1.3-ACCEPTANCE.md` — 验收报告（新增）
  - `CODEBUDDY.md` — 新增 daemon 章节（修改）
  - `docs/workflows/ai_delivery_workflow.md` — 新增 daemon 状态查询步骤（修改）
  - `.gitignore` — 追加 `.daemon/status.json` 等（修改）
- **禁止修改**：
  - `services/`（全部）
  - `apps/`（全部）
  - `packages/`（全部）
  - `data/`（全部）
  - `strategies/`（全部）
  - `.env` / `.env.*`
  - 密钥、webhook、token 文件
  - `scripts/ai/codex_plan.sh`、`codex_dev.sh`、`run_tests.sh`、`collect_result.sh`（V1.1/V1.2 基线脚本，本次不修改）

## 8. 产品需求

- 作为 Mac mini 运维者，我需要通过 `daemon.sh status` 快速查看 CodeBuddy 是否在线、当前任务是什么、处于什么阶段
- 作为开发者，我启动一个 Dev 任务时需要确保没有其他写任务在运行（锁冲突保护）
- 作为流程管理者，我需要知道 daemon 是否异常退出、是否需要 recovery
- 作为安全负责人，状态文件和日志绝对不能包含 token、webhook 或 .env 内容

**功能清单**：
1. `daemon.sh start` — 启动 daemon，校验仓库路径和 Git 根目录，防重复启动
2. `daemon.sh stop` — 优雅停止（SIGTERM → SIGKILL 超时回退），清理 PID 文件
3. `daemon.sh restart` — stop + start
4. `daemon.sh status` — 结构化输出 daemon 状态（在线/离线、PID、运行时长、当前任务、阶段、分支、是否等待审批）
5. `daemon.sh heartbeat` — 更新心跳时间，超时阈值可配置
6. `daemon.sh current-task` — 输出当前锁文件中的任务信息
7. `daemon.sh recover` — 检查锁文件对应的进程是否存活，若已死则标记为 RECOVERY_NEEDED 状态，不静默删除锁

## 9. 量化业务规则

- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）
- daemon 配置项中不包含任何交易参数、行情参数或策略参数

## 10. 数据影响

- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据
- 运行时产物（lock/status/logs）统一落在 `scripts/ai/.daemon/`，不进入数据目录
- `.daemon/` 目录加入 `.gitignore`，不入库

## 11. 技术方案

### 11.1 整体架构

```
scripts/ai/daemon.sh          ← 命令入口（用户/CodeBuddy 调用）
       │
       └── source scripts/ai/lib/daemon_lib.sh   ← 共享函数库
                    │
                    ├── 项目管理（校验仓库/Git/配置）
                    ├── 进程管理（start/stop/restart/status）
                    ├── 锁管理（获取/释放/检测/恢复）
                    ├── 状态文件读写
                    ├── 心跳更新
                    └── 日志与脱敏

scripts/ai/.daemon/           ← 运行时产物目录（不入库）
       ├── daemon.pid          ← PID 文件
       ├── status.json         ← daemon 状态
       ├── task.lock           ← 写任务锁
       └── logs/               ← 结构化日志（轮转）
```

### 11.2 daemon_lib.sh 共享函数库

函数清单：

| 函数名 | 功能 | 说明 |
|--------|------|------|
| `validate_project()` | 校验仓库路径、Git 根目录、STATION_CONFIG 存在 | start 时调用，失败拒绝启动 |
| `is_daemon_running()` | 检查 PID 文件是否存在且进程存活 | 所有命令的前置检查 |
| `acquire_lock()` | 获取写任务锁 | 记录 task_id/pid/branch/started_at/phase |
| `release_lock()` | 释放写任务锁 | stop/recover 时调用 |
| `check_lock()` | 检查锁状态（是否被占用、占用进程是否存活） | 返回 JSON |
| `read_status()` | 读取 status.json | |
| `write_status()` | 写入 status.json | 自动脱敏 |
| `update_heartbeat()` | 更新心跳时间戳 | |
| `check_heartbeat_timeout()` | 检查心跳是否超时 | 默认阈值 300s |
| `log_event()` | 写入结构化日志 | JSON 行格式 |
| `sanitize()` | 脱敏函数 | 移除 token/webhook/key/secret 模式 |
| `rotate_logs()` | 日志轮转 | 按大小/天数，默认保留 10 个文件 |

### 11.3 状态文件设计 (status.json)

```json
{
  "daemon": {
    "pid": 12345,
    "status": "running",
    "started_at": "2026-07-10T14:00:00+08:00",
    "uptime_seconds": 3600
  },
  "current_task": {
    "task_id": "TASK-2026-07-10-002",
    "phase": "CODING",
    "branch": "feature/workstation-v1.3-codebuddy-daemon",
    "started_at": "2026-07-10T14:30:00+08:00",
    "waiting_approval": false
  },
  "heartbeat": {
    "last_at": "2026-07-10T15:00:00+08:00",
    "timeout_seconds": 300
  },
  "last_error": {
    "type": "LOCK_CONFLICT",
    "at": "2026-07-10T14:25:00+08:00",
    "message": "Write lock held by task TASK-001, pid 12340"
  },
  "recovery": {
    "needed": false,
    "stale_lock_task_id": null,
    "stale_lock_pid": null
  }
}
```

**硬约束**：不得包含 token、webhook、完整敏感日志、.env 内容、密钥值。

### 11.4 锁文件设计 (task.lock)

```json
{
  "task_id": "TASK-2026-07-10-002",
  "pid": 12345,
  "branch": "feature/workstation-v1.3-codebuddy-daemon",
  "phase": "CODING",
  "started_at": "2026-07-10T14:30:00+08:00",
  "write_permission": true
}
```

**锁规则**：
- `write_permission=true` 时禁止任何其他 write_permission=true 的锁
- `write_permission=false`（Plan 只读任务）可以共存，但只查询状态不写锁
- 进程失效后**不静默删除锁**，进入 recovery 状态
- recovery 状态可通过 `daemon.sh recover` 手动处理

### 11.5 日志设计

- 格式：JSON 行（每行一个 JSON 对象）
- 路径：`scripts/ai/.daemon/logs/daemon_YYYY-MM-DD.log`
- 轮转：按天 + 按大小（超过 10MB 截断），保留最近 30 天
- 脱敏规则：写入日志前对内容调用 `sanitize()`，过滤 token/webhook/key/secret/bearer 等模式
- 不记录：Prompt 完整内容、.env 内容、密钥值

### 11.6 launchd 模板

文件：`scripts/ai/com.guiyi.codebuddy-daemon.plist.template`

- 包含占位符 `{{PROJECT_PATH}}`、`{{USER_NAME}}`
- 安装脚本 `install_daemon_launchd.sh` 生成实际 plist 但**不自动加载**
- 实际 `launchctl load` 必须由用户确认后人工执行

### 11.7 daemon.sh 命令入口

| 命令 | 退出码 | 说明 |
|------|--------|------|
| `start` | 0/1/2 | 0=成功, 1=已在运行, 2=配置错误 |
| `stop` | 0/1 | 0=成功, 1=未在运行 |
| `restart` | 0/1 | stop + start |
| `status` | 0/1/2 | 0=在线, 1=离线, 2=异常(recovery) |
| `heartbeat` | 0/1 | 0=更新成功, 1=daemon 未运行 |
| `current-task` | 0/1 | 输出 JSON, 1=无任务 |
| `recover` | 0/1/2 | 0=恢复成功, 1=无需恢复, 2=需要人工介入 |

### 11.8 启动校验流程

`daemon.sh start` 执行以下校验：
1. 检查是否已有 daemon 在运行（PID 文件 + 进程存活检查）
2. 校验 `PROJECT_PATH` 配置（从 STATION_CONFIG.md 或环境变量读取）
3. 校验 Git 根目录 = PROJECT_PATH
4. 校验 `workstation/STATION_CONFIG.md` 存在
5. 校验项目名称 = `guiyi-quant-workstation`
6. 校验通过后写入 PID、fork 后台进程、启动心跳循环

### 11.9 优雅退出流程

收到 SIGTERM：
1. 停止心跳循环
2. 释放当前持有的锁（如有）
3. 写入 daemon 状态为 "stopping"
4. 清理 PID 文件
5. 正常退出

SIGTERM 超时（默认 10s）后发送 SIGKILL。

### 11.10 异常退出处理

- 异常退出时将退出码和原因写入 status.json 的 `last_error` 字段
- 如果持有锁文件，不自动删除，标记 `recovery.needed = true`
- 下次启动时检测到残留锁文件，输出警告并建议运行 `recover` 命令

## 12. 交互视觉要求

- `daemon.sh status` 输出人类可读的结构化文本（非裸 JSON）
- `daemon.sh status --json` 输出机器可读 JSON
- `daemon.sh current-task` 输出紧凑的当前任务信息
- 日志格式：`[2026-07-10T15:00:00+08:00] [INFO] daemon started, pid=12345`
- 错误输出使用 `[ERROR]` 前缀，带明确错误码和修复建议

## 13. 安全权限要求

- ❌ 状态文件和日志不得包含 token、webhook、密码、密钥、secret、api_key、access_key
- ❌ 日志不记录 Prompt 完整内容
- ❌ 不读取或记录 .env 内容
- ❌ 不自动 git push / merge / deploy
- ❌ 不自动加载 launchd（仅生成模板）
- ❌ 不修改 `.env` / `.env.*` / token / webhook / RQData 密钥
- ✅ `sanitize()` 函数对所有日志和状态输出做脱敏
- ✅ launchd 模板使用占位符，不硬编码路径
- ✅ `.daemon/` 目录加入 `.gitignore`

## 14. 开发步骤

> 每步标注是否需用户显式授权

### Step 1: 创建目录结构和基础文件（需授权后才写入）

- 1.1 创建 `scripts/ai/.daemon/` 目录和 `scripts/ai/.daemon/logs/` 子目录
- 1.2 更新 `.gitignore`：追加 `.daemon/status.json`、`.daemon/task.lock`、`.daemon/logs/`、`.daemon/daemon.pid`
- 1.3 验证 `.gitignore` 正确：`git status` 不显示 `.daemon/` 内文件

### Step 2: 实现 daemon_lib.sh 共享函数库（需授权后才写入）

- 2.1 创建 `scripts/ai/lib/daemon_lib.sh`
- 2.2 实现所有共享函数（validate_project / is_daemon_running / lock 管理 / 状态读写 / 心跳 / 日志 / 脱敏）
- 2.3 `bash -n` 语法检查通过

### Step 3: 实现 daemon.sh 主控制器（需授权后才写入）

- 3.1 创建 `scripts/ai/daemon.sh`
- 3.2 实现 7 个命令：start / stop / restart / status / heartbeat / current-task / recover
- 3.3 实现启动校验流程（仓库/Git/配置）
- 3.4 实现优雅退出（SIGTERM handler）
- 3.5 实现异常退出记录
- 3.6 `bash -n` 语法检查通过
- 3.7 `chmod +x` 授权

### Step 4: 生成 launchd 模板和安装说明（需授权后才写入）

- 4.1 创建 `scripts/ai/com.guiyi.codebuddy-daemon.plist.template`
- 4.2 创建 `scripts/ai/install_daemon_launchd.sh`（仅输出指令，不自动执行 `launchctl load`）
- 4.3 验证模板使用占位符（不硬编码路径）

### Step 5: 创建验收脚本（需授权后才写入）

- 5.1 创建 `scripts/ai/verify_daemon.sh`
- 5.2 覆盖测试场景：start/stop/status、重复启动保护、PID 失效检测、heartbeat 超时、写任务锁冲突、recovery 状态
- 5.3 `bash -n` 语法检查通过

### Step 6: 编写运行手册和恢复手册（需授权后才写入）

- 6.1 创建 `docs/operations/DAEMON_OPS_MANUAL.md`
- 6.2 创建 `docs/operations/DAEMON_RECOVERY_MANUAL.md`
- 6.3 内容覆盖：启动/停止/状态查询/锁管理/日志查看/异常恢复流程

### Step 7: 更新 CODEBUDDY.md 和工作流文档（需授权后才写入）

- 7.1 CODEBUDDY.md 新增 daemon 章节（命令入口、状态查询、锁检查流程）
- 7.2 `docs/workflows/ai_delivery_workflow.md` 新增 daemon 状态查询步骤

### Step 8: 验收测试（需授权后才执行）

- 8.1 `bash -n scripts/ai/daemon.sh scripts/ai/lib/daemon_lib.sh scripts/ai/verify_daemon.sh`
- 8.2 运行 `scripts/ai/verify_daemon.sh`，确认全部测试通过
- 8.3 `shellcheck` 扫描（环境可用时）
- 8.4 敏感信息扫描：确认无 token/webhook/key/secret 泄露
- 8.5 `git diff --check` 无异常空白
- 8.6 `git diff --stat` 仅含允许路径

## 15. Codex Plan Prompt

```
你现在是 Codex CLI，处于 plan（只读）模式。任务单见 tasks/TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon.md。

要求：
1. 只读取仓库与文档，不写任何业务代码（services/ packages/ apps/ 等既有文件不改）。
2. 仅可将 plan 文本写入 scripts/ai/.out/TASK-2026-07-10-002/plan.md（若该目录不存在先创建）。
3. 产出 plan.md，包含：

   ### A. 仓库现状核对
   - V1.1/V1.2 scripts/ai/ 脚本现状（列出全部文件、确认 bash -n 状态）
   - workstation/STATION_CONFIG.md 中与 daemon 相关的配置项核实
   - CODEBUDDY.md 当前结构分析（确定 daemon 章节插入位置）
   - docs/workflows/ai_delivery_workflow.md 当前结构（确定 daemon 步骤插入位置）
   - .gitignore 当前内容

   ### B. daemon 架构设计
   - daemon.sh 命令入口参数设计（7 个命令的完整参数表）
   - daemon_lib.sh 函数接口设计（每个函数的签名、参数、返回值、错误处理）
   - 进程生命周期设计（启动校验流程、后台运行方式、信号处理、退出流程）
   - PID 管理方案（文件位置、内容格式、重复检测逻辑）
   - 心跳机制设计（更新频率、超时阈值、超时后的行为）

   ### C. 锁机制设计
   - task.lock 文件格式（JSON schema）
   - 写锁互斥逻辑（读写锁区分、冲突检测算法）
   - recovery 状态转换图（进程失效 → 残留锁检测 → recovery 标记 → 人工处理）
   - 锁的自动释放场景（stop/正常退出）vs 不自动释放场景（异常退出）

   ### D. 状态文件设计
   - status.json 完整 JSON schema
   - 各字段更新时机和更新者
   - 敏感字段脱敏策略（在写入前脱敏 vs 读取时脱敏）

   ### E. 日志设计
   - 日志格式（JSON 行格式的完整字段定义）
   - 轮转策略（按天/按大小 的具体参数）
   - 脱敏策略（sanitize 函数的正则模式列表）

   ### F. launchd 模板设计
   - plist 模板的完整结构
   - 占位符列表和替换说明
   - 安装脚本的安全设计（不自动加载，只输出指令）

   ### G. 新增/改动文件清单
   - 分类列出新增文件、修改文件、不入库文件

   ### H. 测试方案
   - 验收脚本 verify_daemon.sh 的测试用例设计（至少覆盖 8 类场景）
   - 边界场景：PID 回收、磁盘满、权限不足、文件被外部删除

   ### I. 风险与待确认项
   - shellcheck 兼容性（bash 3.x vs 4.x vs 5.x 差异）
   - Mac mini 环境差异（/tmp 清理策略对 PID 文件的影响）
   - 与现有 CODEBUDDY.md 工作流的集成风险

4. 严格遵守：不碰业务代码/数据/策略/.env，不 git push/merge/deploy，不真实发送。

输出后等待用户确认 plan。
```

## 16. Codex Dev Prompt

```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 plan：scripts/ai/.out/TASK-2026-07-10-002/plan.md。

范围（严格限定，越界即中止）：
- 新建 scripts/ai/.daemon/ 目录 + logs/ 子目录
- 新建 scripts/ai/lib/daemon_lib.sh（共享函数库）
- 新建 scripts/ai/daemon.sh（主控制器）
- 新建 scripts/ai/com.guiyi.codebuddy-daemon.plist.template（launchd 模板）
- 新建 scripts/ai/install_daemon_launchd.sh（安装说明脚本）
- 新建 scripts/ai/verify_daemon.sh（验收脚本）
- 新建 docs/operations/DAEMON_OPS_MANUAL.md（运行手册）
- 新建 docs/operations/DAEMON_RECOVERY_MANUAL.md（恢复手册）
- 新建 docs/tasks/examples/V1.3-ACCEPTANCE.md（验收报告模板）
- 修改 .gitignore（追加 .daemon/ 相关条目）
- 修改 CODEBUDDY.md（新增 daemon 章节）
- 修改 docs/workflows/ai_delivery_workflow.md（新增 daemon 状态查询步骤）

禁止（硬约束）：
- 修改 services/、apps/、packages/、data/、strategies/ 下的任何文件
- 读取或写入 .env / token / webhook / RQData 密钥
- git push / merge / release / deploy
- 删除历史数据、rm -rf、全权限 mode
- 真实发送企业微信、自动交易
- 任何把密钥写入日志/payload/文档的行为
- 自动写入或加载 ~/Library/LaunchAgents/

完成后：
- bash -n scripts/ai/daemon.sh scripts/ai/lib/daemon_lib.sh scripts/ai/verify_daemon.sh scripts/ai/install_daemon_launchd.sh
- bash -n scripts/ai/*.sh（回归验证已有脚本不被破坏）
- shellcheck scripts/ai/daemon.sh scripts/ai/lib/daemon_lib.sh（环境可用时）
- 运行 scripts/ai/verify_daemon.sh 确认全部测试通过
- 敏感信息 grep 扫描确认无泄漏
- git diff --stat 供 review（仅含允许路径）
- 退出码 0 表示成功
```

## 17. CodeBuddy 执行 Prompt

```
CodeBuddy：请按协作协议（COLLAB_PROTOCOL.md）执行任务单 tasks/TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon.md。

前置条件：
- V1.2.1 收口已完成（scripts/ai/ 脚本基线稳定）
- 任务状态已推进到 APPROVED_DEV 且 plan 已批准

步骤：
1. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？自动加载 launchd？→ 中止并报安全专家。
2. 确认分支 feature/workstation-v1.3-codebuddy-daemon 已创建。
3. 读取 tasks/TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon.md 完整任务单。
4. 调用 scripts/ai/codex_plan.sh --task TASK-2026-07-10-002 生成 plan（若尚未生成）。
5. 经用户确认 plan 后，调用 scripts/ai/codex_dev.sh --task TASK-2026-07-10-002 --plan <plan> 实现。
6. 运行验收脚本：bash scripts/ai/verify_daemon.sh
7. 全脚本语法回归：bash -n scripts/ai/*.sh scripts/ai/lib/*.sh
8. 敏感信息扫描：grep -rE '(token|webhook|password|secret|api_key|access_key)' scripts/ai/daemon.sh scripts/ai/lib/daemon_lib.sh scripts/ai/.daemon/ --include='*.json' --include='*.log' 2>/dev/null；确认无泄露。
9. 调用 scripts/ai/collect_result.sh --task TASK-2026-07-10-002 汇总并脱敏。
10. 调用 scripts/ai/make_delivery_summary.sh --task TASK-2026-07-10-002 --bundle <result_bundle> 生成交付摘要。
11. 回传结果摘要给 WorkBuddy / 用户。不自动 push / merge / deploy。

特别提醒：V1.3 不自动启动 daemon、不自动 load launchd、不自动调用 Codex Dev。所有动作需用户显式执行或确认。
```

## 18. 测试清单

- [ ] `bash -n scripts/ai/lib/daemon_lib.sh` — 共享函数库语法检查（单元）
- [ ] `bash -n scripts/ai/daemon.sh` — 主控制器语法检查（单元）
- [ ] `bash -n scripts/ai/verify_daemon.sh` — 验收脚本语法检查（单元）
- [ ] `bash -n scripts/ai/install_daemon_launchd.sh` — 安装脚本语法检查（单元）
- [ ] `bash -n scripts/ai/*.sh` — 全脚本语法回归（回归，确认 V1.1/V1.2 脚本不被破坏）
- [ ] `shellcheck scripts/ai/daemon.sh scripts/ai/lib/daemon_lib.sh` — 静态分析（环境可用时）
- [ ] `daemon.sh start` 正常启动，写入 PID 文件，probe 进程存活（集成）
- [ ] `daemon.sh start` 重复启动被拒绝，退出码 1（防重复保护）
- [ ] `daemon.sh stop` 正常停止，清理 PID 文件，释放锁（集成）
- [ ] `daemon.sh status` 输出结构化状态（集成）
- [ ] `daemon.sh heartbeat` 更新心跳时间（集成）
- [ ] `daemon.sh current-task` 正确输出或无任务（集成）
- [ ] 写任务锁冲突：第二个 Dev 被拒绝（锁测试）
- [ ] PID 失效检测：模拟进程死亡，锁文件检测正确（recovery 前置）
- [ ] heartbeat 超时检测：超时后状态正确标记（超时测试）
- [ ] recovery 状态：进程失效后锁不静默删除，标记 recovery（恢复测试）
- [ ] `daemon.sh recover` 正确清理失效锁（恢复测试）
- [ ] 敏感信息脱敏验证——状态文件和日志不含 token/webhook/password/secret/key（安全）
- [ ] `.gitignore` 生效——`.daemon/status.json` 等不被 git track（配置验证）
- [ ] 启动校验——非 guiyi-quant-workstation 项目拒绝启动（配置验证）
- [ ] `git diff --check` 无异常空白（回归）
- [ ] `git diff --stat` 仅含允许路径（范围校验）
- [ ] launchd 模板使用占位符，不硬编码路径（安全）
- [ ] `install_daemon_launchd.sh` 仅输出指令，不自动执行 `launchctl`（安全）

## 19. 验收标准

**pass 条件**（全部满足）：

1. `daemon.sh start` 可稳定启动，`daemon.sh stop` 可稳定停止
2. 重复启动不会产生第二个实例（退出码 1）
3. `daemon.sh status` 不依赖进入运行终端即可查询
4. `daemon.sh heartbeat` 正常更新，心跳超时可被检测
5. 单写任务锁有效：第二个 Dev 被拒绝
6. 异常退出后进入可解释的 recovery 状态（锁文件不静默删除）
7. launchd 模板仅生成，不自动加载
8. 不修改归一量化业务代码（services/ apps/ packages/ data/ strategies/）
9. 不执行外部操作（不 push / merge / deploy / 发送消息 / 自动交易）
10. `docs/operations/DAEMON_OPS_MANUAL.md` 和 `docs/operations/DAEMON_RECOVERY_MANUAL.md` 已创建且内容完整
11. `docs/tasks/examples/V1.3-ACCEPTANCE.md` 验收报告已创建
12. 敏感信息扫描 0 匹配
13. `bash -n` 全部通过
14. `git diff --stat` 仅含允许路径

**block 条件**（任一即不通过）：

- 修改触及 `services/`、`apps/`、`packages/`、`data/`、`strategies/`、`.env`、密钥、webhook
- status.json 或日志文件含 token/webhook/password/secret/api_key
- 自动 push / merge / deploy
- 自动加载 launchd
- 含 `rm -rf` 或全权限 mode
- 重复启动保护失效
- 异常退出后锁被静默删除（而非进入 recovery）

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| P0 | daemon 异常退出后锁残留在下一个启动周期被静默删除 | 锁删除前必须检查持有进程是否存活，不存活则标记 recovery；`recover` 命令需人工执行 |
| P0 | 敏感信息泄漏到状态文件或日志 | `sanitize()` 函数对所有输出脱敏；安全专家审核脱敏正则；验收脚本验证 |
| P1 | Mac mini /tmp 被系统清理导致 PID 文件丢失 | PID 文件放在项目内 `scripts/ai/.daemon/` 而非 `/tmp` |
| P1 | bash 版本差异导致语法不兼容 | 使用 POSIX 兼容写法；shellcheck 扫描（环境可用时）；在 Mac mini 实际环境测试 |
| P1 | launchd 模板被误用（用户直接 load） | 模板使用占位符，不填写实际路径；安装脚本添加大段警告注释 |
| P2 | 磁盘满导致日志写入失败 | 日志轮转含大小上限；写入失败时不阻塞 daemon 运行，仅记录 stderr |
| P2 | 与其他任务修改 CODEBUDDY.md 冲突 | 本次修改限定在 CODEBUDDY.md 末尾新增 daemon 章节，最小化冲突面 |
| P2 | shellcheck 在 Mac mini 未安装 | shellcheck 测试标记为"环境可用时"可选，不阻塞验收 |

## 21. 交付记录

- **状态流转**：REQUIREMENT_READY → [用户确认 PRD] → PLAN_READY → [用户批准 plan] → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → [用户 review] → CLOSED
- **测试结论**：待 TESTING 阶段填写
- **交付报告**：`docs/tasks/examples/V1.3-ACCEPTANCE.md`
- **合并前检查**：待填写（`git diff --check` / 测试通过 / 无敏感泄露 / V1.1/V1.2 脚本回归通过）
- **用户 review**：待（不自动 merge / deploy）
- **下一阶段建议**：V1.4 CodeBuddy 自动 dispatch（基于任务状态机自动触发 Plan/Dev/Test）；或 V1.4 多任务队列管理
