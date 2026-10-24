# HTDY 60m 第一版离线执行规则交付

Owner 已交办实施 [交易规则](../HTDY_SIMNOW_V1.md)。基线 `29d0803a3784f0081f9bf72966d504764ddc509a`；
最终数值/规则候选 `a9d6dd3f855006757e39d916ce59daf311bff591`。
任务只增加离线政策、显式输入适配和文档，不改变现役公式、Alert、参考收益、Runtime、Scope或生产数据。

## 实际验证

新增定向：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/htdy_execution services/quant-api/tests/test_htdy_execution_signal.py
```

最终47 passed；覆盖方向/一手/反手、重绘、首启、错过信号、订单/Fill幂等、冲突、休市、资金准入、
换月、未知结果、取消/成交交错、跨品种迟到Fill、完整恢复与checkpoint。新增故障回归均先实际复现失败再修正。
既有HTDY基线23 passed。Ruff、mypy两源码、OpenSpec reference-trading strict及diff检查通过；secret scan零发现。

扩展回归（GUIYI_LOG_DIR指向独占0700临时目录，独立数据库环境变量显式置空）：

```sh
PYTHONDONTWRITEBYTECODE=1 GUIYI_LOG_DIR=/private/tmp/guiyi-htdy-test-logs GUIYI_ISOLATED_MIGRATION_DATABASE_URL='' GUIYI_ISOLATED_PAPER_DATABASE_URL='' PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider tests/unit/htdy_execution tests/unit/paper services/quant-api/tests/test_htdy_execution_signal.py services/quant-api/tests/test_htdy_production_kernel_policy.py services/quant-api/tests/reference_trading services/quant-api/tests/test_alert_evaluator.py services/quant-api/tests/test_alert_service.py
```

结果1038 passed、81 skipped、2 failed。跳过项依赖独立环境，不计为通过；以下两项是精确原基线已存在的苏冰夹具缺陷：

- `test_subing_signal_window_requires_current_source_proof_before_saved_points`
- `test_subing_signal_source_change_during_read_rejects_even_unchanged_visible_metadata`

共同错误为 `SavedSignals` 缺少 `trades`。已从exact基线git archive到独立临时目录，复跑
`services/quant-api/tests/reference_trading/test_formal_history_authority.py`，原样2 failed/7 passed。
没有修改或跳过这两项来制造全绿。初次扩展另两项worker测试因默认日志目录不可写失败，换用独占目录后9项全部通过；
首次mypy默认缓存路径不可写，改用专用临时cache后类型验证通过；未更改应用日志或宿主权限。

## 独立 Review 与结论

按仓库模型路由由Astra High只读独审。已关闭：恢复取消义务被新信号覆盖、取消终态过早释放容量、
初始历史终态恢复、readback前撤单、无法投影的迟到Fill遗漏跨品种撤单；自审另修复冲突信号导致平后误补开。
最终独审固定候选a9d6dd3f，实际47项通过、diff通过，无剩余Confirmed Issue，允许集成develop。

CODE_COMPLETE / TEST_COMPLETE（本任务定向）/ REVIEW_COMPLETE。完整扩展套件仍有上述两项既有失败，
不宣称全量测试通过；它们不归入本次HTDY代码修改。
未发布main/tag、未切换Runtime、未接入账号、未创建真实通知或订单。
唯一后续工作为60m operational品种数据准入；Broker transport、持久化发送及账户总风控仍需后续实现与验收。
