# Newow 周线 60 品种证据索引

本目录只保存紧凑、可审查的当前现场摘要。冻结范围是 operational 60 品种、三策略、`1w`，
固定 `as_of=2026-09-13T06:36:13+00:00`。本轮 PT probe、完整审计和同源离线摘要保存在本工作树
`local-evidence-closeout-20260913/`，其 SHA-256 已绑定在 `readiness-summary.json`；生产明细不提交 Git，
也不构成长期行情事实源。

本轮固定代码 `c412b354e` 的全量只读审计未执行 RQData 行情请求或任何写入。180 个主组合已全部运行并通过
exact scope 校验，主图 READY 6、参考层 READY 9、两者联合 READY 6；联合 READY 仅为 `pd`、`pt` 各三策略。
审计结果仍为 `incomplete`，因为 2,233 个枚举/dependency/metadata/case-section 项保持 `UNKNOWN`；这与
`MATRIX_COVERED=true` 分开，不能声称 60 品种周版数据完成。当前原生结果有 896 个普通 PROPOSED、9 个 RS
source/integrity `REVIEW_REQUIRED`、494 行 Session metadata proposal（247 个唯一目标）和 PF2611 非正价格。

周版 staged capability 只开放 `1w` 的 chart、auxiliary、reference 和 comparator。60 个 explanation 枚举项
均明确为 `UNOPENED / NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN`，不会读取 D1/60m，也不计入 incomplete；联合
READY 的 6 个 case 中，MACD 仍为 WARMING、杯柄仍为 NOT_APPLICABLE，比较器 4 个 NOT_APPLICABLE、2 个
样本不足，不得改写为正常信号。

owner 已单次批准 PT 周线 calibration batch。执行前重新核对的两个 `contract-warmup` dry-run 与冻结
plan hash 完全一致；PT2608、PT2610 随后各串行 apply 一次，分别通过 14/14 与 18/18 个 target，写后重规划
均为 0 target / 0 bar / 0 provider request。RQData `bytes_used` 从 491,412 增至 5,600,535，整批增加
5,109,123 bytes，低于每个目标 10,000,000 bytes 的异常流量停止线。本次写入意图已消费，不授权重试、
metadata、main/tag、Release 或 Runtime。

写后 PT 依赖 readiness 为 `audited / complete=true`：6 项依赖均 `DATA_READY`，零 repair、零 metadata proposal、
零 provider 请求和零写入。旧手写检查器曾错误把 typed wire 值 `ready` 与大写 `READY` 比较，exit 1 原记录保留。
本轮新的固定 PT 检查实际 `accepted=true`：chart/reference 均为 typed READY、snapshot token 相同；PT2610 在
`2026-09-04T07:00:00+00:00` 的唯一初始 CLEAR 为 sequence 0、related BUILD 为空、资格
`INITIAL_CLEAR_NO_ENTRY`，且没有产生 ReferenceTrade。

下一普通数据候选只从本轮完整报告提取为 `ec/EC2607/1w`：连同 1d companion 共 84 根、8 个请求，原生 plan
hash 为 `5c7a1debdae9001497638f747b9ec0eb8cca2c8b3cf66e32ec28351b353dae72`，不含 metadata/source/integrity
阻断。首次独立 dry-run 误传只允许 apply 使用的 expected hash，CLI 在参数层拒绝且零 provider/零写；正确重试
被宿主拒绝，未绕过。因此该候选仍需一次新的明确只读意图重算并匹配 plan/hash，之后若要 apply 还需另一个
单次写入批准。本任务没有执行任何 provider 或数据写入。

真实候选页面验收也保持独立 pending：固定 Web 端口 5174 已被 `/Volumes/扩展盘/guiyi-quant-workstation/apps/quant-web`
中的其他进程占用，本任务未停止或复用它，也未改端口绕过候选身份合同。PT、正常 Trade 样本、gap/source 样本
的真实页面回读没有用 fixture 代替；fixture E2E 结果只证明 UI 行为。
