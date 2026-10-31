# 项目子代理角色清单

本页用于需要协作时快速定位职责，默认主代理直接完成任务，不固定多角色接力、分派模板或独立验收阶段。
授权与停止条件见 [AGENTS.md](../AGENTS.md)，当前现场见 [STATUS.md](../STATUS.md)，模型选择见
[开发规则](DEVELOPMENT.md#codex-模型调度)。角色本身不授权额外操作。

## 主代理与协作

- 确有并行或专门复核价值才分派；说明目标、修改归属与必要上下文，避开用户修改及共享资源冲突。
  独立源码工作可并行；共享生产状态、补数与运行切换按依赖和锁串行，隔离方式按实际冲突选择。
- 实现者承担必要测试与自审；普通改动不强制另找验证或 Review 代理。
  公式、数据时序、并发、迁移、成交与账本等高风险改动的独立 Review 由未参与实现者完成。
- 主代理核对实际 diff、验证结果及必要现场事实；修复后仅复核受影响部分，不为新 commit 重走全套工序。
- 明确谁负责提交和真实执行，避免重复操作；重要歧义按 AGENTS 汇总给 owner，其余工作继续。

## 统一分派输入

一条任务消息说明目标、实际工作区/基线、可改范围、相关入口和预期结果即可；已知上下文直接引用，
不为分派生成独立 Spec、Plan、manifest 或身份表。执行者自行快速核对现场，不把旧消息当当前事实。

## 八类常用角色

| 角色 | 适用职责 | 按需入口 |
|---|---|---|
| `market-data` 行情数据 | 缺口与质量、Session/主力映射、预热、数据维护和读回 | [数据合同](DATA_CENTER.md)、[futures-data](../.agents/skills/futures-data/SKILL.md) |
| `strategy-formula` 策略与公式 | 指标、状态机、公开公式对照、期货适配与参考交易；页面/因果/账户事实分开 | [指标内核](INDICATOR_KERNEL.md)、[Newow](../openspec/specs/newow-product-reference-trading/spec.md)、[SuBing](../openspec/specs/subing-ths-alert/spec.md)、[Reference](../openspec/specs/reference-trading/spec.md) |
| `backend` 后端工程 | API、CLI、仓储、缓存、分页、幂等、恢复与性能 | [架构](ARCHITECTURE.md)、[定位](DEVELOPMENT.md#按任务定位)、[业务合同](../openspec/specs/) |
| `web-chart` Web 与图表 | 布局、图层、切换、快照、记录定位、故障状态与移动端 | [产品](../PROJECT_SOURCE.md)、[架构](ARCHITECTURE.md)、[测试](../TESTING.md) |
| `validation` 验证 | 复杂场景的定向验收、隔离集成、浏览器/API 对照；不放宽断言 | [按影响验证](DEVELOPMENT.md#按影响验证)、[命令](../TESTING.md) |
| `review` 独立 Review | 针对高风险改动检查具体实现与证据，说明确认问题和待验证风险 | [Review 规则](../AGENTS.md#验证与交付)、对应业务 canonical |
| `release-runtime` 发布与运行 | 按目标连续发布、构建、切换、确认和清理，不设冻结阶段 | [release-agent](../.agents/skills/release-agent/SKILL.md)、[部署](../deploy/README.md) |
| `docs-maintenance` 文档与维护 | 唯一入口、引用、被替代计划、死代码与依赖；查清消费者后删除 | [文档入口](DEVELOPMENT.md#文档与版本的唯一入口)、[架构](ARCHITECTURE.md) |

只读本次需要的入口，不要求各角色全部参与或读取全套资料；不为角色复制技能、权限或模型表。

## 统一交付格式

不强制字段或段落模板。用短段落交回结果、关键改动/commit、实际验证、未解决问题即可；
需要接手时补一句下一动作。截图、矩阵、日志和 receipt 优先引用已有产物，不重复制作。
已提交、已发布、已运行与自然业务待观察如实区分；只读任务不为标完成而改代码或生产状态，
自然场景未发生不默认新建监控、通知或后台任务。
