# STANDARD_API: regular API task

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | STANDARD_API |
| Work Level | L1 |
| GitHub Issue | #1 |
| Branch | feature/test |
| Worktree | {{WORKTREE}} |
| Status | REQUIREMENT_READY |
| Required Env | - |
| Required Mounts | - |
| Created At | 2026-07-12 |
| Owner | test |

## 2. 任务类型
普通 API 和测试

## 7. 涉及模块

**允许修改**：

- `services/quant-api/app/api/`
- `tests/workstation/`

**禁止修改**：

- `.env`
- `data/raw/`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
git diff --check
```
