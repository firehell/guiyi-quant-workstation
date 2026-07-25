# 火天大有原版 XMA 实时预警实施计划

## 目标

允许 `huotian_dayou_original_v0` 在 JM 当前实际主力合约的 confirmed 15m bar
上生成专用实时观察预警。预警允许未来函数与重绘，Web 留痕并可由独立 Gate
发送企业微信；它不是正式 `SignalEvent`、回测结论或交易指令。

## 固定契约

- 指标：`huotian_dayou_original_v0`
- 策略：`huotian_dayou_original / v0-observation-only`
- 预警策略：`htdy_original_repainting_realtime_v1`
- 范围：JM 当前实际主力、15m、confirmed bar
- 买多：三连黄 K 首次成立
- 卖空：三连白 K 首次成立
- 同 bar 多空同时成立：单条 `conflict_observation`
- 重绘后不撤销、不更正、不补发；同一 bar 后续 revision 不得重复发送
- Web 与企业微信文案必须声明未来函数、重绘、仅供观察、不是交易指令

## 实施

1. 将现有 original-v0 Python PoC 提升为 quant-core observation-only 内核。
2. 新增独立 `htdy_observation_alerts` 表、只读 preview/list/detail API。
3. 在 live 15m 聚合后由独立开关执行 evaluator；mapping、quality、lineage
   或 confirmed-bar 条件不满足时 fail-closed。
4. 扩展 notification 记录以引用 HTDY observation alert，并使用独立的企微
   开关、队列任务、幂等键和最多三次重试。
5. Web Signals 页面增加“重绘观察预警”页签和 K 线深链。
6. 更新 indicator policy、DECISIONS、SIGNAL_EVENTS 与 HTDY 规格。

## Gate 边界

- 默认关闭：
  - `GUIYI_HTDY_REALTIME_ALERTS_ENABLED=false`
  - `GUIYI_HTDY_WECOM_AUTOSEND_ENABLED=false`
- 代码/模拟 Gate：`HTDY_REALTIME_OBSERVATION_ALERT_READY`
- 单条真实企微 Gate：`HTDY_REALTIME_WECOM_ALERT_PASSED`
- 当前 S6-08 完成前不得部署、启用或真实发送，不得让本任务写入
  `strategy_signals`、`signal_events`、订单或交易表。
