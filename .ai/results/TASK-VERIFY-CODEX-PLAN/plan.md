### 结论

只读检查完成：`scripts/ai/codex_plan.sh` 的路径、只读调用、日志路径、`plan.md` 缺失时 `exit 2` 逻辑都符合本任务预期；但父脚本最终退出码需要在本条最终回复结束后由 CodeBuddy 再确认。

### 修改内容

* 未修改业务代码。
* 未运行 `codex_dev.sh`，未 commit，未 push。
* 已只读检查这些关键文件：
  * `scripts/ai/codex_plan.sh`
  * `.ai/tasks/TASK-VERIFY-CODEX-PLAN.md`
  * `workstation/STATION_CONFIG.md`
  * `tasks/current.md`
  * `CODEBUDDY.md`
  * `docs/AI_WECHAT_WORKFLOW.md`

关键逻辑确认：

* `scripts/ai/codex_plan.sh:40-45` 固定输出：
  * `.ai/results/<TASK_ID>/plan.md`
  * `.ai/logs/<TASK_ID>/codex_plan.log`
* `scripts/ai/codex_plan.sh:78` 使用：
  * `codex exec --sandbox read-only --ephemeral --output-last-message "$PLAN_FILE"`
* `scripts/ai/codex_plan.sh:96-104` 已实现：
  * `plan.md` 不存在或为空时输出 `Codex plan failed: no plan.md generated`
  * 返回 `exit 2`
* `.ai/` 已在 `.gitignore` 中忽略，不进入 Git 跟踪。

### 测试与验证

实际运行过：

* `git rev-parse --show-toplevel`：仓库根目录为 `/Volumes/扩展盘/guiyi-quant-workstation`
* `git status --short --branch`：当前工作区已有大量既有未提交改动，包含 `scripts/ai/codex_plan.sh`
* `bash -n scripts/ai/codex_plan.sh`：通过
* `command -v codex`：`/opt/homebrew/bin/codex`
* `ls -l .ai/results/TASK-VERIFY-CODEX-PLAN/plan.md .ai/logs/TASK-VERIFY-CODEX-PLAN/codex_plan.log .ai/logs/TASK-VERIFY-CODEX-PLAN/codex_stdout.log`：三者均存在
* `git diff --check -- scripts/ai/codex_plan.sh .ai/tasks/TASK-VERIFY-CODEX-PLAN.md workstation/STATION_CONFIG.md`：通过

注意：当前我很可能就是 `codex_plan.sh` 启动的 Codex 子进程，所以父脚本要等我的最终回复结束后，才会继续写入 `Codex exit code`、`Working tree AFTER plan` 和 `[OK] Plan generated`。

### 风险与未完成项

* 父脚本最终退出码不能在子进程内部确认。
* 现有 `codex_plan.log` 当前只记录到 `Working tree BEFORE plan`，这是父脚本等待 Codex 子进程结束时的正常中间态。
* `ps` 被当前环境拒绝执行，无法检查是否还有并行 Codex 进程。
* 当前工作区本来已有大量未提交改动，本任务不能把这些改动算作本轮 dry-run 产生。

### 建议下一步

在本次 Codex 回复结束后，由 CodeBuddy 立刻执行：

```bash
echo $?
test -s .ai/results/TASK-VERIFY-CODEX-PLAN/plan.md
test -s .ai/logs/TASK-VERIFY-CODEX-PLAN/codex_plan.log
tail -80 .ai/logs/TASK-VERIFY-CODEX-PLAN/codex_plan.log
git status --short --branch
```

预期：

* 脚本退出码：`0`
* `plan.md` 非空
* `codex_plan.log` 非空，并包含 `[OK] Plan generated`
* `git status` 不应出现除 `.ai/` 忽略产物之外的新业务文件改动

### 协作建议

* 是否建议开新 Codex 会话：否。当前只是本地只读调用验证。
* 是否建议使用 Plan 模式：否。除非下一步要修复脚本逻辑，否则不需要进入开发。
* 建议同步给 GPT 的文件：
  * `scripts/ai/codex_plan.sh`
  * `.ai/tasks/TASK-VERIFY-CODEX-PLAN.md`
  * `.ai/logs/TASK-VERIFY-CODEX-PLAN/codex_plan.log`
  * `.ai/results/TASK-VERIFY-CODEX-PLAN/plan.md`
  * `CODEBUDDY.md`
  * `docs/AI_WECHAT_WORKFLOW.md`

