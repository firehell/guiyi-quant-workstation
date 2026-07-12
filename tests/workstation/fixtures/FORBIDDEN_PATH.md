# FORBIDDEN_PATH: forbidden path modification fixture

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | FORBIDDEN_PATH |
| Work Level | L1 |
| GitHub Issue | #8 |
| Branch | feature/test |
| Worktree | {{WORKTREE}} |
| Status | TESTING |
| Required Env | - |
| Required Mounts | - |
| Created At | 2026-07-12 |
| Owner | test |

## 7. 涉及模块

**允许修改**：

- `scripts/ai/`
- `tests/workstation/`

**禁止修改**：

- `.env`
- `data/raw/`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
git diff --check
```
