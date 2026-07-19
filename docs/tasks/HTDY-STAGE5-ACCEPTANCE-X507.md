# HTDY-STAGE5-ACCEPTANCE-X507

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-STAGE5-ACCEPTANCE-X507 |
| Handbook Task | X5-07 / E5-07 |
| Branch | codex/htdy-stage5-acceptance-x507 |
| Worktree | /private/tmp/guiyi-htdy-stage5-acceptance-x507 |
| Status | CODE_COMPLETE_GATE_PENDING |
| Risk Level | L2 file-only acceptance |
| Candidate | report 15 / task 23 |
| Created At | 2026-07-19 |

允许修改：X5-07 file-only acceptance service、CLI、测试、任务文档和固定输出目录。

禁止修改：PostgreSQL、策略/参数、candidate/report14、X5-03/04/05/06B packet 和原始结果。

## 实现

- 固定读取并复算 X5-03/04/05/06B packet、artifact、fold manifest、binding、protocol/parameter 与 validation-context hash。
- candidate/report14 trust audit、Review 后 report14 invariance、ReviewNote/exact-bars/browser smoke 必须闭合。
- 缺失、篡改、身份漂移或 Review Gate 未通过时输出 `STRATEGY_VALIDATION_BLOCKED`。
- 完整拒绝链输出 `STRATEGY_EVALUATION_PIPELINE_READY + REJECTED_RESEARCH_CANDIDATE`；完整正向链输出 pipeline ready + validated。
- CLI 无证据路径、DB apply、参数或结果 override，固定写 `data/reports/htdy_stage5_acceptance_x5_07/`。

## 测试

```bash
PYTHONPATH=packages/quant-core services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/test_htdy_stage5_acceptance_x507.py
```

覆盖 real rejected、validated decision、diagnostic rejection、missing、tamper、Review blocked、report14 regression 和 acceptance packet tamper。

## 回滚

删除本分支新增的 service、CLI、测试、任务文档和固定输出目录。无数据库回滚。
