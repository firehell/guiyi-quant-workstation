# PROJECT_PROGRESS.md — 当前项目进度

> 用途：给新的 Codex 线程、Cursor 人工检查和外部审查快速确认当前真实进度。  
> 当前阶段：V1-B：焦煤 JM 3 年真实数据短持有策略闭环。
> 边界：V1 不做实盘、不自动下单、不接 CTP / TqSdk 交易接口。

---

## 1. 当前阶段

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

V1-B 的当前目标是把项目从旧的 V1-A “焦煤 1 年验收样板”推进到更接近正式研究使用的 3 年真实数据闭环：

```text
焦煤 JM 最近 3 年真实数据
→ 1d / 15m / 5m 标准 K线
→ 日线定方向
→ 15m 独立入场
→ 5m 独立入场
→ 持有 5-8 根本周期 K线
→ 止损退出
→ 正式回测报告
→ PostgreSQL 入库
→ Vue Web 资金曲线 / 回撤曲线 / 交易明细
→ K线买卖点 marker
→ 单笔交易复盘 note
→ 信号扫描提醒
```

阶段详情见：

```text
docs/V1B_JM_3Y_SHORT_HOLD.md
```

---

## 2. 当前已具备

- V1 主路线已统一为 RQData + standard Parquet + DuckDB + PostgreSQL + vn.py + FastAPI + Redis/RQ + Vue Web。
- 数据源抽象、`data_role` 隔离、MarketDataReader / LocalParquetProvider 已存在。
- RQData 结构化下载、标准化、质量报告和多周期聚合已有实验链路。
- vn.py adapter、strategy loader、symbol mapper、result converter 已存在。
- 回测任务 API、RQ worker 函数、回测报告模型和明细表已有基础。
- Web 已有 K线工作台、回测报告页、资金曲线、回撤曲线、交易明细、K线 marker、信号扫描页和复盘中心骨架。
- 自动实盘、自动下单、CTP / TqSdk 交易接口不属于 V1。

---

## 3. V1-B 待完成

- JM 最近 3 年真实数据需要作为 V1-B 验收数据完成质量确认。
- 1d、15m、5m 标准 K线需要作为 V1-B 固定输入链路验收。
- 日线定方向规则需要确认只使用已完成日线，不能使用未来 K线。
- 15m 入场和 5m 入场需要作为两条独立回测链路验收。
- 15m 入场后持有 5-8 根 15m K线，5m 入场后持有 5-8 根 5m K线。
- 行情不利时必须按止损方法退出；未触发止损时按短持有窗口退出。
- V1-B 回测报告必须入库，并能被 Web 报告页和 K线 marker 使用。
- 单笔交易必须能创建复盘 note。
- 信号扫描只提醒，不自动下单。

---

## 4. 当前不做

V1-B 明确不做：

- 多品种批量扩展。
- 参数优化、网格搜索、AI 自动生成策略。
- tick 级高频回测。
- 复杂盘口队列撮合。
- Web 策略代码编辑器。
- Web 大屏扩展。
- 自动实盘。
- 自动下单。
- CTP / TqSdk 交易接口接入。
- 修改 vn.py 源码。
- 写入账号、密码、API Key、license、米筐账号、天勤账号、CTP 信息。

---

## 5. 建议下一步任务顺序

1. 更新并提交 V1-B 文档检查点。
2. 只读确认 JM 3 年数据可用性和本地数据索引状态。
3. 制定 JM 3 年 1d / 15m / 5m 数据验收任务。
4. 实现或收敛 V1-B 短持有策略规则。
5. 跑通 15m 独立入场回测并入库。
6. 跑通 5m 独立入场回测并入库。
7. Web 验收报告、曲线、交易明细和 K线买卖点。
8. 从一笔 V1-B 交易创建复盘 note。
9. 做信号扫描提醒验收和回测严谨性审查。

---

## 6. 建议检查命令

```bash
rg -n "V1-B|焦煤 JM|3 年|日线.*方向|15m|5m|5-8|止损|自动下单|自动实盘" README.md AGENTS.md CLAUDE.md docs
```

```bash
git diff --name-only
```

后续实现任务回归：

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```
