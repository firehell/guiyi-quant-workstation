## 1. 基线与回归（RED）

- [x] 1.1 检查实施时 branch、HEAD、dirty state 与本 change 的基线差异；从干净 develop 建立独立任务工作区，保留其他任务修改。阅读 `docs/DATA_CENTER.md` 与本 change spec。
- [x] 1.2 在 `services/quant-api/tests/data_foundation/test_historical_data_manager.py` 添加旧完整 1m → 新数值 refresh 回归，复用 FakeProvider、临时 store 与隔离 Catalog；参数化 continuous/contract × 四种派生周期。运行并记录当前实现的实际失败。
- [x] 1.3 补齐来源失败、quota、commit unknown、独立 family/month，以及“不更新来源的派生可先完成”保护案例；禁止访问生产服务。

## 2. 最小修复（GREEN）

- [x] 2.1 在 `services/quant-api/app/market_data/historical_data_manager.py` 的早期派生循环无条件检查既有 pending minute family/month；复用成功来源发布后的派生入口，不新增第二条 resolver 或重算发布路径。
- [x] 2.2 检查目标移除、failed family、quota 和全局停批分支，保持分区级事务及 partial 语义；运行定向回归直至通过。

定向命令（仓库根目录；只使用测试夹具）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -p no:cacheprovider -q -m 'not isolated_postgresql and not manual_acceptance' services/quant-api/tests/data_foundation/test_historical_data_manager.py services/quant-api/tests/data_foundation/test_daily_maintenance.py services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_catalog_and_service.py
```

## 3. 验收与交付

- [x] 3.1 按 `TESTING.md` 运行本模块必要检查与实际支持的 lint；确认 readback 数值、普通及 streaming 路径均有证据，不把静态推断记录为通过。
- [x] 3.2 独立 Review 本 change 的依赖顺序与失败恢复；检查 diff、secret 及 OpenSpec 一致性，修正反馈后再完成工程集成。
- [x] 3.3 交付实际命令与结果、剩余 Gate、风险和唯一下一步；仅在实现验收后按仓库流程同步规范，不因当前设计就提前更新 STATUS。真实数据修复和 Runtime promotion 必须另行授权。

最终整分支 Spec/Standards Review 已通过，无新增发现。owner 本轮明确要求先关闭两文件 Mypy 基线错误再集成 develop；12 项类型错误已关闭，全量 Mypy 154 个源码文件通过。两项已确认的浏览器基线失败仍为独立未关闭 Gate，不声明完整浏览器验收通过。补修后的完整后端 3248 passed / 16 skipped / 31 deselected，独立 Spec/Standards Review 无 P0–P3 发现；已按 owner 要求将源码提交 `17718f126` 集成 develop。验收边界见 `STATUS.md` 的三项修复候选记录。
