# Alert 状态与 HTDY 60m 参考记录收敛

Owner 已交办完整实现、验证、发布和闭市切换。基线 develop `72bf8f3`；现场 v1.16.30/gen36。
本任务不启用 SimNow、不改变公式/推送受众/30 秒时效，不补历史或补发。

## 验收与实施

1. Alert 合法暖机是未就绪而非计算失败；不制造成功水位。v2 coverage 兼容 v1，重启后的无新输入、
   真正滞后和未验证分别保留；未决失败不能被新日期或重启清除。
2. HTDY `htdy_first_seen_reverse_close_v1` / `latest_only_32_v1` 仅接受 operational 60 品种×60m。
   buy 开多、sell 开空，反向先平后开，同向不加仓；Bar close、零费用/滑点的页面参考，不是 Fill。
   每条输入绑定持久原件、32 根窗口和 hash；已有候选 15m 不自动扩 Scope。
3. 一次事务完成全部启用种子/activation/receipt，共同未来起点、空参考仓位。旧 Event 不补配交易，
   原件/动作/交易/checkpoint 通过原生事务和稳定关联验证；未知提交只读核对，不盲重试。
4. 定向及隔离 PostgreSQL/Redis 验证后独立 Review；再集成、向前发布、权威闭市窗口原生切换，
   保留 10 秒收尾预算与唯一发布树。自然无信号保持待验收，不人为构造信号或真实测试发送。

普通 transport 失败独立保留时间、错误类型和次数，不判定策略故障；计算、输入、持久化和未知提交仍报错。

## 实际验证

开发阶段验证：Reference 非 PG 回归 1208 passed / 10 skipped（后者非验收通过）；
HTDY SQLite 与 PG 原子启用、信号/交易、提交未知定向通过，真实隔离 Redis Inbox 协议 12 passed。
Web type/build、离线 uv lock、12 项 OpenSpec、secret scan 0、定向 Ruff/Mypy 通过。
扩大验证中的历史 codec 测试改用真实 partial/resume 报告验证 pending 存储，保持既有同单元 advance/rebuild；
handover 旧 fixture 补齐已存在的 retry/health 状态，原件失败仍不 ACK，未修改生产处理逻辑。

真实 Canonical 60/60×32 根 60m 冻结完成，7 路跨物理合约。v30 与候选独立进程计算的指标、信号、动作、
交易、收益、transition 和 checkpoint 差异全部 0。私有对照 `output/alert-htdy-20261028/htdy-60m-offline-comparison-v2.json`，
SHA256 `e559b9a1ab19044d5e4708d2440af1c836db7f052103ab32eef82f21046fcd11`。
这是离线 Canonical 对照，`first_seen_proven=false`，不产生自然信号、参考交易或通知。

独立 Review 确认并修复启用时钟 TOCTOU：取锁后、逐路及最终 flush 后按单调时钟重新校验，起点保留 10 秒余量，
PG statement_timeout 5 秒；SQLite 11/PG 9 项通过，Review 已复核关闭。
Review 中的分钟连续暖机进度、未决覆盖写失败跨日恢复均已修复并独立复核关闭。
分钟暖机以带原件 ID 的连续 attempted cutoff 与同代际 ACK 证明，不使用成功水位；下一真实未处理端点仍可报滞后。
诊断持久化失败保留 pending，在后续处理/heartbeat 先写成功，不重试 Event 或 transport。
history 仅输出当前 warming 路由，整体最多 128 条；300 route 场景 journal 53,366 bytes，缺证明保持未验证。
最终 native handover/cohort 299 passed，真实 PG HTDY 13 passed，Web 定向 10 passed；真实 Redis 覆盖/游标/重启额外 1 passed。
版本入口为 1.16.31；并行 develop 研究提交已保留，不覆盖或回滚其他任务工作。

一次性隔离依赖：`guiyi-alert-htdy-pg-20261028`（15486、tmpfs）、
`guiyi-alert-htdy-redis-20261028`（16389、tmpfs、无持久化）。不使用生产依赖进行破坏性测试。

## 实际发布与现场验收

实现 `a59343743` 集成 develop；保留并行研究提交，收敛 main 较早文档/版本冲突（应用源码无新增差异）。
PR534 正式发布 annotated tag/Release **v1.16.31**，exact `dfa9b5aa7920522987ad7f1baf958970e79351c7`。
正式发布树独立 uv/pnpm 离线依赖、Web type/build/topology 通过，600KiB旧chunk警告非本轮新增。

原生计划 `2cb9255fc68f31e59d8f8f9ffde7a62c6c163bed3ff6dd0f58e8370ff2d07f98` 一次 apply 返回 switched，
十服务统一 **v1.16.31/gen37**。六 owner active：Live42519、Alert42525、Reference42531、API42538、Web42545、Feed42707。
完整纯预热、原10秒收尾、旧进程退出、安装/CAS、消费者/Feed启动与原日历恢复均按原生 Gate 完成；未强杀或扩时。

随后一次生产事务启用 HTDY operational 60 品种×60m：计划
`2bce2978905dee6c468818ca0868d98b048cf7f0fb5c821adc29fa02547c6b78`，全部 seed/activation/receipt 独立回读通过。
共同记录起点 **2026-10-28 20:45:24.063786 北京时间**；空参考仓位、零 capture/历史交易回填。
现有1080路加HTDY60路，共1140路。原有forward checkpoint摘要
`c80086a8d12477ce3ea4db4f759f8351d32c83256444bd0631d6800395dc62d9`、3天原件游标及Event计数在切换和启用前后完全相同。
Inbox pending/blocked/UNKNOWN/dependency_wait 均0，completed8302；旧339 BLOCKED与2618恢复原件保留。

新版本 Alert：processing ok，113路ok、7路warming_up、300路unverified等待新分钟输入；推送历史保持。
global仍degraded，不能把重启后缺失的自然覆盖或 provider accepted 当作全业务/手机收到验收。
真实Web RB2701/60m与正式HTTP唯一HTDY流/收益面板正常，显示零留存交易，不以历史重算补齐。
夜盘新输入、计算水位与自然新信号/参考交易仍待实际发生；不新增自动化、不启用SimNow、不重发通知。

私有完整前后像、原生计划、HTDY receipt、冻结对照和实际Web读回位于 `output/alert-htdy-20261028/`（0600）。
测试容器已正常停止并移除，不影响5432/6379生产依赖。
旧v30原生退役计划 `e0241c9b22c7a4d782aab977d1a374a94a879df3ec513a45546d99b42d89d88f` 已通过；63份原件/6个标记已封存至稳定私有目录，精确non-force清理完成。
唯一发布树为 `release-v1.16.31`；清理后部署/恢复guard通过，20:53独立HTTP/身份/owner/游标/checkpoint/Event读回通过。
正式HTDY Events709、苏冰3942；新增参考流60路仍为空seed，无人为信号/交易/通知。

## 实际命令与结论

以下命令均在本任务工作树用锁定解释器及对应 `PYTHONPATH=services/quant-api:packages/quant-core` 执行：

- `python -m pytest -q -p no:cacheprovider -m 'not isolated_postgresql' services/quant-api/tests/reference_trading`：1208 passed、10 skipped，skipped不计通过。
- `python -m pytest -q -p no:cacheprovider services/quant-api/tests/test_alert_runtime.py services/quant-api/tests/test_runtime_health.py services/quant-api/tests/test_handover_consumers.py`：最终213 passed。
- `python -m pytest ... test_runtime_handover.py test_runtime_handover_entry.py test_runtime_cohort*.py test_handover_consumers.py`：实际显式列出对应10文件，299 passed。
- `python -m pytest -m isolated_postgresql ...test_htdy_60m_persistence.py ...test_htdy_activation.py`：15486专用PG，13 passed。
- `python -m pytest ...test_inbox_forward_integration.py ...test_inbox_protocol.py ...test_inbox_runtime.py ...test_inbox_wake.py`：16389隔离Redis，12 passed。
- `python -m pytest ...test_alert_coverage_redis.py`：隔离DB15，1 passed；未清理生产Redis。
- Web定向 `node --test --test-concurrency=1`：10 passed；正式树 `pnpm install --offline --frozen-lockfile --ignore-scripts`、`pnpm build`、`uv sync --offline --frozen`通过。
- `uv lock --check --offline --project services/quant-api`、定向Ruff/Mypy、12项OpenSpec严格校验、secret scan 0及diff检查通过。

工程实现、Review、develop集成、正式发布、原生切换、HTDY启用和唯一发布树收敛完成。
唯一下一步：下一自然交易时段核对新输入、水位与自然HTDY信号/参考交易；未发生前不宣称自然验收完成，不自动安排监控。
