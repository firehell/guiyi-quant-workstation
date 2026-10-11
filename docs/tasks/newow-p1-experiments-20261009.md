# 牛哇 P1 第一项：四个震荡实验

基线 develop `686b9ae2c8c54abe6c5c82256532de7dc6e7e098`。owner 本轮交办 P1 第一项，范围为四个公开震荡测试及 T 菜单、主图和普通／理论页面收益。先前 P0/P2/P1第二项不加入四测试的边界不再限制本项。

来源为手册冻结详情 v3.3.79，完整 SHA256 `3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d`；原件保持 Git 外。原始公式唯一正文见 [手册](../research/newow-v3.2.82/REPLICATION_MANUAL.md#s-05e08fdbb7)。

## 实施范围与验收

四测试独立实验身份，不扩大三正式策略、Recording、Runtime 或选股／推送范围。已验证行情通过既有 MDS/snapshot 入口读取，不构建新资产，不下载或写生产数据。物理合约／segment 分段，换月不静默跨段持有。

- 主图：满10根通道、测试1/2/3 7%止损、测试4 12%；止损 gap 取 `min(stop, open)`，清仓当根不回补。
- 测试2锁定建仓根 HHV10，目标清仓取 `max(target, open)`；测试3只看过去两根部分窗口 MA10 严格上行；测试4止损优先，新高刷新R优先于旧R确认，确认价取 `min(R, open)`。
- 普通收益单独投影：测试1/2/3非止损退出可同根重建、末根Close估值；Marker不增加期末CLEAR。
- 四测试理论值共用基础震荡ideal，不继承四测试门和止损；标签明确该身份。曲线／统计／记录使用同一模式，不冒充账户、因果研究或期货有效性证据。
- T菜单、模式切换、公式说明、止损标记、参考记录；切symbol/周期/基础策略取消请求并清除旧实验事实，拒绝错身份响应。
- 验证公开函数oracle、同根顺序、gap边界、目标不可滚动、MA门、R刷新、warmup、prefix/restart、分段隔离、API参数与请求竞态；定向回归、Web build与真实只读预览，独立公式Review后集成develop。

## 实现与验证结果

已完成四测试纯函数、独立只读实验 API、T 菜单、主图、分段普通／理论曲线和参考记录。正式策略注册表仍为三策略；实验不进入 Recording 或 Runtime。公式版本分别为 `newow_osc_test_page_v3379_v1`、`newow_osc_test2_page_v3379_v1`、`newow_osc_test3_page_v3379_v1`、`newow_osc_test4_page_v3379_v1`。普通模型 `newow_oscillation_experiment_ordinary_v3379_v1`，理论模型 `newow_base_oscillation_ideal_v3379_v1`。

窗口按退出时间筛选完整同合约前缀投影，保留窗口前建仓；尾部换月／缺口不估值强平。当前 readiness 使用最新计算段。取消检查覆盖长循环；前端按纳秒校验 strict-before，避免微秒截止时间被 Date.parse 截断。候选前后端代理仅放行实验 GET，写入、别名及 WebSocket 仍被拒绝。

实际验证（2026-10-09）：

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core <existing-venv>/bin/python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow tests/unit/newow/test_oscillation_experiments.py`：3089 passed，1 skipped；主机实际 socket 回归包含在内。
- `NEWOW_PUBLIC_SOURCE=<frozen-detail.html> npm test`（quant-web）：1022 passed，1 skipped；`npm run build`：typecheck、构建和无环 bundle 检查通过，保留已有 chunk-size 提示。
- 冻结公开函数随机交叉验证：45 组输入、180 个实验结果，Marker、普通和理论交易／汇总／曲线一致。
- 定向 Ruff 通过；`python3 scripts/engineering/secret_scan.py --json` 零发现；`openspec validate --specs --strict --no-interactive` 10 规范通过；`git diff --check` 通过。
- 独立公式／API／Web Review 及候选代理增量 Review 均通过，无待修正 Confirmed Issue。
- Chrome 真实只读候选预览：测试4普通收益、理论切换、测试1、近3月窗口及切周线自动退回基础策略均已读回。RB2701 测试4建仓价3100、12%止损2728，普通窗口收益−1.26%；理论模式明确标注基础震荡理想模型。证据在 Git 外 `outputs/newow-p1-experiments-20261009/`。

首次完整测试有 sandbox socket 权限失败及并行修改中的格式断言失败；修正后以最新树在主机重跑上述完整回归全部通过。Chrome 首轮发现候选前端代理拒绝实验路由，已以失败测试定位、修复并真实读回成功。

验收结论：允许集成 develop。本项不授权发布或 Runtime 切换；页面参考结果不证明期货因果收益。
