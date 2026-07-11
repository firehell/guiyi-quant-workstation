# TASK-2026-07-11-004：JM 实时 1m 真实 Gate（T1/T3）

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-004-jm-live-runtime-gate |
| GitHub Issue | #12 |
| Branch | codex/jm-live-runtime-gate |
| Worktree | /Volumes/扩展盘/guiyi-parallel/jm-live-gate |
| Status | T1_OPS_PASSED / T3_CLOCK_IDLE_NON_TRADING / T3_REAL_PENDING |
| 前置 merge | `codex/v1-live-runtime-closure` @ a7df3aac |

## 1. 任务状态

T1_OPS_PASSED / T3_CLOCK_IDLE_NON_TRADING / T3_REAL_PENDING / CODE_COMPLETE_EXTERNAL_GATES_PENDING

说明：`codex/v1-live-runtime-closure` 已 merge 到当前分支，本轮不再重复 merge。当前已完成 D0 基线核对、T1 render-only、基础服务加载、strict health 和 kill/recovery；T3 已获单次授权并在非交易时段返回 `idle`，尚未完成真实 1m 写入；T4-real 未执行。

## 2. 任务类型

实时行情监听 / Mac mini 部署 / 安全权限

## 3. 参与角色

- 必须：后端开发、DevOps、安全专家、测试专家
- 不需要：前端（禁止改 apps/quant-web）

## 4. 背景

`codex/v1-live-runtime-closure` 在独立 worktree 已实现 live runtime 代码（361 tests passed），状态 `CODE_COMPLETE_EXTERNAL_GATES_PENDING`。该分支已 merge 到当前任务分支，后续严格按 Gate 推进 **D0 → T1-ops → T3-real**，每步只开一个 env flag。

## 5. 目标

1. **D0**：冻结当前 merge 后基线，建立真实 Gate 证据账本，不加载服务、不写真实数据
2. **T1-ops**（外部前置）：API/Web/backtest/signal worker 恢复；strict health；四 flag 全 false
3. **T3-real**：仅 `GUIYI_LIVE_RUNTIME_ENABLED=true`；JM 单次真实 1m + 全周期聚合 + 重启续跑
4. 文档化 Gate 证据到 `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`

## 6. 不做事项

- 不修改 `apps/quant-web/`
- 不开启 `GUIYI_WECHAT_AUTOSEND_ENABLED`、不 T6-real
- 不一次性全开四个 live flag
- 不 CTP / 自动下单
- T4-real 盘后归档可文档化步骤，**本轮不强制执行**（若 T1-ops 未通过则 block）
- 不宣称 `JM_RUNTIME_READY`，直到 T1/T3/T4/T5/T6/T7 真实 Gate 全部通过

## 7. 涉及模块

**允许修改**：

- `services/quant-api/app/services/live_*`
- `services/quant-api/app/runtime_scheduler.py`
- `services/quant-api/app/services/trading_session_clock.py`
- `services/quant-api/app/services/runtime_health.py`
- `services/quant-api/app/services/after_market_archive.py`
- `services/quant-api/tests/`
- `scripts/rqdata_live_*`、`scripts/after_market_archive.py`
- `scripts/run-local-service.sh`、`scripts/dev-healthcheck.sh`
- `deploy/launchd/`
- `docs/tasks/`、`tasks/current.md`
- `.ai/results/TASK-2026-07-11-004-jm-live-runtime-gate/`

**禁止修改**：

- `apps/quant-web/`
- CTP、订单、账户接口
- `.env`（仅文档说明，不提交）

## 8. 产品需求

- runtime health 不假绿：worker/scheduler/checkpoint 真实反映
- 动态 actual contract（`LiveTargetContractResolver`），不硬编码 JM2609

## 9. 量化业务规则

- DCE 夜盘/午休/收盘 grace（`TradingSessionClock`）
- live DB 与 historical active parquet 隔离

## 10. 数据影响

- T3-real：**真实写入** `live_minute_bars` 与聚合表（需用户授权 + 交易时段）
- 默认 dev 阶段 dry-run / unit tests only

## 11. 技术方案

### D0 baseline

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor a7df3aac HEAD
grep -E 'GUIYI_(LIVE_RUNTIME|LIVE_SIGNAL_EVENTS|AFTER_MARKET_ARCHIVE|WECHAT_AUTOSEND)_ENABLED=' .env.example
```

D0 只记录现有基线和 Gate 手册，不加载 LaunchAgent，不开启任何真实写入或发送开关。

### T1-ops

- `scripts/install-local-services.sh` 仅基础服务
- `scripts/dev-healthcheck.sh` → business ok
- 四 flag 全 false

### T3-real

```bash
GUIYI_LIVE_RUNTIME_ENABLED=true \
uv run --project services/quant-api python -m app.runtime_scheduler \
  --once --confirm-live-write --product jm
```

验证 checkpoint 重启续跑。

## 12. 交互视觉要求

无 Web 变更

## 13. 安全权限要求

- 不提交 RQData license、webhook
- 真实写入需用户显式授权 + 交易时段
- macOS 外接卷 LaunchAgent 权限未通过则 T1-ops block，但 merge 仍可完成

## 14. 开发步骤

1. D0：确认 merge 后基线，编写 `JM-LIVE-GATE-EVIDENCE.md`
2. T1-ops 文档与脚本验证（若环境 block 则记录 block 原因）
3. T1-ops 实际加载仅在用户确认外接卷权限和基础服务 Gate 后执行
4. T3-real 仅在 T1 通过且用户单独授权后执行
5. 后续 T4/T5/T6/T7 只记录顺序，不在 D0 执行

## 15. Codex Plan Prompt

```
只读 Plan。必读 docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md（merge 后路径）、AGENTS.md、docs/gpt/NEXT_STEPS.md。
任务：merge live runtime + T1/T3 Gate 计划。禁止改 apps/quant-web。
输出：merge 策略、冲突预判、Gate 顺序、block 条件。
```

## 16. Codex Dev Prompt

```
先 merge codex/v1-live-runtime-closure，pytest 全绿。
按 Plan 修复 merge 冲突。编写 Gate 证据文档。
T3-real 仅在有用户授权且 T1 通过时执行；否则 document block。
禁止改 apps/quant-web，禁止全开四 flag。
```

## 17. CodeBuddy 执行 Prompt

```
worktree: /Volumes/扩展盘/guiyi-parallel/jm-live-gate
branch: codex/jm-live-runtime-gate
merge 必须先于 codex_plan。不 push/merge/deploy 到 main 除非用户 PR。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
uv run --project services/quant-api pytest services/quant-api/tests/ -q
bash -n scripts/run-local-service.sh scripts/dev-healthcheck.sh scripts/install-local-services.sh scripts/local-services-status.sh
for f in deploy/launchd/*.plist.template; do plutil -lint "$f"; done
git diff --check
```

- [x] merge 已完成，当前 HEAD 包含前置 merge
- [x] D0 证据文档已建立
- [x] 文档修改后 `git diff --check` 通过
- [x] shell 语法检查通过
- [x] launchd plist 模板 `plutil -lint` 通过
- [x] T1 render-only 通过，`.run/launchd` 生成 7 个 plist
- [x] `--confirm-load` 已执行，基础 5 个 launchd label loaded
- [x] scheduler / notification worker 未加载
- [x] `dev-healthcheck.sh --json --no-start` passed
- [x] T1 kill/recovery passed
- [x] T1-ops 证据记录
- [x] T3 授权确认、dry-run 和非交易时段 idle smoke 证据记录
- [ ] T3-real 证据或 block 记录

## 19. 验收标准

- `live_runtime.py`、`runtime_scheduler.py` 等文件存在于本分支
- pytest 361+ passed（代码变更或进入真实 Gate 前基准）
- Gate 证据文档存在，状态 honest（CODE_COMPLETE vs JM_RUNTIME_READY）
- 未修改 apps/quant-web

## 20. 风险点

- 旧任务叙述误导重复 merge 或越过 D0/T1 Gate
- 外接卷权限导致 T1 永久 block
- 误开企微或四 flag 全开
- `scripts/rqdata_realtime_poc.py` 中的 `JM2609` 只允许作为旧只读 PoC 证据，禁止作为 T3 runtime 入口

## 21. 交付记录

- 合并目标：main（四条线中 **最后一个** PR）
