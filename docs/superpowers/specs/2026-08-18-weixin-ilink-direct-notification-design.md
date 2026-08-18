# 微信 iLink Direct Notification 设计规格

> 状态：Design Approved / Not Implemented
>
> 日期：2026-08-18
>
> 基线：`develop` 当前 Alert Runtime V2；正式 Runtime 仍按 `STATUS.md` 记录的 exact tag/commit 运行，本文不代表任何 Runtime、真实通知、微信登录、recipient mutation、release 或 promotion 已执行。

## 1. 背景与目标

归一量化是本地、单用户的国内期货量化研究工作站。Alert 只用于人工观察提醒，始终保持 `auto_order=false`，不创建或提交订单。

当前正式 Alert Runtime 使用企业微信 WeCom 通知。新的长期需求是：

- 使用 Tencent 官方 `openclaw-weixin` + iLink，将 Alert 直接发送到个人微信私聊；
- 初始正式 recipient 固定为包括 owner 在内的 4 人，所有正式 Alert 全量同发；
- 不做微信群 GUI 自动化，不使用 Peekaboo、坐标、OCR、AI vision、Hook、Frida 或微信私有协议逆向；
- 不按用户收费或为 4 人分别维护第三方订阅；
- OpenClaw 主要安装资产、state、workspace、cache、logs 尽量放在扩展盘；
- 保持 Alert Event-first、一次尝试、无 replay/backfill/retry/outbox/queue 的现有业务语义；
- 设计应允许未来增加/删除 recipient 和增加新的 Alert Rule，但不提前建设通用消息平台。

本设计替代此前的普通微信群 Peekaboo 方向。旧 Peekaboo 设计与对应 PoC 计划从 active repository 文档中删除，历史仅通过 Git history 追溯。

---

## 2. 已冻结的核心决策

### 2.1 Recipient policy

V1 固定为一个全量 recipient set：

```text
任何正式 Alert
→ owner
→ member_2
→ member_3
→ member_4
```

不实现：

- `rule_code -> recipient group`；
- `rule_code + product -> recipient group`；
- 每用户策略偏好；
- Web recipient 管理页面；
- recipient DB 表。

未来新增第 5 人只修改受控 recipient registry，不修改 evaluator；未来新增 Alert Rule 自动复用同一 sender。

### 2.2 WeCom 退出

目标架构只保留微信 iLink direct DM，不保留 WeCom fallback 或 Composite sender。

源码层在本任务实现中删除 active WeCom code/config/canary/reference；正式运行层在新版本最终 Runtime promotion 之前仍保持旧 exact-tag Runtime 的 WeCom 行为不变。只有新 Runtime promotion 成功后，`STATUS.md` 才能声明 WeCom 已退出 active Runtime。

### 2.3 OpenClaw 的定位

OpenClaw 是外部 Notification Transport Runtime，不是 Alert 业务逻辑，也不是 AI 决策层。

OpenClaw 负责：

- QR 登录；
- bot token；
- `getUpdates` long-poll；
- direct peer/session；
- `context_token` 刷新与持久化；
- Tencent `openclaw-weixin` 生命周期。

归一量化负责：

- Rule/evaluator；
- AlertEvent；
- `AlertNotificationMessage`；
- 消息格式；
- recipient policy；
- 单次发送尝试与错误收敛。

LLM 不进入正式 Alert 发送路径。

### 2.4 不走 OpenClaw durable `send`

不使用 OpenClaw Gateway 公共 `send` / durable delivery 作为正式 Alert transport。当前 OpenClaw `send` 路径会建立 write-ahead delivery queue，并具有 recovery/retry 语义；这与归一量化冻结的 no-queue/no-retry Alert 合同冲突。

采用 `SingleShotWeixinBridge`：只复用 pinned Tencent plugin 的 account/context/send 内部能力，对每个 `AlertEvent × recipient` 最多执行一次 `sendMessage`。

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
     WeixinAlertSender
            │
     immutable registry
            │
       N recipients
            │
            ▼
 SingleShotWeixinBridge
            │
 Tencent openclaw-weixin internals
            │
     sendMessage once / recipient
            │
            ▼
       Tencent iLink
            │
            ▼
      personal WeChat DM
```

旁路长期运行：

```text
OpenClaw Gateway
→ QR login
→ getUpdates long-poll
→ refresh/persist context_token
```

Gateway 与 SingleShot bridge 共享 OpenClaw private state，但 Alert 发送不进入 OpenClaw durable delivery queue。

---

## 4. 归一量化通知层边界

### 4.1 `notification.py`

从现有 WeCom transport 中抽离稳定业务合同：

```text
AlertNotificationMessage
AlertNotificationSender Protocol
format_alert_message()
canary text
```

`AlertNotificationSender` 保持最小接口：

```python
class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...
```

`AlertRuntime` 不再依赖 `WeComWebhookSender` 或任何具体外部渠道。

现有 HTDY / SuBing 正式消息格式原则上保持原语义，不借渠道切换修改 Signal wording、Rule code、frequency/result validation 或 evaluator 行为。

### 4.2 `WeixinAlertSender`

责任：

- 接收已经形成的 `AlertNotificationMessage`；
- 调用 `format_alert_message()` 一次；
- 使用启动时冻结的 recipient snapshot；
- 启动一次 SingleShot bridge process；
- 对所有 enabled recipient 完成独立一次发送；
- 收敛为 privacy-safe summary/error；
- 单个 recipient 失败不阻断其他 recipient。

不负责：

- Rule/evaluator；
- DB Event 创建；
- recipient 注册；
- QR 登录；
- context-token 更新；
- retry/replay/backfill；
- delivery queue/history。

---

## 5. Recipient Registry

### 5.1 存储与职责

Recipient 是运维通知范围，不是研究业务事实，不进入 PostgreSQL。

生产路径通过环境变量注入：

```text
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json
```

目录建议 `0700`，文件必须是 owner-only regular file，权限 `0600`。

Registry 只保存归一量化允许通知的 target；OpenClaw state 继续保存 bot credential、session 和 context token。两者不得混用。

### 5.2 V1 schema

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

禁止保存：

- `context_token`；
- bot token；
- 微信昵称/手机号/微信号/头像/真实姓名；
- 聊天内容；
- Rule/strategy routing。

### 5.3 Startup snapshot

Registry 只在 Alert Runtime 启动时读取一次：

```text
startup
→ read + validate
→ immutable tuple
→ Runtime 生命周期内不 hot reload
```

运行过程中磁盘文件变化不得动态扩张通知范围。新增/删除 recipient 必须走新的范围批准和 Runtime reload/switch。

### 5.4 Fail-closed validation

以下任一情况阻止 Alert Runtime 进入消费循环：

- 文件缺失、非 regular file、权限不是 `0600`；
- JSON malformed；
- `version` 不支持；
- `channel != openclaw-weixin`；
- `account_id` 缺失；
- recipient 为空或全部 disabled；
- alias 重复；
- target 重复；
- target 非 `@im.wechat` direct identity；
- `enabled` 类型非法；
- recipient 数量超过实现定义的安全上限。

代码不得硬编码“必须永远四人”；D4/D5/D6/production Gate 对本次批准 scope 验证 enabled count 精确为 4。

### 5.5 Registration

不建设 Web/UI/DB 管理面。采用本机受控 registration workflow：

```text
用户主动给 Bot 发消息
→ OpenClaw 建立 direct session/context
→ 只读识别唯一新 direct peer
→ 用户指定 alias
→ 写入 private registry
```

顺序注册 `owner -> member_2 -> member_3 -> member_4`。0 个或多个候选 peer 均 fail-closed；不得按昵称猜测、不得默认取第一条结果。

真实 target 不进 Git、不进应用日志。

---

## 6. OpenClaw Sidecar 部署拓扑

### 6.1 扩展盘布局

生产推荐：

```text
/Volumes/扩展盘/openclaw/
├── runtime/
├── state/
├── workspace/
├── cache/
└── logs/
```

归一量化代码只读取：

```text
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw
```

不在应用源码中硬编码卷名。

OpenClaw 运行环境使用其正式路径变量：

```text
OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state
OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json
OPENCLAW_WORKSPACE_DIR=/Volumes/扩展盘/openclaw/workspace
```

### 6.2 External supervisor

OpenClaw 不使用自己的 native service management。归一量化现有 macOS launchd 作为 external supervisor：

```text
com.guiyi.quant-openclaw
→ pinned OpenClaw executable
→ gateway run
→ loopback only
```

必须设置：

```text
OPENCLAW_SUPERVISOR_MODE=external
```

Gateway 只 bind loopback，不进入 FRPC/FRPS/Nginx 公网链路。

OpenClaw 是外部 dependency，不属于 guiyi exact Git commit identity。`local-services-status.sh` 分两个 namespace 检查：

```text
guiyi_runtime.*
external.openclaw.*
```

不得要求 OpenClaw 携带 `GUIYI_RUNTIME_COMMIT`。

### 6.3 Version pin

初始设计基线观察到：

```text
OpenClaw = 2026.8.1
Tencent openclaw-weixin = 2.4.6
```

实施时以 `deploy/openclaw/versions.json` 记录经过兼容性验证的 exact pair；禁止 `latest` 自动漂移，禁止自动升级。

任何版本变化都是独立兼容性任务，必须重新运行 private-seam compatibility tests 和真实 canary Gate。

---

## 7. SingleShotWeixinBridge

### 7.1 唯一 private seam

全仓库只有：

```text
services/quant-api/app/alerts/openclaw_weixin_bridge.mjs
```

允许依赖 Tencent plugin 内部模块。

桥接层只使用 pinned plugin 的窄能力：

```text
auth/accounts
  → loadWeixinAccount()

messaging/inbound
  → restoreContextTokens()
  → getContextToken()

messaging/send
  → sendMessageWeixin()
```

归一量化 Python 代码不认识这些 internal module paths。

### 7.2 Plugin install root discovery

禁止硬编码 OpenClaw managed npm 内部目录。Startup preflight 使用 OpenClaw 正式只读 surface：

```text
openclaw plugins inspect openclaw-weixin --json
```

只接受：

- plugin id 精确为 `openclaw-weixin`；
- loaded/enabled 状态符合要求；
- installed version 精确等于 pinned version；
- install path realpath 位于 `GUIYI_OPENCLAW_ROOT` 允许根；
- bridge required module paths/exports 精确存在。

任何不一致返回 `WEIXIN_BRIDGE_INCOMPATIBLE`，不得 glob、fallback 或猜测替代 module path。

### 7.3 Bridge I/O

Bridge 是一次性子进程，不是 daemon/service。

输入通过 stdin JSON，不把 target/text/account 放 argv：

```json
{
  "account_id": "...",
  "recipients": [
    {"alias": "owner", "target": "..."}
  ],
  "text": "...",
  "timeout_ms": 8000
}
```

stdout 只返回脱敏结果：

```json
{
  "status": "completed",
  "results": [
    {"alias": "owner", "status": "sent"}
  ]
}
```

禁止输出：target、context token、bot token、消息全文、原始 Tencent response、原始 stderr。

### 7.4 Fan-out

一个 Alert 启动一个 bridge process；bridge 对全部 recipient 进行并发/独立尝试，例如 `Promise.allSettled`：

```text
owner    → sendMessage once
member_2 → sendMessage once
member_3 → sendMessage once
member_4 → sendMessage once
```

单个失败不得 short-circuit 其他 recipient。

### 7.5 Context token policy

Tencent plugin 自身可能允许缺少 context token 时继续发送；归一量化 policy 更严格：

```text
context token present → 允许一次 send
context token absent  → CONTEXT_MISSING，0 physical send
```

Context token 失效后的当前 Alert 不 retry、不换 token 猜测、不补发。用户后续主动给 Bot 发消息，由 Gateway 刷新 context token；之后的自然新 Alert 使用新 token，历史失败 Alert 永不 replay。

### 7.6 Error model

归一量化只暴露稳定错误码，例如：

```text
WEIXIN_BRIDGE_UNAVAILABLE
WEIXIN_BRIDGE_INCOMPATIBLE
WEIXIN_ACCOUNT_UNAVAILABLE
WEIXIN_CONTEXT_MISSING
WEIXIN_SEND_TIMEOUT
WEIXIN_SEND_REJECTED
WEIXIN_BRIDGE_FAILED
```

日志允许：

```text
alias=member_3
attempted=4
sent=3
failed=1
elapsed_ms=...
```

禁止：真实 target、token、context token、消息全文、原始 provider response body。

---

## 8. Alert Event 与发送语义

现有冻结合同保持：

```text
completed Bar
→ Rule evaluation
→ new AlertEvent commit
→ notification attempt
```

正式语义是：

> **at-most-one application send attempt per newly created AlertEvent × recipient**。

不承诺 exactly-once 或 provider delivery receipt。

明确禁止：

- retry；
- replay；
- backfill；
- outbox；
- queue；
- delivery DB/history；
- provider failover。

任一 recipient 或 bridge 失败：

- 不 rollback 已提交 AlertEvent；
- 不阻断其余 recipient；
- 不阻断后续 completed Bar；
- 不补发旧 Event。

不需要额外 idempotency store；`AlertService.create_event()` 的 new-event contract 继续作为进入发送阶段的应用事实门。

---

## 9. Startup readiness 与运行期故障

### 9.1 Startup fail-closed

Alert Runtime 进入 Pub/Sub 消费循环前必须满足：

```text
recipient registry valid
approved enabled recipient count = 4
OpenClaw executable / exact version valid
Tencent plugin exact version valid
plugin private seam compatible
Gateway reachable
Weixin account configured
4 / 4 context tokens present
```

否则：

```text
ALERT_NOTIFICATION_TRANSPORT_NOT_READY
→ Alert Runtime 不启动消费循环
```

### 9.2 Runtime failure

启动成功后，如果某个 context token/session/network 后续失效：

```text
Event commit
→ 本次 recipient send failed
→ no retry
→ continue next Bar
```

运行期不能因为单 recipient 失败停止整个 Alert Runtime。

Read-only preflight 只能证明 structurally ready，不能证明 Tencent 当前会接受主动消息。

---

## 10. Canary 与受控 Gate

### D0 — Design

本文档。Lane 2，docs-only，无真实外部操作。

### D1 — Code implementation

实现 notification abstraction、recipient registry、SingleShot bridge、Weixin sender、tests、WeCom active-code retirement、运维 render/status 逻辑。

不安装 OpenClaw、不登录、不写真实 registry、不发送、不切 Runtime。

### D2 — OpenClaw sidecar install

Lane 3 外部 mutation。需单次明确批准。

只安装 pinned OpenClaw + Tencent plugin 到扩展盘并准备 sidecar；不扫码、不发送、不切 guiyi Runtime。

### D3 — Gateway/login/registration

Lane 3。分别涉及 sidecar Runtime/auth/recipient scope mutation。

顺序完成 QR 登录与 4 人 registration；仍不主动发送。

### D4 — Read-only preflight

只读验证结构就绪，得出：

```text
STRUCTURALLY_READY=true|false
```

不能写成 delivery verified。

### D5 — First real canary

现有通用入口保留：

```text
guiyi runtime alert-canary
```

新版本该命令必须走与正式 Runtime 相同的 Weixin sender + 当前 approved registry；不提供 `--target`/`--recipient` 绕过参数。

Canary 必须一次 fan-out 全部 4 个 recipient。

系统证据只能报告：

```text
attempted=4
provider_accepted=4
failed=0
```

不得把 provider accepted 写成 delivered。

D5 PASS 需要同时满足：

- 系统 4/4 provider accepted；
- 四名实际用户人工确认收到。

### D6 — Silent-window canary

D5 后 recipient 不主动给 Bot 发消息，经过至少 24 小时的工程静默窗口，再取得新的单次真实通知授权并执行第二次 4/4 canary。

D6 PASS 同样要求 4/4 provider accepted + 4/4 人工确认。

D6 失败则本方案不得作为唯一正式 Alert 通知渠道，状态为 `阻塞`。

### D7 — Release

D5/D6 PASS 和所有实现验收通过后，才允许进入 release candidate。main/tag 需要独立 release Gate。

### D8 — Continuous notification authorization

新的持续授权范围必须精确包括：

```text
htdy_original_15m × 该 Rule 显式 scope_products × openclaw-weixin × approved recipient snapshot
+
subing_entry_signal_v1 × 该 Rule 显式 scope_products × openclaw-weixin × approved recipient snapshot
```

该授权不能从旧 WeCom 持续授权继承。Recipient set 变化必须重新批准。

### D9 — Runtime promotion

独立 Runtime promotion Gate。只切换 approved exact tag；promotion 本身不隐式发送 canary。

成功后才更新 `STATUS.md` 为 WeCom 已退出 active Runtime。

---

## 11. 文件级实施边界

### 11.1 预期新增

```text
services/quant-api/app/alerts/notification.py
services/quant-api/app/alerts/recipient_registry.py
services/quant-api/app/alerts/weixin.py
services/quant-api/app/alerts/openclaw_weixin_bridge.mjs

deploy/openclaw/versions.json
deploy/openclaw/README.md
deploy/launchd/com.guiyi.quant-openclaw.plist.template
scripts/ops/macos/install-openclaw-sidecar.sh
```

### 11.2 预期修改

```text
services/quant-api/app/alerts/runtime.py
services/quant-api/app/alerts/composition.py
services/quant-api/app/guiyi_cli/main.py
scripts/ops/macos/local-services-status.sh
TESTING.md
AGENTS.md / PROJECT_SOURCE.md / DECISIONS.md / STATUS.md 仅在相应事实或长期合同实际改变时按职责更新
```

### 11.3 预期删除

```text
services/quant-api/app/alerts/wecom.py
services/quant-api/tests/test_alert_wecom.py
```

并移除 active code/config/canary 中：

```text
WeComWebhookSender
build_wecom_sender_from_env
WECOM_WEBHOOK_URL
WECOM_*
qyapi.weixin.qq.com
```

历史 release/evidence 文档中描述当时 WeCom 事实的文本无需为了 grep 归零而改写。

### 11.4 明确禁止修改

- HTDY / SuBing evaluator 公式和业务判断；
- Alert Rule code / existing Rule Scope；
- `alert_rules` / `alert_events` schema；
- Market 八表；
- production DB revision；
- Data Foundation / Canonical；
- order path / `auto_order=false`；
- 新 delivery/recipient DB 表。

---

## 12. 测试矩阵

### 12.1 Notification contract

迁移现有 formatter 测试，验证：

- HTDY/SuBing 文案与 validation 语义不漂移；
- unknown Rule/frequency/result 继续 fail-closed；
- formatter 与 transport 无耦合。

### 12.2 Recipient registry

覆盖：

- 合法配置；
- 文件缺失/非 regular/权限错误；
- malformed JSON；
- version/channel/account invalid；
- empty/all-disabled；
- duplicate alias/target；
- invalid `@im.wechat` target；
- invalid enabled type；
- recipient 数量安全上限；
- startup snapshot 后磁盘变化不影响当前 sender。

### 12.3 Bridge contract

Bridge 支持 `probe` 与 `send` 两类内部动作。

`probe` 只验证 plugin root/version/module shape/account/context store；绝不发送。

`send` 测试使用 fake plugin modules，覆盖：

- 4 recipients → 4 次 physical attempt；
- 1 个失败，其余继续；
- context missing → 0 physical send；
- timeout/crash → 不 retry；
- stdout/stderr 不泄露 target/token/text/provider raw response；
- exact module path/export 不存在 → `WEIXIN_BRIDGE_INCOMPATIBLE`。

### 12.4 Alert Runtime regression

必须继续证明：

```text
new Event → notification
duplicate Event → no notification
DB failure → no notification
notification failure → committed Event remains
notification failure → next Bar continues
```

并新增：

- 3 success + 1 fail 不 rollback；
- bridge timeout/crash 不 retry；
- transport 后续恢复也不 replay 旧 Event。

### 12.5 Operations

新增 engineering tests，验证：

- `com.guiyi.quant-openclaw` label；
- `OPENCLAW_SUPERVISOR_MODE=external`；
- loopback only；
- explicit OpenClaw paths；
- pinned version；
- 不进入 FRPC；
- 不携带 guiyi commit identity；
- fixed executable/argv，无 shell command string；
- `local-services-status.sh` 分离 guiyi/runtime identity 与 external OpenClaw identity。

### 12.6 Secret/privacy

Secret scan 和专门日志测试必须证明 repository/logs 不包含：

- 真实 `@im.wechat` target；
- bot token/context token；
- credential 文件；
- 真实 recipient registry；
- 旧 WeCom webhook；
- 完整 Alert 正文或 provider raw body。

所有测试、mock、render-only 均不得发送真实微信消息。

---

## 13. 验收标准

实现完成但进入真实 Gate 之前，至少满足：

1. HTDY / SuBing evaluator、Rule code、Scope、Event 语义不变。
2. `AlertRuntime` 只依赖 `AlertNotificationSender`，不依赖具体 WeCom/Weixin 类。
3. `AlertNotificationMessage` 与 formatter 从 transport 中独立。
4. WeCom active executable code/config/canary 全部退役，无兼容 sender。
5. Recipient 只来自 `0600` private registry，启动时冻结。
6. SingleShot bridge 对每个 `AlertEvent × recipient` 最多一次 physical `sendMessage`。
7. 无 OpenClaw durable queue、无 retry/replay/backfill/outbox。
8. 单 recipient failure 不阻断其他 recipient，不 rollback Event。
9. Exact plugin version/module shape 不一致 fail-closed。
10. OpenClaw sidecar loopback only、pinned、external-supervised，主要资产位于扩展盘。
11. 无 DB migration、新表、订单路径；`auto_order=false` 不变。
12. 测试/mock/render-only 无真实微信消息。
13. D5/D6 两次真实 4/4 canary 未 PASS 前，不得 release/promote 为唯一正式通知通道。
14. 旧正式 Runtime 的 WeCom 保留到新 exact-tag Runtime promotion 成功。
15. Promotion 成功后才允许 `STATUS.md` 宣布 WeCom 正式退出 active Runtime。

---

## 14. 通用与复用边界

应该通用：

```text
AlertNotificationMessage
AlertNotificationSender
format_alert_message
NotificationRecipient
RecipientRegistrySnapshot
```

不应该在 V1 建设：

```text
GenericNotificationPlatform
ChannelPluginRegistry
Rule→Recipient routing DSL
DB recipient manager
Web notification admin
OpenClaw generic SDK
provider failover
queue/outbox/retry scheduler
delivery analytics
```

未来扩展规则：

```text
第 5 个 recipient → 改受控 registry + 新范围批准
新的 Alert Rule      → 自动复用 sender
新的微信 Bot         → 新 account/recipient scope 设计
新的通知渠道         → 新 sender implementation + 独立 Gate
```

---

## 15. 非目标

本设计不实现：

- 普通微信群；
- OpenClaw 聊天指令控制归一量化；
- AI 判断是否发送 Alert；
- 自动交易/自动下单；
- 用户权限/SaaS；
- notification delivery SLA；
- 微信服务端“已读/已送达”回执；
- 自动 recipient discovery/auto-enroll；
- 自动插件升级；
- OpenClaw public exposure；
- WeCom fallback。

---

## 16. 设计完成条件

本文只定义架构和 Gate，不授权 implementation 或任何真实外部操作。

下一步在用户审查并再次确认本文后，按 Superpowers `writing-plans` 生成 implementation plan。Implementation plan 必须按 Lane 2 code work 与 Lane 3 external Gate 分解，不能把安装、QR 登录、recipient mutation、真实 canary、release/tag、持续通知授权和 Runtime promotion 合并为一个自动任务。
