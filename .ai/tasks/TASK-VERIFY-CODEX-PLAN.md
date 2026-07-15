# TASK-VERIFY-CODEX-PLAN：Codex plan 只读调用验证（dry-run）

> 类型：本地临时验证任务，不纳入业务代码、不关联 GitHub Issue、不进入交付流程。
> 生成：CodeBuddy 验证用（方案 A）

## 目标
验证 `scripts/ai/codex_plan.sh` 的只读 plan 调用是否符合预期：
1. 只读读取 `workstation/STATION_CONFIG.md`。
2. 不修改任何仓库文件。
3. 输出 plan 到 `.ai/results/TASK-VERIFY-CODEX-PLAN/plan.md`。
4. 日志写到 `.ai/logs/TASK-VERIFY-CODEX-PLAN/codex_plan.log`。
5. 若 Codex 超时或未生成 plan.md，脚本须 `exit 2` 并输出 `Codex plan failed: no plan.md generated`。

## 范围
- 仅读取文档，不写仓库文件、不 commit、不 push。
- 不运行 codex_dev.sh，不使用 --allow-no-issue。

## 验收
- [ ] plan.md 生成
- [ ] codex_plan.log 生成
- [ ] git status 未出现非预期改动
- [ ] 退出码符合预期
