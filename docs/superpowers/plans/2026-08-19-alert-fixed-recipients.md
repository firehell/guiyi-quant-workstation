# Alert 固定收件人简化实施计划

日期：2026-08-20

设计：`docs/superpowers/specs/2026-08-19-alert-fixed-recipients-design.md`

状态：Tasks 1–4 repository complete；external rollout not started

## Goal

在不新增数据库 schema、不改变 HTDY/SuBing evaluator/Scope/Event 合同的前提下，把 Clawbot 私聊扩展为
最多四位固定收件人：`owner + 最多 3 位朋友`。HTDY 通知全部 active alias；SuBing 保持 owner-only。

## Global constraints

- Task 只允许仓库代码、测试和文档；不读取或写入正式 recipients/owner/context 配置；
- 不执行真实 init、prepare、confirm、retire、preflight、canary、send、release/tag 或 Runtime switch；
- 不连接 production DB，不修改 Rule/Scope/Canonical/Redis/OpenClaw/plugin；
- 每个 alias 最多一个 child、一次 provider primitive；失败不 retry、queue、replay、backfill 或 fallback；
- Alert Runtime 停止后，才允许单 operator 串行修改 private config；运行中不热重载；
- Alert Application Domain 保持两表，不新增逐收件人持久化事实；
- 任何实际外部操作都需要操作前的范围明确、单次使用执行意图。

## Task 1 — Frozen v2 directory

状态：complete

交付：

- 新增严格 v2 directory loader、安全 I/O、`1..4` 人数与 owner-first 路由；
- HTDY 返回全部 active alias，SuBing 只返回 owner，未知 Rule fail-closed；
- owner-only initializer 只从现有安全 v1 owner source 创建 v2 文件，不覆盖已存在文件；
- active Clawbot dependency 只读取 `GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH`；
- repr、日志与错误不暴露 account、target 或 private path。

主要文件：

- `services/quant-api/app/alerts/recipients.py`
- `services/quant-api/app/alerts/clawbot.py`
- `services/quant-api/tests/test_alert_recipients.py`
- `services/quant-api/tests/test_alert_clawbot.py`

## Task 2 — Two-snapshot friend pairing

状态：complete

交付：

- Node `snapshot_contexts` 只返回给受控 Python parent 的 direct ID/context 数据，不读取消息正文；
- prepare 用随机 nonce + HMAC-SHA256 写入十分钟 fingerprint staging；
- confirm 重新 snapshot，必须恰有一个新增或 token 变化 candidate，并安全原子更新 v2 directory；
- owner 不可 retire，retired alias 不可复用；
- CLI 固定为 `recipients init|prepare|confirm|retire`，mutation 输出只含公开 alias/计数；
- 单 operator、stopped Runtime 边界下不增加后台进程或恢复机制。

主要文件：

- `services/quant-api/app/alerts/recipient_bootstrap.py`
- `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`
- `services/quant-api/app/guiyi_cli/main.py`
- 对应 Python/Node tests

## Task 3 — HTDY fan-out and frozen Runtime identity

状态：complete

交付：

- `ClawbotAlertSender` 是唯一 fan-out owner；HTDY owner-first 顺序发送全部 active alias；
- SuBing 保持 owner-only；每个 alias 一次 runner call，普通失败隔离并继续后续 alias；
- Runtime 构造只加载目录一次，并在返回 sender 前对全部 active alias 完成 zero-send preflight；
- canary 强制显式 `--alias`，一次命令最多向该 active alias 发送一次；
- health 只做结构读取并输出 configured/count/ready/would-send；
- launchd templates 和 macOS scripts 的 active identity 只使用 recipients path；
- HTDY 正文精确追加“研究观察，非交易指令”。

部分送达风险保留为运行时公开摘要和人工确认，不写入逐人 DB，不自动补发。

## Task 4 — Canonical docs and complete local verification

状态：complete

允许修改：

- `AGENTS.md`
- `STATUS.md`
- `TESTING.md`
- 本 design 与 plan

完成标准：

- active canonical 只保留本简化模型；
- production 明确保持 `v1.6.2` 单 owner exact Runtime；
- develop 只标记 `CODE_COMPLETE / TEST_COMPLETE`；
- fresh 全 backend、全 engineering、Node、Ruff、正常 follow-imports Mypy、ops shell、active plist、
  secret scan 和 diff check 全部通过；
- 所有真实 init/prepare/confirm/preflight/canary/release/Runtime Gate 明确 pending；
- scoped docs commit 后进入独立 review，不 push/merge/release/promotion。

## External rollout — not executed

未来如要启用，必须按以下独立步骤重新取得精确执行意图：

```text
owner-only v2 init
-> friend 1 prepare -> normal inbound message -> friend 1 confirm
-> friend 2 prepare -> normal inbound message -> friend 2 confirm
-> friend 3 prepare -> normal inbound message -> friend 3 confirm
-> all-recipient zero-send preflight
-> one exact-alias canary per newly authorized recipient
-> exact HTDY Rule + Scope + alias set + transport authorization
-> main/release/tag
-> exact-tag Alert Runtime switch/readback
-> natural HTDY acceptance
```

人数可以小于四人；不得为凑满人数跳过 pairing 或 readiness。SuBing 在全部阶段仍只通知 owner。任一步
失败都停在原 production 单 owner Runtime，不自动重试或继续后续步骤。
