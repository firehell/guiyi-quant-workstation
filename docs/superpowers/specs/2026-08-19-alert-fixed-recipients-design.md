# Alert 固定接收人私聊设计规格

> 状态：Design Approved
>
> 日期：2026-08-19
>
> 设计基线：`develop@16d09ac0dad295763bf7552e07e06f3222c41c80`
>
> 范围：只扩展 `htdy_original_15m` 的 Clawbot 微信直聊接收面；
> `subing_entry_signal_v1` 继续只通知 `owner`。本文不授权 implementation、production
> migration、私有配置写入、真实 canary/send、release/tag、Runtime promotion、Scope 变更或订单。

## 1. 结论

当前 `openclaw-weixin 2.4.6` 只声明 `direct` chat capability，不支持微信群聊。
因此否决“专用微信群”方案，第一版采用：

```text
一个 HTDY AlertEvent
→ 固定接收人白名单（最多 5 人，包含 owner）
→ 每个接收人一条独立投递事实
→ 每个接收人最多一个 Node child / 一次 sendMessageWeixin()
```

该能力仍属于本地单用户研究工作站。新增的是固定通知接收人，不是登录用户、租户、权限系统、
联系人管理平台或 SaaS。

## 2. 当前事实与可行性结论

设计基线下：

- production Git release 与 Runtime 均为 `v1.6.1`；
- active transport 为 `clawbot-openclaw-weixin`；
- production Rule 精确为 `htdy_original_15m` 与 `subing_entry_signal_v1`，两条 Scope 当前均为 `jm`；
- 当前 Clawbot owner 配置只允许固定 `owner`，每个 committed Event 最多一次发送；
- Alert Application Domain 当前只有 `alert_rules` 与 `alert_events` 两张表；
- 当前没有 replay、backfill、retry、queue、fallback 或订单路径。

经用户批准的只读固定插件探针确认：

- pinned `openclaw-weixin` 版本精确为 `2.4.6`；
- channel capability 为 `chatTypes: ["direct"]`；
- inbound context 固定为 direct；
- context token 以 `accountId + userId` 持久化；
- `sendMessageWeixin()` 接受 direct target 与对应 context token；
- 插件没有 group/chatroom target discovery 或 group context contract。

所以不得把未知 `to` 当作群 ID 试发，也不得把 direct primitive 的通用字符串参数解释成群聊支持。
固定接收人私聊可行，但每个接收人启用前必须主动给当前 OpenClaw 绑定微信发送一条普通消息，
形成或刷新其专属 context token。

## 3. 产品定位与阶段边界

### 3.1 功能定位

本功能加强现有研究观察闭环：同一个已经通过现有 HTDY evaluator 产生的自然 AlertEvent，可以通知
一个由 owner 管理的小规模、固定、显式同意的接收人集合。

### 3.2 第一版范围

- 最多 5 个 active 接收人，包含保留别名 `owner`；
- 仅 `htdy_original_15m` fan-out 到全部 active 接收人；
- `subing_entry_signal_v1` 继续只通知 `owner`；
- 私有 CLI 完成接收人 bootstrap、停用和 zero-send preflight；
- PostgreSQL 记录逐 Event、逐 alias 的投递尝试事实；
- 所有发送保持 at-most-once，不自动重试。

### 3.3 不做事项

- 微信群聊；
- Web 接收人管理页面或公开 HTTP mutation；
- 多用户登录、角色、权限、租户、订阅偏好；
- 接收人自行订阅或退订；
- durable queue、outbox worker、retry、replay、backfill；
- provider fallback、WeCom 恢复或 OpenClaw public message-send；
- 修改 OpenClaw、腾讯插件或监督其进程；
- 修改 HTDY/SuBing 公式、Scope、Market Data 或订单边界。

## 4. Rule 路由合同

路由由代码固定，不从外部任意配置生成：

```text
htdy_original_15m       → all active recipient aliases
subing_entry_signal_v1  → owner only
```

规则：

- `owner` 必须存在且 active；
- HTDY 接收人按 `owner` 优先、其余 alias 字典序排列；
- 未知 Rule、空接收人集合或超过 5 人均 fail-closed；
- 接收人配置不改变 `alert_rules.scope_products`；
- 当前 production 持续授权仍只覆盖现有 owner，新增 alias 必须获得新的精确授权；
- 未来增加 Rule 不继承任何接收人。

## 5. Git 外固定接收人配置

### 5.1 文件合同

新增独立的 v2 recipients 文件，不覆盖现有 v1 owner 文件：

```json
{
  "schema_version": 2,
  "channel": "openclaw-weixin",
  "account_id": "<private>",
  "active_recipients": [
    {
      "alias": "owner",
      "target_user_id": "<private>"
    }
  ],
  "retired_aliases": []
}
```

`<private>` 只是文档中的脱敏示意值，正式文件必须写入已验证的 exact private value。

新 Runtime 只通过以下精确绝对路径环境变量注入该文件：

```text
GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH
```

新代码和新 launchd 模板不再把 `GUIYI_ALERT_CLAWBOT_OWNER_PATH` 作为 active source；旧 exact-tag
模板仍可在独立 rollback Gate 下读取旧 owner 文件。文件与 parent 必须满足：

```text
parent directory = 0700 / current uid / real directory / no symlink
recipient file   = 0600 / current uid / regular file / O_NOFOLLOW
```

### 5.2 Schema 规则

- exact keys，拒绝额外字段；
- `schema_version == 2`；
- `channel == openclaw-weixin`；
- `account_id` 与 `target_user_id` 必须是无首尾空白、无控制字符的非空字符串；
- target 必须符合 pinned direct ID 合同；
- alias 只允许 `[a-z][a-z0-9_-]{0,31}`；
- `owner` 是保留 alias，必须唯一；
- active aliases、target IDs 与 retired aliases 分别唯一；
- active alias 不得出现在 retired aliases；
- active recipient count 为 `1..5`；
- retired alias 永久不可复用；
- token、context token、消息正文和聊天内容不得进入该文件。

v1 owner 文件在 rollout 期间只作为旧 exact-tag Runtime rollback material 保留，不是新代码的第二个
active 接收人源。是否最终删除必须走独立清理 Gate。

## 6. 两阶段接收人 Bootstrap

### 6.1 目标

bootstrap 必须在不要求用户复制微信 ID、不输出 context token、不读取消息正文的前提下，把一个明确
同意的 direct contact 绑定到 operator 指定 alias。

### 6.2 Prepare

```text
guiyi runtime clawbot-recipient-bootstrap prepare --alias <alias>
```

Prepare：

1. 加载并验证当前 v2 recipients 文件；
2. 恢复 pinned OpenClaw account 的 direct context token 状态；
3. 生成本次随机 nonce；
4. 对每个 `userId` 与 `userId + token` 分别生成 keyed fingerprint；
5. 将 fingerprint snapshot 原子写入同一 `0700` private parent 下的 `0600` staging 文件；
6. 只输出 alias、baseline candidate count、`prepared=true`，不输出任何 ID、token、路径或正文。

Prepare 本身是仓库外私有状态写入，执行前需要精确单次 Gate。

### 6.3 首次私聊

Prepare 完成后，只允许目标接收人给绑定微信发送一条普通消息。Guiyi 不监听、不回复、不解释消息，
只依赖既有 OpenClaw 正常入站流程刷新其 direct context token。

Bootstrap 只在 operator 明确执行 prepare/confirm 时读取一次已经持久化的 context 状态；不得启动
getupdates、长轮询、inbound handler、context monitor、Agent、LLM、slash、tool 或 reply 路径。

### 6.4 Confirm

```text
guiyi runtime clawbot-recipient-bootstrap confirm --alias <alias>
```

Confirm：

1. 校验 staging 文件权限、uid、schema、alias 与有效期；
2. 再次恢复当前 direct context 状态并计算同规则 fingerprint；
3. 将新增 userId 或 token fingerprint 变化都视为 candidate；
4. 必须恰有一个 candidate；
5. candidate 不得已绑定给其他 active alias；
6. 将 alias + exact target 原子写入 recipients 文件；
7. fsync 文件与 parent 后重新读取验证；
8. 删除本次 staging 文件；
9. 只输出 alias、candidate count、`recipient_written=true`。

candidate 为 0 或大于 1、staging 过期、权限异常、alias 冲突或 context 不可用时，Confirm
fail-closed；不改变 recipients 文件，也不猜测目标。

### 6.5 停用

停用接收人是另一条显式 CLI mutation：

- `owner` 不可停用；
- target 从 active 列表移除；
- alias 写入 `retired_aliases`，不保留 retired target ID；
- 历史投递事实不删除；
- 只影响停用后新创建的 Event；
- 不补偿、不撤回、不重发历史消息。

## 7. Alert Notification Attempt 数据模型

### 7.1 新表

新增 Alert Application Domain 第三张表：

```text
alert_notification_attempts
```

字段：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `id` | integer PK | ORM/database identity |
| `event_id` | integer FK | `alert_events.id`, non-null |
| `recipient_alias` | varchar(32) | non-null，只存公开 alias |
| `channel` | varchar(64) | 固定 `clawbot-openclaw-weixin` |
| `status` | varchar(32) | `STARTED / PROVIDER_ACCEPTED / FAILED` |
| `attempted_at` | timestamptz | non-null |
| `completed_at` | timestamptz nullable | terminal status 必填 |
| `error_code` | varchar(64) nullable | 仅稳定公开错误码 |
| `created_at` | timestamptz | non-null |
| `updated_at` | timestamptz | non-null |

约束与索引：

```text
UNIQUE(event_id, recipient_alias, channel)
CHECK status IN ('STARTED', 'PROVIDER_ACCEPTED', 'FAILED')
CHECK STARTED            => completed_at IS NULL AND error_code IS NULL
CHECK PROVIDER_ACCEPTED  => completed_at IS NOT NULL AND error_code IS NULL
CHECK FAILED             => completed_at IS NOT NULL AND error_code IS NOT NULL
INDEX(event_id)
INDEX(attempted_at)
```

不得保存：

- account ID；
- target user ID；
- token/context token；
- 消息正文；
- 接收人姓名、手机号或聊天内容；
- provider stack、SQL 或私有路径。

### 7.2 旧字段兼容策略

首版 migration 只 additive 创建新表和约束。现有：

```text
alert_events.notification_attempted_at
```

保留为只读 legacy 字段：

- 旧 Runtime 继续兼容；
- 新 Runtime 创建 Event 时不再写该字段；
- 新投递事实只写 `alert_notification_attempts`；
- 不把旧 event-level timestamp 伪造为逐人 provider 结果；
- 不在本次 migration backfill、drop 或重解释旧字段；
- 后续只有在 rollback material 退出后，才可用独立任务决定清理。

该策略避免 production migration 与 Runtime promotion 之间出现 schema 不兼容窗口。

## 8. 深模块与接口

### 8.1 RecipientDirectory

职责：安全加载、验证和公开固定接收人 alias/target，不做发送或 DB mutation。

主要接口：

```text
recipients_for(rule_code) -> tuple[ClawbotRecipient, ...]
```

路由、alias 顺序、人数上限和 secret-safe error 全部隐藏在实现内。

### 8.2 AlertDeliveryCoordinator

职责：把一个 committed Event 与一个 notification message 转换为逐接收人的 at-most-once 投递。

唯一调用接口：

```text
deliver(event, message) -> tuple[AlertDeliveryOutcome, ...]
```

调用方只需知道：

- Event 必须已经 commit；
- coordinator 会先提交 attempt，再触发外部发送；
- 返回值只含 alias、status 与公开错误码；
- 不抛出某一接收人的私有 provider detail。

### 8.3 ClawbotRunner

每个 recipient attempt 调用：

```text
send_text(recipient, text)
```

每次调用最多启动一个固定 Node child，并最多调用一次 `sendMessageWeixin()`。Node seam 继续只加载
pinned exact-version modules；target 必须来自已经验证的 frozen recipients 文件，不能由 Event、HTTP、
Redis payload 或自由文本提供。

## 9. 投递顺序与状态机

### 9.1 数据流

```text
completed bar
→ existing evaluator
→ commit AlertEvent
→ format one immutable message
→ resolve frozen recipients
→ for each recipient in deterministic order:
     commit STARTED attempt
     run one Node child / one provider primitive
     update PROVIDER_ACCEPTED or FAILED
```

### 9.2 DB-before-send

- attempt insert/commit 失败：不得发送；
- unique conflict：不得再次发送；
- provider accepted：更新 `PROVIDER_ACCEPTED`；
- 明确 provider/child/context failure：更新 `FAILED + public error_code`；
- 结果更新失败：attempt 保持 `STARTED`。

### 9.3 崩溃窗口

Provider 没有 Guiyi 可控的 idempotency key，因此无法同时保证 exactly-once 与不漏发。
本设计选择 at-most-once：

- `STARTED` 可能表示尚未发送、正在发送或 provider 已接受但 DB 未更新；
- read model 将任何仍为 `STARTED` 的 attempt 展示为 `UNKNOWN`，不猜测其是否仍在运行；
- `UNKNOWN` 不自动 retry；
- AlertEvent 唯一约束与 attempt 唯一约束共同阻止自动重复发送；
- Runtime 崩溃可能导致当前 alias 或后续 alias 漏收；该风险必须在验收说明中保留。

### 9.4 故障隔离

- 一个 recipient 返回正常失败时，继续下一个 recipient；
- target/context 缺失不 fallback 到 owner 或其他 alias；
- timeout、crash、malformed output 不 replay；
- Runtime 进程级 crash 结束当前 delivery，不通过新 worker/queue 恢复；
- 顺序固定为 owner 优先，随后 alias 字典序；
- 第一版最多 5 人，以限制最坏发送时长和 provider burst。

## 10. Preflight、Health 与 Canary

### 10.1 Zero-send Preflight

Runtime promotion 前必须对全部 active recipients：

- 验证 private config 权限、uid、schema 与 alias；
- 验证 pinned OpenClaw/Node/plugin exact version；
- 加载 exact account；
- 恢复 exact target 的 context token；
- 不调用发送 primitive；
- 只返回 alias、ready/failed 与公开错误码。

任一 active recipient 未就绪时，不允许启动新 Alert Runtime。

### 10.2 Runtime Health

Health 只公开：

```text
transport = clawbot-openclaw-weixin
recipient_count
ready_recipient_count
recipient_configured
```

不得公开微信 ID、token、context、私有路径或消息正文。结构健康检查不得产生 child 或网络发送。

### 10.3 Canary

- 每个新增 alias 各自一次独立真实 canary；
- canary 文本只表达通知通道测试，不伪造 HTDY Event；
- 每次真实 send 都需要新的精确单次 Gate；
- recipient 或 owner 只确认“恰好收到一次”；
- canary 不写 AlertEvent，不进入连续授权，也不替代自然 Event 验收。

### 10.4 Delivery Status

提供只读 CLI：

```text
guiyi runtime alert-delivery-status --trading-day <YYYY-MM-DD>
```

它只经 Alert Application Domain read model 输出 Event identity、recipient alias、channel、attempted/completed
时间、`PROVIDER_ACCEPTED / FAILED / UNKNOWN` 与公开 error code。它不得输出私有 ID、token、正文、路径，
也不得修改 attempt、补发、重试或触发 child。

## 11. 消息合同

HTDY 全部接收人收到完全相同的正文：

```text
【归一量化】<SYMBOL> <产品名>

火天大有 · <买入观察/卖出观察/双向观察>
主力：<CONTRACT>
15m · <HH:MM> 收线

研究观察，非交易指令
```

规则：

- 不出现 alias、接收人数或其他接收人信息；
- 不出现收益、仓位、下单或“建议交易”表述；
- SuBing owner 私聊格式和路由不变；
- `auto_order=false` 保持不变。

## 12. 测试矩阵

### 12.1 私有配置

- parent/file mode、uid、regular file、no symlink、O_NOFOLLOW；
- exact schema、非法字段、非法 alias、重复 alias/target；
- owner 缺失、人数 0/超过 5、retired alias 复用；
- 所有错误输出不包含 ID、token、context、路径或正文。

### 12.2 Bootstrap

- prepare snapshot 原子性和权限；
- 新 userId、已有 userId token 更新；
- 0/1/多个 candidate；
- staging alias mismatch、过期、损坏、并发替换；
- confirm 原子写入与失败不变性；
- owner 不可停用、retired alias 不可复用。

### 12.3 路由与消息

- HTDY 精确选择全部 active recipients；
- SuBing 精确选择 owner；
- 未知 Rule fail-closed；
- owner-first + alias sort；
- HTDY footer 精确，SuBing 格式不漂移。

### 12.4 数据库与 migration

- 新表字段、FK、check、unique、index；
- isolated PostgreSQL migration upgrade；
- production DB guard；
- 旧 `notification_attempted_at` 保留兼容；
- 新 Event 不写 legacy 字段；
- 不保存私有 identifier 或正文。

### 12.5 Coordinator 与 Runtime

- Event commit 后才进入 delivery；
- attempt commit 后才调用 sender；
- attempt insert/commit 失败不发送；
- provider accepted/failed 结果更新；
- 结果更新失败保留 STARTED；
- 单 recipient failure 不阻塞后续 alias；
- duplicate Event/attempt 不重发；
- timeout/crash/malformed output 无 retry/fallback；
- Runtime preflight 与 health 隔离真实环境；
- delivery-status 只读、STARTED→UNKNOWN、无 child/发送/DB mutation。

### 12.6 Node 与工程验证

- 每个 alias 最多一个 child、一次 primitive；
- target 必须来自 frozen config；
- pinned versions/module shape；
- context 缺失、错误 target、child timeout/crash 的公开错误码；
- Alert backend targeted tests；
- Alembic isolated tests；
- Node seam tests；
- Runtime health 与 launchd render/plist lint；
- Ruff、Mypy、secret scan、`git diff --check`；
- 无 Web 代码变化时不新增接收人 UI 或 browser acceptance。

## 13. 独立 Gate 顺序

以下 Gate 不能相互授权，任何失败、重试、范围变化或跨会话继续都需要新的精确请求：

1. `D1 Code/Test`：develop 实现、测试、自审；无外部 mutation。
2. `G1 Release`：main/tag/release 独立批准。
3. `G2 Production Migration`：additive 创建 attempt 表；不 drop legacy 字段。
4. `G3 Recipient Bootstrap`：每位新增 alias 的 prepare/confirm 私有写入分别受控。
5. `G4 Zero-Send Preflight`：全部 active aliases ready；不发送。
6. `G5 Recipient Canary`：每位新增 alias 各一次真实消息并确认恰好一次。
7. `G6 Bounded Continuous Authorization`：精确冻结 Rule + Product + aliases + transport。
8. `G7 Runtime Promotion`：exact-tag Alert Runtime switch 与读回。
9. `G8 Natural Acceptance`：等待自然 HTDY Event，只读核对逐人 attempt 与人工收件确认。

首个可授权 tuple 只能是：

```text
htdy_original_15m
× current explicit scope_products（当前 jm）
× exact active aliases
× clawbot-openclaw-weixin
```

SuBing 保持：

```text
subing_entry_signal_v1 × current explicit scope_products（当前 jm） × owner × clawbot-openclaw-weixin
```

新增 alias、停用 alias、扩大 Scope、新 Rule、新 transport、第二次 canary、migration、release 或 Runtime
promotion 都不继承历史授权。

## 14. 验收标准

### 14.1 Code/Test 完成

- 所有配置、bootstrap、model、migration、coordinator、Node、Runtime 和 health 测试通过；
- isolated DB identity 与 production 不同；
- secret scan 无 finding；
- no-order、no-retry、no-fallback 合同有明确测试；
- canonical 文档同步更新为三表 Alert Application Domain 与新授权 tuple；
- 未执行任何 production/private/notification/Runtime Gate。

### 14.2 External Gate 完成

- migration revision、exact release/tag、exact Runtime identity 均读回；
- active recipient count 与 alias 集合读回，但不输出私有 ID；
- 全接收人 zero-send preflight ready；
- 每位新增接收人确认一次 canary；
- continuous authorization 精确记录 HTDY alias tuple；
- SuBing owner-only tuple 未扩大；
- `auto_order=false` 且仓库无订单路径。

### 14.3 Natural Acceptance

自然 HTDY Event 到达后：

- 只有一个 AlertEvent；
- 每个授权 alias 恰有一个 attempt；
- 无未授权 alias；
- 无 replay/backfill/retry/fallback；
- 人工收件确认与 DB attempt 分开表述；
- 没有自然 Event 时保持 `NATURAL_ACCEPTANCE_PENDING`，不以 canary 或 synthetic Event 替代。

## 15. 风险与回滚

### 15.1 已知风险

- Provider 无 Guiyi idempotency key，`STARTED/UNKNOWN` 无法自动判断实际送达；
- Runtime crash 可能使当前或后续 alias 漏收；
- 多接收人顺序发送增加单 Event 处理时长；
- recipient context 可能过期；
- 接收人看到的是研究观察，不能保证其理解或遵循“非交易指令”。

这些风险不得通过引入 retry、queue、fallback 或订单路径静默解决。

### 15.2 回滚边界

- additive DB 表不影响旧 Runtime；
- legacy `notification_attempted_at` 保留，使旧 exact-tag ORM 继续兼容；
- v1 owner 私有文件在新 Runtime natural acceptance 前保留为 rollback material；
- Runtime rollback、私有配置切回和最终旧文件清理分别需要独立 Gate；
- 回滚不删除新 attempt 历史，不重发已经创建的 Event；
- 不因回滚恢复 WeCom 或其他 provider fallback。

## 16. 最小实施顺序

```text
Task 1  additive model + isolated migration
Task 2  v2 recipient config + tests
Task 3  two-phase bootstrap + CLI tests
Task 4  AlertDeliveryCoordinator + routing + attempt state machine
Task 5  Node direct-recipient seam + tests
Task 6  Runtime/health/launchd composition
Task 7  message footer + canonical/TESTING updates
Task 8  complete local verification and independent review
```

Task 1～8 只形成 `CODE_COMPLETE / TEST_COMPLETE`。production migration、bootstrap、canary、release、
continuous authorization、Runtime promotion 与 natural acceptance 均保留为独立 external Gate。
