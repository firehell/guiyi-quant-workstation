# PB 铅历史候选收尾

2026-10-07：CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12，允许集成 develop。
历史候选54/60，正式分钟范围45/60。下一项SN锡；PB不改变原13/21队列分母。

## 冻结身份与根因

资格代码 `80cafeb694a9576d0bf3bb53cc66c2829c999e64`，仅加入PB singleton白名单与定向测试。
固定窗口2023-01-01至2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`。
46个物理owner/46段、184维护单元；1m仅作为聚合源，接受5m/15m/30m/60m×趋势/震荡/双策略。

原attempt保持0完成/1部分失败/183未尝试，retry=false，未复用失败attempt。
PB2302/1m/2022-06原失败发布payload为9525根原生Canonical Bar，不是provider raw响应。
SHA `ddab33bc34b4436a493f1e9de4158dca8f9bc6074dbed0f593eeed57b73f5f9c`。
ArrowInvalid在第8369行成交额超18位小数复现；按 `rqdata-turnover-truncate-18-v1` 向零截断，
`5.820766091346741E-11`→`5.8207660E-11`，整数、价格、其他字段及端点不变，scratch原生读回通过，诊断无外部请求。
旧after快照不存在；旧1928文件保持，当前1936前像比旧前像新增8项active key来源UNKNOWN，
不归因于本轮、不伪造旧部分发布数量。当前1936前像全部纳入保护。

## 实际数据与候选验收

新forward计划SHA `9a7b497a8c29cacf5826336b32763728bd29d92c0ce351c9860d5b3996f77ab0`。
单次apply完成184/184：180 READBACK_VERIFIED、4 NO_GAP；480真实源请求、1976派生目标、141条成交额截断，
无生产失败重试或缓存诊断请求。整体理论预算不足/不保证完成事实保留；实际每单元quota检查通过。
1936→4173文件，2237新增、219扩展；194772旧Bar、1193日周文件与Catalog保持，无删除。
独立480原始源4105365行与物理1m全部字段、交易日、端点及141条规范化记录一致。

|周期|独立完整前缀Bar|物理合约月|
|---|---:|---:|
|5m|948243|551|
|15m|316081|551|
|30m|163208|551|
|60m|91939|551|

合计1519471根，按物理Session `(start,end]` 与Decimal高精度核对通过；资产输入另含45个边界点，不混同前缀数量。
12次精确候选构建完成：READY、disabled、generation 0；8基础coverage FULL/各46owner，4融合8条伙伴依赖身份一致。
API一次12 READY/152矩阵GET均HTTP200（另1次初始身份GET），完成后才启动浏览器。
一次Chrome19场景/49原图，无重采；18完整数值场景与1个原生409取消恢复通过，
33742 CLOSED、33776 SVG点、完整曲线/价格/身份/累计收益逐值一致，49原图独立逐张审查通过。
原生audit的NUMERICAL_PASS_VISUAL_PENDING标签保留，实际独立视觉报告补齐视觉验收。
专属API/Web/Chrome已精确退出，端口释放、锁0；最后仅读回12保存态，revision/seq、禁用状态不变，未重扫源。

## 实际验证与保留限制

- `python -m pytest services/quant-api/tests/newow/test_candidate_preview.py -k pb -q`：隔离任务6 passed。
- `node --test apps/quant-web/tests/newowCapabilities.test.ts`：27 passed。
- `test_forward_guards.py`：4 passed；下游本地fixture 4方法/23 subtests通过，capture守卫9项通过。
- `forward_campaign.py --apply --expected-plan-sha256 <上述精确SHA>`、`data_readback_once.py`：exit0。
- `independent_root_preservation.py`、`independent_raw_source.py`、`independent_root_full_prefix.py`：各实际一次exit0。
- `build_assets_once.py`、`final_asset_readback.py`、`coverage_expected.py`、原生preflight GET：exit0。
- `api/readback.py --execute`、`capture_once.py`、原生index/audit：exit0。
- `independent_numeric.py --root outputs/pb-candidate-closeout-20261007/acceptance`：实际执行一次exit0。
- 精确资源退出、Chrome close、`targeted_exit_readback.py`：exit0。

准备阶段tuple路径与CANONICAL环境变量拼写已在生产执行前修正、独审通过。
数值命令首次缺少--root，argparse在任何读回前exit2；原日志保留，修正参数后唯一实际数值执行通过。
Web依赖沿用主树node_modules链接，无安装。仅验证本次修改及必要真实数据/候选验收，不机械重复整体检查。
W1真实44/120预热，趋势/震荡/双策略CLOSED分别9/0/11；0笔指标显示“—”，不作为0%样本。
标签重叠/裁切、tooltip遮挡、早期副图短段/空白及局部MACD断线原样保留，不从视觉推断根因或完整隐藏区域。
日周coverage未证明FULL；页面为page_parity=true/executable=false、零成本参考，不是因果/OOS或账户收益。
未改变正式Scope、Release、Runtime、通知、交易或auto_order=false。

## 证据与交付

证据保留于任务树 `outputs/pb-candidate-closeout-20261007/`（未提交大体积数据）。
绝对根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/pb-candidate-closeout/outputs/pb-candidate-closeout-20261007/`。
旧失败根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/pb-candidate-pilot/outputs/pb-candidate-pilot-20261004`。
最终独审 `recovery/independent-final-closeout-review.json` 为REVIEW_COMPLETE_CANDIDATE_CLOSED，
SHA `2dcb21a4346262f401bae92ce2f093ee6ec7a763e09480984017bb8a7b2eae8a`；绑定数据、资产、API、数值、视觉及精确退出原始证据。
只集成资格与本记录/STATUS/路线图；保留任务证据树及无关修改，不删除或覆盖Canonical。
回滚代码不撤销已通过质量的行情事实，也不改变原失败记录。下一最小步骤：按相同经验推进SN锡。
