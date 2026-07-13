# TASK-2026-07-11-002: Lean V1 端到端 Demo

> 任务状态：APPROVED_DEV

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-002 |
| GitHub Issue | #2 |
| Branch | feature/lean-v1-demo |
| Worktree | /Volumes/扩展盘/guiyi-parallel/lean-v1-demo |
| Status | APPROVED_DEV |
| Work Level | L2 |
| Critical | false |
| Production Write Approved | false |

---

## 1. 任务状态
APPROVED_DEV

## 2. 任务类型
Lean V1 端到端验证任务

## 7. Scope（允许/禁止修改）
- `services/quant-api/tests/`
- **禁止修改**: `services/`, `data/`, `.env`

## 10. 数据影响
无数据影响（只读）

## 14. 开发步骤
1. 在 feature/lean-v1-demo 分支工作
2. 修改测试文件
3. 不提交

## 18. 测试命令
```bash
cd services/quant-api && python -m pytest tests/ -v
```
