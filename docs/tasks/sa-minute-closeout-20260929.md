# SA 四周期历史候选闭环

2026-09-29，P7-07 SA **12/12 CANDIDATE_CLOSED**。数据、disabled候选资产、API、真实Chrome和独立Review全部完成；CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE，允许集成develop。仅交付本项候选与工程记录，不构成正式分钟开放、发布或Runtime promotion。

## 范围与现场

仅 SA 5m/15m/30m/60m × trend/oscillation/dual，固定4输入、8基础流、4融合流、12页面；1m只作聚合源。窗口2023-01-01..2026-09-24，as_of=2026-09-24T07:00:00.000001+00:00。Catalog94合约，最早上市2019-12-06。
冻结源码604b90e7b990163f930618dbee07708b81b974b4，branch codex/sa-minute-closeout，工作区 /Volumes/扩展盘/worktree/sa-minute-closeout/guiyi-quant-workstation。没有产品源码、公式、收益或执行语义改动。原始命令/计划/响应/图片/独立Review保存在本机 outputs/sa-minute-closeout-20260929/，不提交行情、配置、凭据或原始日志；其他任务输出不覆盖或清理。
固定21品种分母与其余队列行保持。AU未启动；正式分钟、main/tag/release、Runtime/worker/Scope/通知/Broker/订单未切换。

## 真实维护与数据验收

12个实际rank1 owner、48份原生dry-run；初始3/48 DATA_READY，候选流原不存在。去重86源1m月/352派生月，预计557220源Bar，保守预算570593280 bytes，现场quota1047341277 bytes；同盘scratch原生发布读回和维护锁校验通过。
bundle SHA67d4a49e1c9423585096cb2adc8b95290422c71f675f79ee9c0f336591e3c8ea。实际apply经宿主正常放行完成86 provider逻辑请求/352派生月，45READBACK_VERIFIED+3NO_GAP，没有维护失败或盲重试；48/48 DATA_READY。
四频各139contract-months全部生命周期前缀独立从同物理合约Canonical1m按Session(start,end]重算；OHLCV/OI逐值一致，5m174390、15m58130、30m30340、60m17720Bar。夜盘交易日/周末归属、75分钟Session、30m15分钟与60m15/30分钟短尾、11次主力切换通过。
586旧七周期文件字节保持，535指针不变、51扩展且保留57165旧Bar、387新指针；278D1/W1指针不变。独立 Review完整重算四频和文件hash通过。独立checker最初误传PyArrow额外kind列导致TypeError，只修正字段选择重验，原checker失败保存；没有生产mutation重试。
SA自身Calendar/Session证明9/21..27周的9/25–27关闭，原生completed week终点9/24 07:00UTC，不借用其他品种事实。

## disabled 候选资产

schema newow_intraday_pilot_20260927，四频base/fusion8次构建完成，12唯一stream READY/enabled=false/activation_generation=0。manifest、source digest、input count、revision/seq/checkpoint精确核对；4融合绑定自身最终base stream/revision/seq/digest/snapshot，独立资产Review通过。
8基础流native availability为FULL，12VALID intervals、905个真实owner/交易日组合，集合与SA Calendar完全相等，unavailable_days=[]、no_trade=0。complete_window_proven=false保留；first_computed_through：5m/15m2023-01-04T14:15Z、30m2023-02-01T15:00Z、60m2023-02-17T15:00Z。FULL不证明窗口首日有策略输出或完整窗口收益。

## API、Chrome 与失败证据

只读8012/5178，固定源码/as_of、SA singleton v27/realtime=false。初始PYTHONPATH误指不存在目录，早期维护实际回退导入editable主树quant-core；冻结worktree与主树59个tracked quant-core文件逐字节一致，独立核对证明源码身份相同。第一次preview启动校验检测到错误路径并退出，原失败保留；修正为冻结worktree quant-core路径后才成功启动，后续优先导入隔离目录。
152保存API请求、12/12READY、12较早窗口、2错频409和fresh同token恢复通过。真实取消/0.253秒短超时AbortError/5m500Bar主图、200记录及曲线恢复通过；取消相关3条ERR_CANCELED已逐条对应，不冒充无错误。
分钟功能矩阵12/12：78PASS/6有据NOT_APPLICABLE，actual history_limit200与DOM IDs、独立chart/ref分页、模式周期回切、辅助和身份通过。
原完整曲线补证GET因300秒snapshot TTL返回409，失败保留；不改旧token或宣称旧GET成功。fresh补证v5在浏览器启动前遭sandbox npm EPERM、v6误要求chart/ref输入hash相同而失败，均保存。真实旧响应证明hash按section/window定义、同token下hash可不同；v7分别绑定各section自身hash与原功能immutable身份，跨section同token，实际页面fresh→全部→已完成累计→即刻完整GET→全部CLOSED数组hash/交易ID/Decimal累计/SVG全部点核对。旧功能仅在revision/seq/input/source/window/curve事实和全部DOM坐标一致时复用。

v7首组实际fresh响应/完整GET/PNG已取得，但校验器对非chart响应的null status误处理而AttributeError；修正null guard后离线重验原raw，通过并由v8聚合准确引用原v7图/JSON，不重新采集此组。全部工具失败与实际响应保留，不视为数据attempt或改变计划。

最终实际分钟完整曲线12/12、earlier12/12通过。12完整图为60m trend保存v7首图+其余11v8；v8聚合准确引用原图/raw，完整数组SHA与原API全集一致，原functional source/generation/window/全部DOM点和记录ID一致。
日周六组33PASS/3原生NEWOW_TREND_REVERSAL_WARMING；SA W1震荡完整窗口真实1CLOSED(-13.13963573287077189939288812pp)、5ROLLOVER_INTERRUPTED，近一年0CLOSED+2中断，非其他品种的零CLOSED完整窗口。六组full/before/returned全部closed点、ID和Decimal累计额外离线检查通过，weekly cutoff绑定SA自身Calendar完成周证明。

## 实际命令与验证

以下命令均已实际执行；python为既有services/quant-api/.venv/bin/python，早期维护按上述逐字节相同源码证明执行，修正后构建/服务优先导入冻结worktree PYTHONPATH；程序使用安全配置，不显示凭据。维护/采集脚本入口相对本项outputs目录，pytest命令相对仓库根：

```sh
python campaign.py --apply --expected-plan-sha256 67d4a49e1c9423585096cb2adc8b95290422c71f675f79ee9c0f336591e3c8ea
python verify_data_only.py
python build_assets.py
python verify_assets_only.py
python verify_api_only.py
python browser/regression_recovery-v5.py --kind cancel-timeout --execute
python browser/verify_sa12.final-v5.py --execute
python browser/earlier_windows-v8.py
python browser/legacy_regression.empty-v2.py --execute
python browser/capture_full_curves-v8.py --execute
python legacy_complete_binding.py
python -m pytest outputs/sa-minute-closeout-20260929/test_scope.py outputs/sa-minute-closeout-20260929/test_complete_curve_binding.py outputs/sa-minute-closeout-20260929/api-v5/test_coverage.py outputs/sa-minute-closeout-20260929/browser/test_record_binding.py outputs/sa-minute-closeout-20260929/browser/test_legacy_binding.py -q -p no:cacheprovider
```

维护/data/8次资产构建/API/Chrome功能/earlier/日周/freshv8/六组legacy全点检查最终均exit0。最后定向测试68passed in1.40s：scope扩大、coverage错报、记录window绑定、跨section自身身份、token/完整CLOSED集合/中间坐标/精确时间、dual身份与真实SA周线曲线的负向保护。每阶段旧失败单独保留，不以orchestrator exit0代替逐项验收。

## 资源收尾与边界

精确核对API/Web唯一listener、command、cwd后，仅SIGTERM PID85346/85118，8012/5178unbound；专属Chrome sa-minute-closeout已close。其他正式服务未触及。数据/disabled资产/旧失败和原图保留；没有删除行情或其他任务文件。
complete_window_proven=false、持有过程不可用、deep MACD额外因果验收未测、D1/W1 older-window未测、页面零手续费零滑点与非可执行口径保持。不声明OOS/Walk-forward、模型账户收益、正式分钟开放、RELEASED或RUNTIME_READY。AU未启动；唯一下一步是由owner按固定队列交办AU。

49张最终原图已逐张实际独立view_image：12分钟主图、12完整曲线、12earlier、12日周主图/曲线、1取消恢复。preflight/helper/data/asset/API/recovery/minute/earlier/legacy独立Review通过，无未解决Confirmed Issue。报告为本项outputs下independent-*-review.md；数值与视觉原图边界分别说明，未把屏外卡片宣称为视觉已看。文档引用/secret scan与diff检查通过后按普通工程流程集成develop，正式状态以Git exact readback为准。
