# 正式版本统一与发布树收敛

Owner交办：从已发布v1.16.21形成一个最终补丁，十服务整组切换并验收后，将旧发布树收敛至唯一现役树。
独立SimNow、数据库/Redis、行情数据、账户、Scope及auto_order=false保持既有边界。

## 实现与候选检查

历史binding使用显式历史reader和有效封存索引；活动binding、安装与进程仍执行原严格身份校验。
`runtime_retention closeout-plan`生成精确证据清单；`seal-closed --plan`在部署锁内复核并原子封存；
cleanup同时检查服务、进程及未闭合恢复引用。封存依据原件typed关闭图重推，不信任索引中的闭合集合；
正常cohort在首个effect前保存私有计划，旧attempt不补写。只封存必要.run字节，保留所有旧unknown原件。

一次集中定向组合：historical_identity、retirement、retention、bindings、cohort、cohort_host、
cohort_forward_recovery、stopped_recovery、cohort_recovery、receiving_readiness、feed_halt_recovery、
reference_trading/receiving_liveness：**409 passed, 1 skipped / 24.00s**。
跳过项要求本轮一次性Redis；本次未改变接收SQL/Redis算法，沿用上一步真实隔离PG/Redis证据，不再创建容器重复验证。
Ruff、`uv lock --check --offline --project services/quant-api`、diff检查通过；新增文件秘密模式扫描无命中。
测试完整命令与输出：`output/recovery-preflight-20261027/controller22-tests.txt`。

旧8树只读ignored清单除依赖/构建/测试缓存外，只有v10/v14的10个.run标记或历史文件，历史SHA均与当前字节相符。
清单：`output/recovery-preflight-20261027/retirement-marker-inventory.json`。
回滚按保留annotated tag/exact commit重建，禁止force删除、重写tag或复用失败attempt。

独立安全Review无未关闭Confirmed Issue，允许进入release candidate。现场Gate仍须实际执行。

## 现场结果

v1.16.22已经PR522发布，exact main/tag d2cc94382ba4158669d33ea549eb4d28d9a646b2。
一次原生计划bf91a6899a79723efb217a0e12c56ae354e3a8691ff7fbb4a8055f5c2e334f00在17:40:53
停服前预热取消，effects为空，错误CANDIDATE_WARMUP_FAILED；未重跑该attempt。
17:43独立读回十服务仍v14/gen31，六常驻原PID active/fresh、API/Web200且来源v14。
旧失败原件及全部发布树保留。

一次Reference只读分段诊断65.34秒，固定码SUBING_REFERENCE_DATA_UNAVAILABLE；只读metadata定位PD2612
10/27日线physical_contract_replay/REPLAY_ENDPOINTS_MISSING。不能倒推bf91未记录的确切失败原因。
既有canonical要求区分Session完成与18:05发布，但SuBing forward漏用Newow已有的publication边界。
后续补丁提取共享MDS publication resolver并补SuBing forward专用窗口，普通页面窗口与预热fresh/saved/seed语义不改；
旧欠期、物理数据、owner及质量仍fail-closed。固定服务/失败条件/白名单码写入新预热失败状态，预算不变。
v22 tag保持原样，修复进入v1.16.23；临近18:05时等待自然盘后任务释放窗口，不抢维护锁。

受影响组合221 passed；两项旧生命周期用例因默认日志目录不在sandbox内失败，使用隔离GUIYI_LOG_DIR后仅补跑两项，2 passed。
新增CLI诊断后仅补诊断模块8 passed。Ruff、离线锁和diff检查通过。
独立安全Review无未关闭Confirmed Issue：允许进入release candidate；publication/typed接收/预算均未放宽。

v23已PR523/main/tag/Release发布，exact86248ce71ebf3fd88033eda24fa57c447b5c0597。候选API/core与Web
版本/来源、type/build/topology通过。18:05自然源维护passed，60/60派生无失败；等原消费者审计退出，18:35:53四日历idle后
新plan324f8ebe…一次apply。18:37:03在Alert预热candidate_blocked取消，effects={}，未停服/重跑/删树。

一次Alert只读分段诊断定位EG/5m；一次此窗口直接replay读回为CONTRACT_REPLAY_COVERAGE_UNAVAILABLE /
REPLAY_PREFIX_MISSING。完整一次Scope只读清单420=408 calculated+7 warming+5 blocked，全部EG2701。
5m expected/actual=12138/69；15m=4046/23；30m=2112/12；60m=1234/7；1d=178/1。
前四项缺口精确为01/28至10/26；日线缺177个上市后端点，首缺01/28。未把当日64bar当成生命周期覆盖。
独立Review确认是真实数据Gate，未发现读取器或控制器缺陷；不能用当前任务的代码发布授权覆盖明确另列的数据修复。

原生ContractWarmupPlanner只读dry-run：EG2701七周期01/28至10/27，30 direct/40 derived月目标、
80,436根目标期望Bar、provider请求预算30，实际执行0；SHA
a6500f465f7fbbe659cebfe75ac6f0d04289047f471933396188b2da9f9f4f19。
数据执行须沿原生锁/原件前像/质量/原子发布/未知提交合同；当前未创建任何数据mutation attempt。

18:48:46–47离场最小读回：十identity matched v14/gen31，六owner active/fresh/source_matches/lockheld，
API200/version14与Web200精确v14；324f private/global同字节cancelled/effects={}，原binding和旧原件不变。
报告SHAfa0aeab3e5da05d99e0e0f8aa581cec19e43e65d87279c6f52b4c6c61e4618b1。
当前结论PARTIAL：10棵release树保留，等待owner决定是否将精确EG2701前缀修复纳入本次；未经此范围调整不下载、
不发布数据、不绕过Gate或删除旧树。独立SimNow及账户/Scope/auto_order=false保持边界。


## Owner扩展范围后的连续执行

Owner明确选择纳入EG2701七周期物理前缀修复并继续切换清理，无需再次批准相同范围。
第一包装仅在计划日期JSON序列化处TypeError，apply_called=false、冻结文件未创建、provider0，原报告保留。
修正序列化后，19:14:35–19:15:09原生a6500f…f4f19锁内复核并一次apply：70 applied/0blocked/0failed，
provider_requests=30/publications=70；Scope、其它合约、MainContractMap、Redis及通知未纳入修复。
独立只读七周期原生plan为NOOP（79d80ffc…8b9ef），EG5m完整replay valid/12138 bars。
仅重建EG派生首页缓存与overview，19:17:28均ready；未再次构建60品种或发送通知。
19:18开始全新v23原生cohort，旧bf91/324f不可重跑；结果在实际完成后追加。


19:22:23全新9abadb1bb11277e2b7f18ea6dae72cfa8ad5c2ec76ffc30e802df582c884fe7c成功switched。
19:23:09→19:23:21独立跨轮：十identity/installed/source exact86248/gen32/root23；六owner active/fresh/
稳定PID/正确来源/锁held；Feed closed_idle/pending0，Reference双fresh完成接收报告；四日历registered且RunAtLoadFalse。
API两次200/version23，Web两次200且字节等于v23 dist；旧原件prior_files_changed=[]，未决恢复Gate通过。
原件8956/唯一8956，completed2546/pending63/blocked44/UNKNOWN0，waiting/dependency0；blocked分类ACTION_CORRUPT6/
NO_CALCULATION38，未假称积压清空或人为制造新行情/推送。
报告independent-v23-20261027T112321Z.json，SHA5d2972cc87a9bd9cc5010955a283f9f102ea5cb53b9a2c9a2cbb32b8b7d0652a。
原生global/private state同字节SHAe8d77eb54e704cb3fa5b5c6a0409b74be09431e8272dc84daa445fea85dddfa0；
binding SHA89daa3ce8089bc98c8dfa30a87056eaa041d03a05f4a941e63574e916aa8ea53。

19:24–19:26原生closeout/seal成功：19条闭合尝试、47份原件、54个marker路径（15存在/3个去重blob），
保留旧unknown字节并封存本次v14前像；plan08482181357b94d1a32c618346108967f40b5d323beeef5421442b938a6840b6。
原生cleanup-plan0fea2f31cef53bb50b6c6151644905035f680e54ea0dc0340cbcf424323ecc10认定9旧树eligible；
19:32:15–19:32:34在部署锁内同前像复核后逐棵git worktree remove，无force：v10/v14/v16/v17/v18/v19/v20/v21/v22。
只剩v23；develop、当前主工作区和独立SimNow树不动，tag/Release保留，临时候选已清理。

浏览器：首页60真实品种/分钟已连接，EG5077，RB3040且10/27；RB真实K线、成交量、指标与参考marker已渲染。
参考收益子面板首次及仅一次重试503，公开固定码SOURCE_IDENTITY_UNVERIFIED。相关source_identity/product_service
v14→v23无diff，独立窄Review确认其为已存历史资产与当前来源的质量Gate，不增加旧checkout引用，不推翻技术cohort。
不强制重建/放宽身份，也不宣称所有页面功能恢复。字段级原因尚未确定，另项保留。
删除后唯一现役树历史seal、F确认及下一部署只读前置终验正在执行，不重启/重跑全工程。


## 删除后最终验收与收尾

19:48:55–19:49:01从唯一v23现役树执行最终只读组合，
`controller23-final-indexed-readonly-v2.json` status=passed：release_trees=1、bindings=10/gen32、
history_seal_valid、stopped_confirmation_valid、pending_recovery_check和next_deployment_prerequisites全部通过。
current_installed_count=11包含独立标签，不改变正式十服务cohort；Session为closed_idle。
历史读取采用完整验证索引、精确绝对路径/SHA及typed闭合链，涵盖本次旧v14前像；没有目录缺失fallback。

旧辅助程序在完整索引已验证后又重复深读历史链，耗时过长，仅停止本任务该只读进程；
没有停止正式服务，也没有改已发布代码，不声明旧递归读取程序成功。新组合复用合同指定的已验证索引。
新组合首轮漏载检查进程所需Feed标志而失败，保留失败报告；v2从真实安装文件读取两项既有标志，
仅设置检查进程环境，未改生产配置；其余历史/未决/安装/保护项复核通过。

结论：版本统一及单发布树收敛COMPLETED，原失败记录、Git历史、数据和独立SimNow保留。
参考收益子面板SOURCE_IDENTITY_UNVERIFIED、pending63/blocked44和自然新行情/推送仍独立待处理，
不能以本次技术完成冒充所有业务健康。下一项最小工作是只读定位该历史资产身份校验失败字段。
