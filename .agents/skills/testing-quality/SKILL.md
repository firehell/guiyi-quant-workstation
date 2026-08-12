---
name: testing-quality
description: 当任务涉及 pytest、前端 test/build、API、Canonical 数据质量、Runtime 或回归测试时使用。
---

# Testing Quality Skill

## 当前测试重点

- Canonical：schema、identity、Session、duplicate、OHLCV、coverage 与物理可读性。
- MarketDataService：continuous / actual_dominant / contract、七周期、分页与 fail-closed。
- Runtime：operational 60、Historical/Live seam、phase、重连、盘后幂等/重试/自然触发边界。
- API 返回格式和错误态。
- 前端图表、空状态、generation token、构建产物拓扑。

## 必测用例

空数据、重复数据、缺失 K 线、异常价格、Session/映射缺失、不可读分区、Live/Canonical seam、
非交易日与当天 Session 尚未同步。

## 常用命令

- 只从 `TESTING.md` 复制当前命令，不维护第二套命令清单。
- migration 测试必须使用 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`；不得把生产 `alembic upgrade` 当测试。
- Runtime 只先做 render-only/只读状态；测试或 dry-run 不授权重载、真实数据写入或手工盘后。

## 禁止

- 只测正常行情。
- 测试依赖真实账号密码。
- 用 fixture、手工触发或 HTTP 200 冒充真实自然时点/业务验收。
