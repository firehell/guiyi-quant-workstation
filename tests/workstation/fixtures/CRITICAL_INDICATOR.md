# CRITICAL_INDICATOR: EMA/MACD warm-up task

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | CRITICAL_INDICATOR |
| Work Level | L2 |
| GitHub Issue | #3 |
| Branch | feature/test |
| Worktree | {{WORKTREE}} |
| Status | TESTING |
| Critical | true |
| Required Env | - |
| Required Mounts | - |
| Created At | 2026-07-12 |
| Owner | test |

## 2. 任务类型
指标开发

## 5. 目标
实现 EMA/MACD seed 和 warm-up 逻辑。

## 7. 涉及模块

**允许修改**：

- `services/quant-api/app/indicators/`
- `tests/workstation/`

**禁止修改**：

- `.env`
- `data/raw/`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
git diff --check
```
