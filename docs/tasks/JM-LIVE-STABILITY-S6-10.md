# HTDY 五交易日长稳与故障恢复 Gate（S6-10）

更新时间：2026-07-26

## 状态

```text
CONTRACT_SKELETON_FROZEN
IMPLEMENTATION_NOT_STARTED
FAULT_INJECTION_NOT_AUTHORIZED
LONG_RUNNING_READY=false
```

## 硬前置

- S6-07 Ready、HTDY S6-08 Passed、S6-09 single-send Passed；
- full backup 和 isolated restore smoke Passed；
- autosend=false；
- SignalEvent 长稳策略只产生 observation event，不自动通知。

## 五日合同

- 至少五个真实 DCE 交易日，包含夜盘和每日 EOD 自动增量；
- 持续采集 Runtime commit、flags、actual mapping、scheduler heartbeat、EOD watermark、
  15m snapshot hash、HTDY candidate/created/unchanged/blocked、事件与通知计数及错误恢复；
- HTDY 同桶不重复、不产生 `signal_changed`，不自动通知；
- live 不进入 historical active；失败记录不得删除或改写；
- 任何代码、policy、schema、strategy 或 Runtime deployment 变化重置五日窗口。

## Approval C

故障注入必须在执行前一次性冻结并批准完整矩阵和时间窗口：live scheduler、未加载或关闭状态的
notification worker 边界、API/Web、Redis、PostgreSQL、网络/RQData 和 Mac 重启恢复。
未取得 Approval C 前只允许工具、Ledger、fake tests 和只读观察。

只有五日 Ledger 与故障恢复全部通过后，才可发布本地个人工作站范围内的
`LONG_RUNNING_READY / JM_RUNTIME_READY`；不包含公网、SaaS、多用户或自动交易。
