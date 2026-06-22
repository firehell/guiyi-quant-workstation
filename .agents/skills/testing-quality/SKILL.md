---
name: testing-quality
description: 当任务涉及 pytest、前端 build、API 测试、数据质量测试、策略测试、回测验证、未来函数测试、回归测试时使用。
---

# Testing Quality Skill

## 测试重点

- 数据完整性：缺失、重复、异常价、时间断点。
- 策略信号时点：当前及过去数据。
- 撮合逻辑：当前信号下一根成交。
- 手续费、滑点、合约乘数、保证金。
- 最大回撤、连续亏损、期望值。
- API 返回格式和错误态。
- 前端图表和空状态。

## 必测用例

空数据、重复数据、缺失 K 线、异常价格、手续费滑点计入、止损触发、连续亏损统计、最大回撤计算、样本内/样本外分离。

## 常用命令

- 后端：`uv run ruff check . && uv run pytest -q`
- 迁移：`uv run python -m alembic upgrade head`
- 前端：`pnpm build`
- 浏览器：打开本地页面并检查 console。

## 禁止

- 没有测试就合并回测引擎。
- 只测正常行情。
- 测试依赖真实账号密码。
