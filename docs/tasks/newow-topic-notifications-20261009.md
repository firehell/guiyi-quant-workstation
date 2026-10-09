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
