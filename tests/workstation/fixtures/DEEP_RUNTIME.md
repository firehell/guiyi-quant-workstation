# DEEP_RUNTIME: scheduler recovery task

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | DEEP_RUNTIME |
| Work Level | L2 |
| GitHub Issue | #2 |
| Branch | feature/test |
| Worktree | {{WORKTREE}} |
| Status | REQUIREMENT_READY |
| Required Env | - |
| Required Mounts | - |
| Created At | 2026-07-12 |
| Owner | test |

## 2. 任务类型
scheduler recovery runtime 跨模块修复

## 7. 涉及模块

**允许修改**：

- `scripts/ai/`
- `services/quant-api/app/workers/`

**禁止修改**：

- `.env`
- `data/raw/`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
git diff --check
```
