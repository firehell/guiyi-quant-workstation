# HTDY 日线窗口修复与牛哇来源差异定位

范围：修复 HTDY 历史读取；只读定位牛哇。未修改公式、参考模型、行情、数据库、正式 Runtime 或通知。

## HTDY

黄金日线原接口返回 `HTDY_REFERENCE_DATA_UNAVAILABLE`。内部错误为
`CONTRACT_ACTIVE_WINDOW_MISSING`：AU2304 到期日为 2023-04-17，却以全局
2026-10-26 为 through 查询。历史 loader 已按物理 owner 正确加载，错误发生在补取 OHLCV 时。

修复为汇总每个物理合约所有分段最后所需 Bar，按其 trading_day/bar_end 查询一次完整前缀。
不以展示窗口裁剪 warm-up；同合约多个质量分段均保留。沿用
`htdy_historical_window32_reverse_close_v1`，无公式或参考交易语义变化。

验证：新增回归先失败，再修复；定向 9 passed；扩展历史/模型/API 29 passed；
独立 Review 加入 Subing service 共 61 passed、允许集成。Ruff 与 diff check 通过。
测试入口为 `services/quant-api/tests/reference_trading/test_htdy_history.py`、
`test_htdy_reference_model.py`、`services/quant-api/tests/test_subing_reference_service.py`、
`test_subing_reference_api.py`，使用 quant-api venv、PYTHONPATH=services/quant-api:packages/quant-core。

开发 API8002 重载后真实读回黄金 `frequency=1d` 返回 200；默认窗口
2026-04-28 至 2026-10-26，5 笔参考交易（1 CLOSED、1 OPEN、3 interrupted）。
这证明历史 API 恢复，不代表实时账户成交或正式服务已发布；当前 HTDY 页面实时记录仍只使用 60m。

## 牛哇

黄金和铝趋势日线在固定 as_of=2026-10-26T07:00:00.000001Z 复现
`SOURCE_IDENTITY_UNVERIFIED`。诊断保留原验证函数并调用它，不跳过或弱化检查。

| 字段 | AU 保存 / 当前 | AL 保存 / 当前 |
|---|---|---|
| input_fingerprints 长度 | 5532 / 5533 | 10514 / 10515 |
| calendar_session_effective_fingerprints 长度 | 5510 / 5511 | 10468 / 10469 |
| 最后 rank1 段截止日 | 2026-10-23 / 2026-10-26 | 2026-10-23 / 2026-10-26 |

两组指纹都是保存前缀完整相同后新增一项，并非旧前缀内部值冲突。
AL 的 calendar 1711→1714、sessions 4513→4517，旧前缀也完全相同。
`verify_saved_input_prefix` 在 input_fingerprints 长度超过保存清单处拒绝；
因此新版主图不能与停在 10/23 的旧参考资产拼接。

实际诊断输出：`output/htdy-window-newow-source-20261026/{au,al}-trend-source.txt`。
本次没有刷新或重建牛哇参考资产，没有把请求截止日缩回 10/23，也没有隐藏失败。
结论仅覆盖 AU/AL 趋势日线，不能推断所有品种/策略/周期均为相同差异。

后续最小动作：按现有历史维护合同规划并更新受影响牛哇参考资产到最新已确认来源，再独立读回。
