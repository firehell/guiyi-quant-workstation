# 火天大有（HTDY）公式输入说明

请将通达信公式放入 **本 worktree 根目录** 下的：

```text
private_sources/htdy/
```

推荐文件名：

- `formula.txt` — 通达信公式纯文本
- `formula.tn6` — 导出文件（若可转换为先 txt）
- `screenshots/` — 公式截图（PNG）

该目录已在 `.gitignore` 中，**不会**被 git 提交。

Codex 会话 B 启动前请确认至少有一个可读公式文件存在。

参考风险审查模板：[`docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`](../../docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md)
