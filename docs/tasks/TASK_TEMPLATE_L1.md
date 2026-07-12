# TASK-{{日期}}-{{编号}}：{{任务名称}}（L1 轻量）

> L1 居家快速开发模板。完整交付请升级到 L2 并使用 [`TASK_TEMPLATE.md`](TASK_TEMPLATE.md)。

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-{{日期}}-{{编号}} |
| Work Level | L1 |
| GitHub Issue | 待创建（L1 可选；升级 L2 前必须回填 #N） |
| Branch | feature/{{slug}} |
| Worktree | 待 init_task_worktree.sh 回填 |
| Status | REQUIREMENT_READY |
| Created At | {{YYYY-MM-DD}} |
| Owner | local-user |

---

## 0.1 机器可读元数据

> L1 新任务应维护本 JSON 块；旧 Markdown 表格仍可被兼容读取。

```json
{
  "schema_version": 1,
  "task_id": "TASK-{{日期}}-{{编号}}",
  "work_level": "L1",
  "github_issue": "待创建",
  "branch": "feature/{{slug}}",
  "worktree": "待 init_task_worktree.sh 回填",
  "status": "REQUIREMENT_READY",
  "owner": "local-user",
  "allowed_paths": [
    "{{ path }}"
  ],
  "forbidden_paths": [
    ".env",
    ".env.*",
    "data/raw/",
    "data/parquet/",
    "data/processed/"
  ],
  "routing": {
    "requested_tier": "auto",
    "allow_auto_escalation": true,
    "max_auto_escalations": 1
  },
  "permissions": {
    "production_access_allowed": false,
    "database_write_allowed": false,
    "external_network_allowed": false,
    "push_allowed": false,
    "merge_allowed": false,
    "deploy_allowed": false,
    "trading_execution_allowed": false
  }
}
```

## 5. 目标

{{ 可量化 / 可验收的产出 }}

## 6. 不做事项

{{ Non-goals：明确不自动交易 / 不自动 push / 不碰数据等 }}

## 7. 涉及模块

**允许修改**：

- `{{ path }}`

**禁止修改**：

- `.env`、`.env.*`
- `data/raw/`、`data/parquet/`、`data/processed/`
- 未列出的业务模块

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
git diff --check
```

## 19. 验收标准

{{ pass / block 条件 }}

## 20. 风险点

{{ 重绘 / 未来函数 / 凭证泄露 / 越界等 }}
