# 微信 iLink Direct Notification 设计规格

> 状态：Design Approved / Not Implemented
>
> 日期：2026-08-18
>
> 基线：`develop` 当前 Alert Runtime V2；正式 Runtime 仍按 `STATUS.md` 记录的 exact tag/commit 运行。本文不代表 OpenClaw 安装、微信登录、recipient mutation、真实通知、release、持续授权或 Runtime promotion 已执行。

## 1. 背景与目标

归一量化是本地、单用户的国内期货量化研究工作站。Alert 只用于人工观察提醒，始终保持 `auto_order=false`，不创建或提交订单。

新的长期目标是：

- 使用 Tencent 官方 `openclaw-weixin` + iLink，把正式 Alert 发送到个人微信私聊；
- V1 recipient 固定为包括 owner 在内的 4 人，所有正式 Alert 全量同发；
- 最终移除 active WeCom，不保留 fallback；
- OpenClaw 只承担安装、配置与 QR 登录，不作为长期 Gateway/Agent Runtime；
- 长期 inbound 只用于刷新 approved recipient 的 `context_token`，绝不进入 Agent/LLM/Slash Command/Tool pipeline；
- 保持 Alert Event-first、每 recipient 最多一次发送尝试、无 replay/backfill/retry/outbox/queue；
- OpenClaw/Node/plugin/state/cache/tmp 尽量放扩展盘；
- 不提前建设通用消息平台、recipient DB、路由 DSL 或 Web 管理面。

本设计替代此前普通微信群 Peekaboo 方向；旧设计和 PoC 计划已从 active repository 文档删除，历史仅通过 Git history 追溯。

---

## 2. 已冻结核心决策

### 2.1 Recipient policy

V1 为一个全量 recipient set：

```text
任何正式 Alert
→ owner
→ member_2
→ member_3
→ member_4
```

不实现按 Rule、品种、用户偏好的分组路由。未来增加第 5 人只修改受控 recipient registry；未来新增 Alert Rule 自动复用同一 sender。

### 2.2 WeCom 退出

目标架构只保留 iLink direct DM。源码层在本任务实现中删除 active WeCom sender/config/canary reference；正式运行层继续保持旧 exact-tag Runtime 的 WeCom，直到新 exact-tag Runtime 完成 promotion。只有 promotion 成功后，`STATUS.md` 才能声明 WeCom 退出 active Runtime。

### 2.3 OpenClaw 不是长期 Gateway

不长期运行 OpenClaw Gateway，也不让任何微信 inbound 进入 OpenClaw Agent pipeline。

OpenClaw 仅作为受控外部依赖提供：

- rootless Node/OpenClaw CLI；
- official plugin install/inspect；
- `openclaw channels login --channel openclaw-weixin` QR 登录；
- plugin config/account credential/state 的官方落盘结构。

归一量化自己的代码负责 recipient registry、registration challenge、`getUpdates` context 维护、Alert message formatting、单次 `sendMessage` fan-out 与 privacy-safe error/status。

### 2.4 不走 OpenClaw durable `send`

不使用 OpenClaw Gateway `send` / message durable delivery。该路径具有 write-ahead queue、recovery/retry 语义，与当前 Alert no-queue/no-retry 合同冲突。

正式发送只经 pinned Tencent plugin 内部 `sendMessageWeixin()`，每个 `AlertEvent × recipient` 最多一次 physical send attempt。

### 2.5 不 fork Tencent plugin

不修改、不 vendoring、不 fork `Tencent/openclaw-weixin`。归一量化只通过一个版本锁定的 private adapter 复用其窄内部模块；exact version/module shape 不匹配即 fail-closed。

---

## 3. 总体架构

```text
                   OpenClaw control plane
                   ----------------------
                   install / inspect
                   QR login
                        │
                        ▼
              Tencent plugin private state
                 account/token/sync/context
                        ▲             ▲
                        │             │
        approved inbound│             │single-shot send
                        │             │
              WeixinContextMonitor    │
              (notification-only)     │
                        │             │
微信 approved user ─────┘             │
                                      │
Market / Indicator / Signal           │
          │                           │
          ▼                           │
     Alert Evaluator                  │
          │                           │
          ▼                           │
     AlertEvent commit                │
          │                           │
          ▼                           │
AlertNotificationMessage              │
          │                           │
          ▼                           │
    WeixinAlertSender                 │
          │                           │
          ▼                           │
 SingleShotWeixinBridge ──────────────┘
          │
          ▼
     Tencent iLink
          │
          ▼
 personal WeChat DM × 4
```

没有 OpenClaw Gateway、Agent、LLM、slash command、tool calling 或聊天回复长期运行面。

---

## 4. Private adapter boundary

全仓库只有：

```text
services/quant-api/app/alerts/openclaw_weixin_adapter.mjs
```

允许依赖 pinned Tencent plugin 内部模块。Python 业务代码不知道 plugin 内部路径。

Adapter 只支持四种动作：

```text
probe
register
monitor
send
```

其中 `probe` 只读兼容性/account/context readiness；`register` 是受控一次性 challenge onboarding；`monitor` 长期 `getUpdates`、只维护 approved recipient context；`send` 一次 Alert fan-out、每 recipient 最多一次 `sendMessageWeixin()`。

禁止 adapter 调用 OpenClaw agent/reply/session routing、Tencent plugin `processOneMessage()`、slash command handler、Agent hook/tool pipeline、OpenClaw durable delivery、notification queue/retry/replay/backfill。

### 4.1 Exact internal seam

初始 exact pair 在实施前再次 readback；设计基线为：

```text
OpenClaw 2026.8.1
@tencent-weixin/openclaw-weixin 2.4.6
```

Adapter compatibility test 精确锁定当前所需 exports：

```text
auth/accounts
  listIndexedWeixinAccountIds
  resolveWeixinAccount

api/api
  getUpdates
  notifyStart
  notifyStop

storage/sync-buf
  getSyncBufFilePath
  loadGetUpdatesBuf
  saveGetUpdatesBuf

messaging/inbound
  restoreContextTokens
  getContextToken
  setContextToken

messaging/send
  sendMessageWeixin
```

若 exact path/export 不存在，返回 `WEIXIN_ADAPTER_INCOMPATIBLE`；不得 glob、fallback、猜测替代路径或兼容多版本。

### 4.2 Plugin root discovery

Python preflight 只通过固定 OpenClaw CLI 的只读 surface 找 plugin root：

```text
$GUIYI_OPENCLAW_ROOT/runtime/bin/openclaw
plugins inspect openclaw-weixin --json
```

必须同时验证：

- plugin id 精确为 `openclaw-weixin`；
- plugin enabled/loaded 状态符合要求；
- recorded/observed version 精确等于 `deploy/openclaw/versions.json`；
- install path 存在且 `realpath` 位于 `GUIYI_OPENCLAW_ROOT` 允许根；
- 4.1 所列 exact module/export shape 可加载。

通过后将 exact plugin root 冻结到当前 process snapshot；`register`/`monitor`/`send` 不自行搜索、改选或更新 plugin root。

---

## 5. OpenClaw 安装与状态布局

生产推荐：

```text
/Volumes/扩展盘/openclaw/
├── runtime/      # rootless Node + OpenClaw CLI
├── state/        # plugin config/account/sync/context
├── cache/        # npm cache
└── tmp/          # OpenClaw/plugin temporary files
```

仓库保存非秘密 dependency identity：

```text
deploy/openclaw/versions.json
```

应用只通过环境变量定位：

```text
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw
OPENCLAW_PREFIX=/Volumes/扩展盘/openclaw/runtime
OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state
OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json
OPENCLAW_CONFIG=/Volumes/扩展盘/openclaw/state/openclaw.json
npm_config_cache=/Volumes/扩展盘/openclaw/cache/npm
TMPDIR=/Volumes/扩展盘/openclaw/tmp
```

`OPENCLAW_CONFIG` 与 `OPENCLAW_CONFIG_PATH` 指向同一文件；private adapter 复用的 Tencent helper 当前读取两种 config surface。

OpenClaw rootless installer 的稳定 Node symlink作为固定 executable：

```text
$OPENCLAW_PREFIX/tools/node/bin/node
```

不依赖系统 `node` 或 shell PATH。

Private adapter 运行时强制：

```text
OPENCLAW_LOG_LEVEL=FATAL
```

以禁止 Tencent plugin 的 INFO/WARN/ERROR 日志写出 recipient/account/raw provider detail。归一量化自己只记录稳定脱敏状态。QR 登录属于人工 control-plane Gate，其终端交互不作为应用 Runtime 日志。

禁止自动更新 OpenClaw/plugin。

---

## 6. Recipient Registry

Recipient 是运维通知范围，不是研究业务事实，不进入 PostgreSQL。

生产路径：

```text
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json
```

目录 `0700`；文件必须为 owner-only regular file，权限 `0600`。

Schema：

```json
{
  "version": 1,
  "channel": "openclaw-weixin",
  "account_id": "<private-account-id>",
  "recipients": [
    {"alias": "owner", "target": "<opaque-user-id@im.wechat>", "enabled": true},
    {"alias": "member_2", "target": "<opaque-user-id@im.wechat>", "enabled": true},
    {"alias": "member_3", "target": "<opaque-user-id@im.wechat>", "enabled": true},
    {"alias": "member_4", "target": "<opaque-user-id@im.wechat>", "enabled": true}
  ]
}
```

禁止保存昵称、手机号、微信号、头像、真实姓名、聊天内容、bot token、context token 或 Rule routing。

### 6.1 Runtime snapshot

Alert Runtime 与 WeixinContextMonitor 均在各自启动时读取并冻结 recipient snapshot；运行中 registry 文件变化不 hot reload。任何 recipient 增删/替换必须取得新的范围批准并重启受影响 Runtime。

### 6.2 Runtime validation

Runtime loader fail-closed：文件缺失、非 regular、权限不是 `0600`、JSON malformed、version/channel/account invalid、recipient 为空或全部 disabled、duplicate alias/target、target 非 `@im.wechat` direct identity、enabled 类型非法或超过实现安全上限。

代码不永久硬编码四人；D4/D5/D6/D8 对本次 approved scope 验证 enabled count 精确为 4。

---

## 7. 受控 registration challenge

不依赖 OpenClaw DM pairing，也不让 unknown sender 进入 Agent pipeline。

唯一注册入口：

```text
guiyi runtime weixin-register --alias <alias>
```

该命令属于真实 recipient-scope mutation Gate，不是普通测试命令。

流程：

```text
确认 WeixinContextMonitor 未运行
→ 解析 pinned plugin/account
→ 生成一次性高熵 challenge code
→ 终端只显示 challenge + alias
→ 指定用户把 exact challenge 发给 Bot
→ adapter register 独占 getUpdates/sync cursor
→ 只接受 exact text + direct from_user_id + non-empty context_token
→ setContextToken(account_id, target, context_token)
→ target 通过 capture-only IPC 返回父进程
→ Python 原子写入/更新 0600 registry
→ 用户可见输出只显示 alias/result，不显示 target
→ challenge 立即失效
```

规则：

- 初始第一个 recipient 注册时，若 registry 不存在，必须从 plugin account index 解析“有且仅有一个”已登录 account，否则 fail-closed；
- 后续注册必须使用 registry 已冻结的同一 account；
- duplicate alias/target 均拒绝；
- 非匹配消息永不回复、永不注册；
- 注册期间已 approved recipient 的新 context token 可以刷新；unknown non-matching sender 不持久化 target/token；
- registration 与 monitor 不得同时消费同一个 getUpdates cursor；初次 4 人注册完成后再启动 monitor；以后增删 recipient 必须先停止 monitor，再 mutation，再重启。

Adapter `register` 的内部 stdout 允许把 matched target 仅返回给 capture-only Python parent；parent 不得打印、记录或透传该值。所有用户可见 CLI/日志必须脱敏。

---

## 8. WeixinContextMonitor

新增 guiyi Runtime 前台命令：

```text
guiyi runtime weixin-context
```

由 launchd `com.guiyi.quant-weixin-context` 托管。它属于归一量化 exact Git Runtime identity，不是 OpenClaw external service。

### 8.1 职责

启动：

```text
load immutable recipient registry
→ exact plugin/account preflight
→ spawn fixed Node + adapter monitor
```

Adapter monitor：

1. 从同一 account persisted sync cursor 开始 `getUpdates` long-poll；
2. 每次响应先持久化新的 `get_updates_buf`；
3. inbound `from_user_id` 在 approved target set 且 `context_token` 非空时调用 `setContextToken()`；其他 sender 直接丢弃；
4. 不读取业务正文、不产生回复、不创建 OpenClaw session、不调用 Agent；
5. 不将 target/body/token 写入 guiyi 日志。

`getUpdates` 允许网络重连/backoff，因为这是 inbound context maintenance，不是 Alert notification retry；该 retry 不得触发任何 outbound message。

Bot token stale/invalid 时 monitor 不自动登录、不生成 QR；只进入 degraded 状态并周期性重新读取同一 account credential，等待人工重新登录后恢复。

### 8.2 Monitor status

Monitor 维护 privacy-safe `0600` status：

```text
<GUIYI_PROJECT_ROOT>/.run/weixin-context-status.json
```

只允许：

```json
{
  "schema_version": 1,
  "status": "ok",
  "recipient_count": 4,
  "last_poll_at": "<ISO8601>",
  "last_context_refresh_at": "<ISO8601|null>",
  "last_error_code": null
}
```

不得包含 account id、target、context token、body 或 provider raw response。

`local-services-status.sh` 在 Alert Runtime enabled 时要求 `com.guiyi.quant-weixin-context` 与 Alert 使用同一 guiyi Runtime root/commit，monitor status=`ok` 且 `last_poll_at` 在 freshness window 内。

Alert Runtime startup 还必须通过 adapter `probe`；已经运行的 Alert Runtime 不因 monitor 后续瞬时 degraded 自动停止或 replay。

---

## 9. Notification domain abstraction

新增 `notification.py`，负责 `AlertNotificationMessage`、`AlertNotificationSender Protocol`、`format_alert_message()` 和 canary text。

`AlertRuntime` 只依赖：

```python
class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...
```

现有 HTDY/SuBing formatter、Rule code、frequency/result validation 和 evaluator 业务语义原则上原样迁移，不借渠道切换修改。

---

## 10. WeixinAlertSender 与 SingleShot send

`WeixinAlertSender` 启动时持有 immutable recipient snapshot + validated exact plugin root；对一个 `AlertNotificationMessage` 只格式化一次；启动一个 adapter `send` 子进程；adapter 对全部 enabled recipients 各调用最多一次 `sendMessageWeixin()`；单 recipient failure 不 short-circuit 其他 recipient；只返回 privacy-safe aggregate result。

Adapter `send` 每次 physical send 前重新从 plugin state 解析同一 account 并要求：

```text
account.enabled == true
account.configured == true
account.token present
context_token present for exact target
```

任一 target context missing → 该 recipient `WEIXIN_CONTEXT_MISSING`，0 physical send。

不重新选择 account/recipient/plugin root；不 retry；不调用 OpenClaw durable message path。provider `ret=0` 只表示 provider accepted，不声称用户 delivered/read。

---

## 11. Adapter I/O 与隐私

`probe` / `send` 使用 stdin JSON；秘密/PII 不放 argv。`monitor` 的 approved targets 也通过 parent→child stdin bootstrap 后关闭 stdin。

固定 executable：

```text
$GUIYI_OPENCLAW_ROOT/runtime/tools/node/bin/node
```

固定 script：

```text
<GUIYI_PROJECT_ROOT>/services/quant-api/app/alerts/openclaw_weixin_adapter.mjs
```

公开错误只使用稳定码：

```text
WEIXIN_ADAPTER_UNAVAILABLE
WEIXIN_ADAPTER_INCOMPATIBLE
WEIXIN_ACCOUNT_UNAVAILABLE
WEIXIN_CONTEXT_MISSING
WEIXIN_CONTEXT_MONITOR_STALE
WEIXIN_SEND_TIMEOUT
WEIXIN_SEND_REJECTED
WEIXIN_SEND_FAILED
WEIXIN_REGISTRATION_TIMEOUT
WEIXIN_REGISTRATION_AMBIGUOUS
```

归一量化日志允许 alias、attempted/sent/failed、elapsed、稳定错误码；禁止 target、account id、token、context token、消息全文、challenge、provider raw body。

---

## 12. Alert Event 语义保持不变

```text
completed Bar
→ Rule evaluation
→ new AlertEvent commit
→ notification attempt
```

正式语义为 **at-most-one application send attempt per newly created AlertEvent × recipient**。

明确禁止 notification retry、replay/backfill、outbox/queue、delivery DB/history、provider failover。

任一 recipient/adapter failure不 rollback Event、不阻断其余 recipient、不阻断后续 completed Bar、不补发旧 Event。

WeixinContextMonitor 的 `getUpdates` 网络重连不属于 notification retry，因为它不会产生 outbound Alert。

---

## 13. Startup readiness

新 Alert Runtime 进入 Pub/Sub 消费前至少满足：

```text
recipient registry valid
approved enabled recipient count = 4
OpenClaw exact version valid
Tencent plugin exact version valid
private adapter module shape compatible
exact account configured/token present
context monitor status fresh/ok
adapter probe = ready
4 / 4 context tokens present
```

否则 `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`，Alert Runtime 不进入消费循环。

运行期某个 context/session/network 后续失效时，本次 recipient fail，其他 recipient 和后续 Bar 继续；不 replay。

---

## 14. Canary 与 rollout Gates

### D0 — Design

本文档。docs-only，无真实外部操作。

### D1 — Code implementation

实现 notification abstraction、recipient registry、adapter `probe/register/monitor/send`、context monitor、Weixin sender、CLI、tests、WeCom active-code retirement、launchd render/status。

D1 不安装 OpenClaw、不扫码、不创建真实 registry、不发送、不切 Runtime。

### D2 — OpenClaw tools install

Lane 3 单次外部 mutation：安装 pinned Node/OpenClaw CLI + pinned Tencent plugin 到扩展盘；不运行 Gateway、不扫码、不发送、不切 guiyi Runtime。

### D3 — QR login + 4 recipient registrations + context monitor activation

Lane 3，分受控操作执行：

```text
QR login
→ owner challenge registration
→ member_2
→ member_3
→ member_4
→ readback registry 4/4
→ 启动 com.guiyi.quant-weixin-context
```

没有 AI/聊天回复。

### D4 — Read-only preflight

只读验证 dependency identity、monitor status、registry、4/4 context；只得出 `STRUCTURALLY_READY=true|false`。

### D5 — First real canary

保留唯一入口 `guiyi runtime alert-canary`，走与正式 Runtime 相同的 Weixin sender/registry，禁止 `--target`/`--recipient` 绕过。

PASS 要求系统 4/4 provider accepted 且四名用户人工确认实际收到。

### D6 — Silent-window canary

D5 后四人不主动给 Bot 发消息，至少 24h 后取得新的单次真实通知授权，再执行 4/4 canary。失败则本方案不能作为唯一正式通知通道：`阻塞`。

### D7 — Release

D5/D6 PASS + implementation verification 后，才允许进入 release candidate；main/tag 为独立 Gate。

### D8 — Continuous notification authorization

持续授权精确为：

```text
htdy_original_15m × 该 Rule 显式 scope_products × openclaw-weixin × approved recipient snapshot
+
subing_entry_signal_v1 × 该 Rule 显式 scope_products × openclaw-weixin × approved recipient snapshot
```

不能从旧 WeCom 授权继承。Recipient set 变化必须重新批准。

### D9 — Runtime promotion

独立 Gate。只切 approved exact tag；promotion 本身不隐式发送 canary。成功后才更新 `STATUS.md` 为 WeCom 已退出 active Runtime。

---

## 15. 文件级实施边界

### 新增

```text
services/quant-api/app/alerts/notification.py
services/quant-api/app/alerts/recipient_registry.py
services/quant-api/app/alerts/weixin.py
services/quant-api/app/alerts/weixin_context.py
services/quant-api/app/alerts/openclaw_weixin_adapter.mjs

deploy/openclaw/versions.json
deploy/openclaw/README.md
deploy/launchd/com.guiyi.quant-weixin-context.plist.template
scripts/ops/macos/install-openclaw-weixin-tools.sh

services/quant-api/tests/test_alert_notification.py
services/quant-api/tests/test_alert_recipient_registry.py
services/quant-api/tests/test_alert_weixin.py
services/quant-api/tests/test_alert_weixin_context.py
tests/engineering/test_weixin_context_launchd.py
```

### 修改

```text
services/quant-api/app/alerts/runtime.py
services/quant-api/app/alerts/composition.py
services/quant-api/app/guiyi_cli/main.py
scripts/ops/macos/install-local-services.sh
scripts/ops/macos/local-services-status.sh
TESTING.md
AGENTS.md
PROJECT_SOURCE.md
DECISIONS.md
```

`STATUS.md` 只在真实外部事实发生时更新；D1 不能提前宣布 WeCom 已退出。

### 删除 active WeCom implementation

```text
services/quant-api/app/alerts/wecom.py
services/quant-api/tests/test_alert_wecom.py
```

并关闭 active executable/canonical references：`WeComWebhookSender`、`build_wecom_sender_from_env`、`WECOM_WEBHOOK_URL`、`WECOM_*`、`qyapi.weixin.qq.com`。历史 release/evidence 中描述当时 WeCom 事实的内容允许保留。

### 明确禁止修改

- HTDY / SuBing evaluator 公式；
- Rule code / existing Rule Scope；
- Alert 两表 schema；
- Market 八表 / Canonical / DB revision；
- order path / `auto_order=false`；
- 新 recipient/delivery DB 表；
- OpenClaw/Tencent upstream source。

---

## 16. 测试矩阵

### Notification contract

迁移现有 formatter tests，证明 HTDY/SuBing wording/validation 不漂移，formatter 与 transport 解耦。

### Recipient registry

覆盖 valid、missing/non-regular/mode、malformed、version/channel/account、empty/all-disabled、duplicate alias/target、invalid target/enabled、安全上限、startup snapshot immutability、atomic write/0600。

### Private adapter

使用 fake pinned plugin tree，不联网，覆盖 exact version/module/export gate、`probe` no-send、`register` exact challenge/timeout/non-direct/unknown ignore、`monitor` approved refresh/unknown drop/no Agent/reply/send、`send` 4 recipients=最多4次、1 fail隔离、context missing=0 send、timeout/crash=no retry、plugin logger FATAL，以及用户可见输出不泄露 target/account/token/context/body/challenge/provider raw response。

### Context monitor

覆盖 sync cursor continuation、status freshness、network backoff、stale token degraded、credential reread recovery、graceful stop、registry immutable snapshot。

### Alert Runtime regression

继续证明：

```text
new Event → notification
duplicate Event → no notification
DB failure → no notification
notification failure → committed Event remains
notification failure → next Bar continues
```

新增 3 success + 1 fail、adapter timeout/crash no retry、transport recovery no old-event replay。

### Operations

验证 `com.guiyi.quant-weixin-context` 与 guiyi Runtime exact root/commit identity 一致、OpenClaw 无长期 Gateway label、fixed Node executable、explicit expansion-disk state/cache/tmp、no FRPC/public bind、`local-services-status.sh` 同时报告 guiyi context monitor 与 external dependency versions、render-only 无外部副作用。

### Secret/privacy

Tracked secret scan + log contract tests必须证明仓库/归一量化日志不包含真实 target、account id、bot/context token、真实 registry、旧 webhook、Alert 正文或 provider raw body。

---

## 17. 验收标准

实现完成但进入真实 Gate 前至少满足：

1. HTDY/SuBing evaluator、Rule code、Scope、Event 语义不变。
2. `AlertRuntime` 只依赖 `AlertNotificationSender`。
3. WeCom active executable code/config/canary 退役，但旧正式 Runtime 在 promotion 前不受影响。
4. Recipient 只来自 0600 private registry，Runtime 启动时冻结。
5. 微信 inbound 永不进入 Agent/LLM/slash-command/tool pipeline。
6. Registration 使用一次性 exact challenge，不按昵称或“最新用户”猜测。
7. `WeixinContextMonitor` 只刷新 approved recipient context，不产生 outbound message。
8. SingleShot send 每 `AlertEvent × recipient` 最多一次 physical `sendMessage`。
9. 无 notification queue/retry/replay/backfill/outbox。
10. 单 recipient failure 不阻断其他 recipient、不 rollback Event。
11. Exact OpenClaw/plugin/private seam 不一致 fail-closed。
12. OpenClaw 只作 tools/control-plane dependency，无长期 Gateway service。
13. Context monitor 是 guiyi exact-tag Runtime service，状态 privacy-safe。
14. 无 DB migration/new table/order path；`auto_order=false` 不变。
15. 测试/mock/render-only 不产生真实微信消息。
16. D5/D6 两次真实 4/4 canary 未 PASS 前，不得把 iLink 作为唯一正式通道。
17. Promotion 成功后才允许 `STATUS.md` 宣布 WeCom 退出 active Runtime。

---

## 18. 通用与非目标

应该通用：`AlertNotificationMessage`、`AlertNotificationSender`、`format_alert_message`、`NotificationRecipient`、`RecipientRegistrySnapshot`。

V1 不建设 GenericNotificationPlatform、ChannelPluginRegistry、Rule→Recipient DSL、DB recipient manager、Web notification admin、OpenClaw generic SDK、Gateway/Agent chat、provider failover、queue/outbox/retry scheduler、delivery analytics。

也不实现普通微信群、聊天指令控制、AI 决定是否发送、自动交易、已读回执、自动 recipient discovery、自动插件升级或 OpenClaw 公网暴露。

---

## 19. 设计完成条件

本文只定义架构与 Gate。下一步 implementation planning 必须拆成：

1. **Lane 2 Code Plan**：所有代码、测试、canonical 与 render-only，绝不执行真实安装/登录/recipient mutation/send/Runtime switch；
2. **Lane 3 Rollout Plan**：D2～D9 受控外部操作，每个真实 Gate 独立，不能自动串联。

任何实现计划都不得重新引入 OpenClaw Gateway、AI inbound、WeCom fallback、notification retry/queue 或数据库 recipient/delivery 状态。