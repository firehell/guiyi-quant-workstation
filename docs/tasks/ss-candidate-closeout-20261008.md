# SS 不锈钢历史候选收尾工作记录

2026-10-08：`CANDIDATE_CLOSED / REVIEW_COMPLETE`，12/12。全部数据、候选、API、完整数值、49原图视觉与精确退出通过最终独审，允许集成develop。历史候选59/60、正式分钟范围45/60，剩余PP。

## 本轮身份与范围

代码 `1517ee6ae48b321943c7de115dfdd03a76fbdb82`，SS独立task worktree。固定窗口2023-01-01至2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`；上市日2019-09-25。fresh只读基线为41个物理owner、164维护单元、0候选stream；七频前像1811个文件、294个dataset。1m仅为聚合源，分钟验收范围5m/15m/30m/60m×趋势/震荡/双策略。

SS不在旧21品种队列内，本轮来自owner新的明确交办；不改写原队列分母，不把旧SS维护计划当作新恢复计划。正式分钟范围、Release与Runtime不因本轮研究候选交办而提升。

## 旧 black 证据与两个不同失败边界

原件根 `outputs/newow-intraday-black-20260927`，旧执行代码和报告保留。SS2302与SS2303的attempt、预算和证据性质分别处理，不能套同一根因或重用旧attempt。

SS2302/1m原生计划窗口2022-02-16至2023-01-18，11个目标月份。原attempt PENDING、retry=false，发生ATOMIC_PUBLISH_FAILED但没有result和失败源payload。旧只读报告确认2022-02至07六个月、51360根Bar已提交，2022-08至12五个月未提交，既有2023-01保持。实际请求数UNKNOWN，按原预算保留11次；包装失败阶段不证明底层Arrow、磁盘或其他具体原因。维护前fresh snapshot没有SS2302/1m/2022-08 active分区；这不补造原失败原因，也不推断当前producer。

SS2303/1m原生计划窗口2022-03-16至2023-02-23。实际6次请求，2022-03至07五个月、42060根Bar提交，2022-08为SOURCE_NUMERIC_REPRESENTATION_UNAVAILABLE，既有2023-01/02两分区保持。旧完整批次为38个owner×四周期152单元：1 GLOBAL_STOP（NUMERIC_FAILURE_PARTIAL_COMMIT）＋151 NEW。原直接1m的413次计划预算不表示已经执行；历史charged792由781个已知请求＋SS2302未知保留11组成，不抹去未知收费或重复计算。

旧独立reconciliation实际核6个持久响应、5个已提交月份、2个既有分区和6个剩余targets。其旧结论是在当时无损decimal128(38,18)合同下阻塞，不代替本轮新规则、fresh计划和独立恢复验收。旧失败attempt仍不重试。

## 旧文件保留与 SourceBatch 隔离证明

`recovery/old-boundary-index.json` 将34份旧证据文件精确路径/SHA、旧native physical分区和fresh前像绑定。旧15m/30m/60m source报告同时含派生周期及共享1m依赖，按每条physical.frequency取身份，不把依赖1m错标成页面周期；去重得到431个旧分区版本。

根代理已实际只读执行 `old_boundary_preservation.py`，结果PASS：431个旧分区版本、766756根旧Bar逐字段保持，4个active版本发生过变更但旧字段保持，producer归因UNKNOWN。当前1811文件作为fresh保护边界；1070个D1/W1文件字节保持。旧四频source及部分提交报告不是完整七频after inventory，不声称旧5m/D1/W1全量快照存在。

SS2303第6个失败响应已完整封存为gzip native SourceBatch：顶层batches/requests，batch包含bars、source_key、requested_ends及price_unavailable。这是provider转换后的Canonical Bar证据，不是RQData原始DataFrame，不伪装成raw缓存，也不复制到新provider响应目录。

该响应10695根Bar，端点2022-07-29T13:01Z至2022-08-31T07:00Z；所有请求端点和交易日与旧STARTED记录一致，price_unavailable为空。压缩SHA `71ae6d179c288bb5938d7df083d0cc64fd5bd35b41dcf69d00b54eb17eb1e6f3`，解压内容SHA `a402276beabd55b0ee73e545c1404751d09c33d75f4855888c6a2b78a362f95e`，与SOURCE_DURABLE及原schema rejection绑定。

根代理已实际执行任务内 `normalization_payload_scratch.py`。原始native schema ArrowInvalid复现；仅15行turnover按 `rqdata-turnover-truncate-18-v1` 向零截断至18位，整数及其他字段/端点保持，原生scratch发布与完整读回PASS。生产写入和provider调用均0。该证明不代表生产发布、旧attempt重试或source substitution已通过。

准备期纯函数测试首次4项中3通过、1失败，原因是实际payload.requests为单元素list，而durable marker.requests才为整数1；初次失败记录保留。按真实结构修正并绑定STARTED请求后，仅该失败项重测通过，其余3项未重复。不是生产维护失败。

## 新恢复、数据与候选资产验收

新计划 SHA `f5408a6eecfab8829e15f82e5cdd2539d21a312d204f72cbc6cf4818a31c43e4`，runner SHA `9d0922bf1730af34e41c77cae94c3d83b08d6a09f4fa30fdc583c9ef7475e985`。4项定向保护测试和精确计划独审通过后，根代理唯一串行apply正常exit0：164/164＝158发布后读回＋6原生NO_GAP；413次全新RQData源请求、1718派生目标、142条成交额截断。零旧响应复用、零diagnostic源；旧SS2302未知与SS2303部分提交原件不改写。

整批保守额度估算不保证完成，执行时在锁内外逐单元检查额度和前像；预算与实际调用一致，未触发停止或重试。实际终态独审通过，不冒充资产准入。

维护后七频快照3750文件、294dataset；fresh1811→3750，新增1939、扩展192、删除0。根代理独立保护审计实际exit0：264717条扩展分区旧Bar全部字段保持、1070日周文件和Catalog不变。原始响应独立核对实际exit0：413份新raw、3460905条记录的全部字段/端点/交易日与物理1m一致，142条整数不变。

四周期原生完整前缀报告实际exit0，每频41owner、491物理月；独立Decimal完整重聚合交叉验证已实际通过，5m/15m/30m/60m分别830877/276959/143008/80561根Bar，共1331405根。整体数据独审 `recovery/independent-data-overall-review.json` 为 REVIEW_COMPLETE_ALLOW_SS_CANDIDATE_ASSET_BUILD，SHA `5f46bd5deb8493341dbbdf095b5e356baca3709f49ed962fb426b0bf110be4d7`。

根代理唯一串行构建12候选资产实际exit0：8基础与4融合原生结果全部completed。每周期资产输入另含40个边界点，实际input为830917/276999/143048/80601；不能将资产事件数冒充完整前缀Bar数。逐项冻结计划、完整manifest、41owner、source hash与终态revision/seq已独立核对，末轮fresh保存态为12 READY、enabled=false、activation_generation=0；4融合的8条真实伙伴依赖精确绑定当前基础stream/revision/seq/snapshot/digest。

8基础coverage实际FULL，各41区段且无unavailable days。原生summary的complete_window_proven仍为false，独立coverage不改写该字段。资产最终独审 `recovery/independent-asset-review.json` 为 REVIEW_COMPLETE，SHA `f1967a5aee2a91454a696a163dc7ba2970fa347d8de17eb92b03b0fccccd2cb4`。最终保存态报告source_prefix_revalidated=false，沿用已经封存通过的源前缀证明；不声称末轮重新扫描全部源。

只读API唯一实际execute已exit0，12组合READY、152矩阵请求全部HTTP200，绑定相同SS代码、as_of、源hash与12上游资产。独审 `recovery/independent-api-review.json` 为 REVIEW_COMPLETE_API_COMPACT，SHA `422d386e05202316cc45c258a8553d1364517fe833140032e4200ee07b16237a`。API compact证据不证明完整数组数值、严格冷启动或Chrome视觉；这些仍由实际页面fulltransport及独立审计验证。

## 浏览器、数值与退出验收

API矩阵结束后，唯一Chrome `ss-candidate` 串行采集实际exit0：19/19场、49新原PNG。native index与audit各实际exit0；完整fulltransport逐chunk、nonce、SHA绑定相同candidate，不以compact证明完整数组。原 `NUMERICAL_PASS_VISUAL_PENDING` 保留，视觉结论另由独立报告承载。

任务内 `independent_numeric.py --root outputs/ss-candidate-closeout-20261008/acceptance` 实际exit0：18场完整分钟/日周数值与取消恢复全部通过，31524 CLOSED逐笔参考价/回报/稳定ID、Decimal200累计及31558全部SVG点一致。年化/MDD由真实DTO及像素对应审核，本脚本未另行从头重算两项公式，不扩张其独立计算范围。W1实际CLOSED趋势10、震荡0、双策略12；零交易字段显示“—”，不写0%。native409、实际cancel/短超时/恢复通过；自然TTL和严格冷性能未证明。

49原PNG均实际逐张查看并保留actualview ledger。W1实际44/120 Bar、历史40区段预热；1280视口顶部字段与部分辅助区域裁切、局部tooltip遮挡按实际记载，不冒充所有字段像素可见。OPEN与换月中断浮动未计CLOSED，页面收益不代表因果或账户收益。

Chrome关闭实际exit0；`stop_preview_exact.py --apply`两次验证exact PID/argv/cwd及独占端口后仅向owned API/Web发送SIGTERM，两服务正常按停止信号exit143。任务临时13字节offline npm配置按SHA精确移除exit0；sandbox prepare首失败保留，host实际既有CLI0.1.22版本读回通过，没有安装、修改全局配置或重启采集。

`targeted_exit_readback.py`实际exit0：2专属PID退出、8012/5178端口无listener、维护锁granted/waiting均0，12保存态disabled/generation0和revision/seq保持。末轮只核12保存态，source_prefix_revalidated=false；未重复源前缀全扫描。

## 实际验证与交付边界

- `test_forward_guards.py`：4项定向保护测试通过；`normalization_payload_scratch.py --execute-scratch`：原失败复现及18位scratch发布读回通过。
- `forward_campaign.py --apply`：164/164完成；raw源、旧数据保护和Session全前缀独立检查各实际exit0。
- `build_assets_once.py`：24个plan/apply子命令全部exit0，12候选READY；asset、coverage与API独审通过。
- `api/readback.py --execute`：12 READY/152 HTTP200；native `capture`、`index`、`audit`和独立完整numeric实际exit0；49原图视觉独审完成。
- exact浏览器/服务退出、配置删除与定向exit读回通过。仅检查本轮影响，无重复全量回归。

本轮生产源码、公式、收益合同、正式消费者范围未改。page_parity=true/executable=false；无Release、Runtime、Scope、通知、订单或研究候选晋升。证据根为本worktree `outputs/ss-candidate-closeout-20261008/`，旧原件独立保留。SS为新增补充恢复品种，不改变旧13/21分母。

最终独审 `recovery/independent-final-closeout-review.json` 为 REVIEW_COMPLETE_CANDIDATE_CLOSED，SHA `63d03a0a55a0f1f83de0743903d95337cef55c0465857c1c4c85f709bfbcc573`；视觉报告 SHA `8dd6098eeb680fe7e203d91a8edb03b0e06d303a95ebcf517200dc1682ae661e`，numeric/exit阶段独审 SHA `3593a5328f91274ae31bcdd436be8de45abc3e8fc25da93ea432a2de3ab62ff5`。原工具VISUAL_PENDING不改写。Git交付仅本记录、STATUS与roadmap补充SS段，无生产源码或其他品种改动。

唯一最小下一步：PP历史候选闭环；本轮未执行PP。
