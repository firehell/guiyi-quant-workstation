# RS 油菜籽四周期历史候选闭环

状态：**CANDIDATE_CLOSED / REVIEW_COMPLETE / DEVELOP_INTEGRATED，12/12**。仅 RS，页面窗口 2023-01-01..2026-09-24，as_of=2026-09-24T07:00:00.000001+00:00。Canonical 1m 仅聚合；5m/15m/30m/60m × trend/oscillation/dual，共12组合。原13/21队列分母保持。

候选数据、资产、API与浏览器采集绑定 `8197ad4d1608ea343b6bfb01936229e244b10862`，资格仅加入 API/Web 单品种预览白名单；正式45品种、持续更新、Runtime、Scope、通知与账户不变。证据在 `.worktrees/rs-candidate-pilot/outputs/rs-candidate-pilot-20261004/`，不提交原始行情、响应或截图。

## 数据与资产

权威供应商起点2012-12-28，页面自2023-01-01。13个物理合约、27个主力区段，存在合约重入，二者不能混用分母。52维护单元=43实际apply读回+9 NO_GAP；69真实1m来源请求、293派生目标发布，合计362分区发布。独立复核912个涉及文件的真实SHA，2203个旧文件引用保持；四周期各13物理合约/125月完整前缀独立重算通过，5m/15m/30m/60m分别102015/34005/18136/11335根Bar。全部108主力区段×周期依赖DATA_READY。

8基础与4融合流READY，enabled=false/activation_generation=0/complete_window_proven=false，computed_through=2026-09-24T07:00:00+00:00。当前宿主只读source_prebuild.py --postbrowser四周期/12流通过，source-assets-postbrowser.json与source-assets-final-v5.json解析后完全一致。沙箱连接OperationalError记录保留；宿主只读事务证明现场，不把沙箱网络错误写成数据缺陷。本轮未重跑维护或构建，旧一次attempt不复用。

## API、页面与验收工具

api-v5/summary.json：12/12 READY、149次矩阵GET；API预检绑定source-assets-final-v5.json和每条stream/revision/seq。第一轮Chrome在5m双策略停止；原始失败与成功前缀保留，page-capture-resume按相同候选身份验证并复用前两场，续采收齐19场/49原图。evidence-index.json PASS，原始collection和原图不改写。主代理逐图审阅分钟主图/完整曲线/较早窗口36张、日周12张与取消恢复1张，独立Reviewer另核D1/W1原图。

首次离线审计报ACTUAL_CHART_NOT_READY：定位日周oscillation/dual四场。native chart为delivered非空465日Bar/151周Bar，当前NEWOW_OSCILLATION_WARMING；reference当前NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING，但有效历史CLOSED仍保留。页面明示价格不可用区间、重新预热、历史覆盖不完整与跨中断排除。工具ready-only断言与已接受的原生状态不一致；仅修验收工具日周精确暖态路径，不改变分钟READY门禁、数据、公式或收益。失败诊断在closeout-initial-diagnostics.json，最终审计与独立Review通过。

显示边界保留：密集Marker标签重叠/部分viewport裁切；较早趋势转折副图仅显示可用短段；15/30/60m趋势转折WARMING；60m未观察到主图分页游标；D1/W1来源价格缺口和当前短计算段预热。持有过程不可用，complete_window_proven=false。页面参考page_parity=true/executable=false，不证明因果/OOS、可执行收益或账户成交。

## 实际验证与交付边界

独立候选资格测试：后端test_candidate_preview.py -k p7_candidate为145 passed/69 deselected；Web newowCapabilities.test.ts为26 passed。候选Web build通过，保留既有动态/静态import构建提示。工具修复测试、离线审计与独立终审见下段；合并态验证已完成，见集成段。

历史真实浏览器证据只属于8197ad4d。develop后续共享冲突恢复与release能力变更的兼容性通过合并态受影响回归验证，不能将原图改标为新develop完整UI验收。正式开放或发布RS须绑定当时候选另行验收；本次完成历史候选及普通develop集成。

## 2026-10-04 终验

19场实际原始响应离线审计NUMERICAL_PASS_VISUAL_PENDING、49原图视觉复核及数据/源码/工具独立Review均通过，组合结果为12/12 CANDIDATE_CLOSED。工具不自行晋升候选：offline-audit仍保留candidate_closure=false，闭环依据另由独立Review与任务记录明确。12分钟组合全量核算39090个CLOSED价格/收益与39114个SVG点。D1 trend/oscillation/dual分别66/20/70 CLOSED，W1分别12/3/14，均为页面参考口径。

日周双策略原始场景缺同频oscillation完整reference，修复暖态误判后该门禁仍实际失败。对同批已索引standalone oscillation场先完整验收，再证明dual与standalone initial/return伙伴chart的identity、snapshot token、chart input hash与全部chart.value完全相同；standalone reference保留自身full-window/token/input/Decimal门禁。最终audit明确partner_reference_evidence=SAME_SNAPSHOT_SEPARATE_SCENE，不将独立场响应伪称dual自身XHR。修复范围仅验收工具wire/legacy_checks/bundle及两份测试，原始捕获与索引不改写。

实际命令（均从RS工作树运行，Python用主仓既有环境，PYTHONPATH=services/quant-api:packages/quant-core:.）：

- `python -m scripts.newow_candidate_tools audit --output outputs/rs-candidate-pilot-20261004/page-capture-resume`：exit0，19场NUMERICAL_PASS_VISUAL_PENDING；独立Reviewer另纯函数重放同批原始证据通过。
- `python -m pytest -q -p no:cacheprovider --tb=short tests/newow_candidate_tools`：225 passed，独立同套225 passed；先前暖态回归测试4 failed复现旧工具，修复后通过。
- `python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow/test_candidate_preview.py`：214 passed。
- `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/newowCapabilities.test.ts`：26 passed。
- `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build`：exit0，vue-tsc/Vite/bundle-topology通过。
- `python3 scripts/engineering/secret_scan.py` 对本轮6文件：finding_count=0；`git -c core.fsmonitor=false diff --check`通过。

资源现场宿主只读核对：原preview-api PID31896、preview-web PID31923均不存在，8012/5178无监听；无需再次停止进程。工作树保留原始证据，不force清理。原始失败、续采、index排他FileExistsError、沙箱连接/进程限制及root计数工具类型误读均保留或在诊断记录注明，不计为业务维护重试。正式开放45/60保持，RS成为第46个历史候选闭环品种，尚未发布或Runtime切换。

## develop 集成

工具修复与任务记录提交 `36ef14f4e`，连同原RS资格提交普通合入develop `d36bad7f24229910c653d073242443b939318a8a`，自动合并无冲突。合并后实际执行：

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short tests/newow_candidate_tools services/quant-api/tests/newow/test_candidate_preview.py services/quant-api/tests/newow/test_after_market_consumer_audit.py`：463 passed。
- `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/newowCapabilities.test.ts tests/useNewowProduct.test.ts tests/newowFusionPanel.test.ts`：127 passed。
- `pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build`：exit0，包含vue-tsc与bundle-topology。

日志保留于本任务outputs/integration-*；独立Reviewer核对合并态工具内容、资格与正式45品种范围。只交付RS历史候选闭环，不执行main/tag/release或Runtime promotion。验收结论：允许集成develop，已实际完成；下一品种按剩余队列另行处理。
