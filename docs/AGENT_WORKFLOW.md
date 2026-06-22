# AI Agent 协作流程

## 工具分工

- Cursor：主 IDE / 人工控制
- Codex：主力开发
- Claude Code：审查和复杂逻辑检查
- WorkBuddy：截图 UI Bug 修复

## 禁止

1. 不允许多个 Agent 同时修改同一个文件。
2. 不允许 WorkBuddy 做大架构。
3. 不允许 Claude Code 默认直接改文件。
4. 不允许 Agent 接实盘自动交易。
5. 不允许提交任何账号密码和 API Key。

## 标准流程

1. 创建任务文件
2. Git checkpoint
3. Codex 开发
4. Cursor 查看 diff
5. Claude Code 审查
6. WorkBuddy 修 UI
7. 人工测试
8. Git commit