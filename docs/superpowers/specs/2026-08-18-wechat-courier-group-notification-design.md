# 微信群 WeChat-Courier 通知设计规格

> 状态：Design Approved / D1 Replan
>
> 日期：2026-08-18
>
> 基线：当前生产 Runtime 仍按 `STATUS.md` 记录的 exact tag/commit 使用 WeCom。当前开发任务已执行到旧 iLink D1 的 Task 5–6 附近，但相关实现尚未形成 `develop` 的正式 active contract；本设计要求立即停止继续扩展旧 iLink 路线，并按本文收口当前 task worktree。

## 1. 背景与目标

归一量化只需要把已经由 Alert Runtime 确定的研究观察提醒发送给固定微信群，不需要聊天机器人、群消息读取、AI 回复、多用户 DM 路由或 iLink session 管理。

新的长期目标：

- 使用 macOS 官方 WeChat.app + 开源 `bladydora/WeChat-Courier-macOS`，把正式 Alert 单向发送到一个固定微信群；
- V1 只有一个通知目标：`primary_alert_group`；群成员由微信自身管理，归一量化不维护四人 recipient；
- 最终移除 active WeCom，不保留 fallback；
- 不使用 OpenClaw、Tencent iLink、`openclaw-weixin`、recipient registry、registration challenge、`context_token`、`getUpdates` 或 `WeixinContextMonitor`；
- 保持 Alert Event-first、每个新 `AlertEvent` 最多一次物理发送尝试、无 notification retry/replay/backfill/outbox/queue；
- 真实群名不进 Git、DB、日志或错误输出，只保存在 Mac mini 私有配置；
- WeChat-Courier、其 Python venv、临时截图和 Swift cache 尽量位于扩展盘；
- 不建设群聊 bot、AI agent、MCP、HTTP bridge、消息监听、文件发送或多群路由。

本设计完全替代 2026-08-18 iLink 四人私聊方向。旧 iLink spec、code plan、rollout plan 删除，不保留 Superseded active 文档；历史只通过 Git history 追溯。

---

## 2. 已冻结核心决策

### 2.1 单一微信群

V1 只有一个群：

```text
任何正式 Alert
→ primary_alert_group
→ 1 次微信群发送尝试
```

不实现：

- 4 人 DM fan-out；
- 按 Rule / 品种 / 用户分组；
- 多群 broadcast；
- 群成员同步；
- recipient DB；
- 群内 inbound 监听与自动回复。

### 2.2 WeChat-Courier 作为外部本地 transport

审阅基线：

```text
repository: bladydora/WeChat-Courier-macOS
commit: 981bd14e238302b2a0e206cb5f28e8e2505bb874
license: MIT
```

正式运行只允许使用经过兼容性验证并 pin 的 exact commit；不得运行 `main`、latest 或自动更新。

WeChat-Courier 本身使用官方 WeChat.app + AppleScript/System Events + 本地截图/OCR；不实现微信协议 bot。上游支持联系人/群聊发送、搜索目标、OCR 目标验证以及默认删除截图。

### 2.3 不直接信任上游 fuzzy target match

上游 `text_matches_target()` 使用 normalized substring match，搜索结果存在多个匹配时会选择最上方匹配项。这不满足归一量化“宁可漏发，不能错群”的 fail-closed 要求。

因此生产不得直接执行上游 `skills/wechat-courier/scripts/send_wechat.py` 作为最终安全边界。

全仓库只有一个项目自有 hardening adapter：

```text
services/quant-api/app/alerts/wechat_courier_adapter.py
```

允许依赖 pinned WeChat-Courier 的窄内部函数，并负责：

- exact commit / exact function-shape compatibility；
- 微信首页可见聊天列表严格唯一匹配；
- 当前聊天标题严格二次确认；
- safety crop reject；
- stdout/stderr/raw OCR 脱敏；
- 单次物理发送；
- 默认删除 OCR screenshot；
- 不调用 queue/watcher/retry_request/MCP/HTTP bridge。

### 2.4 严格目标匹配

目标匹配采用项目自己的 canonical normalization：

```text
Unicode NFKC
→ trim
→ collapse whitespace
→ remove only visual spacing/punctuation allowed by explicit rule
```

首页聊天列表阶段：目标群必须由用户保持置顶，并在当前可见范围内，无需滚动。adapter 只退出已有搜索/浮层，不输入群名、不搜索、不滚动；随后只截取左侧可见聊天列表。多个置顶群允许共存，但必须恰好存在 1 个 OCR box，其 normalized text 与 `target_chat` normalized value 相等。0 个或 >1 个均失败。

标题阶段：必须存在且仅存在一个标题候选，满足：

```text
exact normalized target
或
exact normalized target + trailing member-count suffix
```

允许的 member-count suffix 仅：`(N)` / `（N）`，其中 N 为正整数。不得使用 substring/fuzzy/first-result fallback。

如果目标不在可见首页、同名联系人/同名群、近似群、OCR 拆字、标题无法唯一确认，统一 fail-closed：

```text
WECHAT_GROUP_TARGET_UNVERIFIED
```

### 2.5 单次发送，不使用上游 queue/retry

禁止使用：

```text
watcher.py
enqueue_send.py
wcq.py
retry_request.py
MCP server
HTTP bridge
任何上游 queue mode
```

Alert sender 每次只启动一次项目 adapter；adapter 在目标验证通过后只调用一次上游文本发送 primitive。

OCR 验证允许在一次发送尝试内部做最多 3 次读取重试，因为它们不产生外部消息；一旦执行 Enter/send，不得自动重新发送。

### 2.6 GUI 自动化并发锁

WeChat GUI 自动化不能并发。

项目 adapter 必须使用 non-blocking process lock：

```text
<GUIYI_WECHAT_COURIER_ROOT>/runtime/guiyi-wechat-courier.lock
```

获取失败立即返回：

```text
WECHAT_COURIER_BUSY
```

不得排队等待、不得稍后 retry。这样 canary、自然 Alert 或人工测试不会同时抢占 WeChat。

---

## 3. 总体架构

```text
Market / Indicator / Signal
          │
          ▼
     Alert Evaluator
          │
          ▼
     AlertEvent commit
          │
          ▼
AlertNotificationMessage
          │
          ▼
 AlertNotificationSender
          │
          ▼
  WeChatGroupAlertSender
          │
          ▼
  WeChatCourierRunner
          │ stdin JSON
          ▼
wechat_courier_adapter.py
          │
          ├─ unique exact visible home-chat OCR
          ├─ exact title OCR verification
          ├─ local safety reject
          └─ single send primitive
          │
          ▼
 pinned WeChat-Courier
          │
          ▼
 official WeChat.app
          │
          ▼
 primary_alert_group
```

不存在 OpenClaw Gateway、Agent、LLM、iLink、context monitor、recipient fan-out 或群消息 inbound。

---

## 4. 私有群配置

生产路径：

```text
/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json
```

父目录：`0700`；文件：`0600`；拒绝 symlink / 非 regular file。

Schema：

```json
{
  "version": 1,
  "channel": "wechat-courier",
  "group_alias": "primary_alert_group",
  "target_chat": "<private exact WeChat group title>"
}
```

仓库、日志和公开 CLI 只显示 `group_alias`，不得显示 `target_chat`。

V1 只接受：

```text
group_alias == primary_alert_group
channel == wechat-courier
```

Runtime 启动时读取一次并冻结，不 hot reload。群名变更需要新配置 mutation + 新目标验证 Gate + Runtime reload；运行中修改文件不会自动改变当前 sender。

---

## 5. 外部依赖布局

生产推荐：

```text
/Volumes/扩展盘/wechat-courier/
├── source/          # detached exact upstream commit
├── venv/            # dedicated Python environment
├── runtime/         # lock and local runtime-only state
├── tmp/             # screenshots/temp
└── cache/
    └── clang/       # Swift module cache
```

应用只通过环境变量定位：

```text
GUIYI_WECHAT_COURIER_ROOT=/Volumes/扩展盘/wechat-courier
GUIYI_ALERT_WECHAT_GROUP_PATH=/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json
```

Adapter child 运行环境显式设置：

```text
TMPDIR=<root>/tmp
CLANG_MODULE_CACHE_PATH=<root>/cache/clang
PATH=<root>/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

不依赖 shell profile，不把真实群名放 argv；目标和消息通过 stdin JSON 传入。

D1 只实现 dependency contract 和 fake tests，不执行真实 clone/install/TCC/UI 操作。真实安装与 macOS 权限属于后续独立 Gate。

---

## 6. 通知领域合同

保留旧 D1 Task 1 已抽离的通用层：

```text
AlertNotificationMessage
AlertNotificationSender Protocol
format_alert_message()
ALERT_CANARY_TEXT
```

这些与 transport 无关，继续复用。

新 sender：

```python
class WeChatGroupAlertSender:
    def send(self, message: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> WeChatGroupSendSummary: ...
```

结果语义：

```text
attempted=1
automation_completed=0|1
failed=0|1
failed_aliases=[]|["primary_alert_group"]
```

`automation_completed=1` 只表示本机验证并执行发送动作完成，不代表腾讯服务端 delivered/read。真实 canary 仍需人工确认群内收到。

---

## 7. Event-first 与失败语义

保持当前 Alert V2：

```text
new Event commit
→ notification attempt
→ success / failure
→ end
```

失败不得：

- rollback 已提交 Event；
- 再次按 Enter；
- queue；
- retry；
- replay；
- backfill；
- provider failover。

`WeChatGroupAlertSender.send()` 失败统一抛稳定脱敏错误；`AlertRuntime` 继续捕获并记录 `ALERT_NOTIFICATION_FAILED`。

多个 Rule 在同一个 Bar 产生多条新 Event 时，现有 Runtime 的 message list 顺序逐条调用 sender；GUI lock 防止跨进程并发，不建设消息队列。

---

## 8. 隐私与日志

禁止进入 Git/chat/application log：

```text
真实微信群名
首页聊天列表 OCR 原文
聊天标题 OCR 原文
其他会话名称
截图
Alert 完整消息正文
AppleScript/raw subprocess stderr
```

允许：

```text
group_alias=primary_alert_group
WECHAT_GROUP_TARGET_UNVERIFIED
WECHAT_COURIER_BUSY
WECHAT_COURIER_DEPENDENCY_INVALID
WECHAT_COURIER_SEND_FAILED
elapsed_ms
```

项目 runner 必须 capture/discard 上游 stdout/stderr；不能把上游会打印的 OCR、target 或 `Sent via WeChat to ...` 原样透出。

截图默认由上游 helper 删除；项目 adapter 禁止 `--retain-ocr-screenshot`、`--screenshot`、`--after-screenshot` 等生产路径。

---

## 9. WeCom 退役边界

源码层：新 WeChatGroup sender 完成并验证后，`develop` 删除 active WeCom sender/config/canary references。

正式运行层：当前 exact-tag Runtime 继续 WeCom，直到未来新 exact-tag Runtime 完成 promotion。

因此迁移期间允许：

```text
develop = WeChat-Courier group architecture
production exact-tag Runtime = existing WeCom architecture
```

只有 promotion 成功后 `STATUS.md` 才能声明 WeCom 退出 active Runtime。

---

## 10. 当前旧 D1 Task 5–6 的转轨规则

当前执行中的 task worktree 必须停止继续旧 iLink Task 5–6，并先做 transition audit。

保留：

- `notification.py` 及其 formatter/model tests；
- `AlertRuntime.sender` 对 `AlertNotificationSender` Protocol 的通用化（如果已经实现）；
- 与 transport 无关的测试增强。

删除或回退所有 iLink 专属实现：

```text
recipient_registry.py
weixin.py
weixin_context.py
openclaw_weixin_adapter.mjs
deploy/openclaw/**
com.guiyi.quant-weixin-context.plist.template
weixin-register CLI
weixin-context CLI
GUIYI_OPENCLAW_ROOT / GUIYI_ALERT_RECIPIENTS_PATH wiring
对应 tests/engineering tests
```

如果 Task 5–6 仍有未提交改动，只做路径级、hunk 级定向清理；禁止 `git reset --hard`、`git clean -fd`、整树 checkout 或覆盖其他任务/用户未提交内容。

旧 WeCom 在新 sender ready 前不得提前删除。

---

## 11. 测试策略

D1 全部使用 fake Courier tree / mocked child process / temp private config；不触发真实 WeChat。

必须覆盖：

- config 权限/schema/symlink/alias/channel 校验；
- exact pinned commit identity；
- visible home-chat list 0/1/>1 exact 匹配；
- multiple pinned chats / near-name / split OCR / no-scroll fail-closed；
- title exact + member-count suffix；
- near-match / same-prefix / same-name ambiguity fail-closed；
- raw OCR/stdout/stderr 不泄露；
- screenshot cleanup；
- non-blocking GUI lock；
- one Alert -> one child -> at most one send primitive；
- target verify failure -> zero send；
- child timeout/crash -> no retry；
- Event commit survives notification failure；
- canary JSON uses `automation_completed`, not delivered/provider accepted；
- launchd receives identical Courier root/group config path；
- active iLink/OpenClaw references are zero after transition；
- active WeCom references are zero only after new sender Task completes；
- evaluator/Scope/DB/order boundaries unchanged。

---

## 12. D1 完成后的下一阶段

D1 只完成代码与本地 fake verification。D1 PASS 后再单独写新的微信群 rollout plan，不复用旧 iLink rollout。

新的实际 Gate 顺序应是：

```text
G2 install exact WeChat-Courier on expansion disk
→ G3 macOS permissions + P0 visible pinned-chat/OCR exact verify, no send
→ G4 one real group canary + human receipt
→ G5 stability matrix
   - target remains pinned and visible among multiple pinned chats
   - another chat currently open
   - near-name decoy group
   - WeChat restart/warm state
   - Mac/launchd restart as needed
→ G6 release main/tag
→ G7 continuous WeChat-group notification authorization
→ G8 exact-tag Runtime promotion
```

任何 P0/canary/stability failure均阻塞生产替换；不得退化为 fuzzy match、first result、坐标-only 或无验证发送。

---

## 13. 验收标准

设计完成后的最终代码必须满足：

1. HTDY/SuBing evaluator、Rule code、Scope、Alert 两表与 `auto_order=false` 不变。
2. `AlertRuntime` 依赖 transport-neutral sender Protocol。
3. V1 只存在一个群 alias：`primary_alert_group`。
4. 真实群名仅来自 `0600` 私有文件，Runtime 启动时冻结。
5. WeChat-Courier exact commit pinned；main/latest/auto-update 禁止。
6. 项目 adapter 对首页可见聊天列表与标题执行严格唯一验证，不搜索、不滚动，不直接依赖 upstream fuzzy match 作为最终安全边界。
7. 一条新 Event 最多一次物理 send primitive；OCR retry 不得导致 send retry。
8. 目标无法确认、同名/近似冲突、GUI busy、依赖漂移时 fail-closed。
9. 无 OpenClaw/iLink/context monitor/recipient fan-out/群 inbound/LLM。
10. 无 notification queue/retry/replay/backfill/outbox。
11. WeChat-Courier 主要安装、venv、tmp、cache 位于扩展盘。
12. D1 测试绝不真实操作 WeChat；真实 P0/canary 后续单独 Gate。
13. develop active iLink 文档与代码引用全部退役；历史仅 Git history 追溯。
14. 生产 WeCom 直到未来 exact-tag promotion 前保持现状，不提前改写 `STATUS.md`。
