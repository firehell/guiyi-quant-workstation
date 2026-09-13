# Newow 周线 60 品种证据索引

本目录只保存紧凑、可审查的当前现场摘要。冻结范围是 operational 60 品种、三策略、`1w`，
固定 `as_of=2026-09-13T06:36:13+00:00`。完整审计及 compact 原始 JSON 保存在本机 `/private/tmp`，
其 SHA-256 已绑定在 `readiness-summary.json`；它们没有进入 Git，也不构成长期行情事实源。

当前只读审计未执行 RQData 行情请求或任何写入。结果仍为 `incomplete`，因此尚未运行 180 组合 matrix，
也不能声称 60 品种周版数据完成。repair candidate、Session metadata proposal、RS source/integrity review
以及 PF2611 非正价格须分别处理。

`calibration_batch_candidate` 仅是一份待 owner 单次明确授权的小批次建议。执行前必须重新运行两个
`contract-warmup` dry-run 并核对原生 plan hash；串行 apply，第一目标失败、结果不明、锁忙、hash 漂移、
配额到达任务日上限或异常流量时停止，不自动重试。该建议不授权 metadata、main/tag、Release 或 Runtime。
