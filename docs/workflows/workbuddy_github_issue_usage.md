# WorkBuddy + GitHub Issue 用法（V1.2）

> WorkBuddy 在 V1.1 任务单 / 交付报告基础上，额外输出 GitHub Issue 相关内容。WorkBuddy **不**调用 `gh`、**不**创建 Issue、**不**修改本地代码。

主流程见 [`ai_delivery_workflow.md`](ai_delivery_workflow.md)、[`github_issue_trace_workflow.md`](github_issue_trace_workflow.md)。

---

## 命令 A：生成任务单（额外输出）

WorkBuddy 生成标准 TASK 后，**额外**输出以下块，供用户或 CodeBuddy 创建 Issue：

### 1. GitHub Issue 标题

格式：

```text
TASK-YYYYMMDD-NNN：简短任务标题
```

示例：

```text
TASK-20260709-002：工作站 V1.2 GitHub Issue 留痕
```

### 2. GitHub Issue Body

- 与 TASK 正文一致，或 TASK 全文复制
- 确保包含：背景、目标、不做事项、涉及模块、验收标准、风险点
- 用户可用 `scripts/ai/create_issue_from_task.sh` 直接从 TASK 文件创建，无需手贴

### 3. 建议 labels

至少包含：

```text
type/task
status/requirement-ready
area/<模块>        # 如 area/workstation、area/data
risk/<级别>        # 如 risk/low、risk/medium、risk/high
ai/workbuddy      # 任务由 WorkBuddy 生成时
```

完整列表见 [`github_labels.md`](github_labels.md)。

### 4. 是否需要拆分多个 Issue

说明：

- 本 TASK 是否应拆成多个 Issue（默认 **否**，1 TASK = 1 Issue）
- 若建议拆分，列出子任务标题与依赖关系

### 5. 是否需要后续任务

说明：

- 本 TASK 完成后是否应新建后续 TASK / Issue
- 后续任务建议标题与触发条件

---

## 命令 B：生成交付报告（额外输出）

WorkBuddy 生成正式交付报告后，**额外**输出：

### 1. 适合回填到 GitHub Issue 的版本

- Markdown 格式，适合 `comment_issue_result.sh delivery` 或手贴 Issue 评论
- 结构建议：

```markdown
## 交付报告 — <TASK_ID>

### 完成情况
- ...

### 变更文件
- ...

### 测试结果
- ...

### 风险与遗留
- ...

### 下一步建议
- ...
```

- 同时保存到 `.ai/results/<TASK_ID>/delivery_report.md`（供脚本读取）

### 2. 是否建议关闭 Issue

```text
建议关闭：是 / 否
理由：...
```

- 默认 **否**，由用户最终决定
- 仅当验收标准全部满足且无遗留 P0/P1 时，可建议关闭

### 3. 是否建议新建后续 Issue

```text
建议新建后续 Issue：是 / 否
建议标题：TASK-YYYYMMDD-NNN-...
触发条件：...
```

---

## WorkBuddy 与 CodeBuddy 边界

| 动作 | WorkBuddy | CodeBuddy |
|------|-----------|-----------|
| 生成 TASK | 是 | 否 |
| 创建 GitHub Issue | 否 | 脚本（用户触发） |
| 回填 Issue 评论 | 否（只提供 delivery 文本） | 是（脚本） |
| 更新 Issue label | 否 | 是（脚本） |
| 关闭 Issue | 否 | 否（仅用户） |
| 本地 plan / dev | 否 | 是 |

---

## 相关文档

- 任务模板：[`docs/tasks/TASK_TEMPLATE.md`](../tasks/TASK_TEMPLATE.md)
- WorkBuddy 角色：[`workbuddy_role.md`](workbuddy_role.md)
- Issue 留痕流程：[`github_issue_trace_workflow.md`](github_issue_trace_workflow.md)
