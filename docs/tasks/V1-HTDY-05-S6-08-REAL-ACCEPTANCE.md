# V1-HTDY-05 S6-08 真实自然事件验收

更新时间：2026-07-26

## 状态

```text
STEP5_PREFLIGHT_CODE_READY
FRESH_APPROVAL_A_PENDING
S6_08_NATURAL_EVENT_GATE_PENDING
```

这不是 HTDY 历史验证、收益证明、通知 Ready、交易 Ready 或长稳 Ready。

## 精确观察合同

本任务只允许：

```text
product=jm
contract=当日 RQData rank=1 实际主力
period=15m
strategy=htdy_original_realtime_first_seen/v1.0
indicator=huotian_dayou_original_v0/original-v0
source_mode=live_realtime_repainting
policy=htdy_original_xma_15m_first_seen_v1
repaint_scan_bars=27
partial_allowed=true
first_seen_no_retraction=true
historical_backtest_allowed=false
wechat_autosend=false
auto_order=false
```

原版 XMA 含未来依赖且会重绘。事件只冻结首次检测快照，后续信号消失、反向或源
revision 不撤回、不修改。

## Step 5 前置修复

Step 4 的五日 parent 已冻结 `2026-07-27` 至 `2026-07-31`，但真实 Runtime 在首日开始前
尚无 `2026-07-27` 的 `MainContractMap`。Step 5 增加以下 fail-closed 边界：

- 每个 child day 首轮从 RQData 精确查询 `jm + rank=1 + 当日`；
- 只在既有 `main_contract_map` 创建一条 exact mapping，不新增 migration；
- DB duplicate/conflict、RQData 非 actual contract、日期漂移或已冻结 mapping 漂移均拒绝；
- mapping 与 create-only receipt 在同一 Runtime 事务提交后落盘，后续轮次只校验 receipt 与
  当前 DB 行，不重复修改；
- scheduler 启动预检只验证 parent，不进入 daily write phase；
- 每轮仅输出脱敏 `htdy_observation_summary`，包含 day/contract/bucket、候选/阻断数量、
  created/unchanged/changed 和最新 event id；
- 因 Step 4 工程收口晚于原冻结时间，唯一补救窗口为首日上海时间 `08:30` 前，且必须确认
  首日无 HTDY event、无 daily child；过时或状态不洁立即拒绝，不静默换窗口。

## 执行顺序

取得新代码 checkpoint 对应的三个 fresh hash，并由用户在一条消息中精确批准后，才允许：

1. verify/execute code-only deployment；
2. verify/execute S6-07 code-only rebind；
3. verify service parent；
4. 只开启 live Runtime 与 SignalEvent，autosend 保持 false；
5. 自然等待最多五个交易日，不注入行情、不手工写事件；
6. 首个事件后要求一次同 key `unchanged>0 / created=0 / changed=0`；
7. 立即关闭 SignalEvent 并清空 packet/hash；
8. 验证 Runtime/live/after-market、Web/Review deep-link 与全部禁写计数；
9. create-only 发布 schema-v3 final receipt。

若五个交易日没有自然事件，关闭授权并仅发布：

```text
PENDING_NATURAL_HTDY_EVENT
```

新的五日窗口需要新 parent 与新 Approval A。
