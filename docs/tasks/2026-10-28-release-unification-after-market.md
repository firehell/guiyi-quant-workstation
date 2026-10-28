# 发布树收敛与10/28盘后验收

Owner交办先将发布树收敛为一个，再验收盘后更新；夜盘开盘后另验，不新增自动化。

## 发布与运行

唯一发布/运行树为`.worktrees/release-v1.16.30`，exact
`81963702a75894f9f2d6ef52093bc66ef4a09750`，正式十绑定统一gen36。
Release、annotated tag peeled、远端main及本地main均核对一致；没有创建新tag或扩大Scope。
该版本已包含v29 Reference修复及关闭的SimNow代码；本轮不启用SimNow、不连接柜台或初始化账本。

原生新计划`cd1dbb040257df123b29b5fa7853c484a1979ae855ced3bdd5293c811fddb08e`
一次apply终态switched，消费者、Feed、原日历及保护原件校验通过。
263项定向回归通过（17.79秒）：cohort/host/parked/readback/handover、Reference吞吐/worker及HTDY共享准入/闭市差异。
离线uv frozen/lock检查、Web能力生成/类型/build/topology均通过。
API实际版本1.16.30，Web200的HTML摘要与v30 dist一致。

## 旧树退役

仅精确处理v26、v29；不触碰develop/main、其他任务树、Canonical、DB、配置或账户。
原生closeout计划`81dd8cd9385acc65334f09cba7bf53b115a9d38243f752ced87b773ce9af814a`
核对26次闭合attempt、61份原件和12个marker，原子封存到稳定私有release-retirements目录。
封存后重复扫描binding/plist/loaded/进程/恢复引用无阻断，non-force移除两棵旧源码树。
原tag/Release、原attempt和必要运行JSON保留，可从Git重建源码；删除后unknown部署及恢复guard通过。

## 今日自然盘后

今日任务在v29上自然发生：18:05:07启动、18:11:35结束，60品种、attempt1、passed，无last_failure。
v30保留该成功的原source_commit/hash，公开health为retained；不冒充v30重新运行过盘后任务。
维护锁已释放，Live清理证明为bar keys0、无订阅，rank1与当日快照一致。

两次独立只读校验（旧树删除前/后）均通过：

- 720个发布分区的Catalog指针、文件完整性及provenance与自然原件一致；continuous和contract各60×6周期。
- 60品种当日rank1映射及MDS当日1m/D1共120端点均通过，前后端点完全一致。
- 来源状态SHA `c6cc2b2a3124590501c28bb8fef1deb95f93a1c7d0a66c0a16119b50f3f12988`不变。
- 未增加下载、补跑、Canonical/DB维护写入或通知补发。

18:34已完成的消费者审计：D1主图/参考180/180 READY、辅助740 READY；
W1主图/参考179/180 READY、辅助501 READY，剩余保留既有合同允许的非READY状态。
两范围均audited、失败0、漏检0、未耗尽预算、无修复提案；不把合法非READY改称READY。
独立重算当前完整Catalog/Calendar/Session/合约/分区摘要，与原D1/W1 input_revision均一致，未沿用未验证的旧报告。

19:13删除后再读：十身份matched，六owner active，Inbox pending/blocked/UNKNOWN/dependency_wait均0，
completed8302、恢复2618及旧BLOCKED339保留；全部原件游标追尾，维护锁空。
盘后health为ok/retained、成功交易日2026-10-28；global原有degraded不由本次清理消除。

## 验证命令与证据

- `uv sync --frozen --offline --project services/quant-api`及`uv lock --check --offline --project services/quant-api`。
- `pnpm -C apps/quant-web install --offline --frozen-lockfile`及`NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build`。
- 指定临时日志及API/core PYTHONPATH后运行`python -m pytest -q -p no:cacheprovider`上述九个定向文件：263 passed。
- 原生`app.runtime_cohort plan/apply-plan`、`runtime_retirement build_closeout_plan/seal_closed`及重复`runtime_retention cleanup-plan`。
- 全部新鲜报告、原生公开计划及今日自然原件保存在`output/release-unification-20261028/`；私有原生attempt保持稳定目录原件。

本轮发布树收敛与盘后部分已完成。下一步仅在夜盘自然开盘后验证新1m、5m边界吞吐、首根完成60m及新Event；无夜盘品种次日日盘另验。
