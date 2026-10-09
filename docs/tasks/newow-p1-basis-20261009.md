# 牛哇 P1 第二项：XP1及周日口径联动

基线develop `7d8a87e21`。只完成XP1及basis，四测试、选股、推送、策略/收益数值、资产构建和发布Runtime不在范围。

XP1独立版本`newow_period_conflict_v3379_v1`：`hit = trend.week == up && trend.day == down`；code为XP1或null，保留week/day状态。原CDV2公式、scores、R/MM、action、exposure全部不变，729冻结来源组合逐值核对。

页面版本`newow_basis_decision_v3379_v1`：week方向周、执行日；day方向日、执行60分。buy/hold→holding→up；sell→cleared→down；wait→idle→neutral，不复用CDV2中wait归down。不同产品/合约/segment、错频、重复、未来或非ready事实不可用；不以缺失代替空仓。融合复用主图`newowComparisonCompatible/newowDualDominance`，有效空主导回退趋势；partner未就绪或主导与综合分析cutoff不同不产生新basis动作。

|方向|执行|行|动作|强度|冲突|立场|
|---|---|---|---|---|---|---|
|neutral|任意|N|等待|tip|否|谨慎持仓/灰|
|down|down|DD|空仓|violate|否|空仓防御|
|down|up|DU|减仓|tip|否|谨慎观望|
|down|neutral|DN|空仓|tip|否|空仓防御|
|up|down|UD|等待|tip|是|谨慎持仓|
|up|neutral|UN|等待|tip|否|谨慎持仓|
|up|up|UU|建仓|ok|否|积极做多|

同一个decision驱动综合卡动作、强度/触发条件/理由、冲突和状态卡立场、进度方向；XP1单独显示，不混成UD冲突。状态名称和原评分保留背景身份；错配动作改为状态描述，旧周日方向收进明确标记的背景证据。主升浪无桶仍保留原显示，不造三周期输入。仓位仍为原跨策略参考强度，不是账户意图。

验证：测试先红（XP1字段缺失28项、页面basis控件缺失），再绿；后端CDV2/oracle/presentation/product_service 218 passed。源JS9组合及2basis×2bucket原文/oracle、missing/owner/future/dual/进度/旧guard回归已通过。Web全量1013 passed/1 skipped，typecheck/build/Worker拓扑通过；独立Review三项修复后64定向全部通过，允许集成。Ruff/secret0/diff通过。

实际Chrome RB固定只读快照：周/日口径可切换，日/60分UU输出建仓、遵守、各周期方向一致与积极做多一致；保存`outputs/newow-p1-basis-20261009/day-basis.{png,txt}`。该样本非冲突，XP1/UD由原值oracle与挂载回归证明，不声称全市场/逐像素验收。预览历史分析快照与行情报价保持既有独立身份；dual不同cutoff明确不可用。

命令：`NEWOW_PUBLIC_SOURCE=<冻结detail.html> node --test tests/*.test.ts`；`npm run build`；`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow/{test_cdv2,test_v3379_manual_audit,test_cdv2_presentation,test_product_service}.py`；`openspec validate --specs --strict --no-interactive`；`python3 scripts/engineering/secret_scan.py --json`。

原有未提交审计手册保持，不混入本提交；本页与canonical保存本次公式/实现身份。未切换正式运行版本。
