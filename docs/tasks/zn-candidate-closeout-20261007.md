# ZN 锌历史候选收尾

2026-10-07：CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12，允许集成develop。
数据、12资产、API、唯一Chrome19场、数值、视觉、精确退出与最终ao独审已实际通过。
历史候选57/60、正式分钟范围45/60；锌属P7B-07，原13/21队列分母不变，下一项FU未启动。

## 冻结身份与原失败边界

资格代码 `af1773bea3d3893431096fc9b5ab5e9ed03ef3b7`，仅ZN singleton资格与相关定向测试，正式范围不变。
窗口2023-01-01至2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`；46物理owner/46段、184维护单元。
权威上市日2007-03-26，页面窗口不回推到上市日。1m仅聚合源，验收5m/15m/30m/60m×趋势/震荡/双策略。
旧ZN2302/1m/2022-08失败发布payload有10695条原生Canonical Bar，不冒称provider raw。
按 `rqdata-turnover-truncate-18-v1` 向零截断；整数、价格、其他字段、端点与源窗口不变，scratch原生证明PASS。

原attempt为0完成/1失败/183未尝试、retry=false，不复用原失败attempt。
旧after快照缺失；1948个旧文件与当前1960前像的12个新增key保持，新增来源UNKNOWN，不归因于本轮。
新增key是ZN2302/1m与5m的2022-02至2022-07，不能据此补造旧提交边界；失败来源active为0。
所有当前1960前像纳入保护，旧文件、失败payload与原attempt不改写。

## 已封存数据、资产与API

冻结forward计划SHA `9c1fdcaf0de386dbc267948d1272c9b6c0fe7da812d1eccb6e8ae425ca07b3ca`。
唯一apply完成184/184：178 READBACK_VERIFIED、6 NO_GAP；478真实源请求、1952派生目标、128条成交额18位截断。
当前1960→4173文件，2213新增、217扩展、0删除；198088旧Bar、1193日周文件与Catalog保持。
独立478个原始源共4083510行，与实际物理1m字段、交易日、端点及128条规范化记录绑定，整数部分不变。

|周期|独立完整前缀Bar|物理合约月|
|---|---:|---:|
|5m|947637|551|
|15m|315879|551|
|30m|163104|551|
|60m|91881|551|

合计1518501根，按物理Session `(start,end]` 与Decimal200逐值核对；每周期资产输入另有45个边界点。
12原生候选构建与保存态读回READY、disabled、generation0；8基础FULL各46个VALID owner区段。
4融合的8条真实 `input_manifest.source_dependencies` 与同周期基础资产revision/seq/digest/snapshot匹配，
同source/window/asof/owner与公式身份保持，不制造独立persistedpartnerrevision字段。
summary complete_window_proven=false保留；FULL来自native availability，不推为日周FULL。
资产独审 `recovery/independent-asset-review.json` 为REVIEW_COMPLETE_CANDIDATE_ASSETS，
SHA `52592cfe719ded5ee02813af451231f2872e80820a0b590167db1fe58fac3e67`。
API12 READY/152矩阵GET均HTTP200（另1次初始身份GET），于2026-10-07T13:52:40Z完成后启动Chrome。

## 本次采集迟缓与任务内配置

原 `playwright_cli.sh` 每次用npx解析 `@playwright/cli`；每个1MiB chunk都会启动新的wrapper/npx进程。
原npm日志证实registry metadata检查连续3次ECONNRESET，最终200 cache stale耗时约71秒，
不是缺数组、缩短transport、UI数值异常或修改60/65/110门禁。
npm日志证明每次读取ZN worktree根 `.npmrc`，项目配置优先于用户/global配置；
npm-registry-fetch的offline只读缓存优先于libnpmexec的在线偏好。

root只在ZN项目 `.npmrc` 设置 `offline=true`，使用已存在CLI0.1.22缓存；
原生 `--version` 实际exit0、0.53秒。配置文件13bytes，SHA
`6edbe708f8417cb9c94bb1262554e4396658c9d5bbb40048d20dd80232a4fb3b`；
CLI入口SHA `fda252270793401d2856530a5f503adf7fc326fc07bed97e413138f67c50662b`。
配置取证 `recovery/task-npx-offline-config.json` SHA
`7333cc1b3ecfae356aa8b3b292a959c1907d95ebc0f778b6a2085578bef73315`。
现有capture进程未重启、原spool/nonce/seq/hash与PNG保持，无重采/重放；fulltransport和所有时限/身份/错误门禁不改。
不修改用户/global配置、技能或模块代码。该临时项目配置已按上述exact SHA核验后删除，最终exit报告保留删除读回；不修改用户/global配置。

Chrome open最终实际exit0；root在其命令尚未完成时提前启动capture的流程失误如实保留。
最终只能依各场实际native identity、完整响应、transport、DOM/SVG及错误门禁验收，不以最终open成功反推采集当时状态。
唯一capture session54602实际exit0，19场/49原图完整封存。原9/19与30图只是阶段进度，不计为额外采集或全量通过。
未因迟缓杀进程、重采、缩窗、补XHR或放宽门禁。

## 实际全量验收与交付

唯一Chrome capture实际exit0，19场/49新原图全部封存；await原生index实际exit0之后才运行audit和numeric，各一次exit0。
不存在提前运行audit缺index的错误，不沿用AL的准备失败记录。
29463 CLOSED、29497 SVG点，完整数组、价格、稳定身份/排序/分页、累计收益、全曲线点与native409/cancel恢复独审通过。
49原图实际逐张视觉审查通过，视觉报告SHA
`7907085847042f57a515acfe77e20348395ed73d040a2d4f25016bb14e963ddf`。
原生NUMERICAL_PASS_VISUAL_PENDING标签与原件保持，由独立视觉补充实际视口验收。
W1当前44/120、历史45区段预热保留；趋势/震荡/双策略CLOSED分别6/0/9，0笔统计为“—”，不是0%。
OPEN与换月中断浮动不入已完成收益；日周coverage不推FULL。
密集标签重叠、tooltip遮挡、视口裁切及较早副图短段/空白局限按实际原图保留，不从图片推完整数组或根因。

stop、专属Chrome close和exitreadback均实际exit0；API26619/Web26818已退出。
最终读回时间2026-10-07T14:47:53.917907Z，8012/5178无监听、维护锁granted/waiting均0。
仅fresh12保存态身份/revision/seq及disabled/generation0保持，source_prefix_revalidated=false，不重扫源。
临时项目offline配置已按exact SHA删除并封入exit报告；当前配置不残留，无用户/global变更。

资格定向pytest实际5 passed、Web27 passed、forward guards4 passed。
入口测试首次所选nodeid尚无新增zn参数，因此没有测试执行；补参数后实际RED再GREEN，不计生产失败。
没有补跑全仓库、其他品种或重新下载/构建。无失败attempt重用、重采或后台监控。
最终ao独审 `recovery/independent-final-closeout-review.json` 为REVIEW_COMPLETE_CANDIDATE_CLOSED，
SHA `e318b8db9a1c38b8b15e59c2d42a0e39c11c310d03e046e9e88d8330c1671e17`，
绑定旧边界、forward、数据、资产、API、完整数值、49原图视觉、任务配置与精确退出证据。
page_parity=true/executable=false，页面零成本参考不证明因果/OOS、Paper或真实账户收益。
正式Scope、Release、Runtime、通知、交易与auto_order=false不变。

证据根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/zn-candidate-closeout/outputs/zn-candidate-closeout-20261007/`。
旧证据根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/zn-candidate-pilot/outputs/zn-candidate-pilot-20261004/`。
本次只交付资格代码、STATUS、本任务记录与roadmap P7B-07实际ZN行，不提交大体积原始数据。
不删除或覆盖Canonical；回滚代码不撤销已通过质量的行情事实，也不改变原失败证据。
唯一下一步：按既定串行队列处理FU燃料油；本次不发布或提升Runtime。
