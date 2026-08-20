# Alert 固定收件人简化设计

日期：2026-08-20

状态：develop `CODE_COMPLETE / TEST_COMPLETE`；全部外部 Gate pending

范围：`clawbot-openclaw-weixin` 私聊固定收件人

## 1. 结论

本设计是本功能唯一 active 合同。它采用本地单用户、单 operator 的个人工作站模型：

- active 收件人为 `1..4` 人，固定包含 `owner`，最多增加 3 位朋友；
- `htdy_original_15m` 通知冻结目录中的全部 active 收件人；
- `subing_entry_signal_v1` 始终只通知 `owner`；
- 每个收件人最多启动一个固定 Node child，并最多调用一次 `sendMessageWeixin()`；
- 不新增 PostgreSQL 表，不保存逐收件人发送事实；
- 失败不 retry、queue、replay、backfill 或 fallback；
- Alert Runtime 必须停止后才能修改 Git 外收件人配置，运行中不热重载。

当前 production 仍是
`v1.6.2@dbdf6da49d75353a478675a3584de0f91c8bd85c` 的单 `owner` exact Runtime。
本实现没有初始化四人配置，没有发送消息，也没有发布或切换 Runtime。

## 2. 产品边界

### 2.1 做

- owner 管理一个小规模、固定、已同意接收研究观察的私聊集合；
- HTDY 使用同一 Event 正文按确定顺序逐人发送；
- SuBing 保持原 owner-only 语义；
- 用两次 context snapshot 的 fingerprint 差异绑定朋友，不要求用户复制微信 ID；
- 用结构健康、全收件人 zero-send preflight 和精确单 alias canary 分开验证配置、上下文和真实发送。

### 2.2 不做

- 微信群聊、收件人 Web/HTTP 管理、多用户权限或订阅系统；
- 逐收件人数据库事实、送达查询接口或消息正文存储；
- durable queue、自动恢复、retry、replay、backfill 或 provider fallback；
- 修改 OpenClaw、腾讯插件，或监督其进程；
- 修改 HTDY/SuBing 公式、Rule、Scope、Event 唯一性、Market Data 或订单边界。

## 3. Rule 路由合同

路由只由代码中的 exact Rule 决定：

```text
htdy_original_15m       -> owner + every other active alias
subing_entry_signal_v1  -> owner
```

规则：

- `owner` 必须存在且排第一；其余 alias 按字典序稳定排列；
- active count 必须为 `1..4`；
- 未知 Rule、空集合、重复 alias/target 或非法配置全部 fail-closed；
- 收件人配置不修改 `alert_rules.scope_products`；
- 未来新增 Rule、alias、Scope 或 transport 不继承已有授权。

## 4. Git 外 v2 配置

新代码的唯一 active 收件人源通过以下环境变量注入：

```text
GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH
```

文件合同：

```json
{
  "schema_version": 2,
  "channel": "openclaw-weixin",
  "account_id": "<private>",
  "active_recipients": [
    {"alias": "owner", "target_user_id": "<private>"}
  ],
  "retired_aliases": []
}
```

安全规则：

- parent 为 current uid 的真实 `0700` 目录，不允许 symlink；
- 文件为 current uid 的普通 `0600` 文件，按 `O_NOFOLLOW` 打开并核对 inode；
- schema 使用 exact keys；alias 只允许 `[a-z][a-z0-9_-]{0,31}`；
- account、target、active alias、retired alias 均按各自唯一性校验；
- retired alias 不可复用，`owner` 不可停用；
- token、context token、消息正文、姓名和聊天内容不得写入文件、日志或 CLI 输出；
- Runtime 构造只加载一次并冻结，运行中不重新读取。

旧 v1 owner 文件只供本次 owner-only v2 初始化读取；它不是新 Runtime 的第二个 active source。

## 5. 单 operator 配置流程

所有配置 mutation 只能由一个 operator 在 Alert Runtime 已停止时串行执行。没有多写者协议，也不允许
两个终端同时操作。

### 5.1 Owner-only v2 初始化

```text
guiyi recipients init
```

初始化从现有安全 v1 owner 文件读取 exact account/target，排他创建只含 `owner` 的 v2 文件，完成权限、
原子替换、fsync 和重读验证。已存在 v2 文件时拒绝覆盖。

这是仓库外真实配置写入，必须有范围明确的一次性执行意图。当前未执行。

### 5.2 每位朋友的 prepare / 首次私聊 / confirm

```text
guiyi recipients prepare --alias <alias>
<目标朋友向绑定微信发送一条普通私聊>
guiyi recipients confirm --alias <alias>
```

Prepare 与 Confirm 是两个独立真实操作：

1. Prepare 读取一次 pinned direct context snapshot；
2. 用 32-byte random nonce 和 HMAC-SHA256 保存 user 与 user+token fingerprint；
3. staging 只保存 alias、时间、nonce、fingerprint，采用同一 private parent 下的 `0600` 文件；
4. staging 有效期固定为 10 分钟；
5. 朋友的普通私聊由既有 OpenClaw 入站流程形成或刷新 direct context；Guiyi 不监听、不回复；
6. Confirm 再取一次 snapshot，必须恰有一个新增或 token 变化的 direct candidate；
7. candidate 未绑定、alias 可用且 staging/inode 均一致时，才原子写入 v2 directory 并删除 staging；
8. 任一歧义、过期、权限、身份或结构错误都 fail-closed，不猜测、不部分写入。

Prepare 和 Confirm 各自需要新的精确单次执行意图。当前没有任何朋友完成 pairing。

### 5.3 停用

```text
guiyi recipients retire --alias <alias>
```

停用只允许非 owner active alias。目标从 active 列表删除，公开 alias 进入不可复用的
`retired_aliases`；不保留 retired target，不修改历史 Event，也不补偿或重发历史消息。生效仍需之后的
新 Runtime switch。

## 6. Runtime 与发送行为

### 6.1 构造

Runtime 构造顺序固定为：

```text
activation marker
-> exact dependency/version validation
-> load and freeze v2 directory once
-> zero-send probe every active recipient
-> construct sender/runtime
-> caller explicitly enters run_forever
```

任一收件人 preflight 不 ready 时，整个 Alert Runtime fail-closed，不订阅 Redis、不发送。

### 6.2 Event 发送

```text
completed bar
-> existing evaluator
-> commit one AlertEvent
-> format one immutable message
-> resolve recipients from the frozen directory
-> owner first, then sorted aliases
-> one runner call per alias
-> one Node child and at most one provider primitive per runner call
```

一个普通 alias 失败时继续后续 alias；进程级异常不被吞掉。公开日志/异常只包含 alias 和计数摘要，
不含 private target、context、路径或消息正文。

本模型接受部分送达风险：前面的 alias 可能成功、后面的 alias 可能失败或因进程退出未执行。系统不保存
逐人结果，也不能从 `alert_events.notification_attempted_at` 推断逐人送达；该字段仍只是既有 Event 级
批次尝试元数据。operator 只能结合当次公开摘要和人工收件确认判断情况，不能自动补发。

## 7. Preflight、Health 与 Canary

### 7.1 Zero-send preflight

```text
guiyi runtime clawbot-preflight
```

它对冻结目录中的全部 active alias 逐一验证 exact account/target context，允许启动受限 child，但绝不调用
发送 primitive。输出仅含 configured、recipient/ready count 与公开失败 alias。它是独立外部 Gate，当前未执行。

### 7.2 Runtime health

Health 只做本地结构校验，不启动 child、不发送。公开字段固定为：

```text
transport
configured
recipient_count
ready_count
would_send=false
```

不得公开 alias 列表、account、target、context、路径或正文。

### 7.3 Canary

```text
guiyi runtime alert-canary --alias <active-alias>
```

一次命令必须精确选择一个 active alias，最多发一条固定 canary。每次真实 canary 都需要新的精确单次执行
意图；它不创建 Event、不改变 Scope、不进入连续授权，也不能替代自然 Event 验收。当前未执行。

## 8. 消息合同

HTDY 全部 active 收件人收到同一正文，并以以下文字结束：

```text
研究观察，非交易指令
```

正文不得包含 alias、收件人数、其他收件人、收益承诺、仓位或下单建议。SuBing 的正文和 owner-only
路由不变，`auto_order=false` 不变。

## 9. 独立 Gate

以下 Gate 不相互授权，任何失败、重试、范围变化或跨会话继续都需要新的明确请求：

1. develop code/test：仓库实现与本地验证；已完成；
2. owner-only v2 init：仓库外私有配置写入；pending；
3. 每位朋友 prepare：每人一次独立 staging 写入；pending；
4. 每位朋友 confirm：每人一次独立 v2 directory 写入；pending；
5. 全收件人 zero-send preflight：pending；
6. 每位新增 alias 的单次真实 canary 与人工确认：pending；
7. 精确 bounded authorization：HTDY exact Rule + Scope + exact alias set + transport；pending；
8. main/release/tag：pending；
9. exact-tag Alert Runtime promotion/switch/readback：pending；
10. 自然 HTDY Event 验收：pending。

SuBing 的授权 tuple 始终保持：

```text
subing_entry_signal_v1 x explicit scope_products x owner x clawbot-openclaw-weixin
```

在第 9 项成功前，production 继续使用当前 `v1.6.2` 单 `owner` exact Runtime。

## 10. 验收标准与风险

### 10.1 Code/Test

- v2 directory、两步 pairing、路由、fan-out、Node、CLI、health 和 launchd 测试通过；
- 全 backend、全 engineering、Node、Ruff、正常 follow-imports Mypy、shell/plist、secret scan 与 diff check
  fresh 通过；
- Alert Application Domain 仍只有 `alert_rules`、`alert_events` 两张表；
- 未执行任何真实 config、preflight、canary、release 或 Runtime 操作。

### 10.2 已知风险

- 顺序发送会增加单 Event 处理时长；
- direct context 可能失效；
- 单 alias 失败或 Runtime crash 会造成部分送达；
- 没有逐收件人持久化证据，无法自动确认或恢复送达；
- canary 通过不等于自然 Event 送达，也不表示策略有效或交易建议。

这些风险必须如实保留，不通过自动重试、消息队列、第二套 provider 或订单路径掩盖。
