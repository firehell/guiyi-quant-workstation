# 模拟交易中心 · SimNow 账户观察

`simulation_observer.py` 以一个独立进程绑定一个明确授权的 SimNow 账户。它复用锁定版原生 TD 登录与查询，
将成功资金、持仓、委托和成交读回写入专用 PostgreSQL schema。它跳过默认结算确认，不连接 MD，报撤单入口拒绝调用。
Web API 通过只读事务查询数据库，连接柜台由宿主负责。

仅在获得相应环境和账户的连接授权后，使用私有账户目录与权限 0600 的 JSON。配置字段为
`alias`、`environment`（`SIMNOW_FIRST`）、`account_id`（已登记的钥匙串账户指纹），以及可选的
`deployment`（策略 ID、公式版本、参数 Profile、风险政策与物理合约）。宿主沿用已有 SimNow 第一套前置、
钥匙串凭据加载器和跨宿主账户锁。首次现场验收使用 `--verify`，要求同一连接内两轮四段读回一致，完成或失败后退出。
数据库由操作员显式应用 [simulation_schema.sql](simulation_schema.sql)。写进程使用
`GUIYI_SIMULATION_WRITER_DSN`，API 使用 `GUIYI_SIMULATION_READER_DSN`。两者按相应 schema 使用独立角色权限。

从仓库根执行，环境变量由本机秘密管理注入，目录路径使用实际绝对路径：

```sh
PYTHONPATH="$PWD/services/quant-api" services/newow-vnpy/.venv/bin/python \
    services/newow-vnpy/simulation_observer.py --observe --verify \
    --account-config /absolute/private/account.json --workdir /absolute/private/account-runtime
```

[模拟交易中心合同](../../openspec/specs/simulation-center/spec.md)。

## 火天大有离线执行演练

`simulation_execution.py` 的 `OfflineExecution` 先接受离线双轮柜台结构样本，再收取 HTDY completed 信号与有物理合约证据的执行输入。
它以 PostgreSQL 记录 reducer 命令、风控决定、VeighNa 请求领取和原生结构证据。`prepare()` 返回 `OrderRequest` 或 `CancelRequest`。
`reconcile()` 需要输入已匹配的离线回包和有来源的样本费用；同日快照缺已知委托或成交时保留上一次通过读回。
`realized_trades()` 从可重放账本计算已对账平仓样本损益，统一标记 `OFFLINE_CTP_REHEARSAL`。

测试在一次性空库依序应用 `simulation_schema.sql` 和 `simulation_execution_schema.sql`。使用隔离测试 DSN，
运行 `tests/test_simulation_execution.py` 和 `quant-api/tests/simulation_center/test_execution_store.py`。离线表独立于现有 SimNow 验收数据库。
