## Context

基于 `develop@284ae9abeb2eaf045899fbebe82419360bc01560`。`run` 已用全局 generation、section generation、controller identity 和 abort 状态筛选响应；`failConflict` 却仅清空 chart/reference/explanation 资源，相关请求仍满足 `isCurrent`。

已隔离复现：已有 chart → explanation 请求挂起 → chart 刷新发现同 Bar close 变化 → `NEWOW_SHARED_BAR_CONFLICT` → explanation 晚到并恢复数据。单纯设置 `input_conflict` 无法隔离异步世代。

## Goals / Non-Goals

目标：被失效资源的所有旧请求永久失去写入资格；新请求可正常重建；导航、缓存与展示状态保持一致。

不做：通用 query library、全站状态机、后端 snapshot 改造、自动无限重试、UI 重设计或公式变更。

## Decisions

### 1. 一个私有失效操作，影响范围由调用点决定

在当前 composable 内提取私有 `invalidateSection`，不新增公共模块。普通失效顺序为：推进 section generation；abort 并删除旧 controller；删除 in-flight token；清空数据；对 chart/reference 调用既有 `resetPagination`；最后设置目标 lifecycle/error。全部同步完成，不插入 await。

默认 lifecycle 使用现有 `not_requested`；冲突使用 `input_conflict`。chart 清理同时重置 current-window provenance、window、fingerprint、generation signature 与 page limit；reference 清理 window、fingerprint、page limit，响应内 cursor 随 data 清除。

Abort 用于及时停止工作；generation/controller identity 才是晚到写入的最终防线。fetch 忽略 abort 时也必须安全。`run.finally` 保持请求身份检查，不得删除后来请求的 controller/token。

### 2. 明确失效范围

| 触发 | 失效范围 | 保留行为 |
|---|---|---|
| chart/reference/explanation 的事实、响应或分页冲突 | 五个 section 全部失效，清空 auxiliary cache | 保守拒绝继续使用来源已冲突的共享快照 |
| auxiliary 或 comparator 自身响应身份/内容非法 | 该 section；清空 auxiliary cache | 不推断其他 section 已冲突 |
| 409/token 不兼容 | 先收集 loaded 或 in-flight token 匹配的 section；维持既有 auxiliary 依赖清理 | 当前发起重建的请求可继续一次无旧绑定重建 |
| 接受的 chart 来源 generation 真正变化 | reference/explanation/auxiliary/comparator | 保留刚验收的 chart |
| identity、current/history 切换或 dispose | 全部资源与在途请求 | 保持现有全局 generation 与 resolver 隔离 |
| 同一服务端 token 接受的不同 chart 窗口 | 不失效独立 reference | 同窗口分页仍严格校验 hash/page identity；无 token 仍严格指纹 |

主要事实冲突清空五个 section 是有意的局部行为收紧：`compatibleToken` 会读取全部五个 section，因此不能留下旧 auxiliary/comparator 供下一次请求继续选择冲突 token。只清三个 section 或仅隐藏解释面板都没有消除根因。

### 3. 重建中的当前请求是显式例外

私有操作允许当前 409 重建请求“仅清结果与导航、保留本请求资格”。只有 `run` 的一次重建分支可选择这个模式；普通冲突不得使用。先计算受影响集合，再清 token，避免边遍历边清空导致漏掉关联请求。

保留请求的情形不推进其 section generation，不 abort/delete 其 controller；旧结果清除后状态恢复 loading，重建请求去除旧 snapshot/window binding。仍只允许一次重建，第二次失败进入既有失败处理；429 不触发自动重试。其他受影响 section 全量失效，即使其已加载 token 匹配而新请求 token 不同，也取消该 section 的当前请求以避免资源混世代。

## Alternatives considered

- 只调用 abort：不能防止忽略 abort 的 fetch 晚到，不采用。
- 所有失效都增加全局 generation：会误取消合法局部加载及当前一次重建，不采用。
- 各分支继续复制清理语句：容易遗漏分页、token 或 controller，采用局部复用消除重复。

## Validation

在 `tests/useNewowProduct.test.ts` 复用 controlled Promise 与真实 composable，覆盖主要三 section 冲突 × 其他在途 section，至少包含原 chart/explanation 数值冲突复现。断言 signal 已 abort、数据为空且 lifecycle 不被晚到 resolve/reject 改回；故意让 fetch 忽略 abort。

另覆盖：冲突后新请求成功而旧 finally 不删除新请求身份；auxiliary cache 不恢复冲突结果；compatibleToken 不再拿到旧 token；current-window 标记与分页 cursor 被清除；当前 409 请求仍只重建一次；429 无重试；相容跨窗保留 reference 统计和 cursor；同窗 fingerprint 冲突仍被拒绝；identity/history/dispose 的既有行为。

使用现有 `e2e/newow-product.spec.mjs` 的受控 route fixture 复现“冲突后解释保持失效、新加载恢复”流程。只在隔离 5182 页面执行，不能把 fixture 结果解释成真实行情正确。

## Rollout and risks

无需后端部署、API 迁移或 formula version 变更。主要用户可见变化是共享事实冲突时相关辅助信息也清空，避免继续展示失效快照。源码可以单独 revert；必须连同测试与规范保持一致。实施与第一、三项没有代码依赖，可独立 Review。
