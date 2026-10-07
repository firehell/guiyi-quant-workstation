# AO 氧化铝历史候选恢复

当前状态：CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12；2026-10-06完成验收，历史49/60、正式45/60。工作树 `.worktrees/ao-candidate-closeout` 从 develop `51014a266255f539831c3fce2096f51a14f74715` 创建。页面窗口2023-06-19..2026-09-24、as_of=2026-09-24T07:00:00.000001+00:00；1m仅聚合，验收四分钟周期×趋势/震荡/双策略12组合，候选保持disabled/generation0，不包含正式开放、发布、Runtime、通知或交易。

沿用原油已集成的 `rqdata-turnover-truncate-18-v1`，仅成交额超过18位小数向零截断，整数、价格、成交量及持仓不变。旧AO失败attempt不复用、旧部分提交不回滚；旧证据在 `/Volumes/扩展盘/guiyi-quant-evidence/deferred-worktree-cleanup-20261004-204254/ao-candidate-pilot/outputs/ao-candidate-pilot-20261001/`。

恢复前只读基线22物理合约/88依赖/0候选；新七周期前像1204文件与旧失败后快照字节完全相同。旧9765行payload SHA8639c184928e6ea2c8a957ad27bff5c063acfebf5c44198da5ca069e0cc374b0，在当前入口只有row3254成交额1.4551915228366852E-11→1.4551915E-11，全部其他字段及端点保持，真实scratch发布读回通过。零成交量不等于成交额应归零。

新forward plan SHA `ad621896091b529dac4f8f967d2628b7ecc6c8ceff6d02d02254c8b4f87bc11a`，冻结88单元、去重154源月/627派生月上限、11个引用及runner SHA，独立执行审查通过。4项助手定向守卫测试通过，不重复原油整体测试。整批保守额度估算高于当前账户余额，不能保证整批完成；逐unit锁外/锁内fresh额度检查，未知提交或失败立即停，不盲重试。raw在validation前封存，旧bytes/Bar及日周守卫不变。

同类候选顺序暂定 AO→RU→BU→CU→NI→PB→SN→AL→ZN→FU。AO/CU及RU/BU/PB/SN/AL/ZN均已由旧失败原始payload确认成交额超过18位小数；六个新增确认的离线证据封存在recovery/similar-product-payload-proof.json，零provider调用/生产写入。NI/FU仍需逐品种证明真实根因后恢复。PP数据合同校验失败与SS既有数据阻断单列，不套用精度修复。排序按已知原因、合约数量与恢复复杂度；当前不做其他品种写入。

只读基线助手残留SC46断言，在写入前修为AO22。plan stdout旧46段数是汇总错误，88个实际计划和最终dry-run文件正确，脚本已改len(rows)，未重跑成功计划。scratch助手误改schema常量在import前退出，修正后PASS。工具错误与旧maintenance失败分开保留。

新原始证据仅保存本工作树 `outputs/ao-candidate-closeout-20261005/`。数据、12资产/API/浏览器及退出验收均已完成，原始失败证据保持。

## 实际数据与资产验收

新forward88/88完成，154真实源请求、627派生目标发布、19条turnover向零截断。实际新增抓取1299120行1m；七周期前像1204→1909文件、705新增/76扩展，74711旧Bar及544日周文件/Catalog保持，1128旧active文件未变。独立Decimal200按Session(start,end]核对627341派生Bar：5m391497、15m130499、30m67384、60m37961；四频各233物理月，22owner/21边界。原额度估算仍为保守估计，不等于实际字节。

一次原生资产计划/apply构建8基础+4融合，12/12 READY disabled/generation0；实际完整saved manifest、seq/revision/cutoff及融合伙伴均独立读回通过。趋势FULL；震荡PARTIAL保留上市初期预热。4项task-only守卫测试通过；没有源码改动，不重跑已通过SC整体测试。一次API验收12/12 READY，152保存请求全部HTTP200，独立读回审查通过。

acceptance/candidate.json冻结当前51014a266、AO及完整窗口，真实loopback preflight通过；普通沙箱GET曾URLError，服务仍在监听，按宿主流程获得仅loopback只读访问后通过，不是生产维护失败。专属Chrome一次串行完成19场景，无失败重采。

## 页面、退出与最终验收

实际命令：`recovery/test_forward_guards.py` 定向4 passed；`forward_campaign.py`、`data_readback_once.py`、`build_assets_once.py`、`final_asset_readback.py`、`coverage_expected.py`、`api/readback.py --execute` 均exit0。`acceptance/capture_once.py` 一次19/19退出0，native `index` PASS、`audit` NUMERICAL_PASS_VISUAL_PENDING。独立数值全18页面+取消场景19/19 PASS，28379 CLOSED逐笔价格/稳定ID/收益、Decimal200全部累计与全部SVG点通过；49实际PNG逐张view_image通过。API保存152请求全部HTTP200。

W1双策略task-only采集等待沿用原油已验证initial/return各110秒及原65秒按钮/稳定门槛，无错误豁免；实际采集无重跑。主页面密集标签、视口裁切/震荡统计区在视口下方，W1转折36/120预热、震荡0 CLOSED/annual —保留；日周使用真实XHR，不冒充额外完整GET。分钟趋势FULL、震荡上市初期PARTIAL；页面零成本参考口径不可执行，不代表OOS、自然TTL或融合所有状态机证明。原生真实取消、客户端timeout、错频409和fresh恢复通过。

独立最终 `independent-closeout-review.json` SHA `9ef5d08cd5efb6dfa438ca4d609add1698acff9294e266f639dbee4282d444d3` 为 REVIEW_COMPLETE_CANDIDATE_CLOSED。数值报告SHA `5e993eb097bed951b2f376524193ded8d6c54a04769a8aed4d4d443a61f32794`，视觉SHA `b60cc9712dbf04ea110096bb3eadaa9684f97406801f89da329b2c53f81f177c`。

精确API42646/Web43406命令/cwd/端口复核后SIGTERM，专属Chrome退出；`targeted_exit_readback.py` 实际PASS：两PID退出、8012/5178无监听、维护锁granted/waiting均0，12完整stream身份/revision/seq与预览前相同，disabled/generation0。末轮source_prefix_revalidated=false，仅绑定已封存全源证明并读回12状态，不重复全源扫描。无未完成外部Gate；无正式开放、发布、Runtime、Scope、通知、交易。原失败attempt/旧55部分提交保持，无回滚或盲重试。允许集成develop；下一最小步骤RU橡胶精确恢复。
