# CURSOR-HTDY-VALIDATION-PROTOCOL-C501

更新时间：2026-07-19

对应手册任务：`C5-01`（原 `E5-01`）

## 结论

状态：`COMPLETED / CURSOR_VALIDATION_PROTOCOL_PREPARED`

为 `huotian_dayou_strict / v0.1.0-backtest-candidate / JM / 15m` 落盘验证协议文档、机器可读冻结配置、SHA-256 证据、JSON Schema 与定向测试。未跑正式回测/OOS，未写 DB，未改 report14，未接 live/SignalEvent/企业微信。不得标记最终 frozen。

## 产物

| 路径 | 作用 |
|---|---|
| `docs/strategy_specs/htdy/VALIDATION_PROTOCOL_V1.md` | 协议正文 |
| `configs/oos/htdy_strict_validation_protocol_v1.json` | 机器可读配置 |
| `configs/oos/schemas/htdy_validation_protocol_v1.schema.json` | Schema |
| `data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json` | SHA-256 证据 |
| `services/quant-api/tests/test_htdy_validation_protocol_c501.py` | 定向测试 |

`config_sha256`（文件字节）：`f9ef6961cb3f08f23a23736212503067cb5b18251a9a0087976706ad057a7bee`
`parameter_hash`：`84d80219d2a27d115dfdd36fe7bdf0ea41530e2fc9f2a188ec48bf9db37c2eb8`
`source_commit`：`994799c4998087bee41dc9b2b21f059357bad8dc`

## 验证

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_validation_protocol_c501.py
```

结果（2026-07-19）：**9 passed**。

## 边界

- `freeze_status=protocol_prepared_not_final_frozen`
- `persist_to_db=false`；`baseline_report_id=null`；`report14_policy=do_not_touch`
- hard reject 与 E5-05/X5-05 跳过/诊断分支已写入配置
- 不假定策略有效；D4-00 Gate 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`

## 下一入口

手册 `C5-06A`（Review/Web 通用能力预构建）。
