# WorkBuddy Security Boundary

更新时间：2026-07-16

WorkBuddy Unified V3 必须 fail-closed。

## 禁止

- 自由 shell；
- 裸调 `codex`、`codex_plan.sh`、`codex_dev.sh`；
- 模糊审批；
- 自动串联 stage；
- 自动 retry；
- push / merge / deploy / release / close；
- mark PR ready；
- 写 `.env`、token、webhook、cookie、license、账号凭据；
- 写 DB / Parquet / runtime 生产路径；
- 删除或重写 `data/raw/`、`data/processed/`、`data/parquet/`；
- 将 `validation`、`legacy_reference`、`candidate`、`failed` 当 active 输入；
- 自动交易、无人值守下单或信号转订单；
- 将 WorkBuddy memory 当状态源。

## 审批

`approve` 必须带：

```bash
--confirm-user-approval
```

`sync-pr` 必须带：

```bash
--confirm-github-write
```

用户最终保留 Plan、生产写入、merge、deploy 和 Issue/PR closure 决策。

## Writer Lock

WorkBuddy 不成为代码 writer。核心开发仍由 Codex 执行，writer lock 使用 `codex`。

Cursor 人工接管仍按 [`WRITER_LOCK_HANDOFF.md`](WRITER_LOCK_HANDOFF.md)。
