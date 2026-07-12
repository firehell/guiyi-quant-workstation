# WRONG_BRANCH: branch mismatch fixture

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | WRONG_BRANCH |
| Work Level | L1 |
| GitHub Issue | #5 |
| Branch | feature/other |
| Worktree | {{WORKTREE}} |
| Status | REQUIREMENT_READY |
| Required Env | - |
| Required Mounts | - |
| Created At | 2026-07-12 |
| Owner | test |

## 7. 涉及模块

**允许修改**：

- `scripts/ai/`

**禁止修改**：

- `.env`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
git diff --check
```
