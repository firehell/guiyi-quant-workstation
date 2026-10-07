# SN 锡历史候选收尾

2026-10-07：CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12，允许集成 develop。
历史候选55/60，正式分钟范围45/60；锡仍属P7B-08，原13/21队列分母不变。下一项AL铝。

## 冻结身份与根因

资格代码 `589629352827a31c8352d6c9f8f43386459782b1`，仅加入SN singleton白名单及定向测试，正式范围不变。
窗口2023-01-01至2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`。
45个物理owner/45段、180维护单元，无reentry；权威上市日2015-03-27。
1m仅聚合源，接受5m/15m/30m/60m×趋势/震荡/双策略。

原attempt保持0完成/1部分失败/179未尝试，retry=false，未复用失败attempt。
SN2302/1m/2022-08原失败发布payload为10695根原生Canonical Bar，不是provider raw响应。
SHA `c713092228fd015f864b54f79b693973e4e4a29d62cb4f99a058c7ea1a38c0a5`。
8处成交额超18位小数，对应第2565/3495/3960/4425/4890/7215/8610/9075行。
按 `rqdata-turnover-truncate-18-v1` 向零截断，整数、价格、其他字段和端点不变，scratch原生完整读回通过，无诊断外部请求。
旧after快照不存在；旧1952文件保持，当前1984前像新增32项active key来源UNKNOWN，
不归因于本轮，不伪造旧部分发布数量；当前1984前像全部纳入保护。

## 实际数据与候选验收

新forward计划SHA `41143cefd581c1263a6cf85f73ec1a0f707db4e942165c565e77e0c487c9992f`，12项冻结引用独审通过。
唯一apply完成180/180：174 READBACK_VERIFIED、6 NO_GAP；467真实源请求、1908派生目标、108条成交额截断。
无生产维护失败重试或缓存诊断请求。整体理论预算不足/不保证完成保留，实际逐单元锁内quota检查通过。
1984→4147文件，2163新增、212扩展；106334旧Bar、1193日周文件与Catalog保持，无删除。
独立467原始源4056120行与物理1m全部字段、交易日、端点及108条规范化记录一致，整数部分不变。

|周期|独立完整前缀Bar|物理合约月|
|---|---:|---:|
|5m|942762|540|
|15m|314254|540|
|30m|162264|540|
|60m|91406|540|

合计1510686根，按物理Session `(start,end]` 与Decimal200逐值核对通过；每周期资产输入另含44个边界点，不混同前缀数量。
12次精确候选构建完成：READY、disabled、generation 0；8基础coverage FULL/各45owner，4融合8条真实伙伴依赖一致。
API一次12 READY/152矩阵GET均HTTP200（另1次初始身份GET），于2026-10-07T06:08:07.077787Z完成后才启动Chrome。
一次Chrome19场景/49原图，无失败重采；18完整数值场景与1个原生409取消恢复通过，
28352 CLOSED、28386 SVG点、完整曲线/价格/身份/累计收益逐值一致；49原图独立逐张实际查看通过。
原生audit的NUMERICAL_PASS_VISUAL_PENDING标签不改，独立视觉报告补齐视觉验收。
专属API30502/Web31420已精确退出，Chrome sn-candidate已关闭，端口8012/5178释放、锁0；
末轮仅12保存态读回，revision/seq、禁用状态不变，source_prefix_revalidated=false，未重扫源。

## 实际验证与准备阶段修正

- 任务PYTHONPATH下 `python -m pytest services/quant-api/tests/newow/test_candidate_preview.py -k sn -q`：6 passed；Red阶段1 failed/5 passed保留。
- `node --test apps/quant-web/tests/newowCapabilities.test.ts`：27 passed；`test_forward_guards.py`：4 passed。
- 下游4方法/23纯子测试、5个native render用例、退出助手9 fixture及fcwd协议6项定向测试通过。
- `forward_campaign.py --apply --expected-plan-sha256 <上述精确SHA>`、`data_readback_once.py`：实际一次exit0。
- `independent_root_preservation.py`、`independent_raw_source.py`、`independent_root_full_prefix.py`：各实际一次exit0。
- `build_assets_once.py`、`final_asset_readback.py`、宿主 `coverage_expected.py`、原生preflight四GET：exit0。
- `api/readback.py --execute`、`capture_once.py`、原生index/audit：exit0。
- `independent_numeric.py --root outputs/sn-candidate-closeout-20261007/acceptance`：首次实际执行exit0。
- 修正后的 `stop_preview_exact.py --apply`、Chrome close、`targeted_exit_readback.py`：exit0。

覆盖检查首次早于保存态文件生成，在计算前FileNotFoundError；随后沙箱连接被拒绝、未查询，原日志均保留。
宿主唯一实际coverage计算通过。Web首次shell相对日志路径错误，在helper启动前退出；改绝对路径后首次启动成功。
退出助手首次把 `lsof -Fn` 的隐含 `fcwd` 字段漏掉，在意图保存和任何信号前fail-closed，targets/issued均未生成。
只修两行严格三字段解析，6项正负例测试与独审通过后，双次完整argv/cwd/独占端口验证，才第一次真正SIGTERM。
旧退出助手SHA及首次guard日志保留，未放宽身份条件、未重复补数或资产构建；新助手SHA
`975bd73648a43faba87a0c53cf209f3a11aab9727c15be462dd7477550eec055`。
Web依赖沿用主树node_modules链接，无安装；没有机械重跑全仓库或60品种整体验证。

W1当前49/120预热及历史44区段不足披露保留，趋势/震荡/双策略CLOSED分别6/0/6；0笔指标为“—”，不伪称0%样本。
日频CLOSED为47/14/57。标签重叠/裁切、tooltip遮挡、早期副图短段/空白及局部线段限制保留，不从视觉推断根因。
日周coverage不推断FULL；page_parity=true/executable=false、零费用零滑点参考，不是因果/OOS或账户收益。
未改变正式Scope、Release、Runtime、通知、交易或auto_order=false。

## 证据与交付

证据保留于任务树 `outputs/sn-candidate-closeout-20261007/`，不提交大体积原始数据。
绝对根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/sn-candidate-closeout/outputs/sn-candidate-closeout-20261007/`。
旧失败根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/sn-candidate-pilot/outputs/sn-candidate-pilot-20261004`。
最终独审 `recovery/independent-final-closeout-review-v2.json` 为REVIEW_COMPLETE_CANDIDATE_CLOSED，
SHA `9871c14b8cacb237efd0b86021425b391abc53a439c85de93cece8b564e71b21`，绑定数据、资产、API、数值、视觉、准备修正及精确退出证据。
v2仅更正首版汇总报告旧未尝试计数183→179，并绑定原报告SHA；原封存报告保留，其他内容机器核对完全等同。
只集成资格与本记录/STATUS/路线图，保留任务证据树及无关修改，不删除或覆盖Canonical。
回滚代码不撤销已通过质量的行情事实，也不改变原失败记录。下一最小步骤：推进AL铝。
