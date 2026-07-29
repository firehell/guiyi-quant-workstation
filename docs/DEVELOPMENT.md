# 开发流程

更新时间：2026-07-26

本文件是归一量化**唯一开发流程**说明。旧多入口控制面 / 双入口 / 分级路由长文已退出正式架构（Git 历史可查）。

本项目是**单用户本地研究工作站**，主要执行者是 AI（GPT 设计 / Codex 编码 / 用户批准）。流程原则：减少非必要仪式，但真实资金 / 真实数据 / 真实发送的安全护栏**一分不减**。风险分级细则以本文件为准，`AGENTS.md` 为工程总纲；二者如有冲突以 `AGENTS.md` 的硬规则为上位。

## 1. 工具模型

```text
GPT（浏览器，需求/设计/审查）
  + GitHub（Issue / PR / canonical docs）
  + Codex（编码执行）
  + 用户（Plan / 生产写入 / merge / deploy 批准）
```

- Cursor：人工 IDE、调试、最终验收与 Git 操作。
- iPhone ChatGPT：仅 Codex 远程入口，不另建状态源。
- 禁止把对话 memory、`.ai/results`、已废弃任务池当作项目事实源。

## 2. 三车道模型

**核心原则：默认走轻；能回滚 → 轻，不能回滚且碰真钱 / 真数据 / 真发送 → 重；只有命中下面 Lane 3 清单才走重流程。** 把默认值放在"轻"这一侧：能回滚的改动默认不背 Gate、不背 task 文档；仪式只加在真实不可逆写入上。

判定顺序（自上而下，命中即停）：

1. 这次改动命中第 3 节的 **Lane 3 清单**吗？命中 → **Lane 3**。
2. 否则，是策略 / 指标 / 回测的**研究实验**吗？是 → **Lane 1**。
3. 否则 → **Lane 2**。

### Lane 1 — 研究快车道

**适用**：策略 / 指标 / 回测实验、参数探索。

**流程（轻）**：

- 不需要 task 文档、不需要 Gate、不需要 approval packet。
- 非 `main` 分支 / worktree → 跑实验 → 在轻量实验台账记一行：策略版本 / 参数 / 品种 / 周期 / 区间 / 关键指标。

**P0 安全由代码强制，不靠仪式**：

- 严格研究只用 `data_role=primary` / `quality_status=passed` 数据；如需 warning 数据必须显式 opt-in，且结果必须标注。
- 禁止未来函数；成交口径强制 `next_bar_open`。
- 不写 live 表、不触发 `SignalEvent`、不发企业微信、不自动下单。
- 实验产物只落隔离文件 / 结果目录，不进正式 report / lineage，不得触碰 `report 14/15` lineage。

**对应代码基础**：回测 runner 的 `research_only=True` 分支（绕开正式 profile binding snapshot）；研究快车道 spec（建设中）。

### Lane 2 — 常规工程

**适用**：前端、非资金后端、文档、测试补全、只读探针、非策略公式的重构。

**流程（轻）**：

1. GitHub Issue（或口头确认）说明目标与范围。
2. 在非 `main` 分支 / worktree 开发。
3. 运行 `scripts/engineering/preflight.sh`。
4. 小步实现 + 定向测试 / `scripts/engineering/test.sh`（`engineering` 或 `all-safe`）。
5. 开 PR 或交用户审查。

- **不需要 hash Gate，不需要强制 task 文档；不自动 merge。**

### 2.1 Worktree 生命周期（bootstrap）

- `main` 保持 canonical/release；`develop` 启用后只接收人工审查后的集成；两者都不是开发分支。
- task 使用 `feature|fix|docs|research|refactor/<task-id>-<slug>`，位于外置盘
  `GuiyiWorktrees/tasks/`。先用 `worktree_flow.py` dry-run，再由用户确认 `--apply` 的本地操作。
- 本地工具只创建、盘点或清理已合入且 clean 的 task；不 push、不 merge、不创建 PR、不更改 GitHub
  规则、不打 tag、不切 Runtime。详见 `docs/WORKTREE_RELEASE_WORKFLOW.md` 与 ADR-WS-003。

### Lane 3 — 真实不可逆写入

**适用**：命中第 3 节清单的操作才进；安全一分不减。

**流程（重）**：

1. 必须有 GitHub Issue，写清风险与回滚。
2. 保留 `docs/tasks/<TASK_ID>.md` 作为执行契约。
3. 先 Plan / 设计审查，用户明确批准后再 Dev。
4. **真实写入必须使用业务专用、hash-bound、scope-bound approval packet / Gate**；没有专用 Gate 就禁止真实写入，先独立设计 Gate。Issue 中用户批准是决策记录，**不能替代代码层 hash 校验**。
5. **fail-closed**：禁止未来函数、静默降级数据源、削弱 secret / mount Gate。
6. 交付必须含：变更文件、测试命令与结果、风险、未完成项。

## 3. Lane 3 边界清单

下列操作属于**真实不可逆写入 → 必须走 Lane 3**。**未列入清单的一律默认 Lane 1 / 2。**

- **live 表写入** / live runtime 部署或重启为写入态。
- **企业微信**（或任何外发通知）真实发送。
- 生产 **PostgreSQL migration** / schema 变更 / 任何写生产 DB 的操作。
- **数据湖写入**：`data/raw/` 原始数据，或 primary/passed 行情资产的产生、修改、回填、覆盖。
- **策略公式 / 回测撮合与成本口径变更**（影响可信基线，如 `report 14` lineage）。
- **生产配置 / 密钥 / `.env`** 相关。
- **自动交易 / 下单路径**（V1 不做）。

运维约定（属 Lane 3 范畴）：本地 launchd 的 Python 服务必须由 `run-local-service.sh` 直接 `exec services/quant-api/.venv/bin/python`；不得再以 `uv run` 作为被监管外壳，否则 bootout/kickstart 可能只结束外壳并遗留占用端口的子进程。Web 继续直接执行已安装的 Vite preview。盘后调度器使用相同的直接解释器契约，但仍由独立 runner、label 和审批 Gate 管理。

## 4. 状态源

| 源 | 用途 |
|---|---|
| `STATUS.md` | 当前状态仪表盘（未关闭 Gate / 事实锚点 / 红线） |
| `STATUS_ARCHIVE.md` | 历史叙事与完整 flag 归档 |
| GitHub Issue / PR | 任务生命周期 |
| `docs/tasks/`（根目录） | 当前活跃任务契约 |
| `docs/tasks/archive/INDEX.md` | 历史任务归档索引 |
| `DECISIONS.md` | 长期决策 |
| 版本化报告 / PR | 证据 |

已退出 active：旧任务池 / 旁路摘要 / 控制面 stage 状态机（已从文档树删除）。

## 5. 工程入口（推荐）

| 脚本 | 职责 |
|---|---|
| `scripts/engineering/preflight.sh` | 只读环境 / 分支 / 脏树提示（`--strict`：本地 main/master/develop 或 dirty 失败；`--ci`：跳过分支检查，仍阻断 dirty；不削弱 secret） |
| `scripts/engineering/test.sh` | 固定 profile 测试（`engineering` / `docs` / `backend-health` / `all-safe`）；禁止自由 shell |
| `scripts/engineering/check-secrets.sh` | secret 扫描（默认 fail-closed；不打印真值；CI 禁用 `--warn-only`） |
| `scripts/engineering/runtime-health.sh` | 只读 `/health` JSON 契约探针；完整读取最多 1 MiB 的 JSON，超限 fail-closed |
| `scripts/engineering/worktree_flow.py` | 本地 worktree 盘点、初始化、task 创建/清理；默认 dry-run，不操作远端或 Runtime |

```bash
bash scripts/engineering/preflight.sh --json
bash scripts/engineering/check-secrets.sh
bash scripts/engineering/test.sh engineering
bash scripts/engineering/runtime-health.sh --json

# Makefile
make engineering-preflight
make engineering-test
make engineering-secrets
# CI: make engineering-ci   # 或 ENGINEERING_PREFLIGHT_ARGS=--ci
```

高风险真实写入（Lane 3）：业务专用、hash-bound、scope-bound approval packet / Gate；没有专用 Gate 就禁止真实写入。

旧入口（如历史 `scripts/ai/*` 调度脚本等）：**已删除**。勿再调用。

## 6. Fail-closed 原则

- 缺环境变量、外置盘、数据挂载：失败并报告，不自动创建或切换降级源。
- 测试命令拒绝 `git push/merge`、危险 sandbox、管道写破坏。
- 不自动关闭 GitHub Issue/PR；清理清单仅建议。
- 企业微信默认 preview；真实发送须用户确认。

## 7. 推荐阅读顺序（接手）

1. `STATUS.md`
2. `AGENTS.md`
3. 本文件
4. `PROJECT_SOURCE.md`
5. `DECISIONS.md`
6. 任务相关 deep canonical 或 Issue/PR

## 8. 工作站模式

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
POST_FREEZE_REAL_PILOT_PASSED
WORKSTATION_FINAL_CLEANUP_COMPLETE
```

工程入口：`scripts/engineering/*`。现行 ADR：`docs/decisions/ADR-WS-002-simplified-github-codex-workstation.md`。不重建多入口控制面。Step 6 Pilot（Issue #43 / PR #44）已合入后标记 `POST_FREEZE_REAL_PILOT_PASSED` / `WORKSTATION_FINAL_CLEANUP_COMPLETE`。
