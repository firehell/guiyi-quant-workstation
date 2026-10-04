# 盘后增量问题修复

owner交办“上面定位的问题都修复下，目标是让health为健康”。基线develop `542a5444b`，
任务树`.worktrees/fix-after-market-health`；不重试旧未知提交或禁重试源请求，不改交易阶段、Scope或通知受众。

## 当前结论

代码、独立Review、发布和既有Runtime切换完成；正式 `/api/runtime/health` 两次整体`ok`，
盘后组件`ok/retained`，expected及last_success为2026-09-30。新版本自然盘后尚未发生，不声明`RUNTIME_READY`。
生产数据修复6/8成功；BZ/EG真实源质量失败保持零发布、禁止重试。完整消费者矩阵和自然业务未借由health冒充通过。

发布：候选`f262cf10ff29a5335f451c8848825d574868e30f`，PR #407正常merge，
annotated tag `v1.11.2` peeled commit `35217d5ab2c87b9173306d142ccf9f72285a3ec6`，
GitHub Release非draft/非prerelease；merge源码树与候选相同。运行于exact detached/clean
`.worktrees/release-v1.11.2`，六服务configured/loaded root和commit一致，API版本1.11.2、API/Web HTTP200。

## 定位与实现

- 9/24旧失败为夜盘日历权威缺失；当前metadata恢复链与night authority定向33项通过，
  9/30自然盘后主业务已经真实passed。没有重跑9/24或抹掉历史失败。
- 10/1–4休市skip正确；旧版本success未跨Runtime接续导致missed。
  新增独立`after-market-history.json`，记录原commit、原文件hash和规范化状态hash；
  当前失败、未知、运行中、卡住或无效文件优先，旧成功不能掩盖。历史failure单独保留。
- Market安装从capture、preflight到切换与原失败恢复期间持续持有旧writer同一OS guard，
  避免“取证后旧writer又写入”的竞态；不放宽promotion predicate，不创建新自然status。
- 9/30消费者D1 180/W1 123旧版检查incomplete/budget_exhausted。
  现版audit限定同实例/namespace/精确输入复用真正的
  `CONTRACT_REPLAY_COVERAGE_UNAVAILABLE/REPLAY_PREFIX_MISSING`，保留code/reason/context，
  普通页面请求、取消、其他缺口和基础设施异常不缓存。
- 合法部分planner结果保留unverified及已完成case，不制造warm-up计划。
  修复后AU缺口现场D1 6.918秒、W1 13.574秒，各24/24 section完成；数据缺口仍如实失败。
  此证据不推广为全60消费者性能或验收通过。

原9/30归档源已由另一清理任务移动到
`/Volumes/扩展盘/guiyi-quant-evidence/develop-cleanup-20261004-203824/release-v1.11.0-20260930/retired-v1.10.39/after-market-status.json`。
源commit `653e736f5952146a2ea401634d32a605e7b9a0d5`，原文件SHA
`6ed66b566012bc795ca8c677ab270077abf5f9a9315a218f06066ecf233d988a`。
显式导入dry-run ready后apply retained；原自然current_run/last_run仍null，retained_success公开原始来源。

## 实际验证

任务树执行，`PYTHONPATH=services/quant-api:packages/quant-core`、隔离venv、pytest `-p no:cacheprovider`：

```sh
python -m pytest -q services/quant-api/tests/data_foundation/test_after_market_history.py services/quant-api/tests/test_runtime_health.py services/quant-api/tests/newow/test_after_market_consumer_audit.py services/quant-api/tests/newow/test_product_service.py tests/engineering/test_market_runtime_launchd.py
python -m pytest -q services/quant-api/tests/data_foundation/test_after_market.py services/quant-api/tests/data_foundation/test_runtime_promotion.py services/quant-api/tests/data_foundation/test_runtime_status_authority.py services/quant-api/tests/data_foundation/test_after_market_history.py
python -m pytest -q tests/engineering/test_repository_hygiene.py tests/engineering/test_canonical_consistency.py
pnpm -C apps/quant-web build
```

分别280 passed、159 passed、29 passed；Web typecheck/build/bundle topology通过，发布树冻结重建也通过。
Ruff、OpenSpec strict10项、secret scan零发现、diff检查通过。Mypy所触模块仍有13项基线错误，无新增，未宣称全仓类型检查通过。
独立审查发现的真实异常code匹配、failure后skip、未来日期、retained_at幂等与writer竞态均修正；
最终280项独立回归通过、无未解决Confirmed Issue；真实Python→Bash→Python subprocess证明fd继承、互斥及退出释放。
Alert语义另有27项定向验证通过：旧transport错误仅保留诊断，成功时间已恢复provider_accepted；
当前degraded原因是coverage=unverified，按现行canonical不得伪造覆盖。

## 生产恢复与边界

证据根：`/Volumes/扩展盘/guiyi-quant-evidence/after-market-health-20261004/`。
初次只读清点60当前rank1物理合约×D1/W1：42完整、8纯prefix缺口、10缺失对应已有typed quality facts。
恢复只对8个纯缺口，复用原生weekly recovery逐物理合约`1w`，同合同D1+W1完整闭包。
现场DB `guiyi_quant`、Alembic `20260919_0047`，maintenance可用；下载前账户限额1GiB、已用112413695字节，
预留64MiB预算，Canonical磁盘可用671488663552字节；未执行0048 migration。

| 单元 | 实际源请求 | 发布分区 | 结果 |
|---|---:|---:|---|
| AG2612 | 10 | 20 | passed |
| AU2612 | 11 | 22 | passed |
| BZ2611 | 5 | 0 | RQDATA_ZERO_OHL_INVALID |
| CU2611 | 11 | 22 | passed |
| EC2611 | 5 | 10 | passed |
| EG2611 | 4 | 0 | RQDATA_ZERO_OHL_INVALID |
| MA2611 | 11 | 22 | passed |
| SN2611 | 11 | 22 | passed |

总68个真实exchange-daily源请求，118分区发布，0生产retry。每次失败先停止批次并独立只读核对：
已完成单元replan0，失败单元原plan hash/端点保持、锁0；只有无unit目录/无启动journal且请求不相交的
unattempted单元另做fresh prepare后首次执行。三份prepare SHA分别：
`74435f16e3d89a7707394a405a0db4440f1303c5f946934babdba366c3b8fa0e`、
`3c1ae07027c909bd95e67d7718687c92fe376c2ef2a0c099d838654b935c486a`、
`7216ee95cced1cc9de8dae6275b53e3c4b4d080a5f6b65a74672f2cab9b07730`。

BZ保存源2026-03-27 O/H/L=0、close7618、volume2、turnover455400；
EG保存源2026-02-11 O/H/L=0、close3919、volume1、turnover39000。
两者是真实有成交异常，不属于NO_TRADE；applied0、outcome_unknown=false、retry_allowed=false。
不下载重试、不改阈值、不缩窗、不以插值/rounding或新plan hash绕过。
A2611禁重试源与AL2302/15m旧未知结果未触碰；其余10项typed quality不伪装为普通下载缺口。

最终独立清点`final-current-prefix-inventory.json`：60合约48 raw完整、12 raw blocked，
后者为BZ/EG两个真prefix缺口与10个已有typed quality对应raw缺失。
`final-recovery-independent-readback.json`确认六个恢复合约replan0、1136 D1/240 W1逐周Decimal七字段无差异，
源calls68/saved68、激活118、失败原hash保持、锁0；此次provider0、生产writes0。

最终目标8品种consumer-only只读复查`final-targeted-consumer-readback.json`完成192.001秒，
D1及W1各24 case，所有group预算未耗尽；六个恢复品种各3策略chart READY，BZ/EG各3策略DATA_UNAVAILABLE。
384 section全部已启动：READY225、WARMING33、NOT_APPLICABLE30、DATA_UNAVAILABLE96；无UNSTARTED。
六恢复品种两频各3主图和3参考交易均READY，共72 chart/reference；aux只余原生WARMING或不适用，
96个DATA_UNAVAILABLE全部来自BZ/EG，reason均REPLAY_PREFIX_MISSING，无其他失败。
各case/section原始状态全保留；只证明本次8品种有界检查完成，不能推广到60消费者或自然盘后。
该复查provider0、生产writes0，不调用after-market、不写自然status。

## Runtime与剩余证据

render、原preflight(non_trading_interval/60)、Market三个label、API/Web/log rotate、既有Alert及weekly
原安装器均exit0。历史proof独立保留；休市Live60 CLOSED、heartbeat存在，新版本自然Bar为空。
Alert已启用、两个原收件配置保持；processing ok、provider_accepted、连续失败0，coverage unverified使组件degraded。
weekly仍missed，不参与operational overall；没有人为补跑、ack、replay、补发或新增任务。

旧v1.11.1 detached/clean、配置/loaded/process引用为零，13份`.run`证据和SHA保存到
`retired-v1.11.1/`后非force remove。初次AU和旧完整有界消费者证据保存在`earlier-consumer-probes/`，
旧完整probe用错误异常code缓存候选，明确不能证明最终性能；所有失败原始证据保留。
任务树自身4个probe与归档SHA一致后移除，普通Git task worktree及已合并本地/远端分支非force清理；
只保留最新正式发布树，未清理其他任务树。

最小下一步：对下一个自然交易日完成Live/Alert覆盖及盘后消费者验收；BZ/EG需合格源事实与安全恢复证明，
现有禁重试合同保持，不能因整体health为ok声称数据全部完成。
