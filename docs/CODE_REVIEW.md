# 归一量化代码审查指南

外部审查（ChatGPT / 人工）时使用本指南。将 `git diff`、相关文件与本指南一并粘贴到审查对话中，请审查员只输出审查意见，不直接修改仓库。

产品面与数据边界以 `STATUS.md` / `docs/ARCHITECTURE.md` 为准；本文不授权外部 mutation。

---

## 1. 审查角色

审查员应关注：

```text
架构审查
数据身份与质量审查
量化逻辑审查
风控与安全边界审查
```

默认只审查，不直接修改文件。输出应包含：

```text
问题清单
风险判断
修改建议
测试建议
是否建议合入 develop
```

---

## 2. 当前项目路线

```text
RQData
→ staging + 质量校验
→ Canonical Parquet（1m/1d/1w direct + 5m/15m/30m/60m 聚合）
→ 八表 Catalog / MainContractMap
→ MarketDataService
→ Market Web + data/runtime API/CLI
```

当前 **不** 包含：backtest 子系统、Signal/Review/Strategy Web、signal RQ worker、自动交易。
盘中 Live 只存在于 `operational_products.txt` 的有界 Market Runtime，且与 Historical Canonical 分离；
不得将其扩写为全品种 Runtime 或正式历史事实源。

---

## 3. 必查边界

- coverage/physical failure：fail-closed，无 legacy 回退、无静默缩窗、无跨频。
- `continuous` 与 `actual_dominant` 不可互换；dominants coverage 须与 Catalog 同口径。
- 无订单：任何创建/提交订单路径必须拒绝；`auto_order=false`。
- 密钥与路径：不在 diff、日志、错误文案中暴露 webhook、token、密码、内部路径、SQL、stack。
- 未来函数：策略/指标不得使用未确认未来数据；HTDY realtime 应用路径已退役。
- 文档与代码一致：不得把已卸 surface 写成「当前仍提供」。

---

## 4. 建议测试

按影响面从 `TESTING.md` 选取定向 pytest / `pnpm --dir apps/quant-web test`；深业务变更补对应领域套件。不得用 CI 绿代替本地必要检查。

---

## 5. 不做

- 不因单次 smoke 宣称盈利、长稳、交易或生产就绪。
- 不要求 PR/Review 作为个人 develop 授权条件（见 `AGENTS.md`）。
- 不把 dry-run 或历史证据当作正式数据写入授权。
