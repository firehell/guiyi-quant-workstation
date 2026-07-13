---
kind: Epic
schema_version: "2.0"
epic_id: "WORKSTATION-V2-DEMO"
title: "工作站 V2 端到端 Demo — 10 场景合成验证"
status: EXECUTING
risk_level: R1
owner: "WorkBuddy"
tasks:
  - "DEMO-R0-READONLY"
  - "DEMO-R1-CODE"
  - "DEMO-R2-DRYRUN"
  - "DEMO-R3-ONESHOT"
  - "DEMO-RESOURCE-LOCK"
  - "DEMO-WRONG-BRANCH"
  - "DEMO-ALLOWED-PATH"
  - "DEMO-APPROVAL-EXPIRY"
  - "DEMO-RESULT-REDACTION"
  - "DEMO-LEDGER-5DAY"
readiness_flags:
  ws_v2_006_gates_ready: true
  ws_v2_007_bundler_ready: true
  ws_v2_008_ledger_ready: true
  all_unit_tests_pass: true
created_at: "2026-07-13"
---

# WORKSTATION-V2-DEMO: 工作站 V2 端到端 Demo

## 前置条件

- WS-V2-001 至 WS-V2-008 全部已 merge 到 main
- 392 单元测试通过（3 预存失败）
- 不修改业务模块
- 使用合成 fixture 模拟真实场景

## 验证场景

| # | 场景 | 描述 | 预期 |
|---|------|------|------|
| 1 | R0 只读 | R0 任务只能执行 audit，不能 dev/write | BLOCK dev |
| 2 | R1 代码 | R1 任务 plan → dev → test 流程完整 | PASS |
| 3 | R2 dry-run | 无批准阻断；批准后仅写临时 fixture | BLOCK→PASS |
| 4 | R3 一次性 | 批准消费一次即失效 | CONSUMED |
| 5 | 资源锁竞争 | 两个任务竞争同一锁，第二个阻塞 | BLOCK #2 |
| 6 | 错误 worktree/branch | Branch 不匹配被 gate 阻断 | BLOCK |
| 7 | allowed_paths 越界 | 写入 forbidden path 被阻断 | BLOCK |
| 8 | 批准过期/plan_hash/重放 | 过期/伪造/重放批准全部阻断 | BLOCK×3 |
| 9 | 结果包与脱敏 | Token/webhook/密码脱敏，evidence index 生成 | REDACTED |
| 10 | 五日 ledger | 5 天 runtime gate ledger 模拟，finalize 报告 | READY |

## 产出物

1. Demo 验证结果（10 场景 pass/fail 矩阵）
2. 已知限制清单
3. 迁移指南（V1 → V2）
4. 建议 commit message
5. 合并 main 条件评估
