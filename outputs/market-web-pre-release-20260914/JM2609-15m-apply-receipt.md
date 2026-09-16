# JM2609 15m 数据修复回执

时间：2026-09-14 22:41 CST

执行代码：`d3b6439320c4020370c2f89aa040da5059b705e9`

授权范围：`jm / JM2609 / 15m / 2025-09-15..2026-08-18`。未扩展到其它合约、频率、Scope、Rule、
Event、通知、Release 或 Runtime。

## Apply 前计划

- 命令：`guiyi data contract-warmup --symbol jm --contract JM2609 --through 2026-08-18 --frequency 15m`
- plan SHA-256：`d48a04f8ff510f53ddc796a9610210f1b4f85a125edd3c8d5809f4b71dd1c818`
- dependency：`1m`
- 目标：8 个 1m 月分区、8 个 15m 派生月分区
- 15m missing：3165；provider requests：8

## Apply 结果

- `status=passed`
- `readonly=false`
- `applied=16`
- `blocked=0`
- `failed=0`
- `failures=[]`
- 返回 plan hash 与批准 hash 一致

## Apply 后读回

同参数只读重规划：

- `direct_target_count=0`
- `derived_target_count=0`
- `expected_bar_count=0`
- `provider_request_count=0`
- `targets=[]`
- `failures=[]`

当前代码的默认 JM SuBing 页面请求返回 HTTP 200，固定 `as_of=2026-09-14T11:00:00Z`，统计窗口
`2026-08-18..2026-09-14`，`source=historical_replay`，`formula_version=subing_ths_15m_v3`，返回 21 条
参考记录与 26 个信号。显式把 `since` 扩到 2025-09-15 会继续暴露另一个 `JM2601` 历史缺口；该合约不在
本次授权范围，未执行任何额外 apply。
