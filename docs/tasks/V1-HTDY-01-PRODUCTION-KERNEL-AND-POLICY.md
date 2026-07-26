# V1-HTDY-01 Production Kernel and Policy

日期：2026-07-26

## 结论

`HTDY_ORIGINAL_PRODUCTION_KERNEL_READY` 与
`HTDY_REALTIME_REPAINTING_POLICY_READY` 仅表示 Step 1 的纯函数、exact policy、Registry binding 和
Python/Web golden 已冻结。`FORMAL_BACKTEST_POLICY_UNCHANGED`：original 仍为
`observation_only`，不得进入 formal history/backtest、普通 live、alert、SignalEvent、Notification、
WeCom 或交易。

## 冻结范围

- `huotian_dayou_original_v0/original-v0` 的 centered clipped XMA production kernel；25 的 double
  future horizon=24，conservative repaint scan zone=27；该 exact kernel 仅接受 `channel_period=25`。
- exact JM actual-rank1 15m partial first-seen repainting observation policy，validator 对 missing、extra
  或 drifted identity/safety field fail-closed。
- tracked Python/Web golden payload（12 位规范化数值、非有限值为 null）和 canonical hash；所有输入
  序列都 fail-closed 为一维，payload 时间冻结为 JSON 可序列化 ISO-8601 文本。
- Web 仍只允许 historical/browser observation overlay；不新增 live 或 alert capability。

## 明确未做

- 未修改 Runtime/service/evaluator、数据库/model/migration、SignalEvent、Notification/WeCom、strict
  strategy 参数、Stage 5 或 report 14/15。
- 未运行真实 realtime、未写数据、未发送通知、未部署；这些需要后续 hash/scope-bound Gate 与用户授权。
- 未关闭 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，尤其 `XMA(6)` 外部 oracle 仍 unresolved。

## 验证

执行 Step 1 required Python focused suite、Web full tests/build、Ruff、secrets check 与 diff check；具体
命令和输出由同次 checkpoint evidence/report 记录。

## 当前精确哈希

```text
htdy_original_source_sha256=560d78e901387e54916e9850eb880d3d34565a8b6cebd28f552c33ad6bbcfeaf
realtime_observation_policy_sha256=603bf5adfca33903bdec3983f54937fec653bcd4f49e77e5a1bf120fe38378c2
golden_payload_sha256=de09bd32c4305568bfe1163ecdd718ea5ed0dbb06069ac49eb162043b1ec79bd
```
