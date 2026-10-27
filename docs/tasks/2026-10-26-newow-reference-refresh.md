# 牛哇参考资产更新与收益展示恢复

owner交办：更新受影响的牛哇参考资产至最新已确认来源，恢复参考收益展示。
完成日期：2026-10-27。范围为既有canonical历史Reference资产，不扩展forward Scope。

## 结果

最终独立canonical身份、revision状态、MDS末端与保存水位扫描：1260/1260 current，0 stale、0 blocked。
980路更新的完整来源校验由原生执行协议完成；代表API12项再次触发读时来源校验。
最终全量扫描未对1260路逐路重读全部manifest指纹，不将其表述为完整来源指纹再次复验。
原生刷新控制文件routes为空，全部资产existing_control为空。
本次更新980路：日线200、60分钟240、短分钟540；原已最新280路保持不变。

| 周期 | 既有路数 | 最终已确认末端（北京时间） | 更新路数 |
|---|---:|---|---:|
| 1d | 240 | 2026-10-26 15:00 | 200 |
| 1w | 240 | 2026-10-23 15:00 | 0 |
| 60m | 240 | 2026-10-26 15:00 | 240 |
| 5m | 180 | 2026-10-26 15:00 | 180 |
| 15m | 180 | 2026-10-26 15:00 | 180 |
| 30m | 180 | 2026-10-26 15:00 | 180 |

日/周/60分钟为operational 60品种×趋势/震荡/主升浪/双融合；短分钟为60品种×趋势/震荡/双融合。
不含短分钟主升浪，不纳入非canonical旧身份。`FROZEN_INTRADAY_FREQUENCIES=()`，公共分钟读取主库latest-completed，旧冻结常量不是active Gate。

根因是持久参考资产落后于当前Canonical来源，日线曾停在10/23，短分钟停在10/09，
不能通过忽略input/calendar/session/mapping指纹差异恢复展示。本次按原历史起点更新，短分钟保留各自原始since：522路为2025-09-25，PD/PT共18路为2025-11-27。
源合同、策略公式、参考模型和零成本口径不变；旧revision/batches留存。
未下载行情、未改Canonical、未改Scope或启用状态、未回填实时首次记录、未发送通知、未交易、未切换正式Runtime。

## 执行与恢复

复用build_historical_refresh、原生planner/service、全局刷新控制锁、Canonical维护锁、
exact plan hash、源身份校验、CAS和原子revision发布。每路重新核对canonical identity/since；
日/周/60分钟融合等待三个基底，短分钟融合等待趋势与震荡两个基底到达同一目标末端。
旧pending计划完成后重新读取实际水位，不能仅凭控制项消失判断已最新。

原52条pending保留并按REBUILD_REQUIRED协议恢复。第一阶段440路完成后独立扫描720/720 current。
全主库补充扫描发现540路短分钟落后。短分钟分段完成75、323、134、7、1路，共540路。
每段后重新审计剩余范围；SOURCE_BUSY仅在证明未写入时延期，不抢锁、不盲重试。
后续审计依次为1098 current/142 stale、1252/8、1259/1、1260/0。失败日志保留，未遇未知提交后继续mutation。

默认后台预算不能覆盖完整物理前缀；专用离线预算先为WorkBudget(1,1000000,1800,4096000000)。
AL5m原生估计568004输入/2326544384字节，完整只读计划实际284008输入/72707313字节。
AL5m持久原生plan独立codec回读hash：
`2c1ab4f2157b16ffd08465b6714550c96954b2786e50745232d59ed125a64fa5`。

SC5m原生估计1234424输入/5056200704字节，在规划前超预算而干净停止，control无pending/inflight。
独立Review后仅本次runner预算调整为WorkBudget(1,2000000,1800,8192000000)，
预算进入原生plan hash，估计/实际量/deadline检查均保留，不改Runtime配置。
目标文件名加入budget canonical摘要并逐字段读回，新旧预算目标分别保留。
SC5m原生plan独立codec读回预算与10/26 07:00Z末端一致，hash：
`59b090af7122c3cfa75768bd3523a5e08a743637b50f44a515ffb46dea18651f`。

只在同一路advance/rebuild的同一原生Canonical lease内复用只读MarketData输入，
不跨路缓存、不缓存策略输出、不改变source/CAS/deadline。动态cancel/after_batch/now按borrow绑定；
拒绝嵌套，清理异常不得覆盖原始未知存储错误。独立Review及回调生命周期验证通过。

执行基线5477293046，现场develop后续被其他任务推进；后续Reference改动属于forward inbox，
未修改本次historical planner/service/refresh链。本次交付为真实Reference更新和任务记录。
恢复应先读回保存revision/checkpoint与原生控制状态，再生成精确新计划；不得直接改active指针或删除批次。
最终浏览器辅助指标重试后已正常；截图：`/private/tmp/guiyi-newow-reference-restored-final.png`。

## 实际验证

- `PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest services/quant-api/tests/reference_trading/test_historical_refresh.py -q`：32 passed、2 skipped。
- 同环境test_historical_refresh_priority.py与test_source_identity.py：17 passed。
- 独立Review运行test_history_input_cache.py：8 passed；临时脚本py_compile通过。
- 开发API：AL/AU趋势日线overview/curve/history均200/ready，各921点；AL震荡、AU主升浪日线均三段200/ready。
- 开发API：AL趋势60m三段200/ready，1723点；正式8000的AL趋势日线三段200/ready，921点。
- 最终代表API：AL趋势5m/15m、AL融合30m、AU趋势1d共12项均200/ready，曲线点分别2000/1969/1906/921。
- 浏览器实际显示AL日线曲线、年化5.39%、累计页面参考22.18个百分点、56次参考、当前未闭合参考及历史记录。
- 最终全量审计1260 current、原生控制0；接口和浏览器证据不冒充账户收益、整体Runtime健康或全部页面逐一视觉验收。

本地审计与执行产物在`output/newow-reference-refresh-20261026/`：
`audit-all-final.json`、`audit-all-final.log`、`api-all-final.json`、各段results/log、精确target；
复现脚本为`audit.py`、`apply.py`、`guiyi_newow_maintenance.py`、`guiyi_shared_refresh_components.py`、`api-check.py`。
这些脚本仅为本次维护归档，不新增正式后台任务。
