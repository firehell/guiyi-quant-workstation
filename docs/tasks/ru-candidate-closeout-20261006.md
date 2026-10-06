# RU 橡胶历史候选恢复

状态 CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12；历史50/60、正式45/60。从已闭环AO的develop27ebde9a5创建独立工作区，新增RU singleton资格4文件，6项API/1项Web测试和独审通过，冻结ce6186722。窗口2023-01-01..2026-09-24，as_of2026-09-24T07:00:00.000001+00:00；1m仅聚合，验收四频×三模式12组合，私有disabled/generation0。无正式开放、Release、Runtime、通知或交易。

旧RU失败工作树和attempt保留：旧48=4完成/1已知失败/43未尝试，RU2305原8源/32派生实际40新增文件保留，898旧文件不变；当前938文件。RU2309/1m/2022-09旧3795行payload row810 turnover7.450580596923828E-9需24位小数，采用已批准rqdata-turnover-truncate-18-v1得到7.450580596E-9，其余字段/端点不变，真实scratch publish/readback PASS，零新源调用/生产写入。

新48原生dry-run、78源/320派生预算、maxunit55219200B、当前quota1073741824B，整体保守预算通过；4task守卫测试通过，锁0。旧完成对象只重新确认无缺口，不重复下载；旧失败attempt不复用，新forward冻结精确scope/hash/preimage，锁外/锁内fresh quota，失败/未知提交停止、不盲重试。

任务输出仅保存在outputs/ru-candidate-closeout-20261006/，新恢复及全部验收均完成，原始证据保留。

新forward plan SHA 7b977c03abec63014fce7fb050f4332f9ab00e5399c6df820d6897efd5727d37，11引用/48单元冻结。

## 实际恢复与一次数据验收

唯一forward exit0，48/48=41READBACK_VERIFIED+7NO_GAP，78真实源请求/320派生/1行turnover截断。旧attempt未复用，所有unit读回无缺口、锁0，预算守卫通过。938→1285文件，347新增/51扩展/0删除、887active不变；68981旧Bar与365日周文件/Catalog保持。78raw/452595行全部字段/端点独立匹配真实1m；原生四频和独立Decimal200全物理前缀277659 Bar（5m172575/15m57525/30m30024/60m17535）、各139合约月/12owner通过。

新独审overall SHA8f886ee340a97c3790ff6af78b20cbeca571c24c6254015d434e831d92686c98为REVIEW_COMPLETE_ALLOW_RU_CANDIDATE_ASSET_BUILD；未重复来源扫描。12串行候选构建与实际最终验收均完成。新增准入定向6API/1Web、4任务守卫、一次Web类型/production build及bundle topology通过，无全量回归。

资格测试编辑工具未匹配到预期旧SC参数串，在任何真实维护前失败；按当前参数补齐后验证通过；API合约正则AO→RU、numeric任务日期修正均在相应首次执行前完成。raw离线审计首次缺importmodule在读取raw前退出，旧log保留，补齐后唯一实际raw全验通过；未重下行情/重放生产attempt。

实际API第一执行退出1：task-only helper upstream结果键残留ao-，第一组合GET后在保存result前KeyError；原api/summary.json全部NOT_RUN、原失败log保留，不能计成功API证据。api-v2修ru-并新增完整12upstream identity集合请求前守卫，封存结果只以新输出为准；不重放数据/asset，不重验已封存成功组合。

## 最终资产、页面与退出验收

12原生plan/apply串行一次完成exit0，无build失败/resume；fresh complete savedmanifest、stream/revision/seq/cutoff与四对融合八partner identity独审PASS，sourcePrefix不重复扫描。四频trend/oscillation均FULL，12READY disabled/generation0。候选资格源码冻结ce6186722；最后文档commit不改变产品代码。

实际命令：`pytest .../test_candidate_preview.py -k ru -q -p no:cacheprovider` 6passed/214deselected；Web single产品测试1passed；`pytest .../test_forward_guards.py -q -p no:cacheprovider` 4passed；`npm run build` 类型/Vite/bundle topology PASS。`forward_campaign.py --apply --expected-plan-sha256 7b977c03...`、`data_readback_once.py`、`build_assets_once.py`、`final_asset_readback.py`、`coverage_expected.py` 均exit0；API v2 `readback.py --execute` 12/12READY、152保存HTTP200。原API失败不算通过，v2独审实际请求前矩阵检查通过。

真实Chrome `capture_once.py` 一次19/19退出0，native `index` PASS / `audit` NUMERICAL_PASS_VISUAL_PENDING；独立numeric唯一执行19/19PASS、22534 CLOSED逐笔价格/稳定ID/收益、Decimal200全部累计和全部SVG点一致，49actualPNG逐张view_image通过。W1dual等待复用原油/AO已审initial/return110秒+原65秒按钮/稳定门槛，不放宽错误标准，实际无重采。真实取消/clienttimeout/错频409/fresh恢复通过。W1转折36/120预热、W1osc0CLOSED/noSVG/—明确；OPEN/中断浮动不计完成交易，密集标签/crop/较早窗口rightblank保留。日周真实XHR，不冒充额外completeGET；页面零成本参考不代表OOS/可执行收益/完整状态机或自然TTL证明。

最终独审independent-closeout-review.json SHA bb0ffa35dd298f36cfc9c1486827ee5dd3f78ae1e0cc473d45f28d75853a078b为REVIEW_COMPLETE_CANDIDATE_CLOSED；独立numeric whole SHA cf6bcedcb4ceabd43d1257ef68dace52b243276524d2195973999e29383df836；49图visual SHA587da928e6788b42d96ef25188e16061f058a07f6895875a169284388d1a2a1a。

精确API97031/Web97127经命令/cwd/端口双核对退出，专属Chrome退出。`targeted_exit_readback.py` 实际PASS：两PIDgone/8012与5178free、维护锁granted/waiting0、12完整stream/revision/seq与final相同，disabled/generation0；末轮source_prefix_revalidated=false，绑定已封存证明并只读12状态，不重复全源扫描。无未完成外部Gate；旧失败/部分提交全部保持，无回滚或生产重试。允许集成develop；未执行正式开放、Release、Runtime、Scope、通知或交易。下一最小步骤BU沥青。
