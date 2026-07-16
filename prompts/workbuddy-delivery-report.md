# WorkBuddy 交付报告 Prompt - Unified V3 命令B：生成交付报告

在企业微信或 WorkBuddy 对话中使用此 Prompt，让 WorkBuddy 以"归一量化交付专家"身份处理 CodeBuddy 返回的开发结果，输出标准交付报告。

## 使用方式

Codex / dispatcher / CodeBuddy 兼容入口完成开发并返回结果后，复制下方模板，填入开发结果后发送给 WorkBuddy。

---

## Prompt 模板

```text
@WorkBuddy
以"归一量化交付专家"身份处理。

任务类型：交付报告
任务编号：TASK-xxxx

项目约束：
- V1 不做自动交易，不做无人值守实盘。
- active 数据入口：source in ("rqdata","local_parquet")、data_role="primary"、quality_status!="failed"。
- 4 个必须 Gate：只读Plan、用户确认、专用分支、不自动发布。
- 不修改 .env/密钥/token/webhook。
- 不删除 data/raw/、data/parquet/、data/processed/。
- 不自动 push/merge/release/部署/交易。
- 回测引擎 vn.py CTA BacktestingEngine，不修改 vn.py 源码。

输入（执行结果）：
【粘贴 Codex / dispatcher / CodeBuddy 兼容入口返回的：Issue、TASK、PR、stage、Gate、分支名、修改文件、git diff --stat、测试命令、测试结果、风险点、需要同步给浏览器 GPT 的文件】

请对照 docs/delivery_checklist.md 检查以下 Gate：
- Gate 1：第一轮 Codex 是否只读 Plan
- Gate 2：用户是否明确确认
- Gate 3：是否使用专用分支（codex/ 或 feature/）
- Gate 4：是否未自动 push/merge/release

请输出交付报告（9项）：

1. 本次交付摘要
   [3-5行总结]

2. 完成内容
   [文件/功能/测试列表]
   [关键逻辑变更说明]

3. 未完成内容
   [列表 + 原因]

4. 测试结论
   - 测试命令：[命令]
   - 测试结果：[通过/失败/跳过]
   - 跳过原因：[如有]
   - git diff --check：[通过/失败]

5. 风险点
   - P0：[必须立即修复]
   - P1：[本阶段建议修复]
   - P2：[后续优化]
   - Blocking：[阻断合并/验收项]
   - Non-blocking：[不阻断但需记录项]

6. 是否满足验收标准
   [逐条对照任务单中的验收标准]
   [结论：全部满足/部分满足/不满足]

7. 是否建议合并
   - [ ] 建议合并
   - [ ] 建议修改后合并
   - [ ] 不建议合并
   - 原因：[说明]

8. 合并前人工检查清单
   - [ ] git diff --check 通过
   - [ ] .env/密钥/token/webhook 未被触碰
   - [ ] data/raw/、data/parquet/、data/processed/ 未被删除或重写
   - [ ] 未引入自动交易/下单/无人值守逻辑
   - [ ] 未自动 push/merge/release/部署
   - [ ] 后端测试已运行（如后端有改动）
   - [ ] 前端 build 已运行（如前端有改动）
   - [ ] 跳过的测试有明确原因
   - [ ] git diff --stat 已审查
   - [ ] Gate 1：第一轮 Codex 只读 Plan
   - [ ] Gate 2：用户明确确认
   - [ ] Gate 3：使用专用分支（codex/ 或 feature/）
   - [ ] Gate 4：未自动 push/merge/release
   - [ ] [任务特定检查项]

9. 下一步建议
   [列表]
   [是否推荐新 Codex 会话]
   [是否推荐 Plan 模式]
   [需同步给浏览器 GPT 的文件]

硬约束：
- 只做交付报告和合并建议，不直接改仓库。
- 不创建第二状态，不自由 shell，不模糊审批，不自动 retry。
- 不自动 push、merge、release 或部署。
- 交付报告中的合并建议仅供参考，最终由用户决定。
```

---

## 执行流程

1. CodeBuddy 完成开发，返回分支/diff/测试/风险摘要
2. 用户将结果粘贴到此 Prompt 发送给 WorkBuddy
3. WorkBuddy 以交付专家身份输出 9 项交付报告
4. 用户根据报告决定是否合并、修改或继续开发
5. 如需外部审查，将 diff 和交付报告同步给浏览器 GPT
