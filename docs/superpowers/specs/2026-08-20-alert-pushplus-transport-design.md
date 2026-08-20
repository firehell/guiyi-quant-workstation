# Alert PushPlus Transport 设计

日期：2026-08-20

状态：v1.6.4 released / Runtime promoted；自然 HTDY/SuBing Event 验收 pending

## 目标

把 Alert 的通知实现收敛为 PushPlus：HTDY 通知一个由 owner 与最多三位朋友组成的专用 Topic，SuBing
继续只通知 owner。移除 OpenClaw/Clawbot 固定私聊与未完成的 WxPusher 代码，不保留兼容路径。

## 边界

- `AlertNotificationDispatcher` 只把 Rule 映射到逻辑 audience，不认识 provider token 或 Topic。
- `NotificationTransport` 是最小 provider-neutral seam；当前 composition 只装配一个 PushPlus adapter。
- HTDY：`htdy_observers`，每个 Event 一次 Topic 请求。
- SuBing：`owner`，每个 Event 一次无 Topic 请求。
- 使用官方 Python SDK `perk-pushplus-sdk==1.2.1`，固定 `wechat` channel 与 `txt` template。
- SDK shortCode 仅表示 provider 接受，不表示微信最终送达；Event 不新增逐人送达状态。
- 不实现 Open API 成员同步、callback、逐人 fan-out、retry、queue、replay、backfill、fallback 或订单。

## 配置与安全

唯一环境变量为 `GUIYI_ALERT_NOTIFICATION_CONFIG_PATH`，指向 Git 外 private JSON：

```json
{
  "schema_version": 1,
  "transport": "pushplus",
  "transport_config": {
    "message_token": "<32-character token>",
    "htdy_topic": "<topic code>"
  }
}
```

parent 必须为 `0700`、file 必须为 `0600`、owner 必须是当前 uid；拒绝 symlink、替换竞态、额外字段、
非法 token/Topic。token、Topic code、完整 shortCode 不进入仓库、日志、health、Event 或 CLI 输出。

## 运维与健康

API 与 Alert launchd 必须指向同一个配置路径。结构健康检查不联网，只公开
`transport=pushplus`、`configured`、`audience_count=2`、`would_send=false`。真实 canary 必须显式选择
`--audience owner|htdy_observers`，并属于独立通知 Gate。owner 与 HTDY Topic 的单次真实 canary 均已完成、
由 provider 接受且由用户确认实际收到；release 或 Runtime switch 不得重复执行这两次历史 canary。

## Topic 管理

Topic 成员只在 PushPlus 外部管理。创建者与最多三位朋友扫码加入专用 Topic；可以先以当前成员启用，
之后加入第 4 人。operator 每次人工核对总人数在 `1..4` 内；Guiyi 不保存成员身份，也不调用 Open API
查询成员。超过 4 人、未知成员或更换 Topic 属于新的授权范围。

## 上线边界

当前 production exact-tag `v1.6.4` Runtime 已启用 PushPlus；Git 外 token/Topic 配置与 owner、HTDY
Topic 两次历史 canary 已完成，release/switch 未重复 canary。持续运行边界只允许
`htdy_original_15m × jm × htdy_observers × pushplus-wechat-topic` 与
`subing_entry_signal_v1 × jm × owner × pushplus-wechat`；自然 HTDY/SuBing Event 验收仍 pending。后续如需
更换 provider，只新增 adapter 并在 composition 选择唯一 active provider，不改 Rule、evaluator、Event
或数据库，并重新取得对应受控外部操作意图。
