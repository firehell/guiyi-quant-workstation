# HTDY S6-08 schema-v3 真实验收证据

状态：

```text
JM_LIVE_SIGNAL_EVENT_PASSED
LIVE_SIGNAL_EVENT_GATE_PASSED
HTDY_FIRST_SEEN_EVENT_OBSERVED
```

## 身份

- Runtime commit：`844b3f9beded6aae3375e25e34a7e5250f0a1ae2`
- PostgreSQL revision：`20260721_0025`
- 交易日：`2026-07-28`
- 品种/实际主力/周期：`jm / JM2609 / 15m`
- 事件：`SignalEvent.id=4 / long / signal_created`
- policy：`htdy_original_xma_15m_first_seen_v1`

## 执行结果

- 首次自然事件：`created=1 / changed=0 / unchanged=0 / blocked=0`
- 同事件幂等探测：`created=0 / changed=0 / unchanged=1 / blocked=0`
- SignalEvent 授权已关闭，packet/hash 已清空。
- 企业微信 autosend 始终为 false。
- 未构造行情、未注入 bar、未手工写事件。
- 未创建 ReviewNote、notification、order 或 trade。

## Final receipt

- 文件：`final_receipt.json`
- 文件 SHA-256：`e1a34399310c8a585127bea65851f6f49d78c73d428e285cb29e855db74f2d98`
- canonical receipt hash：`9aee80f1be1b6041910b55ccfed3fdfbce3929c192aff7ec5b34ab71cb4001ea`

该证据只证明 exact HTDY realtime observation-only 自然事件 Gate 通过，不证明历史
有效性、收益、通知 Ready、交易 Ready 或长稳 Ready。
