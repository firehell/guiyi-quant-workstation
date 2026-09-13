# Newow 周线 60 品种证据索引

本目录只保存紧凑、可审查的当前现场摘要。冻结范围是 operational 60 品种、三策略、`1w`，
固定 `as_of=2026-09-13T06:36:13+00:00`。完整审计及 compact 原始 JSON 保存在本机 `/private/tmp`，
其 SHA-256 已绑定在 `readiness-summary.json`；它们没有进入 Git，也不构成长期行情事实源。

初始全量只读审计未执行 RQData 行情请求或任何写入。结果仍为 `incomplete`，因此尚未运行 180 组合 matrix，
也不能声称 60 品种周版数据完成。Session metadata proposal、RS source/integrity review、PF2611 非正价格及
其余物理历史缺口仍须分别处理。

周版 staged capability 只开放 `1w` 的 chart、auxiliary、reference 和 comparator。60 个 explanation 枚举项
均明确为 `UNOPENED / NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN`，不会读取 D1/60m，也不计入 incomplete；完整
审计仍由其余权威依赖的真实缺口判定为 incomplete。

owner 已单次批准 PT 周线 calibration batch。执行前重新核对的两个 `contract-warmup` dry-run 与冻结
plan hash 完全一致；PT2608、PT2610 随后各串行 apply 一次，分别通过 14/14 与 18/18 个 target，写后重规划
均为 0 target / 0 bar / 0 provider request。RQData `bytes_used` 从 491,412 增至 5,600,535，整批增加
5,109,123 bytes，低于每个目标 10,000,000 bytes 的异常流量停止线。本次写入意图已消费，不授权重试、
metadata、main/tag、Release 或 Runtime。

写后 PT 依赖 readiness 为 `audited / complete=true`：6 项依赖均 `DATA_READY`，零 repair、零 metadata proposal、
零 provider 请求和零写入。PT 三策略 matrix 随后以只读方式运行，趋势与震荡主图 `READY`，主升浪主图和参考层
返回公开 `NEWOW_INTERNAL_ERROR`；内部只读复现定位为 `NEWOW_PRODUCT_PAIRING_CONFLICT`。PT2610 的 41 根周线
从首根即处于黄带、历史没有真实 BUILD 转换，第 40 根首次转蓝并产生 eligible CLEAR，因此现有稳定配对合同
拒绝制造入场。修改该表达方式会影响策略动作和 ReferenceTrade 语义，需独立 owner 决策，不能归类为数据缺口。
