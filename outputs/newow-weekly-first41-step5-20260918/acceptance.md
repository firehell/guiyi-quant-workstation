# 首批 41 品种周线步骤 5 验收（候选只读）

候选 `1675aa42a13afe4eccd319e29d444e98d2f31d20`；默认页面导航不带 `as_of`，
API 与 Web 均为隔离只读预览。共同完整周截止 `2026-09-18T07:00:00.000001Z`。
首批六品种沿用步骤 4 的同业务代码证据；B/C 的原始首载尝试和新分区证据在本目录。

## 结论

- 固定 41 品种／123 组合均有明确页面结论：111 主图及参考可读；AL、SC、SS、ZN 四品种的 12 组合数据阻断。
- 37 品种的 W1 消费依赖全部 `DATA_READY`；四阻断品种仍在分母。原生审计 1670 依赖：1660 READY、8 UNAVAILABLE、2 合法短 owner NOT_APPLICABLE；零 provider／零写入。
- B/C 的 93 可读组合有 744/744 分区 HTTP 200、共同截止；适用状态含 12 MACD 预热、9 照妖镜预热、31 震荡比较器区段不足，图表质量版本为独立 W1 v1，当前展示窗口缺价中断计数为零。
- 首批六品种的 PD/PT MACD 各三组合预热；AO、EC、LC、PS 也有辅助预热。正常预热不等于数据缺口或全策略 READY。
- D1 候选 chart 60×3 有 179 ready、RS 震荡一项合法 warming。原生全域审计初次 1800 秒预算耗尽；四个有界只读批次补齐 84 项，旧汇总为 176 READY、RS 震荡 1 WARMING、AL 三项 DATA_UNAVAILABLE、0 未检。随后在同一截止时间重新只读审计 AL、ZN 六项均 READY；按各品种最新结果合并为 179 READY、1 WARMING、0 未检。审计跨多个时刻，未冻结统一数据修订，不能声称一次原子批次通过。
- 其余 19 品种的 W1 和 60m 候选路由 38/38 拒绝；正式产品仍只开放 D1。
- 六次首次尝试异常独立保留：步骤 4 的 RB 震荡代际冲突、BU 趋势等待超时，以及 B/C 四次浏览器进程故障；后续是独立新导航，不覆盖最初失败。

## 逐品种

| 品种 | W1 来源 | 三策略页面 | 辅助／阻塞 | D1 图表 | D1 全历史审计 |
| --- | --- | --- | --- | --- | --- |
| AU | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| RB | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| CU | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| BU | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| PD | 全部 READY | 3/3 可读 | MACD 预热 | ready/ready/ready | READY/READY/READY |
| PT | 全部 READY | 3/3 可读 | MACD 预热 | ready/ready/ready | READY/READY/READY |
| A | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| AG | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| AL | DATA_READY 90, DATA_UNAVAILABLE 2 | 0/3 阻断 | 最新 AL2611 1w REPLAY_ENDPOINTS_MISSING，2025-11-21；早期曾报 1d 前缀缺口 | ready/ready/ready | READY/READY/READY（重检；早期三项不可用） |
| AO | 全部 READY | 3/3 可读 | MACD/照妖镜预热 | ready/ready/ready | READY/READY/READY |
| AP | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| C | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| CF | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| EC | 全部 READY | 3/3 可读 | MACD/照妖镜预热 | ready/ready/ready | READY/READY/READY |
| FG | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| FU | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| HC | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| I | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| JD | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| JM | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| L | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| LC | 全部 READY | 3/3 可读 | MACD/照妖镜预热 | ready/ready/ready | READY/READY/READY |
| LH | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| M | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| MA | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| NI | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| P | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| PB | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| PP | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| PS | 全部 READY | 3/3 可读 | MACD 预热 | ready/ready/ready | READY/READY/READY |
| RM | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| RU | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| SA | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| SC | NOT_APPLICABLE 2, DATA_READY 88, DATA_UNAVAILABLE 2 | 0/3 阻断 | SC2611 1w REPLAY_ENDPOINTS_MISSING，首缺 2025-11-07 | ready/ready/ready | READY/READY/READY |
| SN | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| SS | DATA_READY 80, DATA_UNAVAILABLE 2 | 0/3 阻断 | SS2611 1w REPLAY_ENDPOINTS_MISSING，首缺 2025-11-21 | ready/ready/ready | READY/READY/READY |
| TA | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| UR | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| V | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| Y | 全部 READY | 3/3 可读 | 无辅助预热 | ready/ready/ready | READY/READY/READY |
| ZN | DATA_READY 90, DATA_UNAVAILABLE 2 | 0/3 阻断 | 最新 ZN2611 1w REPLAY_ENDPOINTS_MISSING，2025-11-21；早期曾报 1d 前缀缺口 | ready/ready/ready | READY/READY/READY（重检） |

## 证据边界

- `page-matrix.json` 与 `browser-b.jsonl`、`browser-c.jsonl` 保存每页原始首载；步骤 4 的 `acceptance.md` 保留六品种最初异常与 PT 后续授权读回。
- `section-matrix-bc.jsonl` 保存每个可读 B/C 组合的主图、五辅助、参考、比较器及 token；`w1-readiness-41x3.json` 保存完整来源依赖。
- `d1-api-chart-60x3.jsonl` 与原生 `d1-readiness-60x3.json` 代表不同窗口与口径；原生报告初次预算耗尽，四个 `d1-native-remainder-*.json` 对原 84 未检项给出终态。`d1-native-combined-summary.json` 保留当时的 176/3/1，`d1-al-zn-fresh-readback.json` 保留后续 AL、ZN 的六项重检；数据状态可能在串行审计期间改变。
- `snapshot-blockers.json` 保留早期快照 409，`snapshot-blockers-readback.json` 保留最新四品种 W1 409；首个错误诊断有时序变化，不是精确数据修复计划或生产写入授权。

状态：`PARTIAL`。本步 123/123 与 D1 180/180 均有明确结论，但 W1 12 项来源阻断；D1 现有逐品种重检结果也不能代替同一冻结修订下的完整复验，不能进入 release candidate。
最小下一步：对 AL、SC、SS、ZN 做逐合约只读 source/plan 核查，准备精确数据差量；任何真实下载／Canonical 写入另取批次授权。
