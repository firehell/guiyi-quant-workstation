# TASK-2026-07-12-020: Codex Review And Structured Results

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-020-codex-review-results |
| Work Level | L1 |
| GitHub Issue | 待创建（L1 可选） |
| Branch | feature/unified-task-dispatcher |
| Worktree | /Volumes/扩展盘/guiyi-parallel/workstation-router |
| Status | TESTING |
| Required Env | - |
| Required Mounts | - |
| Base Branch | feature/unified-task-dispatcher |
| Created At | 2026-07-12 |
| Owner | local-user |

## 5. 目标

完善工作站 review、测试和结果收集阶段，新增只读 Codex review 入口，并生成结构化结果包。

## 6. 不做事项

- 不调用真实 Codex；测试使用 stub。
- 不 push、merge、deploy。
- 不触碰 `.env`、凭据、数据目录或交易逻辑。

## 7. 涉及模块

**允许修改**：

- `docs/tasks/TASK-2026-07-12-020-codex-review-results.md`
- `docs/workflows/ai_delivery_workflow.md`
- `scripts/ai/`
- `scripts/ai/lib/`
- `tests/workstation/`

**禁止修改**：

- `.env`
- `.env.*`
- `data/raw/`
- `data/parquet/`
- `data/processed/`
- 未列出的业务模块

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
python -m pytest -q tests/workstation
git diff --check
```

## 19. 验收标准

- `codex_review.sh` 支持互斥 review target，始终 read-only，输出结构化 Markdown。
- `collect_result.sh` 生成 `result_bundle.json`、`execution.json`、`execution_summary.md`、`changed_files.txt`、`diff_stat.txt`。
- result 阶段不调用模型；测试失败、越界修改、forbidden path 和敏感信息会进入阻断状态。
- critical 任务保留 external review 标志，不能仅凭 Codex review 关闭。

## 20. 风险点

- 结果包字段需要兼容旧的 `result_bundle.json` 消费方。
- Shell 脚本需要避免回显 token、webhook、password、DATABASE_URL 等敏感值。
