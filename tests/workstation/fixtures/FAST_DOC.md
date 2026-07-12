# FAST_DOC: L0 documentation task

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | FAST_DOC |
| Work Level | L0 |
| GitHub Issue | - |
| Branch | feature/test |
| Worktree | {{WORKTREE}} |
| Status | APPROVED_DEV |
| Required Env | - |
| Required Mounts | - |
| Created At | 2026-07-12 |
| Owner | test |

## 2. 任务类型
文档修改

## 5. 目标
更新工作站说明文档。

## 7. 涉及模块

**允许修改**：

- `docs/workstation/`

**禁止修改**：

- `.env`
- `data/raw/`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
git diff --check
```
