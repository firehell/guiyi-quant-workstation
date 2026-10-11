# Newow 当前身份历史资产构建与验收

状态：COMPLETED / REVIEW_COMPLETE。60 个 operational 品种的1260个新 public historical exact identity
全部构建、注册并通过独立数值验收；360项融合和180项主升浪消费者检查另外通过，不重复计作资产。
本任务已完成历史资产闭环，未发布、切换或启用新 Runtime，不代表因果收益或自然通知验收完成。

## 范围、基线与证据

- 1w、1d、60m：趋势、震荡、主升浪、双策略融合；5m、15m、30m：趋势、震荡、双策略融合。
- 不建立短分钟主升浪或四测试资产，不创建账户、订单，不发送通知。
- 固定截止 `2026-10-09T15:00:00.000001+08:00`；不使用属于10月12日的周五夜盘。
- D1/W1窗口从2023-01-01，分钟从2025-09-25；仅按权威上市时间截断，不缩窗掩盖缺口。
- 最终验收代码基线 `5f0f978f9fea6593da31aa2c1e776b101b93a641`，冻结为
  `campaign-after-period-label-fix.json`；此前campaign保留。后续文档提交不改变构建源码。
- 新历史流全部 disabled、activation_generation=0，page_parity=true、executable=false。

真实现场报告位于 `outputs/newow-history-v4-20261010/`：

| 证据 | 结果与边界 |
| --- | --- |
| `complete-product-acceptance-v2/` | 42品种、882资产、252融合、126主升浪，全通过 |
| `remaining-product-acceptance-v3/` | 18品种、378资产、108融合、54主升浪，全通过 |
| `final-matrix-acceptance.json` | 180份报告绑定当前plan/receipt/revision/seq/digest、融合依赖；1260唯一资产全通过，原生矩阵1260 READY且同一修订 |
| `protected-after-1260.json` | 与`protected-before.json`整份相等，1447旧流、720 enabled forward及受保护计数未变 |
| `develop-asgi-api-acceptance.json`及`develop-asgi-api-final-generation.json` | RB真实develop API：21流、15持久化策略详情，全分页通过，最终21修订再次确认；不是全部60品种API测试 |

资产检查包括正式身份、禁用状态、所有batch连续性和hash链、输入指纹/数量、完成水位、
稳定entry/exit关联、物理合约与segment、Decimal收益。消费者遍历全部分页，检查cursor进展、
重复记录、记录与曲线各自窗口、三组统计和Decimal收益。数值证据来自分产品完整报告；
最终metadata在修订未变时绑定这些报告，不将READY单独当作数值证明。

最终独立Review实读180份报告及SHA、唯一身份、通过计数和最终同修订矩阵，未发现Confirmed Issue。
保护快照SHA为`607a34a9d3523f4f8d36607eb7637c255647c86f5d78acf7d63d8aaac5fcf90e`，
旧batches24493、actions111712、trades42313、activation720、alert_events1449不变。
这只证明快照所覆盖的状态/表，不外推全Redis游标、所有transport表或消息送达。

## 必要修正

1. 融合lineage修复已合入develop `e1d26a1db6ce989407cdf61db0f24a56ee5f426f`。
   D1/W1完整manifest分别保存原始reader的`source_input_fingerprints`与实际融合的`input_fingerprints`，
   使用`newow_fusion_saved_sources_v2`；分钟compact仍为v1。RB日周融合以新revision修复，
   交易、展示和checkpoint语义等价，旧revision保留，最终验收使用两份修复plan/receipt。
2. 持久化availability修复已推送develop `59d6d6ae0e030a69cd01c4a1dd8d7ad74b2ebcf5`。
   D1/W1包含非当前rank1 owner的物理预热点，导致COVERAGE_IDENTITY_CONFLICT；复用既有
   `reference_owned_points`过滤全部周期，正式owner内的真实计算段冲突仍fail-closed。
   RB日周真实persisted接口由409恢复200；公式、参考交易和资产身份不变。
3. 页面周期标签修复已推送develop `5f0f978f9fea6593da31aa2c1e776b101b93a641`。
   同时识别旧day/week/hour和正式1d/1w/5m/15m/30m/60m，周线显示周K、分钟显示对应周期，
   未知值不伪装日线。公式、收益和历史构建源码不变。

## 数据修复、预算与恢复

AG2612、AU2612、BZ2611、CU2611、EC2611、EG2611的5m/30m共12组118分区，
以及MA2611、SN2611的5m/30m共4组44分区，使用通过校验的既有Canonical 1m原生聚合。
合计162分区、150833条缺失派生Bar、1919条保留重叠值，provider请求0；真实值、Catalog、
publication provenance及原生剩余缺口读回通过，原1m hash不变。
对应`derived-prefix-*-readback/acceptance`、`remaining-gap-acceptance.json`及旧preimage记录均保留。

最初AG30m原生发布成功而包装器date JSON序列化失败，终端receipt缺失；停止后以独立权威
postcondition确认10分区已完成，没有重试或补造回执。AU30m的passed曾被包装器误按completed判断，
同样停止后读回确认，没有重做发布。24份冻结旧派生文件SHA验证通过，这是保留证明而非回滚演练。

RM2701 W1真实源缺失，未用D1合成W1。原生冻结18 direct targets：9个D1上下文月及9个W1月。
首次attempt被维护锁阻断且provider/applied/publications均0；新attempt2在自然周审60品种完成、
释放锁后一次执行18 applied/18 provider requests/18 publications。
`rm-week-acceptance.json`核对18分区、11份旧preimage、173条原D1值、37条W1值及quality，
剩余targets=0、weekly interruptions=0；随后才构建并验收RM资产。
源修复先于其消费者验收；其他已通过品种的源未由本任务再次改写。

SC5m保守metadata bound为1080775条/4426854400 bytes，超过原预算且在plan/写入前阻断。
仅SC AND 5m调整为1100000条/4505600000 bytes，单stream、1800秒、窗口/质量/公式及原生
预算校验不变；既有plan不覆盖。独立Review通过后实际540393条、每路约138MB，一次完成三路。
其他周期仍使用原预算。计划bytes不是OS内存上限。

SM15m的SOURCE_BUSY发生在取得原生cache scope lease之前。构建停止并只读确认两路
无intent/receipt、stream未注册且锁已释放，才续接一次；`sm-source-busy-preflight.json`保留。
最终`build-resume-v4.log`正常exit0。未知提交结果不能据此类推为可重试。

构建每周期一个CLI子进程，验收每品种/类别一个子进程，不并行writer，不强停自然Runtime。
现场较大SC构建Python约1.08GiB，多次系统free采样约41%～51%；这些是采样，不代表全过程峰值。
临时GET-only、SQL readonly预览8012/5178已正常关闭，正式服务未切换。

## 实际工程与页面验证

- 融合lineage联合回归81 passed / 1 skipped（可选隔离PostgreSQL DSN未设置）；另7项定向通过。
- 派生前缀相关contract warm-up回归66 passed / 151 deselected。
- `pytest -q services/quant-api/tests/reference_trading/test_newow_persisted_query.py services/quant-api/tests/newow/test_intraday_pilot_contracts.py services/quant-api/tests/reference_trading/test_newow_hint_action_reads.py`：53 passed。
- `pytest -q services/quant-api/tests/reference_trading/test_historical_integration.py -k real_canonical_catalog_mds`：1 passed / 1 deselected，真实SQLite Catalog/MDS。
- 在apps/quant-web运行`node --test tests/newowPagePerformance.test.ts tests/newowPagePresentation.test.ts`：7 passed；`vue-tsc -b --noEmit`通过。
- 相关Ruff、OpenSpec strict 11/11、secret scan 0 findings、git diff --check通过；高风险修正及验收器独立Review通过。

临时develop固定截止页面实测RB日线、周线、5m。曲线、统计和最新三条记录与
`api-visual-rb-summaries.json`一致：累计/胜率/平均/次数分别为
65.73%/52%/3.62%/79，9.11%/69%/7.21%/13，134.45%/62%/0.57%/1749。
日线展开79条记录可折叠；周线/5m周期标签已修正。
截图为`visual-rb-d1-performance.jpg`、`visual-rb-w1-performance-fixed.jpg`、
`visual-rb-5m-performance-fixed.jpg`，仅证明RB三个周期视觉样本。

页面默认since=2023-01-01，分钟读取实际保留的物理预热前缀，5m默认1749次不同于固定
since=2025-09-25请求的1612条记录；逐值比较使用同一实际窗口。默认日期/READY不能证明
完整2023分钟覆盖。接口真实resolved cutoff为15:00整，较请求少1微秒，已分别记录。
现役v1.14.18旧v3基础/v1融合接口200不证明develop新v4/v2资产，D1/W1 include_fusion=true
仍有legacy路径，因此融合用真正persisted消费者单独验收，未混淆来源。

后续最小工程项：短分钟策略详情每页重复约11～13MB完整展示数据，实测每页约10～14秒。
应优化这一响应/分页开销并保持数值、修订和快照合同；本次不改变该接口合同。
发布、Runtime启用和自然业务证据仍是独立任务，不能由本次历史完成推导。
