# MA 四周期历史候选处理

2026-09-28，P7-02 **CANDIDATE_CLOSED：12/12 历史候选闭环，REVIEW_COMPLETE，允许集成 develop**。会话 `01a0e7ac-e302-7c61-bf58-828470f9c986`；实际 goal 已创建，无 token budget。本记录只处理 MA，不创建下一品种会话。

## 冻结身份与范围

维护源码/develop 起点 `946dd59ceb8d7f5810930f08363cc98cf0044acc`；资产构建/首阶段候选代码 `e85777586fc743af0dcedde8055cbcb988d0862f`；最终产品代码 `48b12bfb73686c042d0f287a8b1d7a5b14cc86b3`。任务分支 `codex/ma-minute-closeout`，工作区 `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/ma-minute-closeout`。唯一原始证据目录 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/ma-minute-closeout-20260928/`，下文证据路径均相对该目录。当前 API 8012 / Web 5178 为 MA 单品种只读候选；正式 API 8000 / Web 5173 未切换。

范围：MA `5m/15m/30m/60m × trend/oscillation/dual`，4输入、8基础流、4融合流、12页面。历史 `max(2023-01-01,权威上市日)..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`；完成 Bar 截止 `2026-09-24T07:00:00+00:00`。1m 仅可信聚合源，不开放 Newow 1m 策略或页面。ReferenceTrade 为零费零滑点 page-parity，`executable=false`，不是因果收益、账户持仓或成交。

## 数据维护与独立读回

初始 48 项物理 prefix 依赖仅 3 项 DATA_READY、45 缺前缀；12 候选保存流均空。MainContractMap rank1 共 12 owner：MA2305、MA2309、MA2401、MA2405、MA2409、MA2501、MA2505、MA2509、MA2601、MA2605、MA2609、MA2610。MA2305 权威上市日 2022-05-19，证明 MA 在 2023 年前已存在；维护按每个物理合约上市事实补足计算 prefix，不把页面起点当作 warm-up 起点，也不套用 FU 合约上市日。

原生 HistoricalDataManager 精确 dry-run 去重后为 **88 源月、363 派生月**。只通过原生维护锁、重新计算 plan hash、staging/hard validation、不可变发布、Catalog 提交及读回执行；独立恢复前像保存七周期 pointer 与文件 SHA。wrapper 限制 MA/固定合约/频率/窗口/请求数，durable O_EXCL attempt，失败即停，无自动重试。

- 实际使用 `campaign-plan-v2.json` SHA `5f5a48f40471e7eb0515fb123ae4fc9c4c153c269d8ec66a784047f163097a5c`；脚本 SHA `54ec43082334f998a54396cfb117c2b68a55ff8854a3bda4b0c504ddb6105ca5`；dry-run SHA `183d4f2ed1efc37e70122250a81e95dee38108beb3fd05c839ddb2379745f25a`。
- 原计划未执行，保留 `campaign-plan.json`；初版逻辑计数在校验前增量、readback 更换 manager 后丢失的问题经独立 Review 修正后才执行。实际 48 单元：45 READBACK_VERIFIED、3 NO_GAP，**88 provider 逻辑请求、363 派生提交**，失败/重试均 0。见 `campaign-complete.json`、`campaign-apply.txt` 和 `campaign/` 每单元 plan/attempt/result/readback。
- 五频分区 320→720：269 原 pointer 不变，51 计划内部分覆盖分区扩展，新增 78 源、322 派生。88 源操作=78 新增+10 扩展；363 派生操作=322 新增+41 扩展。全部 609 旧七周期物理文件 bytes/SHA 保留，51 扩展分区每个原 Bar 逐值不变，289 D1/W1 pointer 不变。不能写成“全部原 pointer 不变”。见 `inventory-difference.json` 精确 targets 与 `inventory-final.json` URI/SHA。
- `dependency-final-readback.json`：48/48 DATA_READY。四份 `aggregation-<frequency>-full-prefix-readback.json`：每频 144 contract-month、12 owner，同合约 Canonical 1m 按历史 Calendar/Session `(start,end]` 重算逐值一致；夜盘/trading_day/短尾/边界保留。5m 181356、15m 60452、30m 31552、60m 18428 Bar；禁止跨频替代或缩窗。

额度现场剩余 1,050,811,952 bytes；570435 源 Bar ×1024 bytes/bar 的预留估算为 584125440 bytes，磁盘余量约 778GB。该预算不代表实际网络字节，88 仅计交给 provider 的逻辑请求。`quota-readback.json` 和 `quota-current.txt` 保留原证据；不从当前额度反推 FU 失败的消费。

MA 同盘 scratch 原子发布样本为 MA2305 2023-01 的真实 5280 Bar，源/scratch SHA 均 `b744f9e6054defb9549993a2adbc33e2f5d57422e27180dbb211b99eb5752114`。首次发布成功后因只读对象缺字段报错；后续只替换原 partition 的 file_path 读回，没有再次发布。两份原日志保留。MA 维护未再现 `ATOMIC_PUBLISH_FAILED`；这不解释 FU 的 UNKNOWN 根因，也不授权重试 FU。

## 候选资格最小修复

原预览后端只接受黑色系集合，前端 v26 也拒绝 MA，首次启动 fail-closed 为 PREVIEW_SCOPE_INVALID。经任务授权修复共享 P7 队列资格，一次覆盖 21 项资格；实际配置仍只有 MA。

`e857775` 修改 `product_release.py`、候选配置校验、capabilities、Web 类型/解析及对应测试/canonical：保留原 black v26 合同；新增 v27 `single_product_intraday_candidate`，只允许 P7 非 black 单品种且只向 Web 返回实际配置 singleton；扩展品种混合、重复、未知身份拒绝，正式分钟和 Newow1m 继续关闭。未改变行情 resolver、策略公式、ReferenceTrade 配对或收益模型。

维护证据仍绑定原 `946dd59`；首阶段候选资产/API/Web 统一绑定 `e857775`。`candidate-before-preview-fix.json`、`source-assets.json` 原证据保留；重新准备 `candidate.json`、`source-assets-v2.json`，没有改写旧身份。

## 保存资产

隔离 schema `newow_intraday_pilot_20260927`。全部使用原生 planner/service、SavedFusionSources 与保存资产 repository；初始流为空，**新增 8 基础+4融合，复用 0**。没有复制 resolver、公式或自行计算融合。

四频 native replay input count（含 11 个 owner 边界事件）：5m 181367、15m 60463、30m 31563、60m 18439。每频精确 plan/capacity/resume、基础和融合 attempt 位于 `assets/`；四频 base/fusion 实际输出位于 `<frequency>-build_base-run.txt` / `<frequency>-build_fusion-run.txt`。无构建重试。

`source-assets-final.json` 独立只读证明 12 保存流/summary/manifest 截止点一致且 READY，来源 prefix 与 plan source evidence 一致；全部 enabled=false、activation_generation=0。独立审查方另行只读查库、复算 8 plan hash /12 stream identity/4 fusion依赖，结果一致。资产完整不表示 Runtime promotion。

## API 与 Chrome

`api/readback.py` 实际运行：152 GET、12/12 READY；主图、基础/融合参考历史、快照、记录分页、附图及非适用杯柄分别检查。`api/earlier_windows.py` 的 `api/earlier-window-readback.json`：12/12 PASS，先普通 chart_before 再 chart_older_window，Bar 不重叠、日期更早、快照一致；不是用参考记录分页替代更早主图。

`snapshot-recovery-readback.json`：跨周期旧 token 的 chart/reference 均实际 409 NEWOW_SNAPSHOT_GENERATION_CONFLICT，正确 token 下新 chart/reference 同快照恢复。

实际 Chrome session `ma-minute-closeout`，固定 Web5178/API8012/as_of/e857775；浏览器响应使用被动 XHR responseText 观测并绑定实际请求，未 mock/拦截响应。首次取消探针确实取消/超时，但复制样板的 observer allowed 仍指向 JM，导致 XHR_COMPACT_OBSERVATION_MISSING；保留失败 JSON/CLI 与原 observer。只修正观察器 MA 白名单、版本与固定 helper SHA 后再次采集，修正版 v2 三项为 OBSERVED_CANCELLED / OBSERVED_TIMEOUT / OBSERVED_RECOVERED。冷探针前仅重启 MA 候选 API 清理缓存，源码、数据、as_of、scope 不变；正式服务未动。

首次12页面采集11项功能通过；5m趋势近一年记录实际409，原行保留不计闭环。较早窗口API审计与Chrome有并行读回；SnapshotCache默认32项/300秒、get不延长TTL，过期/淘汰仅为调查线索，不认定根因。新文件v2重验5m，并修正task-only checker，使blocked terminal/HTTP error不能误标errors_warmup PASS。没有修改产品缓存预算/TTL、公式或数据。

功能最终集合 `browser/functional-matrix-final.json` 为原9+恢复3，共326实际响应；12项checks全部PASS或明确N/A，同日参考分页4 PASS、8有据N/A。`browser/full-curve-observations-v2.json` 12完整面板补拍且记录ID/曲线点列逐值绑定原功能观察。补拍初次oscillation选择器把列表外当前OPEN卡也算入，严格比较失败后改用与原功能相同的直接记录列表选择器另存v2，原失败保留。

旧e857的60m trend较早UI真实失败：chart_before/chart_older_window均200且同token，前端NEWOW_RESPONSE_INVALID清空冲突事实，原DOM/技术详情/CLI及完整wire保留。原normalizer离线准确拒绝 `chart.price_reference.as_of conflicts with generation as_of`；price as_of=2026-06-15T07:00Z、meta=2026-09-24T07:00:00.000001Z。不能用API PASS或RB既有D1记录豁免本轮分钟UI阻断。

`855c54f` 根因修复：后端chart投影使用请求generation as_of，旧窗口末Bar仍独立anchor_bar_end；价格公式/raw/input hash不变。前端合并普通/较早分页保留已接受price_reference，符合“普通左翻不改顶部最新价格”；显式历史切换resetAll后首响应仍重新锚定。9参数RED证明时间身份失败；新增不同140/130/110价格断言RED后验证普通/较早合并均不改最新价格。服务测试fake reader原先忽略as_of返未来Bar，改为按<=as_of过滤以遵守真实reader合同，不放宽产品校验。

根因修复后产品、资产与请求证据分层保留：12资产仍是e857构建，原数据/manifest未改；`source-assets-final-v3.json`在855c54f独立只读再核对全部12流PASS；`candidate-e857.json`保留旧配置，candidate.json记录新代码、原asset_build_code_sha和maintenance_code_sha。API/Web仅候选副本重启到855c54f，最终phase-v3证据单独保存，不拿e857旧页面绿灯代替新代码。

`48b12bf` 补齐实际读回发现的顶部价格展示问题：855 的较早窗口已经加载，但展示层仅接受 currentChartWindow，导致价格变为“未开放”。direct-price 分支现在接受已证明的 current 或 historical 窗口；仍校验实际最新 anchor、owner、segment、calculation identity 与 generation as_of。未放宽旧 explanation fallback、OPEN 当前参考或无来源价格。新增历史有效/无窗口证明/错误 anchor 回归先 RED 后 GREEN；三个 Web 模块 153 passed，build 通过，独立 Review 16 passed。最终 `source-assets-final-v5.json` 对全部原12资产只读再核对 PASS。

深缩放 v7 触发图表既有 near-left 自动分页；15m 趋势截图与即时 DOM 价格不一致，5m 趋势 After 价格隐藏，均保留失败。静态链路与真实末Bar/末frame/price_reference 纯函数验证表明，chart lifecycle 从 ready 转 loading 时价格临时隐藏，恢复 ready 后同锚点重新显示；不是已证实的稳态价格回归。v8 另存全部自动请求 URL/HTTP、active 请求和价格稳定采样，待自动分页完成、按钮解除 disabled、五次稳定样本后截图。分页 pending 显示“未开放”的既有 UX 限制单独披露，不用 pending 截图冒充稳态失败，也不放宽价格来源校验。

最终48b较早API `api-v5/earlier-window-readback.json` 12/12 PASS；完整API `api-v5/summary.json` 12/12 READY、152 GET，`snapshot-recovery-readback-v5.json` 的两项错频token实际409后正确快照恢复；`scope-readback-v5.json` 再核对实际MA singleton/两端源码身份。最终 `browser/ma5m-cancel-timeout-observations-v5.json` 实际取消/250ms短超时/恢复三项通过。

`browser/earlier-window-observations-v8.json` 12/12稳态较早主图通过，12图独立逐张审查、可见Marker与实际older Bar时间匹配；180条已记录HTTP响应全部200，每项最后五次样本active=0、界面ready且顶价稳定。观察器没有保存requestfailed列表，因此不从该数组推断“无任何transport abort”。该组不作为深窗口完整MACD或参考曲线的证明。

最终48b完整功能 `browser/functional-matrix-final-v5.json` 为12/12，325实际XHR，76 PASS/8有据同日分页N/A；`browser/full-curve-observations-v5.json` 12张完整面板且ID/曲线点列逐值等于本阶段功能原行。12主图与12完整曲线已独立逐张审，统计匹配对应base或fusion响应，不拿首阶段e857截图代替最终版本。

`browser/legacy-regression-final.json` 为D1/W1 × 三模式共6项兼容回归：主图、完整已完成累计曲线、近一年记录、切换返回和错误检查均PASS；D1辅助PASS，W1辅助明确WARMING（NEWOW_TREND_REVERSAL_WARMING）。实际D1/W1全窗口through/available_through均2026-09-24、cutoff=2026-09-24T07:00Z；不套用旧准备阶段的9/18猜测。空Bar和过期reference负向校验实际拒绝。D1/W1更早主图分页不在本轮额外兼容检查内，不声明全套E2E通过。日周12张主图/曲线图已独立逐张审，112实际响应身份/as_of/HTTP200及返回ID/curve points核对通过。compact未包含日周summary，日周统计仅视觉核对，不宣称其wire逐值复算。

既有边界：持有过程曲线不可用，明确显示已完成累计；分页pending顶部价短暂显示“未开放”；较早主图组不证明深窗口MACD全拼接覆盖。原失败、未完整取景及各修正版均保留，不修改失败记录为PASS。

## 实际工程验证与 Review

以下均保存真实输出，不使用历史绿灯代替：

- `python -m pytest services/quant-api/tests/newow/test_candidate_preview.py -q`：90 passed（任务 worktree/PYTHONPATH，`preview-green-v2.txt`）；新增后端与 Web 身份测试各有修改前 RED 输出。
- `node --test tests/newowCapabilities.test.ts`：25 passed，0 failed（任务 Web；`web-preview-green.txt`）。
- `npm run build`：vue-tsc、Vite、bundle topology 通过（`web-build.txt`；既有 dynamic import 提示无构建失败）。
- 最终展示修复 `node --test tests/useNewowProduct.test.ts tests/newowProductTypes.test.ts tests/newowDetailPresentation.test.ts`：153 passed、0 failed（`older-price-presentation-green.txt`）；`npm run build` 的最终 typecheck/build/topology 通过（`web-build-presentation-fix.txt`）。
- 任务 `test_scope.py -q -p no:cacheprovider`：9 passed；独立审查方另跑 9 passed。
- scoped Ruff、OpenSpec 检查、secret_scan finding_count=0、git diff --check：通过。首次 canonical 条目放在非 Requirements 区造成检查失败；修正位置后使用实际 task worktree 检查通过，失败输出保留。
- `independent-review.md` 包含维护前 exact plan、安全计数修复、候选资格、实际七频文件与资产只读补审，以及 XHR漏审更正。另有较早窗口根因修复的真实回归：`pytest test_older_chart_windows.py test_product_service.py -q` 99 passed，`node --test tests/useNewowProduct.test.ts tests/newowProductTypes.test.ts` 137 passed，Web build/Ruff/diff check通过；独立审查另跑28后端及2前端含显式历史测试通过。最终48b分钟12主图/12完整曲线、较早主图12及日周6组合均已独立审查，允许候选闭环与集成develop。

## 恢复边界与后续

旧不可变文件、pointer 前像、精确 plan/attempt/readback 均保留。维护已完成，不重复 apply 或删除 attempt；若后续新问题需要修复，只按已证明对象执行精确 forward 维护。候选保存流保持隔离 disabled，不把删除流作为回滚方式。产品代码可通过普通 forward revert 恢复候选资格，正式发布未切换。

本任务不包含 main merge/tag/release、Runtime/worker/Scope 启用、真实通知、Broker/订单或账户，`auto_order=false` 保持。最终矩阵为 `browser/matrix.json`：12/12 CANDIDATE_CLOSED，12资产新增、复用0；未用旧阶段失败或N/A提高完成率。任务交付至develop，精确Git结果由本轮提交/远端读回确认。候选工作区仍被8012/5178预览进程使用，保留，不清理其他任务。唯一最小下一步：由总控安排P7-03 UR，本会话不创建下一品种会话。
