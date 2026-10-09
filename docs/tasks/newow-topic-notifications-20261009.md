# Newow 四策略三周期 Topic 推送

Owner 2026-10-09 明确交办开启趋势、震荡、双策略、主升浪三周期推送到既有 Topic 四人，
并确认只推送建仓、减仓、清仓等动作。三周期沿用当前 1w/1d/60m，60 operational products。

实施基线为现役 v1.14.8@3e1838e60，独立任务树，不夹带 develop 尚未发布的公式及视觉改动。
任务包含必要 migration、发布及 Runtime 切换；只消费启用后新完成且新 observed 的动作，不补发历史。
通知独立于 Reference Trading，使用既有 secure PushPlus transport/Topic，先提交 one-shot claim，
成功仅声明 provider accepted，失败/未知不重试。网络调用置于独立线程。

验证：定向默认关闭、时间边界、12组合、动作/提示分离、身份去重、并发 claim、失败/未知及重启；
0050 additive schema dry-run 与隔离 PostgreSQL；独立 Review；发布 exact identity 及生产 readback。

恢复：通过 policy disabled 停止后续发送；不删除既有记录，不移动 tag，不重放未确认请求。
0050 只创建通知 policy/delivery 表，保留旧数据和旧 schema。自然信号及 Topic 成员实际收到仍需独立 evidence。

## 已完成的源码验证

100项通知/worker/forward/transport/config相关测试通过，真实隔离 PostgreSQL 的0050及并发4项通过。
Reference worker安装定向9项、Alert安装相关17项通过。另两项Market安装测试在本版与未改v1.14.8
均因当前non_trading_interval路径失败，已复现为基线时间依赖，不以本次改动造成解释，不改生产门禁。
Web typecheck/build/topology通过，uv lock offline check通过，Ruff、OpenSpec11/11、secret0、diff通过。
独立Review结论允许集成develop，未发现本版Confirmed Issue。

PG首次实跑发现psycopg rowcount不可靠，修正为INSERT RETURNING确认claim；复跑4项通过。
生产只读preflight实际核实720路enabled/READY，三策略与fusion两种真实payload字段适配；
主升浪CLEAR NO_ELIGIBLE_ENTRY仍为正式动作，不以参考交易配对资格过滤。
现有transport唯一Topic配置结构及安全权限通过；无群成员查询凭据，四人数量未独立验收。

## 实际发布与启用

PR422已合并main@130140a7b6f7cf8ae879c3ac097f4ef699bb441e，annotated v1.14.9与GitHub Release一致；
develop已集成，未把develop尚未发布的视觉和公式改动带入Runtime。发布树独立100回归通过，两个本地editable
实际import绑定发布树，57第三方依赖版本与v1.14.8相同。

生产0050写前只读schema0049/720READY、schema-only快照与dry-run通过；实际迁移只新增通知两表，
读回schema0050、policy0/delivery0/defaultoff。随后现有9服务切换：API/Web200，loaded root/commit matched。
Market安装第一次在guard阶段阻止（旧树未自然盘后运行，既有锁目录缺失），用标准after_market_recovery_guard
初始化精确互斥锁后继续；没有维护attempt、下载、回填或status造假，retained failure历史字节不变。

上海时间2026-10-09 21:00:51启用newow_actions_v1，现场及独立只读DB读回enabled=true、products60、
四策略×三频720路、Topic hash匹配，worker running且通知tick错误0，delivery为空。
自然信号provider accepted与四人实际收到均未验收；整体health仅保留既有盘后retained failure，不能宣称Runtime Ready。
证据目录：`output/newow-topic-notifications-20261009/`，含迁移preimage/dry-run/after与activation readback及逐阶段安装日志。

停止推送（保留所有claim）：现役secure环境下执行
`python -m app.notifications.cli disable`；重新enable使用新的边界，不重放历史。status只读不输出Topic或provider流水号。
最小下一步：等待启用后的首个自然BUILD/CLEAR，再核对one-shot provider结果与Topic成员收到；不增加定时监控或测试广播。
