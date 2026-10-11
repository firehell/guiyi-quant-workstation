# L.M.S 4.0.5 复刻研究说明

## 当前结论与身份

`lms405-evidence-v0.1` 是部分还原的研究工具，不是原作者系统，也不是可执行候选。已实现两腿动作语义、披露时间隔离、区域几何观察和本地行情只读适配；BBB/keybar、行情分类、区域生成、站稳、退出许可没有可辨认公式，仍为 UNKNOWN。独立模式输出 INDETERMINATE，不通过任意 MA/ATR 参数冒充原版。

最终定向测试 `pytest services/quant-api/tests/lms405 -q`：24 passed；`ruff check`：passed。独立审查两项 P2 已修复，包括同事务前缀子状态。

本轮没有订单、Fill、账户、收益、自动晋升、公开 API 或 Runtime 修改。单位数量只用于动作合同验证。继承 [sources.csv](sources.csv) 44 条索引，不将其中所有条目认作 4.0.5：5.0 的风险参数与 6.0 染色规则不加入此版本。

## 规则、来源与验证

|规则|证据等级|实现与验证|边界|
|---|---|---|---|
|相等多空持仓为锁定；恢复多头平空、恢复空头平多|作者明确披露：E41|Position 保存 long/short；LOCK、UNLOCK_LONG/SHORT；完整单位生命周期测试|作者将其比作空仓，本实现保留 gross 两腿；不能抹掉保证金或成本|
|回补与解锁不同|证据支持的候选：E41/E43|REENTER_LONG/SHORT 只接受当前空仓；UNLOCK 只接受等量双腿|没有已披露完整回补时间线，不能推断原触发规则|
|完整区间需触及两个端点|作者明确披露：E41|只输出端点是否在该 Bar 范围；不输出交易许可|跨 Bar 测试的重置与时限未披露；同 Bar 双触及的先后未知|
|大波动短线后回补、小波动稳定惯性持有|作者明确披露的概念：E41|UNKNOWN|波动、稳定性、惯性的阈值和统计窗口未披露|
|近保护区找反向 VPLUS；强弱、趋势中断与 M 段|作者明确披露的框架：E02/E43|UNKNOWN|价格区不能直接变成 keybar；E43 提前保护构成机械等到评级完成规则的反例|
|五 keybar、两结构、BBB|作者明确披露数量，公式未知：E07|UNKNOWN|不以实体比、ATR、突破 lookback 自创参数补齐|
|1/4 系统有人干预，5 有自动运行自述|作者自述：E10/E21|人工事件单独标记，未复刻自动下单|5 的自动化证据不能用作 4.0.5 自动执行证据|

详情：[E41](https://weibo.com/1885745060/Rf0dDugg8)、[E43](https://weibo.com/1885745060/RdYmChTUW)、[E02](https://weibo.com/ttarticle/p/show?id=2309405352159557844998)。其他来源的完整链接和版本归属见索引。

## 输入、输出和动作重放

核心入口 `guiyi_quant.lms405`：

- `Bar`：具体合约、带时区的 completed bar_end、Decimal OHLC；拒绝不完整和非法价格。
- `Zone`：稳定 id、合约、上下端点、known_at、source、可选 expires_at。需显式 Bar.start，且仅 `known_at < bar.start` 且未过期进入观察；编辑后正文不能按原发布日期补填 known_at。
- `Event`：id、具体合约、effective_at、known_at、Action、source、manual。仅事前披露事件进入重放；迟到的事后说明仅用于证据，不改写过去状态。
- `Position`：Decimal long/short；净仓可为零但 gross 非零。初始空仓是单位研究假设，不能作为作者账户事实。可显式传入已知初始快照。
- `apply_action`：空仓进入/回补、等量锁定、解锁、指定腿减持、CLEAR。CLEAR 的 quantity 必须为 gross 总量。非法转换显式失败，不静默净额化。
- `replay_events`：事件去重、相同 id 冲突拒绝、不同合约拒绝、同刻多个动作因顺序不明拒绝。重启可保存 initial Position，但必须用严格晚于已重放游标的事件后缀；不能把旧事件再次加到恢复状态。
- `inspect_bar(mode='author')`：观察可用区域的端点与收盘位置；同 Bar 双触及为 INTRABAR_ORDER_UNKNOWN，始终不冒充突破确认或策略信号。
- `inspect_bar(mode='independent')`：不读取作者区域；原生成公式缺失，环境、信号和建议动作不可判定。

输入的动作是作者行为的归一记录，不是预测。重放输入动作成功不得进入动作预测匹配的分子。本版本没有完整信号策略，不能把所有输出 UNKNOWN 说成无误报。

## 证据集与时间合同

既有 44 条材料全部为已见过的开发证据。本轮 Chrome 重新核对 E43 正文与图片，必要截图保存在原研究包 E43-visible.png（图片只有 875–882 的文字区间，不是带时间坐标的 K 线），重新核对 E41（已编辑）。未新增可冻结的完整行为案例，留出集合为空；不存在盲测结果。

独立审查发现 Bar 内发布区域不能匹配该 Bar 之前的触及；已改为只有节点在 Bar 开始前可用才做几何观察，Bar.start 不明时拒绝观察。事务退出异常也不能保留 WINDOW_READABLE 标签。

E43 2026-08-18 16:33 说明前日按 870–875 防御，回补失败，日内高点 886。缺少原始前日节点发布、实际动作时间、手数和可辨认 K 线周期，不补造完整链条。

E02 2026-10-09 17:22 发布的 FG2701 区域在目标窗口收盘后，不放入此前重放。E11 快照显示 JM 双腿等量，但不能确定进入、锁定、解锁发生时间；FG 空头表格未充分确认版本身份。E35 其他品种的锁仓说明不能替代 FG/JM 完整案例。

保留本轮已访问来源及观察说明；没有系统搜索饱和或读完全量微博。价格完全同为期货也不保证与作者数据一致：物理合约、夜盘交易日、供应商 Bar 边界、周期与取价仍需逐一确认。

## 本地覆盖与实际结果

统一入口 `MarketDataService.query_contract_trading_days`，独立 repeatable-read/read-only 事务，质量和物理端点校验保持不变。仅读取现有 Canonical，不下载、不插值、不缩窗、不换主连。

|请求|1m 结果|此前前缀|
|---|---|---|
|FG2609，2026-08-10～08-21|DATASET_OR_PARTITION_MISSING|本轮未通过主窗口，不声称前缀齐全|
|FG2701，2026-09-21～10-09|2,865 Bar；UTC 09-18 13:01～10-09 07:00|上市以来 56,100 Bar，UTC 01-16 13:01～09-18 07:00|
|JM2701，同上|2,865 Bar；同上|上市以来 56,100 Bar，UTC 01-16 13:01～09-18 07:00|

夜盘属于后续交易日，9月18日 UTC 起点并非越界。数据湖 root 必须显式指向既有权威根，隔离工作区的空数据目录不可替代。初次错误根产生 PARTITION_INTEGRITY_INVALID，纠正根后取得上述结果；未修改数据。

[coverage.json](coverage.json) 保存此次读回；生成的价格路径 [comparison.html](comparison.html) 用实际行情展示。截图周期未确认，因此 1m 仅作价格路径研究，不用于 K 信号验收。没有逐 Bar 作者 OHLC 样本，数据差异与 tick 误差不可计算。

## 可运行命令

从任务/集成仓库根运行，使用现有 API 虚拟环境：

```sh
GUIYI_CANONICAL_DATA_ROOT=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical \
PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python \
scripts/research/lms405_replay.py \
--env-file /Volumes/扩展盘/guiyi-quant-workstation/.env \
--frequency 1m --mode author --output /private/tmp/lms405-author-replay
```

`--mode independent` 重跑独立候选模式；缺少区域生成公式时明确不可判定。`--output` 必须为新的研究目录，不允许覆盖原运行。输出 report.json、可读合约的 JSON 价格观察和 comparison.html；原行情 JSON 不作为正式行情资产提交。

## 验收与失败报告

数值：两合约实际价格路径可读；节点误差未知。信号：公式、周期与事前节点不足，误报/漏报均 null。行为：完整且有明确时间的可验收案例 0，匹配率 null；不是 0% 或 100%。成交/收益：EXECUTION_FACTS_MISSING，不计算。

趋势延续、盘整往返、反向冲击只能检查几何观察与拒绝编造行为；尚无原策略规则支持相关信号验收。单位动作生命周期、非法转换、时序冲突、缺失条件、合约边界、strict-before、函数前缀与增量一致性、Position 恢复一致性均有测试；这些测试不证明原策略一致。

独立区域生成、留出行为验证、成本因果研究仍被公式/证据缺口阻断。最小下一步是正常访问同合约的一组连续事前节点与明确动作记录，确认周期和版本后构建真实生命周期样本；FG2609 数据缺口在本轮不下载约束下保留。尚不允许作为 active 策略或进入任何交易阶段。
