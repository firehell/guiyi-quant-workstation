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
| `v1.9.15` Release candidate | `codex/release-v1.9.15` 基于 `origin/develop@a6ea680ed8d9150e0b9920e71563a3de18f7dd1e` 准备候选，Release PR `#333` 已指向 `main`。适用验证、两轴独立 Review 与 GitHub checks 都必须按 PR 的 current exact head 单独核验；其中任何一项都不构成 release 授权。Market Detail 仅包含已完成的 A–D staged workspaces；B3 Alert Scope Control 与 Slice E final cutover 明确延期，不属于本 Release 完成声明。它尚未合入 `main`、创建 tag 或发布 GitHub Release，也未执行 PF 数据 apply、Runtime promotion 或自然验收。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。

## Pending Gate

- Release PR `#333` 已创建；Owner 决定 release 前必须读取 current exact head 的 release identity、全量适用检查、Standards/Spec 双轴独立 Review 与 GitHub checks；GitHub 当前没有上报 CI checks。这些证据不授权真实 RQData/Canonical apply、`main` 合入、tag、GitHub Release、Runtime promotion 或 Scope/通知变更。
- exact RC 形成后，`main` 合入、annotated `v1.9.15` tag 与 GitHub Release 仍需一条引用 exact 40 字符 SHA 的新明确授权。
- exact-tag 的 `PF2611` read-only plan、随后引用 exact plan hash 的真实 RQData/Canonical apply、以及 Runtime promotion 均是彼此独立的人工 Gate。
- 仍须等待自然 completed SuBing 15m Event、immutable `AlertEvent` 与 one-shot PushPlus provider acceptance；不得用 synthetic、replay、backfill 或手工发送替代。
- 最终 G12 仍须由用户人工确认微信实际收到同一自然 Event；provider accepted 不能替代实际送达确认。
