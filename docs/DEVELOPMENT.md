# 个人开发与本地验证

本文只提供日常开发导航。工程授权与外部操作规则见 `AGENTS.md`；当前状态见
`STATUS.md`；产品和数据边界见 `PROJECT_SOURCE.md`、`DECISIONS.md` 及对应 deep
canonical；可执行命令见 `TESTING.md`。

## 日常 develop 流程

```text
develop
-> 检查 branch、worktree、dirty state 与最近提交
-> 保留并避开其他任务或用户已有修改
-> 只修改当前任务范围
-> 按影响运行本地验证
-> 提交并按需要推送 develop
```

普通源码、测试、文档和仓库内普通删除可按上述流程执行。删除前先关闭 active
references；历史恢复使用 Git，不建立 archive、backup 或 legacy-copy。

## 修改前检查

- 确认当前任务目标、允许范围、验收标准和禁止范围。
- 数据、策略、回测、Alert、Runtime 或发布语义有冲突时 fail-closed，并以对应
  canonical 和 `STATUS.md` 为准。
- 不读取、输出、提交或记录凭据；不覆盖、不清理无关 dirty paths。

## 按影响验证

- 文档或注释：引用检查、`git diff --check`，以及适用的 OpenSpec/secret scan。
- Web：定向 unit/E2E，再按风险运行完整 Web unit、Playwright 和 build。
- 后端：定向 pytest，再按风险运行模块/完整 pytest、Ruff 和 Mypy。
- 数据身份、策略、migration、Runtime、live 或通知：追加对应领域测试；isolated
  PostgreSQL 只按 `TESTING.md` 使用专用可销毁数据库。
- 任何必要检查失败时只报告失败，不声明完成。

测试、fake runner、route intercept、render-only、dry-run 和只读 health 都不授权真实
RQData、Canonical、DB、Redis、Scope、Runtime、通知或发布操作。

## 受控外部操作索引

以下操作必须在首次 mutation 前取得目标和范围明确的单次执行意图：

- 真实 RQData 下载、正式 Canonical 或生产数据库写入/删除；
- Runtime/live 启用、切换、promotion 或受控 Redis acknowledgment；
- Alert Scope/transport 变更或真实通知；
- main/tag/release、Git 历史重写、force update 或 GitHub rules 修改。

执行边界与持续授权只看 `AGENTS.md`；当前 release、Runtime、Scope、evidence 和
pending Gate 只看 `STATUS.md`。本页不复制业务合同。

## 相关入口

- 工程规则：`AGENTS.md`
- 当前状态：`STATUS.md`
- 产品与长期决策：`PROJECT_SOURCE.md`、`DECISIONS.md`
- 架构与数据：`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`
- active OpenSpec：`openspec/specs/`
- 验证命令：`TESTING.md`
- 本机部署导航：`deploy/README.md`
