# 当前状态

更新时间：2026-09-04

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`；已完成版本的实现和验证过程从 Git tag、GitHub Release、PR 与 Git history 追溯。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| 正式 Release | `v1.9.14@ca15456eaff988db4fe61c37657ca37302a7f977` 仍是最新正式 release，GitHub Release 已于 2026-09-03 发布。 |
| `main` | `main@10d19c3a2b266fb0aefb9abd320d96ff46d410aa` 在 `v1.9.14` tag 后多出一次未发布的合入；它不是 release、tag 或 Runtime 候选，不能作为现役版本事实。下一次 release 必须从当时的 `develop` 重新走审查、release PR、tag 与 Runtime Gate。 |
| Runtime | 五项 launchd 仍指向 clean、detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.14-r1@ca15456e`。截至 2026-09-04 的只读 readback：API/Web/Live/Alert 为 `running`，After-market 已加载并按调度 `not running`；最新 Runtime health 为 `failed`，原因是 2026-09-03 的自然盘后 `LIVE_DOMINANT_MISMATCH`，因此不是 `RUNTIME_READY`。 |
| Database 与 Canonical | 最近 production 只读 readback 为 Alembic `20260903_0045`；RQData session anchor repair 已发布并保留 D1/W1 原始事实。active Canonical 只读 readback 为 8,801 个 Dataset、42,575 个分区、44,629,532 行。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY 为 `jm × 15m`；SuBing 为 execution-time operational 60 个品种 × 15m，Scope hash `ce1daca77aeb1abe134806b67aebd96b2c35db3ba82aa10af58f6e5a2e4f5fa2`。两条 Rule 均为 enabled；SuBing Event 为 0。 |
| Develop 中工作 | `develop` 上的 Newow futures validation、SuBing detail workspace 与 physical-contract warm-up 都是未发布的开发工作。warm-up task branch 仍需与最新 `develop` 收敛、完成实现/验证/独立 Review 后才可能形成 RC；代码存在不等于 release、数据 apply、Runtime promotion 或自然验收。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。

## Pending Gate

- 先完成当前 warm-up repair 的代码收敛、定向/模块验证和独立 Review；其中不授权真实 RQData/Canonical apply、release、Runtime promotion 或 Scope/通知变更。
- 修复代码若形成 RC，release PR、`main` 合入、annotated tag 与 GitHub Release 仍各需新的明确授权。
- exact-tag 的 `PF2611` read-only plan、随后引用 exact plan hash 的真实 RQData/Canonical apply、以及 Runtime promotion 均是彼此独立的人工 Gate。
- 仍须等待自然 completed SuBing 15m Event、immutable `AlertEvent` 与 one-shot PushPlus provider acceptance；不得用 synthetic、replay、backfill 或手工发送替代。
- 最终 G12 仍须由用户人工确认微信实际收到同一自然 Event；provider accepted 不能替代实际送达确认。
