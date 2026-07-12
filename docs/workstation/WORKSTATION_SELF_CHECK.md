# 工作站自检说明

更新时间：2026-07-12

> 控制平面自检入口：[`scripts/ai/workstation_doctor.sh`](../../scripts/ai/workstation_doctor.sh)
> 业务服务健康检查：[`scripts/dev-healthcheck.sh`](../../scripts/dev-healthcheck.sh)（不同域）

## 快速开始

```bash
# 完整自检（doctor + pytest）
make workstation-test

# 仅 doctor
make workstation-doctor

# 或手动
scripts/ai/workstation_doctor.sh --strict --skip-installed-profiles
python3 -m pytest -q tests/workstation
```

## workstation_doctor.sh

聚合 AI 工作站控制平面 preflight，**不调用 Codex 模型、不访问网络/数据库/真实外置数据**。

| 选项 | 说明 |
|------|------|
| `--json` | 输出结构化 JSON 报告 |
| `--strict` | 任一 failed/warn 检查 → exit 1 |
| `--skip-installed-profiles` | 跳过 codex 安装检查（CI / 无 Codex 机器） |

检查项（摘要）：

1. `git` / `python3` / 可选 `uv` / `pnpm`
2. `codex --version`（仅版本，不调模型）
3. TASK parser + router smoke
4. 四档 profile 模板 [`configs/ai/profile_templates/`](../../configs/ai/profile_templates/)
5. dispatcher dry-run、writer lock、env check
6. `.ai/results/` 可写
7. 当前 branch 非 `main`/`master`（`--strict`）
8. 输出不含凭据模式

## 集成测试约束

`tests/workstation/integration/` 场景 A–I 全部：

- 在 `tmp_path` 临时 git 仓库运行
- 默认 `GUIYI_AI_DRY_RUN=1`（mount / result 等需 env gate 的场景除外）
- `GUIYI_SKIP_CODEX_ENV_CHECK=1`
- 使用 stub 子命令，不调用真实 Codex

| 场景 | 验证点 |
|------|--------|
| A FAST_DOC | `routing_tier=fast`，dev sandbox=workspace-write |
| B STANDARD_API | `routing_tier=standard` |
| C DEEP_RUNTIME | `routing_tier=deep`，自动 `high-readonly` |
| D CRITICAL_INDICATOR | `routing_tier=critical`，`external_review_required` |
| E BLOCKED_PRODUCTION | bootstrap + dispatch 生产 Gate |
| F WRONG_BRANCH | Branch Gate |
| G LOCKED_WORKTREE | writer lock 冲突 |
| H MISSING_MOUNT | env fail-closed |
| I FORBIDDEN_PATH | result 阻断 forbidden path |

Fixture TASK：[`tests/workstation/fixtures/`](../tests/workstation/fixtures/)

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 全部通过（或非 strict 下仅 warn） |
| 1 | `--strict` 下存在 failed/warn |
| 2 | 参数错误 |

## 故障排查

- **branch_not_main failed**：在 feature branch 运行；或在本地验证时使用非 strict doctor
- **codex warn**：安装 Codex CLI 或使用 `--skip-installed-profiles`
- **profile_templates failed**：检查 `configs/ai/profile_templates/*.json` 是否与 `route_task.py` profile 表一致
- **env_check failed**：TASK Required Mounts 缺失；doctor 使用 `STANDARD_API` fixture，不应要求外置盘

## 相关文档

- 路由策略：[`ROUTING_POLICY.md`](ROUTING_POLICY.md)
- 环境 fail-closed：[`ENVIRONMENT_FAIL_CLOSED.md`](ENVIRONMENT_FAIL_CLOSED.md)
- 架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
