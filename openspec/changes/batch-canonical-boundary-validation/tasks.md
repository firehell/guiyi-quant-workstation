## 1. 基线与真实组合回归（RED）

- [x] 1.1 检查实施时最新 develop、工作区和 closeout 修复状态；从包含所需依赖的干净基线开展。不得覆盖 `closeout_binding.py` 或其测试中其他任务修改。
- [x] 1.2 阅读 `canonical-market-storage`、`docs/DATA_CENTER.md` 及本 design；枚举 `valid_boundary`、`boundary_validator` 的所有源码/测试调用和 closeout 身份检查，冻结本次修改范围。
- [x] 1.3 在 `services/quant-api/tests/data_foundation/test_storage.py`、`test_calendar_authority.py` 或 `test_composition.py` 的合适现有夹具上，使用真实 DatabaseCoverageSource 注入 store，添加 SQL 计数回归，记录原实现 1/5/60 根的线性增长失败。publish 与 readback 分开测量。
- [x] 1.4 添加七周期/夜盘/短尾 Bar/W1 跨月/错误 trading_day/缺失事实/lifecycle/warm-up/稀疏日期/history floor 语义矩阵，保留既有测试，不用省略 validator 的夹具代替正式组合。

## 2. 一致替换内部合同（GREEN）

- [x] 2.1 在 `services/quant-api/app/market_data/coverage_source.py` 实现一次调用局部的 `valid_boundaries`，复用 endpoint pairs 与 SessionWindowBatch；批量读取所需事实，删除 scalar 正式入口，不加跨调用缓存。
- [x] 2.2 在 `services/quant-api/app/market_data/storage.py` 将 callback 类型改为 PartitionBoundaryValidator，保留逐 Bar 结构检查并在其后一次调用 batch callback；维持其余发布/读取和错误处理。
- [x] 2.3 在 `services/quant-api/app/market_data/composition.py` 更新注入；在 `closeout_binding.py` 精确更新同实例 bound-method 断言。同步更新测试，验证 None/旧 scalar/错误 coverage 或 session 拒绝，不改 closeout 其他业务行为。
- [x] 2.4 更新所有直接测试调用与 callback fixture；搜索确认无 active scalar 调用残留。增加独立验证间权威事实变化回归，确保没有跨调用缓存。

## 3. 验收与交付

- [x] 3.1 执行以下隔离定向测试，记录查询数与语义结果；失败先修正，不通过扩大豁免或放宽边界获得通过。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -p no:cacheprovider -q -m 'not isolated_postgresql and not manual_acceptance' services/quant-api/tests/data_foundation/test_storage.py services/quant-api/tests/data_foundation/test_calendar_authority.py services/quant-api/tests/data_foundation/test_composition.py services/quant-api/tests/data_foundation/test_closeout_binding.py services/quant-api/tests/data_foundation/test_daily_maintenance.py
```

- [x] 3.2 按 `TESTING.md` 扩展到 data_foundation 隔离模块回归及必要 lint，验证 maintenance/composition/strict-read 连通性；不连接 production PostgreSQL、Redis 或 RQData。
- [x] 3.3 独立 Review 重点核对范围等价、错误传播、query count、closeout 精确来源绑定与新旧 callback 同步替换；完成 OpenSpec、diff、secret 检查。
- [x] 3.4 交付实际命令、结果及前后查询数；实现验收后再按仓库流程同步规范和集成 develop。代码完成不等于真实运行提速已验收，不执行数据写入、closeout apply 或 Runtime promotion。

实施验证：定向 269 passed；data_foundation 1285 passed / 12 skipped / 16 deselected；全量 Ruff、四个改动源码的定向 Mypy 及独立 Spec/Quality Review 通过。真实 store publish/readback 的 SELECT 次数在 1/5/60 根 × 1/3 日下分别固定为 continuous 5/5、contract 6/6。初次全量 Mypy 发现 `domain.py`、`bounded_metadata.py` 两个未改文件的 12 项基线错误；已按 owner 后续要求修复，全量 154 个源码文件通过。

最终整分支 Spec/Standards Review 已通过，无新增发现。owner 本轮明确要求先关闭两文件 Mypy 基线错误再集成 develop；12 项类型错误已关闭，全量 Mypy 154 个源码文件通过。两项已确认的浏览器基线失败仍为独立未关闭 Gate，不声明完整浏览器验收通过。补修后的完整后端 3248 passed / 16 skipped / 31 deselected，独立 Spec/Standards Review 无 P0–P3 发现；已按 owner 要求将源码提交 `17718f126` 集成 develop。验收边界见 `STATUS.md` 的三项修复候选记录。
