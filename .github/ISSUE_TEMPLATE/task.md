---
name: Task
about: 归一量化工作站标准任务 Issue
title: "TASK-xxxx："
labels: ["type/task", "status/requirement-ready"]
---

# TASK：任务标题

> 与本地 TASK 文件 1:1 绑定。本地标准源：`docs/tasks/` 或 `.ai/tasks/`。

---

## 1. Task ID

`TASK-YYYYMMDD-NNN-short-name`

---

## 2. Status

`REQUIREMENT_READY` | `PLAN_READY` | `APPROVED_DEV` | `CODING` | `TESTING` | `DELIVERY_READY` | `CLOSED` | `FAILED` | `REPLAN`

---

## 3. 背景

【为什么做这件事？当前痛点或触发原因】

---

## 4. 目标

【完成后应达到的可验证结果，1–3 条】

---

## 5. 不做事项

- 不修改 `.env`、密钥、token、webhook
- 不自动 push、merge、release、部署
- 【任务特定排除项】

---

## 6. 涉及模块

允许修改：

-

禁止修改：

- `.env`、`.env.*`
- `data/raw/`、`data/processed/`、`data/parquet/`
- vn.py 源码

---

## 7. 技术方案

【实现思路、接口变更、依赖关系】

---

## 8. 数据影响

- 数据源：
- 聚合周期：
- 归档影响：
- 质量 Gate：

---

## 9. 配置影响

【是否涉及 `.env.example`、Docker、scheduler、worker 配置】

---

## 10. 开发步骤

1.
2.
3.

---

## 11. 测试清单

- [ ] `bash -n scripts/ai/*.sh`（若改脚本）
- [ ] `git diff --check`
- [ ] 【任务特定测试】

---

## 12. 验收标准

1.
2.
3.

---

## 13. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| P0 | | |
| P1 | | |
| P2 | | |

---

## 14. 执行记录

| 阶段 | 时间 | 操作者 | 说明 |
|------|------|--------|------|
| 任务创建 | | WorkBuddy | |
| Issue 创建 | | 用户 | |
| Plan 完成 | | CodeBuddy | |
| Dev 完成 | | CodeBuddy | |
| 测试 | | CodeBuddy | |
| 交付报告 | | WorkBuddy | |
| 关闭 | | 用户 | |

---

## 15. 交付记录

【WorkBuddy 正式交付报告摘要；CodeBuddy 执行摘要、测试结果回填评论】
