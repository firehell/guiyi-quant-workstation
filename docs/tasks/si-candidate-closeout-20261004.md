# SI 工业硅四周期历史候选收尾

本地证据归档（2026-10-07）：任务工作树原始输出已移至 `.ai/worktree-cleanup-20261007-233713/si-candidate-closeout/outputs/si-candidate-closeout-20261004/`；主仓独立 Review 输出已移至 `.ai/develop-cleanup-20261007/outputs/si-candidate-closeout-20261004/`。下文命令和原输出路径保留为执行时记录，证据内容未改动。

状态：COMPLETED / CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12；允许集成 develop。仅 SI，固定页面窗口 2023-01-01..2026-09-24，as_of=2026-09-24T07:00:00.000001+00:00。Canonical 1m 仅聚合；5m/15m/30m/60m × trend/oscillation/dual，共12组合。SI为补充行，原13/21队列分母保持。

数据、资产、API与浏览器产品源码冻结于 `125f3dbfbe79317cf1fee1204e57944a0750dc95`，工作树 `.worktrees/si-candidate-closeout`；原始证据在该树 `outputs/si-candidate-closeout-20261004/`，独立Review在主仓同名outputs/review，不提交原始行情、响应或截图。任务从2026-10-04开始，最终收尾在2026-10-05；正式45品种、Release、持续Runtime、Scope、通知及账户不在本次交付范围。

## 原停止边界与本轮数据

旧2026-10-01唯一SI2308/5m发布1个源月与1个派生月后，账户级额度增量2576409超过原1024倍估算1612800，归属仍未知。原parent/unit PENDING/retry_allowed=false与发布读回证据保留在归档；本轮先核对该原单元完整窗口NO_GAP和已发布bytes，未重新执行原单元或复用失败attempt。

新冻结continuation-plan-frozen.json SHA `d48db6aac1aa85e45893c81fb911fd2f10f186ab85aa2b66dcf4191da7d72131` 仅包含107个原未尝试尾单元。每单元fresh计划/preimage、执行前/锁内/执行后quota、1024倍估算、排他attempt、锁及读回守卫不变；总源/派生预算含旧1+1。本轮107=104 READBACK_VERIFIED+3 NO_GAP，220真实源请求与893派生发布，累计221/894。17个无源请求单元出现账户正增量，仅按原账户守卫处理，不能归因本品种。

30个主力owner区段/27个物理合约；SI2401、SI2506、SI2507存在非连续重入。候选保留30区段与29边界，维护为27物理合约×4=108唯一单元。四周期各275个物理合约月，5m/15m/30m/60m分别221490/73830/39376/24610根Bar，共359306；独立以固定SHA的Canonical 1m、Session(start,end]、Decimal200重新聚合全部字段与端点通过。全部120主力区段×周期依赖DATA_READY，actual=expected=effective>0/no_trade=0。

七频before/after：1259→2236 active文件，977新目标/136扩展/0删除，1123 Catalog行未变；全部1259旧不可变bytes保留，扩展分区100280旧Bar逐字段保持，636日周文件及Catalog行完全不变。维护完成后锁0。

## 禁用候选与验收工具

8基础与4融合计划逐份冻结并独审，真实构建全部COMPLETED。四趋势四震荡覆盖FULL，30owner区间、unavailable_days=[]；当前12流READY、enabled=false/activation_generation=0/complete_window_proven=false，computed_through=2026-09-24T07:00:00+00:00。融合严格绑定本轮伙伴revision/seq与完整window依赖摘要，不启用。

源资产v5保留。首次真实页面preflight在任何GET前报OWNER_DUPLICATE：验收工具把合法物理合约重入误判重复。仅修改preflight.py与定向测试；有owner日期时必须所有四频全部owner具备完整合法ISO日期、候选窗内、全局排序非重叠、signature唯一且四频完全一致。无日期unique旧报告兼容，裸重复仍拒绝。新只读source_segments_readback.py从原生DependencyOwner加日期，并证明source hash/12state-summary/去日期后的原owner facts与v5完全相同，排他生成source-assets-segment-identity.json，原v5不覆盖。

验收工具SHA `6a46557ccff80b718d0a6af6b0359d535e05805d59c30863f6e4d59c6f6714e9` 独立Review通过；API辅助只允许该精确单文件dirty，其他services/packages/scripts仍拒绝。HEAD和产品公式/数据/收益逻辑未变。真实4 GET preflight通过，source segment证据SHA `681c2100c9b6d349f9337036815d6c7d904fd15bbf2fb5fe6e9212e03b34b0b3`。

## 实际验证

- `python -m pytest -q -p no:cacheprovider --tb=short tests/newow_candidate_tools services/quant-api/tests/newow/test_candidate_preview.py services/quant-api/tests/newow/test_after_market_consumer_audit.py`：482 passed；独立工具244 passed，定向45 passed。
- `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/newowCapabilities.test.ts tests/useNewowProduct.test.ts tests/newowFusionPanel.test.ts`：127 passed。
- `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build`：exit0，vue-tsc/Vite与bundle-topology通过。
- 连续campaign守卫6测试与preplan辅助4测试通过；`git -c core.fsmonitor=false diff --check`、工具secret scan通过。

页面参考page_parity=true/executable=false；不证明OOS、因果可执行收益、完整融合状态机重放、自然TTL或账户成交。complete_window_proven=false保持。历史候选已闭环；普通develop交付以Git记录为准，正式开放仍45/60。


## 最终页面与退出验收（2026-10-05）

API12/12 READY，矩阵149 GET及初始身份1 GET均HTTP200，分段身份、冻结revision/seq/source/upstream及完整数组摘要一致；API保存count/hash/首末记录，Chrome原始full arrays另经全量复算。Chrome一次串行采集19场（12分钟＋6日周＋取消恢复）、49张原图，原生index SHA `a7fd280b3dfe2576f8cbfb359c81708225c7eeeaf666c4a3366666bd499a82a0`；`python -m scripts.newow_candidate_tools capture/index/audit --output outputs/si-candidate-closeout-20261004` 实际exit0。原生19场均NUMERICAL_PASS_VISUAL_PENDING/candidate_closure=false原件保留；root及独立Review实际逐张查看49原图通过，独立原生纯离线replay等值、18曲线场14822 CLOSED价格回报与14858 SVG点Decimal200全量复算PASS，组合形成REVIEW_COMPLETE_CANDIDATE_CLOSED，未改原审计字段。

`source_prebuild.py --postapi/--postbrowser`两次fresh只读source与原v5整文件一致SHA `e6180b3f5595ec5949d9021bfd32dffd2daa24051b443e6ab2790a4ae434ca29`。独审后仅关闭本次Chrome session与专属API/Web PID15556/15636；`task_exit_readback.py`实际PASS，两PID退出、8012/5178无监听、维护锁granted/waiting均0、12流disabled/generation0及完整state一致。无新增Runtime、Scope、Rule、通知或账户操作。

日周震荡历史PARTIAL、周线当前44/120与29预热区段、不可用年化/回撤、OPEN/rollover浮动不入CLOSED及密集标签viewport局限保留。页面参考不证明因果/OOS可执行性，取消场不代替自然TTL及完整卡片身份验收。数据/资产/页面证据仍只归属冻结125f3候选，工具修复及普通集成不将其升级为新develop全UI或正式发布证据。

关键独立证据：主仓 `outputs/si-candidate-closeout-20261004/review/decimal200-full-prefix-review.json`、`reentrant-tool-review.md`、`segment-and-api-gate-review.json`、`final-browser-review.md`及资源/收尾终审。历史候选47/60，正式分钟45/60，SI和RS未正式发布/启用，原13/21分母保持；旧SI停止证据未覆写。
