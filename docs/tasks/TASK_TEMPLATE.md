# TASK 标准任务单模板

> 配套：`docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`、`docs/workstation/WORKBUDDY_UNIFIED_V3.md`、`docs/workflows/status_machine.md`。
> 用法：复制本模板，替换 `{{ }}` 占位符；状态流转以 dispatcher / TASK / Issue / PR 为准；参与专家由 WorkBuddy 按 TASK/route 选择最少必要集合。
> 所有 Prompt（第 15–17 节）必须遵守 allowed paths / forbidden paths、审批 Gate 与测试要求。
> **WorkBuddy 只做 intake、协调、QA、视觉验收和交付摘要；核心代码由 Codex 执行；不 push / merge / deploy。**

---

````markdown
# TASK-{{日期}}-{{编号}}：{{任务名称}}

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-{{日期}}-{{编号}} |
| Work Level | L2 |
| GitHub Issue | #{{N}} |
| Branch | feature/{{slug}} |
| Worktree | {{由 init_task_worktree.sh 回填}} |
| Status | {{状态}} |
| Required Env | {{如 `DATABASE_URL`, `POSTGRES_PASSWORD`；无则填 `-`}} |
| Required Mounts | {{如 `/Volumes/扩展盘`；无则填 `-`}} |
| Created At | {{YYYY-MM-DD}} |
| Owner | WorkBuddy |

## 0.1 机器可读元数据

> 新任务应维护本 JSON 块；旧 Markdown 表格仍可被兼容读取。

```json
{
  "schema_version": 1,
  "task_id": "TASK-{{日期}}-{{编号}}",
  "work_level": "L2",
  "github_issue": "#{{N}}",
  "branch": "feature/{{slug}}",
  "worktree": "{{由 init_task_worktree.sh 回填}}",
  "status": "{{状态}}",
  "owner": "WorkBuddy",
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

## 1. 任务状态
{{ IDEA / REQUIREMENT_READY / PLAN_READY / APPROVED_DEV / CODING / TESTING / DELIVERY_READY / CLOSED / FAILED / REPLAN }}

## 2. 任务类型
{{ 普通功能开发 / 数据模块开发 / 实时行情监听 / 多周期聚合 / 策略开发 / 策略研究与验证 / 企业微信告警 / Dashboard / 回测模块 / 数据质量检查 / Mac mini 部署 / AI 工作流优化 / WorkBuddy 协调 / GitHub 版本管理 / 安全权限 / 测试体系 / 交互视觉规范 / 阶段交付复盘 }}
参照：`docs/workstation/WORKBUDDY_UNIFIED_V3.md` 与 route 结果。

## 3. 参与角色
- 必须：{{ PM, PO, QA, ... }}（按 TASK/route 选择最少必要专家）
- 可选：{{ ... }}
- 不需要：{{ ... }}

## 4. 背景
{{ 为什么做、来源想法、关联历史任务 / Stage }}

## 5. 目标
{{ 可量化 / 可验收的产出 }}

## 6. 不做事项
{{ Non-goals：明确不做的范围，尤其是"不自动交易 / 不自动 push"等 }}

## 7. 涉及模块
{{ 代码模块 / 接口 / 文件，如 services/quant-api/app/signal/* }}

## 8. 产品需求
{{ PRD：场景 / 边界 / 验收目标 }}

## 9. 量化业务规则
{{ 交易时段 / 夜盘 / 节假日 / 主力合约 / 切换 / 手续费 / 滑点 / 乘数 / 保证金 }}

## 10. 数据影响
{{ RQData 使用 / 1m 基础 / 聚合 / 归档 / 缺失重复 bar / active Gate / 是否真实写入（dry-run 默认） }}

## 11. 技术方案
{{ 架构方案 / 模块边界 / 接口契约 / 数据流·策略流·信号流·告警流 }}

## 12. 交互视觉要求
{{ 信息架构 / 消息格式 / 状态颜色（红涨绿跌）/ 展示规范 }}（页面 / 告警类必填）

## 13. 安全权限要求
{{ 不碰 .env/token/webhook / 不删数据 / 不自动 push-merge-deploy / dry-run 默认 / 脱敏 }}（外部 / 凭证类必填）

## 14. 开发步骤
1. {{ step }}
2. {{ step }}
（每步标注是否需用户显式授权）

## 15. Codex Plan Prompt
```
{{ 只读 plan 提示词：分析仓库、产出方案，不修改代码 }}
```

## 16. Codex Dev Prompt
```
{{ 开发提示词：按方案实现，默认 dry-run，明确测试点 }}
```

## 17. WorkBuddy / Codex 执行 Prompt
```
{{ 固定入口提示词：WorkBuddy 仅调用白名单 facade；核心代码由 Codex 执行；声明不自由 shell / 不 push / 不 merge }}
```

## 18. 测试清单

### 18.0 自动化测试命令

`run_tests.sh` 只解析本标题下第一个 fenced `bash` 代码块。每行一条命令；禁止危险命令、网络命令、重定向和 shell 命令组合。

```bash
bash -n scripts/ai/*.sh
grep -rE 'pattern' scripts/ai/ --include='*.sh'
git diff --stat
git diff --check
```

- [ ] {{ 单元测试 }}
- [ ] {{ 集成测试 }}
- [ ] {{ 回归测试 }}
- [ ] {{ 烟测 }}
- [ ] {{ 专项：数据聚合正确性 / 信号准确性 / 企业微信重复漏发误发 / Mac mini 稳定性 }}

## 19. 验收标准
{{ 明确 pass / block 条件；引用 PRD 验收目标 }}

## 20. 风险点
{{ 重绘 / 未来函数 / 过拟合 / 夜盘跨日 / active 未分层 / 凭证泄露 / 越权发送 / 自动部署 }}

## 21. 交付记录
- 状态流转：{{ IDEA → ... → CLOSED }}
- 测试结论：{{ pass / block }}
- 交付报告：{{ 链接 / 摘要 }}
- 合并前检查：{{ git diff --check / 测试通过 / 无敏感泄露 }}
- 用户 review：{{ 待 / 已 merge / 已 deploy }}
- 下一阶段建议：{{ ... }}
````

---

## 使用说明

- 本模板与 GitHub Native Control Plane / WorkBuddy Unified V3 配套：TASK 定执行契约，Issue 定生命周期，Draft PR/PR 定交付容器。
- 任务编号统一 `GQ-YYYYMMDD-NNN`（或 `TASK-YYYYMMDD-NNN` / 工作站命名空间），由任务创建方在 Issue/TASK 中分配，不重复、不跳号。
- **状态门控铁律**：Plan Prompt 在 `PLAN_READY` 启用（只读）；Dev / Exec Prompt 在 `APPROVED_DEV` 才启用。
- 所有"真实写入 / 发送 / 部署 / 回滚"动作默认需用户显式授权；模板第 13、14、20 节必须显式声明。
