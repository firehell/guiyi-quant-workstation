# 苏冰开发持续模型

`/research/subing-decision` 区分“持续模型”和“历史回放”。持续模型只读取既有 completed ObservationStream，不新增 Market 订阅、Alert Scope、通知、正式 Runtime 或 Broker 操作，始终 `auto_order=false`。历史回放原结果和理论后续开盘执行身份保留。

## 已确认的账户与时间语义

首版只允许焦煤模型账户，独立初始资金10万元。记录实际启动时刻，历史与启动前完成观察只预热；不恢复历史持仓或追补历史动作。

执行身份 `next_completed_1m_close_slip1_actual_knowledge_v1` 使用实际处理时刻作为知识边界。意图只能在知识边界之后的完成1m收盘加不利1tick撮合，继续检查成交量、OHLC、涨跌停、费用、保证金和原保护退出。Fill分别记录决策源Bar、成交源Bar、实际获知/处理时刻和物理合约。日终和下一开盘复核沿用统一候选；开盘价只在首根1m完成后可知，不在开盘价回填成交。

`guiyi_quant.subing_account.AccountEngine` 是批量与增量共用的撮合/账户实现。统一需求、机会窗口、跨日毛浮盈和退出义务仍来自原候选。页面不计算交易规则。旧批量入口保持原约束和身份。

## 持久化与恢复

独立本机PostgreSQL数据库 `guiyi_subing_development` 保存运行身份、不可变事件及可重建状态；隔离测试只用 `guiyi_subing_development_test`。不迁移或写既有生产业务表。每批完成观察的原输入、Session、执行事实、实际获知时刻、模型决策和成交一起提交，事件hash链、期望sequence及单worker advisory lock约束重复/并发。事件不可UPDATE/DELETE/TRUNCATE，运行identity不可改写。

重启从不可变身份和逐事件输入重建全部指标/账户，比较当次决策、Fill和状态hash，再核对最终投影；代码、预热来源、原行情、Session或输入身份不一致则拒绝恢复。提交结果不明先读回，不盲重试。处理失败后的内存对象不能继续使用，必须停止并从已提交事件重建。

完成1m/30m/60m均核对权威Session的下一预期端点；同端点的高周期先处理。缺口或游标过期停止，不假装连续。新交易日通过MDS加载前一完整日线；缺失不沿用旧方向。执行事实必须属于当日、同物理合约，且在处理时刻已可知。

账户已开始后事实中断，保留最后可信估值、固定止损/EMA及已知部分保护义务，暂停新增和撮合，明确要求人工复核，不静默恢复。换月保留旧仓和义务、暂停该品种新增，不用新主力价格退出旧仓，不自动移仓。当前只订阅既有主力流，旧合约处置仍需后续明确方案。

## 操作入口

项目根目录，Python入口使用 `PYTHONPATH=.:services/quant-api:packages/quant-core`：

```sh
# 显式建立隔离开发数据库和项目私有连接文件，不在HTTP请求中建表
services/quant-api/.venv/bin/python scripts/dev/subing_model_setup.py
# 通过既有MDS准备完整物理前缀，显式新目录，读Canonical/Catalog
services/quant-api/.venv/bin/python scripts/research/subing_model_prepare.py --through YYYY-MM-DD --out EXPLICIT_NEW_DIRECTORY
# 首次启动前只读检查；已启动时拒绝重复创建
services/quant-api/.venv/bin/python -m app.subing_model.worker --check-start --prepared EXPLICIT_DIRECTORY
# 首次指定实际启动时刻；--once只处理一轮，供读回/恢复验收
services/quant-api/.venv/bin/python -m app.subing_model.worker --start --prepared EXPLICIT_DIRECTORY --once
# 以后恢复同一run，不重置账户
services/quant-api/.venv/bin/python -m app.subing_model.worker
```

`.run/subing-model-active.json` 保存唯一开发run指针，心跳只表示进程状态；连接文件权限0600，不提交、不打印。无launchd安装或自动重启。停止用当前前台进程Ctrl-C，保留数据库和指针；不能删除指针来绕过恢复失败。

当日执行事实采集使用 `scripts/research/subing_model_facts.py --contract JMxxxx --day YYYY-MM-DD --out EXPLICIT_NEW_DIRECTORY`，上限6次逻辑provider调用、无自动retry；失败保留attempt。成功资产须以绝对路径及SHA256显式登记在 `.run/subing-model-facts-index.json`，形如 `{ "YYYY-MM-DD": { "path": "/absolute/path/jm.json", "sha256": "..." } }`。没有登记且校验通过的当日事实就不撮合；旧费率不能替代。请求不会触发provider下载。

只读 `GET /api/v1/subing-model/status` 返回独立开发投影与新鲜心跳；无active时NOT_STARTED，读取失败503，心跳过期明确停止。API不创建run，不驱动模型。开发Web代理与API须指向同一工作区。

## 14品种观察与归一化候选

固定集合 `jm lc rb sa fg ma ec v pr ta ur sh sc cj`。除JM外只观察，不生成模型账户、手数、收益或组合结果。

本轮归一化研究取截至准备日的最近120根已完成30m ATR14中位数，与JM中位数相除；近轴/极端MACD/止损缓冲分别按原JM的4/17/13乘该比值。它是单次固定尺度研究，未调优，未做tick取整，未平衡乘数、保证金或账户风险，不能直接执行。该快照不随实时行情自动修改参数；其他品种需owner确认候选及逐品种验证后才可启用。完整物理前缀或执行事实不足必须显示不足；已见数据不构成OOS证据。
