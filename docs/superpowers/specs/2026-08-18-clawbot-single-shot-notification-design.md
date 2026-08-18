# Clawbot Single-Shot Alert Notification Design

> 状态：Design Approved / Not Implemented
>
> 日期：2026-08-18
>
> 设计基线：`develop` 在本设计讨论开始时为 `3c029c484a81e9a1aaed5f0027ff704f043348be`。当前 production 仍按 `STATUS.md` 运行 exact-tag `v1.4.2` / `fb96506493763340e082ed85e8112b60d6670d65`，通知通道仍为 WeCom；本设计不提前改写该生产事实。

## 1. 目标

归一量化的长期通知目标收口为一件事：

```text
新的自然 AlertEvent 已提交
→ 使用现有 Alert 文本格式
→ 通过已经安装并登录的 OpenClaw 微信 Clawbot
→ 向唯一 owner 的微信 direct chat 尝试发送一次
→ 结束
```

V1 不再维护第二套通知方案。最终 active source 中：

- WeCom = 0；
- WeChat-Courier / GUI 微信自动化 = 0；
- OpenClaw public `message send` = 不作为正式 Alert 发送路径；
- Clawbot single-shot sender = 唯一通知 transport。

本设计只改变 notification transport，不改变 Alert evaluator、Rule、Scope、Alert 两表、Event identity、Market Data Foundation、Execution Review、Canonical、DB revision 或订单边界；`auto_order=false` 始终不变。

---

## 2. 已批准的核心选择

### 2.1 保持 Alert V2 的 at-most-one / no-retry 语义

正式合同继续是：

```text
new AlertEvent commit
→ notification attempt
→ success / failure
→ end
```

对每个 `new AlertEvent × owner`：

- bridge child process 最多 1 个；
- `sendMessageWeixin()` 最多调用 1 次；
- context 不可用时 physical send = 0；
- send 抛错时 physical send = 1，结束；
- 不 retry；
- 不 queue；
- 不 replay；
- 不 backfill；
- 不 outbox；
- 不 provider failover；
- 不恢复 WeCom/Courier fallback。

通知失败永远不得 rollback 已提交 Event。旧失败 Event 永远不补发；只有未来新 Event 才产生新的通知机会。

### 2.2 不使用 OpenClaw public `message send`

OpenClaw 当前 public outbound/core send 路径具有 durable delivery / queue / recovery 语义，因此不作为归一量化正式 Alert path。

正式路径只复用腾讯 `openclaw-weixin` 已安装插件中的低层单次发送能力：

```text
loadWeixinAccount()
restoreContextTokens()
getContextToken()
sendMessageWeixin() exactly once
```

不得调用：

```text
openclaw message send
Gateway send RPC
sendDurableMessageBatchCore
OpenClaw delivery queue
OpenClaw broadcast
OpenClaw Agent/LLM/tool send
```

### 2.3 OpenClaw/Clawbot 仍拥有认证和聊天生命周期

归一量化不接管：

- QR 登录；
- bot token 生命周期；
- Clawbot inbound；
- Agent / LLM / tool / memory / normal chat；
- `getUpdates`；
- context token 更新与持久化；
- OpenClaw Gateway supervision；
- OpenClaw 自身升级。

归一量化只读取已经存在的 account/context state，并在发送时调用经过冻结兼容性验证的 single-shot seam。

---

## 3. 最终架构

```text
Market / Signal
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
AlertNotificationSender Protocol
      │
      ▼
ClawbotAlertSender
      │
      ├─ immutable owner config
      │
      ▼
ClawbotRunner
      │ stdin JSON
      ▼
openclaw_weixin_single_shot.mjs
      │
      ├─ exact dependency/version check
      ├─ loadWeixinAccount(account_id)
      ├─ restoreContextTokens(account_id)
      ├─ getContextToken(account_id, target_user_id)
      ├─ missing context => zero-send fail closed
      └─ sendMessageWeixin(...) exactly once
      │
      ▼
Tencent iLink
      │
      ▼
owner 的 Clawbot direct chat
```

继续保留 transport-neutral 层：

```text
AlertNotificationMessage
AlertNotificationSender Protocol
format_alert_message()
ALERT_CANARY_TEXT
```

`AlertRuntime` 继续只依赖 `AlertNotificationSender`，不认识 OpenClaw/Tencent 细节。

---

## 4. 唯一 owner 身份

### 4.1 私有 owner 文件

生产路径：

```text
/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json
```

Schema：

```json
{
  "version": 1,
  "channel": "openclaw-weixin",
  "owner_alias": "owner",
  "account_id": "<private normalized clawbot account id>",
  "target_user_id": "<private opaque user id ending @im.wechat>"
}
```

只允许固定：

```text
version == 1
channel == openclaw-weixin
owner_alias == owner
```

要求：

- parent exact `0700`；
- file exact `0600`；
- parent/file 均为 current Runtime uid；
- regular file；
- reject symlink；
- exact schema keys；
- `account_id` 非空、无控制字符；
- `target_user_id` 非空、无控制字符且必须以 `@im.wechat` 结尾。

Runtime 启动时读取一次并冻结 immutable owner snapshot，不 hot reload。

### 4.2 owner 文件绝不保存这些值

禁止保存：

```text
bot token
context_token
baseUrl credential
微信昵称
微信号
手机号
真实姓名
聊天内容
OpenClaw session transcript
```

OpenClaw/Tencent state 仍是这些 secret/runtime state 的唯一 owner。

### 4.3 V1 不支持多 owner

V1 精确只有：

```text
owner_alias = owner
```

不实现 recipient list、fan-out、多 account routing、多 owner broadcast、按 Rule/品种路由或 recipient DB。

---

## 5. Owner bootstrap

正式 Runtime 不允许每次扫描 OpenClaw 状态猜 recipient。自动发现只发生在一次性 bootstrap。

### 5.1 Read-only dependency discovery

bootstrap 先运行只读 discovery：

```text
openclaw --version
openclaw plugins inspect openclaw-weixin --runtime --json
openclaw channels status --channel openclaw-weixin --probe --json
node --version
```

从官方 OpenClaw surfaces 读取并冻结：

- exact OpenClaw version；
- exact Node version；
- exact `openclaw-weixin` recorded/plugin version；
- exact plugin install root；
- channel configured/enabled/probe facts。

不得猜 npm global path、`~/.openclaw`、`latest`、`main` 或扫描多个插件目录。

### 5.2 唯一 owner candidate

V1 bootstrap 要求 exactly one configured/indexed `openclaw-weixin` account。

腾讯 plugin QR login account data 中的 `userId` 是扫码人的 `ilink_user_id`；V1 只有当以下交叉验证全部成立时才形成 owner candidate：

```text
exactly one configured account
→ account data userId exists
→ userId ends with @im.wechat
→ restore that account's persisted context tokens
→ getContextToken(account_id, userId) returns non-empty token
→ candidate count == 1
```

0 个或 >1 个 candidate、multiple account、account/user mismatch、context missing 全部 fail closed，不选择 first/latest/default/recent peer。

如果 context missing，用户只需正常在微信里给现有 Clawbot 发一条消息，让 OpenClaw 按其正常机制刷新 context；归一量化不得自己启动 getUpdates 或构建 ContextMonitor。

### 5.3 Bootstrap 输出与写入

发现阶段 stdout 只允许：

```json
{
  "status": "ready",
  "channel": "openclaw-weixin",
  "owner_alias": "owner",
  "account_count": 1,
  "owner_candidate_count": 1,
  "context_available": true
}
```

不得打印 account id / target id / token / context。

只有独立显式 `--confirm-write-owner` Gate 才允许把 candidate 原子写入 `alert-clawbot-owner.json`；该操作是 notification recipient scope mutation。

---

## 6. External dependency contract

归一量化不安装第二套 OpenClaw，不管理 Gateway，不自动升级现有 Clawbot。

### 6.1 版本冻结

代码实现开始时，从用户当前已安装环境的 read-only discovery 生成：

```text
deploy/clawbot/versions.json
```

概念 schema：

```json
{
  "schema_version": 1,
  "openclaw_version": "<observed exact>",
  "openclaw_weixin_version": "<observed exact>",
  "node_version": "<observed exact>"
}
```

这三个值必须来自实际安装读回，不能从 GitHub `main`、npm `latest` 或本文推断。

版本变化默认 fail closed，必须重新执行 compatibility review/probe 后才允许更新 manifest。

### 6.2 固定路径环境

归一量化通过固定环境变量定位已经存在的安装：

```text
GUIYI_OPENCLAW_BIN
GUIYI_OPENCLAW_NODE_BIN
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT
GUIYI_OPENCLAW_STATE_DIR
GUIYI_OPENCLAW_CONFIG_PATH
GUIYI_ALERT_CLAWBOT_OWNER_PATH
```

API 和 Alert launchd 必须收到完全相同的这些路径。

launchd 非空注入值继续高于 `project.env/.env` 同名值；不得因 shell profile 改变 dependency identity。

child 环境由 runner 明确构造，至少设置：

```text
OPENCLAW_STATE_DIR=<GUIYI_OPENCLAW_STATE_DIR>
OPENCLAW_CONFIG=<GUIYI_OPENCLAW_CONFIG_PATH>
```

不得盲目继承冲突的 `OPENCLAW_*` / `CLAWDBOT_*`。

### 6.3 唯一 private seam

全仓库只有：

```text
services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs
```

允许知道腾讯插件内部 module path/export。

对 implementation-time 实际冻结的 plugin 版本，seam 必须要求 exact compiled module shape，概念上包括：

```text
<plugin_root>/dist/src/auth/accounts.js
  loadWeixinAccount

<plugin_root>/dist/src/messaging/inbound.js
  restoreContextTokens
  getContextToken

<plugin_root>/dist/src/messaging/send.js
  sendMessageWeixin
```

如果实际已安装 package layout 与此不同，以 G1 读回和 exact-version compatibility review 为准；禁止 glob、guess、fallback path 或 vendoring/fork。

只有这个 `.mjs` 文件允许 import 腾讯 private modules；Python application code 不得直接读取腾讯 account/context file schema。

---

## 7. Single-shot bridge contract

bridge 只支持：

```text
probe
send
```

不提供 login、inbound、register、message tool、broadcast、media、queue 或 arbitrary target CLI。

### 7.1 stdin，不使用 argv 传秘密/正文

父进程固定 argv：

```text
[exact_node_binary, openclaw_weixin_single_shot.mjs]
```

payload 只经 stdin JSON：

```json
{
  "action": "send",
  "account_id": "...",
  "target_user_id": "...",
  "text": "..."
}
```

这样 account/target/text 不进入 process argv/`ps`。

### 7.2 probe

`probe`：

```text
validate exact plugin/version/module shape
→ load exact account
→ account token/config present
→ account.userId == owner.target_user_id
→ restoreContextTokens(account_id)
→ getContextToken(account_id, target_user_id)
→ require non-empty context
→ READY
```

probe physical send = 0。

公开结果仅：

```json
{
  "status": "ready",
  "account_configured": true,
  "context_available": true
}
```

### 7.3 send

`send` sequence 必须精确：

```text
validate exact dependency
→ load exact account
→ require account.userId == owner target
→ restoreContextTokens
→ require non-empty context
→ call sendMessageWeixin once
→ success / throw
→ END
```

context missing：

```text
CLAWBOT_CONTEXT_UNAVAILABLE
physical send = 0
```

account/dependency invalid：

```text
CLAWBOT_DEPENDENCY_INVALID
physical send = 0
```

单次调用失败：

```text
CLAWBOT_SEND_FAILED
physical send = 1
```

bridge 不调用腾讯 plugin `sendWeixinOutbound()`、message-sending hooks、Agent pipeline 或 OpenClaw core message send；这是有意为之，用于保持归一量化自己的 single-shot/no-retry 合同。

### 7.4 timeout / crash

父进程只启动一个 child；timeout、signal、malformed JSON、child crash 均视为单次失败并结束，不重新 spawn。

---

## 8. Python sender

新文件：

```text
services/quant-api/app/alerts/clawbot_owner.py
services/quant-api/app/alerts/clawbot.py
```

核心接口：

```python
@dataclass(frozen=True, slots=True)
class ClawbotOwner: ...

class ClawbotRunner:
    def probe(self, owner: ClawbotOwner) -> None: ...
    def send_text(self, owner: ClawbotOwner, text: str) -> None: ...

class ClawbotAlertSender:
    def send(self, message: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> ClawbotSendSummary: ...
```

`ClawbotAlertSender.send()` 只做：

```text
format_alert_message(message)
→ runner.send_text(owner, text)
```

不得包含 retry/fallback/recipient discovery。

---

## 9. CLI

### 9.1 保留通用 canary

唯一真实发送测试入口继续是：

```text
guiyi runtime alert-canary
```

它只能使用 frozen owner + 固定 `ALERT_CANARY_TEXT`。

禁止增加：

```text
clawbot-send
--target
--account
--message
broadcast
send-user
```

canary 成功结果语义：

```text
attempted=1
provider_accepted=1
failed=0
failed_aliases=[]
```

失败：

```text
attempted=1
provider_accepted=0
failed=1
failed_aliases=["owner"]
exit=1
```

`provider_accepted=1` 只表示腾讯 single-shot API call 返回成功，不代表 delivered/read；真实 canary 仍需要用户人工确认微信收到。

### 9.2 `clawbot-preflight`

新增：

```text
guiyi runtime clawbot-preflight
```

只调用 `runner.probe(owner)`，physical send = 0。

成功：

```json
{
  "schema_version": 1,
  "command": "runtime.clawbot-preflight",
  "status": "ok",
  "readonly": true,
  "channel": "openclaw-weixin",
  "owner_alias": "owner",
  "account_configured": true,
  "context_available": true,
  "would_send": false
}
```

Courier 专属 `alert-target-verify` 删除。

### 9.3 bootstrap CLI

新增受控：

```text
guiyi runtime clawbot-owner-bootstrap
```

默认 discovery 为 readonly；`--confirm-write-owner` 才写 private owner config。

不得把实际 account/target id 放 stdout/stderr。

---

## 10. Runtime composition / health

### 10.1 Composition

当前 Courier factory：

```text
build_wechat_group_sender_from_env()
```

最终替换为：

```text
build_clawbot_sender_from_env()
```

`build_alert_runtime()` 在启动时：

```text
activation marker
→ operational products/taxonomy
→ load frozen owner
→ resolve exact dependency
→ runner.probe(owner)
→ Redis source/heartbeat
→ AlertRuntime
```

probe 失败 => `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`，Alert Runtime 不启动。

运行后单次通知失败只影响该 Event 的通知，不停止 Event truth，也不 replay。

### 10.2 HTTP / CLI health

`/api/runtime/health` 与 `runtime status` 的 `notification_transport_configured` 只代表 structural configuration：

```text
required paths present
owner config structurally valid
versions manifest exact
plugin root/module shape exact
```

health 不发消息、不联网发送、不执行 owner bootstrap、不修改 OpenClaw。

account/context live readiness 由 Alert startup preflight 与显式 `clawbot-preflight` 负责。

---

## 11. launchd / supervision

归一量化仍只有既有五服务：

```text
com.guiyi.quant-api
com.guiyi.quant-web
com.guiyi.quant-live
com.guiyi.quant-after-market
com.guiyi.quant-alert
```

不新增 Clawbot/OpenClaw launchd label。

OpenClaw/Clawbot 是 external dependency；归一量化不得：

- start/stop/restart Gateway；
- login/logout；
- update plugin；
- modify OpenClaw config；
- own a second supervisor。

API/Alert plist 仅注入固定 dependency paths，不注入 account id、target id、token、context 或 Alert 正文。

---

## 12. local-services-status

状态脚本必须按 supervised Runtime root 的 active source identity 报告 transport，而不是按 inspector repo 猜测。

迁移期间：

```text
legacy exact-tag runtime:
  wecom.py present
  clawbot.py absent
  => alert.notification_channel=wecom

new exact-tag runtime:
  clawbot.py present
  wecom.py/courier files absent
  => alert.notification_channel=clawbot-openclaw-weixin

ambiguous/none:
  => unknown
```

新 Runtime 公开：

```text
alert.notification_channel=clawbot-openclaw-weixin
alert.notification_owner_alias=owner
external.openclaw.status=ready|invalid|missing
external.openclaw.version=<non-secret exact version>
external.openclaw_weixin.status=ready|invalid|missing
external.openclaw_weixin.version=<non-secret exact version>
external.clawbot_owner_config=ready|invalid|missing
```

禁止输出 account id / target id / token / context / message。

OpenClaw external dependency identity 绝不能纳入 `GUIYI_RUNTIME_COMMIT`；Guiyi Git exact-tag identity 与 external OpenClaw dependency identity 分开报告。

legacy production v1.4.2 不因 OpenClaw 缺失/invalid 而失败，因为其 active transport 仍是 WeCom。

---

## 13. 隐私与日志

Guiyi Git/application logs/stdout/stderr 禁止：

```text
account_id
target_user_id
bot token
context_token
真实微信身份
Alert 完整正文
raw Tencent response
raw OpenClaw/plugin stderr
```

允许：

```text
channel=openclaw-weixin
owner_alias=owner
CLAWBOT_CONTEXT_UNAVAILABLE
CLAWBOT_DEPENDENCY_INVALID
CLAWBOT_SEND_FAILED
ALERT_NOTIFICATION_FAILED
elapsed_ms
```

bridge 必须 capture/sanitize child/module errors，Python parent 不透出 raw vendor detail。

腾讯/OpenClaw 自身 private logs 可能包含 opaque account/target id；本设计只保证 Guiyi 不采集、不复制、不暴露这些外部日志，不虚假承诺第三方 sidecar 自己永不记录这些值。

---

## 14. Active source retirement

D1 完成后 `develop` 的 active notification source 必须满足：

```text
WeCom active implementation refs = 0
WeChat-Courier active implementation refs = 0
Clawbot = 唯一 target transport
```

删除 Courier active code/tooling：

```text
services/quant-api/app/alerts/wechat_courier.py
services/quant-api/app/alerts/wechat_courier_adapter.py
services/quant-api/app/alerts/wechat_group_config.py
对应 Python/engineering tests
deploy/wechat-courier/**
scripts/ops/macos/install-wechat-courier.sh
Courier launchd env/status wiring
Courier-only CLI alert-target-verify
```

WeCom active implementation不得恢复：

```text
services/quant-api/app/alerts/wecom.py
services/quant-api/tests/test_alert_wecom.py
WeCom factory/config/canary env
WECOM_WEBHOOK_URL
qyapi.weixin.qq.com
```

历史 `STATUS.md`/release evidence 中已经发生过的 WeCom 事实继续保留；只有新 exact-tag Runtime promotion 成功后，当前状态段才更新为 Clawbot active / WeCom retired。

---

## 15. 测试策略

D1 代码测试不得真实发送微信，使用 fake pinned plugin tree / temp state / mocked child / fixture owner。

必须覆盖：

### owner config

- missing / malformed / extra keys；
- symlink / non-regular；
- parent `0700` / file `0600`；
- parent/file current uid；
- exact channel/alias；
- malformed account id；
- malformed target id / no `@im.wechat`；
- error never leaks private values。

### dependency

- observed exact OpenClaw/Node/plugin versions；
- exact plugin root from inspect-derived config；
- exact module files/exports；
- wrong version/layout => fail closed；
- no glob/guess/latest/fallback。

### bridge probe

- account missing => fail / send=0；
- account unconfigured => fail / send=0；
- account.userId mismatch => fail / send=0；
- context missing => fail / send=0；
- ready => success / send=0。

### bridge send

- context missing => physical send 0；
- success => `sendMessageWeixin` exactly 1；
- throw => exactly 1；
- timeout/crash/malformed stdout => no second child/no retry；
- public stdout/stderr sanitized；
- argv contains no target/text/account。

### Runtime

- Event commit precedes notification；
- duplicate Event => no send；
- DB failure => no send；
- notification failure => Event survives；
- failure does not stop next new Bar processing；
- no replay/backfill/retry/outbox/queue。

### CLI

- `clawbot-preflight` readonly=true / send=0；
- owner bootstrap discovery readonly；
- `--confirm-write-owner` explicit mutation only；
- `alert-canary` fixed owner, no arbitrary target/account/message flags；
- canary uses `provider_accepted`, never `delivered/read`。

### ops

- API/Alert exact same Clawbot env paths；
- launchd path authority > env file；
- legacy v1.4.2 reports WeCom；
- new runtime reports Clawbot；
- ambiguous identity fail closed；
- legacy WeCom runtime does not require OpenClaw readiness。

### forbidden surface scans

Active code/current canonical must not contain functional paths for：

```text
openclaw message send
WeChat-Courier
GUIYI_WECHAT_COURIER_ROOT
GUIYI_ALERT_WECHAT_GROUP_PATH
WECOM_WEBHOOK_URL
WeComWebhookSender
build_wecom_sender_from_env
queue/retry fallback inside Clawbot sender
```

历史 STATUS/release text 不为 grep=0 而篡改。

---

## 16. Rollout Gates

代码实现和真实外部操作分离。

```text
D0  Design approved
↓
D1  Clawbot code replacement; Courier/WeCom active source retired on develop
↓
R1  independent code review: Critical=0 / Important=0
↓
G1  real installed OpenClaw read-only discovery; freeze exact versions/paths
↓
G2  owner bootstrap + explicit private owner write; no send
↓
G3  clawbot-preflight; account/context ready; zero send
↓
G4  exactly one real alert-canary; provider_accepted=1 + human receipt
↓
G5  stability check: OpenClaw/Clawbot restart/context refresh + no-send preflight;
    any additional real canary requires a fresh explicit Gate
↓
G6  release candidate → main → annotated tag
↓
G7  continuous notification authorization for current approved Alert Rule Scope × owner
↓
G8  exact-tag Runtime promotion
↓
G9  wait for first natural Alert; confirm Clawbot receipt; no synthetic/replay/backfill
```

### G1

Read-only only；不得 update OpenClaw/plugin、不得 send。

### G2

`--confirm-write-owner` 是 recipient scope mutation，需要独立明确授权。

### G4

真实 canary 是一次真实微信发送，只允许一条固定 canary；失败不得自动重跑。再次 canary 需要新授权。

### G7

持续通知授权精确覆盖：

```text
current approved htdy_original_15m Scope × owner
+
current approved subing_entry_signal_v1 Scope × owner
```

不覆盖新 Rule、新 Scope、新 recipient、canary retry、release、promotion、DB/Canonical/order mutation。

### G8

promotion 不隐含 canary，不 replay 历史 Event。只有 promotion 成功后，`STATUS.md` 当前 Runtime/notification facts 才更新为 Clawbot active、WeCom retired。

### G9

只等自然 completed Bar → Rule → new AlertEvent → single-shot owner send。没有自然 Event 就保持 pending，不制造 synthetic Event 补证。

旧 v1.4.2 Runtime worktree 至少保留到 G9 作为显式 rollback material；它不是自动 provider fallback。任何 rollback 需要新的人工 Gate。

---

## 17. 验收标准

最终实现必须同时满足：

1. `AlertNotificationMessage` / `AlertNotificationSender` 保持 transport-neutral。
2. `AlertRuntime` Event-first/no-retry/no-replay 语义不变。
3. V1 只有一个 owner，身份由私有 immutable owner config 冻结。
4. owner bootstrap 必须唯一交叉验证 account `userId` 与 persisted context；不得 first/latest/default guessing。
5. context token 不复制进 Guiyi config/DB/Git。
6. 只有 `openclaw_weixin_single_shot.mjs` 知道腾讯 private module path/export。
7. 不使用 OpenClaw public `message send` / Gateway send / durable delivery queue。
8. 每个新 AlertEvent × owner 最多一次 `sendMessageWeixin()`；context missing = zero send。
9. no queue/retry/replay/backfill/outbox/provider failover。
10. Guiyi stdout/stderr/log 不暴露 account/target/token/context/message/raw vendor data。
11. WeCom 和 WeChat-Courier active source/tooling 全部退出 develop；历史事实保留在 Git/STATUS history。
12. production v1.4.2 WeCom 在 G8 前保持真实现状，不提前停止。
13. OpenClaw/Clawbot 继续由其现有 runtime 管理；Guiyi 不新增第二 supervisor。
14. evaluator/Rule/Scope/Alert DB/Market/Canonical/Execution Review/order path 零语义变化；`auto_order=false`。
15. 真实 owner write、canary、continuous authorization、release、Runtime promotion 均为互不继承的独立 Gate。
