# P7-09 AG 分钟历史候选闭环

状态：**COMPLETED / 12/12 CANDIDATE_CLOSED**。仅 AG，固定 4 输入、8 基础策略、4 融合资产、12 页面；1m 仅作聚合源。窗口 2023-01-01–2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`。冻结源码 `718349a62f3117962d70f64fb314c70ac7fbbd19`，验收期间产品源码、公式和版本未改。

本机原始 evidence、helper、失败日志和截图保留于 `outputs/ag-minute-closeout-20260929/`，不提交生产原始数据、配置或凭据。仅提交本记录、STATUS 的 AG 入口及 P7-09 行；其他品种与固定 21 分母不改。

## 数据与维护

现场得到 20 个 actual rank1 owner、80 份原生 contract_warmup 依赖，初始 10/80 DATA_READY。实际 149 次行情源请求、679 个去重派生月完成，最终 80/80 DATA_READY；保留 930 个旧七周期文件及全部旧 Bar，479 个 D1/W1 pointer 不变。Instrument 不提供产品上市日期；所选物理合约上市事实不冒充产品上市日。

首次整包估算超过账户剩余额度，在 attempt 前停止并保留预算失败。随后冻结逐原生单元额度 gate：1024 bytes/Bar 仍是项目估算，不是供应商上限；每单元及锁内 apply 前现场查额度，源请求次数和下载预算不放宽。

原 campaign 在 AG2310/60m 原生发布成功后，因零源请求单元观察到正账户 quota delta 停止，原因 `QUOTA_ESTIMATE_EXCEEDED_OR_OTHER_CONSUMER`。该账户级 delta 未归因于其他进程，也不伪称本任务下载。独立只读核对证明该单元发布已完成、旧文件/行保留、无剩余目标和维护锁；未重跑。新 continuation 只执行 64 个尚未启动单元，保持原 symbol、物理合约、窗口、数据标准和累计预算，链接原停止记录；不覆盖原 attempt/stop，也不伪造原 campaign-complete。

原计划 SHA `bccdc970ff45a5dcbb48799acf0a854e4deb0a61d45d68729b56e77638e47261`，continuation SHA `de6e3a2e753099dc3866050a9d30fb12d672121132f4857288c61caea3005ab0`。最终状态为 69 READBACK_VERIFIED、10 NO_GAP、1 PUBLICATION_VERIFIED_READONLY。维护证据见 maintenance-complete.json、stopped-unit-publication-readback.json、independent-data-review.md；失败和未执行初版计划均保留。

四周期逐物理合约完整生命周期 prefix 各 20 owner / 239 contract-months，通过原生 expected closure 和独立 Decimal 200 精度重聚合：

| 周期 | 独立逐值比较物理 Bar | 每候选原生输入项 | 最终 seq | first_computed_through UTC |
| --- | ---: | ---: | ---: | --- |
| 5m | 483918 | 483937 | 1892 | 2023-01-04 13:30 |
| 15m | 161306 | 161325 | 632 | 2023-01-04 13:30 |
| 30m | 82867 | 82886 | 325 | 2023-01-05 13:30 |
| 60m | 48018 | 48037 | 189 | 2023-01-11 07:00 |

总计 776109 物理 Bar 的 OHLCV/OI/turnover/time 与同合约 Canonical 1m、Session `(start,end]` 一致。原生输入项另含 19 个换月边界，不冒充物理 Bar。AG 自身夜盘/跨午夜/周末、30m 15分钟尾及60m 15/30分钟尾、19次换月和无 owner 重入证据见 futures-boundaries.json。

## 候选身份与覆盖

八个原生构建步骤正常 exit 0，12 native report 均 completed；没有资产构建中断、未知提交或重试。候选 schema `newow_intraday_pilot_20260927` 中 12 资产全部 READY、enabled=false、activation_generation=0。独立核对 native plan/report/attempt、公式/profile/model、stored manifest/source digest、checkpoint/index/seq/revision/snapshot，以及四个融合资产对最终两基础流的依赖。

八条基础流 availability 为 FULL、各20 VALID interval、unavailable_days=[]；融合绑定最终基础依赖，不虚称其 summary 有独立 FULL 字段。全部12资产 complete_window_proven=false，computed_through=`2026-09-24T07:00:00+00:00`，first_computed 如上。FULL 不代替窗口首日输出或全窗收益证明。全部API/browser后最终12 stored_state逐字段与验收前一致，仍disabled/generation0。证据见 source-assets-final-v5.json、coverage-expected.json、review-assets-independent.json、final-asset-readback.json。

## API、Chrome 与独立审核

冻结工作区只读 API 8012 / Web 5178 实际 identity SHA/as_of/realtime=false 通过，product-capabilities v27 仅 AG。API12组合 READY、较早窗口12 PASS；错误周期 snapshot 两次409，fresh snapshot chart/reference同身份恢复通过。

临时候选入口由任务helper run_preview.py启动：分钟仅读取隔离schema中的persisted disabled资产，缺失时不回退；D1/W1每请求沿用当前正式配置的原生legacy reader。数据库default_transaction_read_only=on；此周期分派仅用于本项验收，未修改产品源码或正式服务配置。

专属 headed Chrome `ag-minute-closeout` 实际功能12/12，78 PASS / 6有据同日分页 N/A；主图、记录请求/DOM IDs、辅助、切周期和恢复分开核对。真实pending请求取消、0.2538秒客户端AbortError和5m恢复通过。较早视口12/12的真实price/markers、5次稳定viewport采样、active请求为0和topprice固定检查通过。

12组 fresh 完整CLOSED曲线立即绑定自身GET、section/window/token/source generation、原完整身份集合及全部坐标；独立审核逐值核对33687 CLOSED IDs、33711 SVG点与Decimal累计值。六组D1/W1回归33 PASS / 3原生趋势转折WARMING；全窗CLOSED数量按 D1趋势/震荡/融合、W1趋势/震荡/融合为65/24/73/6/2/9，全部曲线点独立复核通过。AG自身Calendar确认9月25–27日非交易日、最后交易日9月24；native完成周as_of和实际reference_cutoff=`2026-09-24T07:00:00Z`分别保留并绑定，不借其他品种截点。

61张原PNG全部逐张原尺寸独立查看：功能主图/曲线24、取消恢复1、较早12、日周12、完整曲线12。无 Confirmed Issue。图片身份裁剪、hover局部遮挡及明细表未全入视口等可见范围限制保留；记录分页与全部ID的验收依赖实际DOM/响应，不把未见表格虚称视觉通过。六份visual-review结果与独立数值 independent-acceptance-audit.json 的实际PASS各自保存，不以截图替代算术或请求事实。

较早视口保留非阻断 Risk / Needs Verification：本次AG原图与请求证明主图跨窗口累积，MACD仅覆盖最后接受的有界窗口；冻结useNewowProduct/Workspace与newow-product-reference-trading exact accepted window合同一致。因此只关闭更早price/markers/topprice检查，跨窗口全段辅助覆盖未验收，不改合同或顺手扩实现。

## 实际验证与收尾

使用原 quant-api venv；产品导入绑定冻结工作区。下列 `python -m pytest` 均实际 exit 0，路径以本仓库根为基准：

- `outputs/ag-minute-closeout-20260929/test_scope.py -q`：14 passed（scope-tests.txt）。
- `outputs/ag-minute-closeout-20260929/api-v5/test_coverage.py -q`：6 passed（final-coverage-negative-tests.txt）。
- `outputs/ag-minute-closeout-20260929/browser/test_record_binding.py -q`：3 passed（final-record-binding-tests.txt）。
- `outputs/ag-minute-closeout-20260929/test_complete_curve_binding.py -q`：41 passed（final-complete-curve-binding-tests.txt）。

共64定向测试；原生aggregation/Session/reference interruption边界回归58 passed（native-boundary-tests.txt）。verify_assets_only.py、verify_api_only.py、verify_browser_only.py和final_asset_readback.py实际exit0；独立review_offline_maintenance.py、四频review_offline_aggregation.py、review_assets_independent.py及independent_acceptance_audit.py --saved实际exit0/PASS。

早期合并pytest调用被根conftest导入guard拒绝、helper准备时误启动的专属CLI及独立补充coverage断言误期望12行等失败原输出保留；修正调用/检查合同后验证通过，不涉及数据或资产重跑。独立审核没有新增GET、Browser、DB、RQData或production写入。

临时API/Web精确PID/cwd/listener确认后退出，8012/5178无监听、原PID不存在，专属Chrome关闭；resource-cleanup-readback.json实际PASS。正式分钟开放、main/tag/release、Runtime/worker/Scope/audience/通知/账户未切换，auto_order=false保持。complete_window_proven=false、持有过程、deep MACD因果专测、日周较早窗口和跨窗口全段aux仍未验收；未声明OOS、可执行收益或账户收益。

验收结论：**允许集成 develop**。唯一最小下一步：等待owner交办 P7-10 NI；本轮没有启动NI或其他品种。
