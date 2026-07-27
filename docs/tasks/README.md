# 任务契约目录

本目录**根目录只存放当前仍在推进的活跃任务**契约；已完成 / 已收口 / 已被取代的历史任务全部移入 `archive/`，索引见 `archive/INDEX.md`。

任务生命周期以 **GitHub Issue / PR** 为准；项目状态与未关闭 Gate 以 `STATUS.md` 为准（历史叙事见 `STATUS_ARCHIVE.md`）。开发流程见 `docs/DEVELOPMENT.md`。

## 当前活跃任务（根目录）

锚定 `STATUS.md` 未关闭 / 阻塞 Gate：

- `V1-HTDY-04-S6-08-SCHEMA-V3-GATE.md`、`JM-LIVE-SIGNAL-EVENT-S6-08.md`、`V1-HTDY-REALTIME-INTEGRATION-CLOSEOUT.md` — S6-08 自然 first-seen event + 一次幂等探测的下一入口与实时集成收口锚点。
- `JM-LIVE-WECOM-SINGLE-S6-09.md` — S6-09 企业微信单条发送（串行、须精确批准）。
- `JM-LIVE-STABILITY-S6-10.md` — S6-10 五交易日长稳。
- `V1-DATA-REAUDIT-STATUS-001.md` — Audit V2 / 全历史 residual triage 状态锚点。
- `V1-FINAL-ACCEPTANCE-S6-11.md` — V1 最终验收。
- `S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md` — 数据库 revision/binding/checkpoint 当前事实锚点。

历史任务不在此列出，请查 `archive/INDEX.md`。

## 何时需要任务文件

适用：策略公式、回测口径、数据库 / migration、数据湖写入、live 表、企业微信真实发送等。

命名建议：`docs/tasks/<TASK_ID>.md`（与 Issue 标题或编号可对读）。

## 相关入口

- 工程规则：`AGENTS.md`
- 开发流程：`docs/DEVELOPMENT.md`
- 当前状态：`STATUS.md`

旧工作站控制面协议、workflows、GPT 摘要已从 active tree 删除；勿再引用。
