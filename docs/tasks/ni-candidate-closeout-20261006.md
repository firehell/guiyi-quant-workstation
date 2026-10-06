# NI 镍历史候选恢复闭环（2026-10-06启动，2026-10-07验收）

状态：CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12。允许集成 develop。

代码冻结 `03099ce8ca10dd884a2bd227c9edf059ae7a286a`，独立 `codex/ni-candidate-closeout` worktree。仅三个文档改动，无生产源码修改，不重复既有整体验证。历史窗口2023-01-01到2026-09-24，as_of=2026-09-24T07:00:00.000001+00:00，41个物理owner；1m仅聚合，候选为5m/15m/30m/60m×趋势/震荡/双策略。

## 精确恢复边界

原失败证据从清理归档读取，0完成/1部分失败/163未尝试，原attempt PENDING/retry_allowed=false。旧NI2302/1m/2022-09响应未保存，原根因保持UNKNOWN，不复用原attempt。525原分区到539部分提交分区的全部旧immutable bytes保留。5个NI2611/2026-09既有active扩展保留旧Bar且新增端点在旧cutoff之后；producer UNKNOWN，不归因于本任务。新计划绑定当前1836文件前像。

新精确诊断NI2302/1m/2022-09：9525行原始响应先封存，3条turnover超18位小数，真实ArrowInvalid复现；按已确定的 `rqdata-turnover-truncate-18-v1` ROUND_DOWN处理后任务scratch逐字段读回通过，整数、其他字段和端点不变。诊断1次外部请求、0生产写入；只证明当前响应，不反推旧响应。

冻结新forward计划SHA `4ed549c004734b078cd6d7412cce2a476217453634d1abfc98285654f6f874e4`，单次164单元=157读回通过+7无缺口。407 native源请求中首次精确复用诊断一次，forward新增外部406次，加诊断实际共407次；1703派生目标、9条成交额截断。逐unit前像、锁、quota、旧Bar和原子提交守卫通过，无生产失败重试。overall theoretical budget/completion_guaranteed=false保留，实际完成依赖逐单元回执，不改预算结论。

## 实际验收

- 当前1836→3756文件，1920新增、190扩展；95303旧Bar、1072日周文件与Catalog保持。
- 原始407源分区3532965行逐字段等于Canonical，整数和其余字段不变；独立Decimal200/Session `(start,end]`核对41owner、每频491物理月：5m857421、15m285807、30m147576、60m83133，共1373937Bar。
- 12个精确native plan/apply串行完成，保存态均READY、disabled、generation=0，8基础coverage FULL；四组fusion的8条source_dependencies边精确绑定base stream/revision/seq/digest/snapshot。
- 原生4GET预检通过；API12组合、152GET全部HTTP200。API结束后专属Chrome一次19场49原图，无重采，原60/65/110门禁不变。
- native index/audit唯一执行通过，原状态NUMERICAL_PASS_VISUAL_PENDING原样保留；独立18完整数值场28558笔CLOSED及28594 SVG点通过，cancel原生409及fresh恢复通过，独立49原图逐张实际视觉审查通过。
- 精确任务API PID35076/Web PID35195两次完整cmd/cwd/监听校验后SIGTERM；Chrome `ni-candidate`关闭。末轮仅12保存态与资源读回：同revision/seq、disabled/generation0，8012/5178 free，锁granted/waiting0，source_prefix_revalidated=false。

## 实际命令与局部修正

Python固定本task services/quant-api、packages/quant-core及根目录PYTHONPATH，使用既有 `.venv/bin/python`；配置由既有安全加载器使用，未输出凭据。

- `diagnostic_source_once.py --apply --expected-plan-sha256 77c5ddd82b29a25ce18b484c78817e7413278cd50b0ba54d6d849229e943cde1`：exit0。
- `forward_campaign.py --apply --expected-plan-sha256 4ed549c004734b078cd6d7412cce2a476217453634d1abfc98285654f6f874e4`：exit0。
- `seven_frequency_snapshot_readonly.py --output-name seven-frequency-after.json`宿主唯一实际扫描、`source_prebuild.py`、四份`aggregation_full_prefix_final.py`：exit0。
- `independent_root_preservation.py`、`independent_raw_source.py`、`independent_root_full_prefix.py`：各一次exit0。
- `build_assets_once.py`、`final_asset_readback.py`、`coverage_expected.py`：exit0。
- `api/readback.py --execute`、`acceptance/capture_once.py`、native `index/audit`、`independent_numeric.py`、`targeted_exit_readback.py`：各一次exit0。

定向helper验证：runner21tests、offline8tests/15subtests、capture guard13正反例通过；冻结诊断/forward/cache/baseline适配与实际数据/资产/视觉/闭环独审通过。未重跑无改动生产模块、全量Web或其他品种。

只读wrapper首snapshot因沙箱本机DB连接OperationalError在扫描前停止，原log保留；宿主同命令实际扫描通过。source工具首读不存在的铜模板dependency-readback在查询前退出，改为真实已封存NI baseline.saved_streams后定向执行通过并独审，未制造第二份基线。旧boundary准备期两个不适用假设纠正后仅实际一次保留验证通过，失败日志保留。浏览器准备时existing wrapper保护断言在写入前退出，随后仅加入已完成12/152 API守卫。上述均非生产维护重试。

最终独审 `independent-final-closeout-review.json`：REVIEW_COMPLETE_CANDIDATE_CLOSED，SHA `d973705b2bb51b289e558c67628536af38dc5834aee8dbf2f871dc6b736726fe`。
证据根：`.worktrees/ni-candidate-closeout/outputs/ni-candidate-closeout-20261006/`；原失败归档：`/Volumes/扩展盘/guiyi-quant-evidence/develop-cleanup-20261004-203824/ni-minute-closeout-20260929/`。

## 保留边界与下一步

历史候选当前53/60，正式45/60；NI仍属P7-10，原13/21分母不变。W1真实44/120副图预热及15/1/17 CLOSED、密集标签/较早副图短段/Tooltip与视口裁切、非严格cold性能局限保留。页面参考page_parity=true/executable=false，不作为OOS或因果执行证据。旧响应根因UNKNOWN与既有NI2611扩展producer UNKNOWN保持。

本任务未改变正式Scope、release、Runtime、通知、账户或交易。候选未启用，无需回滚已验收数据；保留immutable与所有attempt证据，不删除或覆盖。下一品种PB铅，依原生现场与额度生成新精确计划；不复用失败attempt或盲重试。
