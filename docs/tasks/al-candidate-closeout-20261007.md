# AL 铝历史候选收尾

2026-10-07：CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12，允许集成develop。
实际数据、12资产、API、Chrome数值/视觉与精确退出验收通过，最终ao独审完成。
历史候选56/60，正式分钟范围仍为45/60；
铝属P7B-09，原13/21队列分母不变。下一项ZN锌尚未启动。

## 冻结身份与原失败边界

资格代码 `16a339e083899858ee551dce2544aead2aa354e4`，仅AL singleton资格与相关定向测试，正式范围不变。
窗口2023-01-01至2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`。
46个物理owner/46段、184维护单元；权威上市日1999-01-04，页面窗口不回推到上市日。
1m仅聚合源，验收5m/15m/30m/60m×趋势/震荡/双策略。

原attempt保持0完成/1失败/183未尝试、retry=false，未复用原失败attempt。
旧AL2302/5m失败发布payload为Canonical Bar取证，不冒称provider raw；原件SHA
`111603d42fc560fcdb03ca79ab0c57d8b54ee41eeef7727ec1595926e78094e8`。
成交额仍采用 `rqdata-turnover-truncate-18-v1` 向零截断，整数、价格、其他字段、端点与源窗口不变。
旧after快照缺失，旧部分发布边界UNKNOWN，不伪造提交数量或归因；失败来源active为0。
旧1957文件与当前1957前像SHA一致、无新增key或扩展；当前全部前像纳入保护。

## 实际数据与候选验收

冻结forward计划SHA `94f305f5a7a074ad42d3b4c2137202908c320108a97796dddc5eb9615706f973`。
唯一apply完成184/184：177 READBACK_VERIFIED、7 NO_GAP；484真实源请求、1947派生目标、2条成交额截断。
无失败维护重试、诊断缓存或额外provider取证；预算与逐单元锁内额度守卫不放宽。
1957→4172文件，2215新增、216扩展，0删除；245980旧Bar、1192日周文件与Catalog保持。
独立484个原始源共4097895行，与实际物理1m全部字段、交易日、端点和2条规范化记录绑定，整数部分不变。

|周期|独立完整前缀Bar|物理合约月|
|---|---:|---:|
|5m|940335|551|
|15m|313445|551|
|30m|161848|551|
|60m|91175|551|

合计1506803根，按物理Session `(start,end]` 与Decimal200逐值核对通过；
每周期资产输入另含45个边界点，不混同前缀Bar数量。
12次精确候选构建与保存态读回：READY、disabled、generation 0。
8基础coverage FULL，各46个VALID owner区段；4融合的8条真实 `input_manifest.source_dependencies`
与同周期基础资产revision/seq/digest/snapshot一致，不制造额外伙伴版本字段。
summary的complete_window_proven=false保持；FULL依据独立native availability覆盖，不推为日周FULL。

API一次12 READY/152矩阵GET均HTTP200（另1次初始身份GET），API完成后才启动Chrome。
一次Chrome19场景/49原图，完整数值与原生409取消恢复验收通过，无失败重采。
30474 CLOSED、30508 SVG点，完整价格、稳定身份/排序/分页、累计收益与全部曲线点独审通过。
49原图实际逐张查看通过，视觉报告SHA
`c07fcb05e0ac532f8f592c4546af6213c9a5f833fc32b11db96259e8c14b0086`。
原生NUMERICAL_PASS_VISUAL_PENDING标签与原件不改，由独立视觉报告证明原图验收范围。

专属API74054/Web74192精确退出，专属Chrome关闭；stop、Chrome close与exit实际exit0。
退出读回于2026-10-07T10:53:04Z封存，8012/5178无监听、维护锁granted/waiting均0；末轮仅12保存态读回，revision/seq与禁用状态保持，
source_prefix_revalidated=false，未重复扫描完整行情源。

## 实际验证与交付范围

- API资格定向pytest：5 passed；Web能力测试：27 passed；任务forward guards：4 passed。
- `forward_campaign.py --apply --expected-plan-sha256 <上述精确SHA>`、`data_readback_once.py`：实际一次exit0。
- 独立raw-source、preservation、完整四频前缀与聚合数学审查通过；不以源码推断代替实际发布读回。
- `build_assets_once.py`、`final_asset_readback.py`、宿主 `coverage_expected.py`：exit0。
- `independent_asset_incremental.py`与最终纯metadata审查各执行一次，12资产/8 FULL/8伙伴边通过。
- `api/readback.py --execute`、`capture_once.py`、原生index/audit与独立完整数值审查：exit0。
- `stop_preview_exact.py --apply`、Chrome close、`targeted_exit_readback.py`：exit0。

沿用SN最终精确退出助手的三字段cwd协议（含fcwd），完整argv/cwd/独占端口双次检查后才SIGTERM，
O_EXCL保存意图和issued记录，失败零信号守卫与禁重试保持；本轮不改产品公式、Canonical schema或退出标准。
原生audit首次在index尚未生成时FileNotFoundError，未执行数值审计；随后index实际PASS、audit实际PASS。
首次日志保留，不计生产维护失败或Chrome重采。所有准备阶段原日志保留，旧UNKNOWN不改写为确定事实。
未机械重跑整个仓库或其他品种；任务结束不启用后台监控。

W1当前44/120、历史45区段预热及数据不足警告保持，趋势/震荡/双策略CLOSED分别4/0/8；
0笔统计为“—”，不是0%样本。OPEN与换月中断浮动不进入已完成收益。
标签局部重叠、tooltip遮挡、较早趋势转折副图短段/空白及裁切视口限制保留，不从图片推断完整数组或根因。
分钟持有过程暂不可用；日周coverage不推断FULL。
page_parity=true/executable=false、零费用零滑点参考，不是因果/OOS、Paper或真实账户收益。
正式Scope、Release、Runtime、通知、交易与auto_order=false均未改变。

## 证据与交付

证据根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/al-candidate-closeout/outputs/al-candidate-closeout-20261007/`。
旧失败根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/al-candidate-pilot/outputs/al-candidate-pilot-20261004/`。
数据overall、资产、数值、视觉与退出报告均封存；资产独审SHA
`9d7fed225647ea54bb59283668c775b08ae2e3c87e7f078361517a557c0a1b69`，
退出读回SHA `391033953c0ecb6684a4fe5444b936e5a7d852ad483d1a27690efb20bd8933b9`。
最终ao独审 `recovery/independent-final-closeout-review.json` 为REVIEW_COMPLETE_CANDIDATE_CLOSED，
SHA `5d3f68f119dcd1e9456f1bd2a25b94ed9874f7b590ffa5ff5d127bdd173a22dc`，绑定完整数据、资产、API、数值、视觉与退出证据。
只交付资格代码与本记录/STATUS/路线图，不提交大体积原始数据，不删除或覆盖Canonical。
回滚代码不撤销已经通过质量校验的行情事实，也不改变原失败证据。
唯一下一步：按既定队列处理ZN锌；本次不发布或提升Runtime。
