# 正式历史读取与展示收敛（2026-10-24）

## 目标与边界

Owner 已交办：盘后 Canonical 是历史行情、指标、信号与参考交易的唯一正式口径；较晚来源修订由历史重算处理。实时首次事件、通知和旧不可变记录保留作审计，不能反向改写或补发。不宣称缺失的观察原件恢复，不把未完成交易日标为完整。

本项仅源码、领域合同和离线验证；不连接生产服务、数据库或 Redis，不修改 STATUS、版本、Runtime 配置或 output 证据，不发布或提交。现场数据修复和运行切换由主任务独立交付。

## 实现

- Newow 正式产品参考固定 `PersistedNewowReference`；SuBing 正式参考固定 `PersistedSubingReference`。废弃 reader-mode 环境开关不能选择另一个公共历史实现；未构建、过期、来源不明和质量异常不回退到现算或 forward。
- HTDY 保留其既有专用 Canonical 历史模型；图表信号与该模型使用同一实现，环境开关不再将它切换到另一种参考身份。
- SuBing 参考与图表信号共享完整历史输入前缀证明。读取保存点前后都验证当前 Canonical；图表窗口之前的预热前缀修订也必须拒绝，保留既有分页和元数据证据边界。
- 正式历史图仅显示 Canonical 历史信号。通用记录面板只读首次事件审计，不再通过未验证的 generic snapshot 包装第二个正式历史入口。真实事件、实际观察时间和通知均不改写。
- 历史信号缓存绑定已加载 Bar 的 OHLCV、成交额、持仓量及物理/计算身份；正式行情 replace、正式参考源身份变化或主动重试均重新读取。即使可见 Bar 不变，较早前缀修订也不能保留 COMPLETE 缓存；旧请求晚到与失败不覆盖或补成实时信号。
- 底层 generic snapshot API 明确标记为 immutable audit snapshot，不能单凭该快照或 checkpoint CURRENT 宣称当前 Canonical 来源已验证。

## 实际验证

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:services/quant-api:packages/quant-core:services/quant-api/tests:services/quant-api/tests/reference_trading \
GUIYI_LOG_DIR=/private/tmp/guiyi-formal-history-review \
services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
 services/quant-api/tests/reference_trading/test_formal_history_authority.py \
 services/quant-api/tests/reference_trading/test_signal_window.py \
 services/quant-api/tests/reference_trading/test_source_identity.py \
 services/quant-api/tests/test_subing_reference_api.py \
 services/quant-api/tests/newow/test_composition.py \
 services/quant-api/tests/reference_trading/test_historical_integration.py \
 services/quant-api/tests/reference_trading/test_api.py
```

结果：47 passed、1 skipped。跳过的是需要独立数据库的既有集成项；本任务未连接数据库。

```sh
cd apps/quant-web
node --test tests/historicalSignalRanges.test.ts tests/newowRecordingPanel.test.ts tests/referenceTrading.test.ts
```

结果：18 passed。覆盖 Canonical-only 选择、可见 Bar 修订、可见 Bar 不变但源前缀换版、失败清除旧 marker、过时响应拒绝、夜盘审计交易日及禁止 generic 面板选择历史流。

5 个修改的 Vue SFC 经 `@vue/compiler-sfc` 编译通过；`git diff --check` 通过。

## 待主任务完成

独立高风险 Review、全 Web/typecheck/build、必要扩展回归、正式发布/运行切换和自然验收仍由主任务执行。离线测试不证明生产数据完整或 Runtime 已切换。

补充失败路径验证：正式参考来源撤销或读取失败时同步清除图表旧 COMPLETE 信号，且错误未解除前禁止由 unchanged Bars 重绘。HTDY 保留旧 result 的错误路径同样覆盖；定向 Web 18 passed，vue-tsc -b exit 0。

## 主线程扩大验证与交付隔离

完整 Web 1195 passed / 3 skipped；扩展后端 894 passed / 81 skipped（需独立服务/数据库的既有项）；P2 参考读取失败撤销旧信号修正后定向 Web 18 passed，类型检查和完整 build/topology 通过。reference-trading OpenSpec strict、secret scan、diff 检查通过；独立 Review 无剩余 Confirmed Issue，允许集成 develop。最初后端两项因临时日志目录未创建失败，创建独占目录后完整集合重跑通过，旧输出不冒充业务失败。

develop 相对已发布 v1.15.17 还含其他任务的 input/formula/launcher 变化，因此正式 v1.15.18 从 exact v17 独立最小回移本修复，不发布其他未完成合同。正式候选、现场维护续接和实际读回完成后另记，不用 develop 验证替代候选验证。

正式最小补丁 v1.15.18 已经 PR466 发布，main/tag peeled `062310abd5eca6fac442bd565258ab0b05fa2d73`，合并树与候选 `814471345658affa415e8c247ae74a5de24c5a6a` 完全相等；Release非draft/非prerelease。精确补丁后端819 passed/81 skipped、完整Web1168 passed/3 skipped、构建及独审通过。回合develop冲突保留已验证完整实现，不把v17最小补丁覆盖其他未发布功能；运行续接仍单独验收。
