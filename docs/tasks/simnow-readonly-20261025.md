# SimNow 账户只读核验 — 2026-10-25

## 目标与边界

Owner交办在已完成测试环境认证/登录后，接通资金、持仓、委托、成交只读查询。
实现一次性独立CLI，不扩大为正式交易适配器、自动执行、行情源、账本或持续Runtime。
当前开发基线为develop `c8af860c2881493721fe6ebdf8bbda17ff4e8092`；保留既有ignored连接/登录结果，
不修改它们或其他任务。开始时develop已包含v1.16.1；本任务不依赖旧v18运行快照，不执行发布或切换。

## 实现与实际验证

- `scripts/broker/simnow_readonly.py`：固定官方测试前置、Mac SDK四参数登录、隐藏输入、认证/登录各一次；
  四类查询串行、间隔1.1秒，完整收尾后再下一项；两轮逐值对比、身份/交易日/重复/异常保护、Decimal字符串。
- `docs/SIMNOW_READONLY.md`：字段、只读请求白名单、测试环境副本、非原子/非Ledger、输出与恢复边界。
- `tests/unit/simnow_readonly/test_readonly.py`：24项无网络fixture测试通过。
- 实际原生SDK四查询均在未Init、未RegisterFront、无真实凭据状态下返回未连接-1，证明参数绑定匹配，
  不冒充真实查询通过。前序登录结果16:21 `LOGIN_PASSED` 独立保留，本次尚未实际查询账户。
- 独立Review复现保证金非零但无仓/挂单时误报空账户的问题；定向回归先失败后修正通过。
  CurrMargin/FrozenMargin/FrozenCommission非零禁止空账户结论，矛盾事实另列warning。

实际命令：

```sh
/private/tmp/guiyi-simnow-probe-20261025-001/venv/bin/python -I tests/unit/simnow_readonly/test_readonly.py
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/ruff check scripts/broker/simnow_readonly.py tests/unit/simnow_readonly/test_readonly.py
python3 scripts/engineering/secret_scan.py --json
git -c core.fsmonitor=false diff --check
```

结果：24 passed；Ruff通过；secret finding0；diff通过。`.command` 的 `zsh -n` 通过。
Native可选SDK不加入API依赖、没有import到生产服务；不触发无关Web或DB测试。

## 验收与剩余

CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；实际四类账户核验 EXTERNAL_EVIDENCE_PENDING。
用户本地隐藏输入后输出私有文件 `output/simnow-readonly/snapshot-*.json`，必须独立读取此结果才可确认
两轮读取完成、稳定及实际账户状态。代码测试不能代替真实回报。

即使测试环境读取完成，也不证明第一套模拟环境或正式执行账本已核验；
`execution_eligible=false`、`ledger_reconciled=false`、`atomic_snapshot=false`始终保持。
未知或未完成不能当作账户空仓，非零保证金与空仓/无单矛盾应另查。Init/Release无进程级硬截止，
25/15秒是响应等待限制，不能承诺整个进程相同上限。

未读写凭据文件、未保存密码、未改生产配置/Runtime/数据库/行情、未请求订单/撤单/结算确认。
回滚只涉及独立CLI源码；忽略的私有结果不可随源码回滚删除。无需撤销任何生产写入。
