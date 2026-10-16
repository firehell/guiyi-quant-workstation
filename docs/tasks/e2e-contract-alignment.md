# 既有 E2E 夹具与页面合同失配修复

基线 `186d3854858853e257d0a4fef4d01766aebb19ed`。主体为浏览器测试、夹具、截图与验证文档；
公式、数据或 Runtime 不变，另保留两处由旧失败测试揭示的最小UI修复：读取错误时不得显示成功空态；卡片不得漏掉现有质量提示。旧失败曾在候选与未修改基线逐项复现，本任务用于关闭这些工程例外。

## 根因与覆盖

- Newow 默认副图为主力照妖镜；旧测试仍查 MACD 与短名称“照妖镜”。“杯柄说明”现位于“详情与口径”折叠菜单。
- 原始 ReferenceTrade 事实置于独立折叠区；外层与页面参考收益共用历史 CSS 类，旧宽泛选择器出现多匹配。
- 旧策略概览按钮已退出页面；动作标签为被动展示。测试改为检查被动标签身份、同 Bar 顺序、精确原始价与无账户语义，
  现有 `NewowProductChartStage.test.ts` 的 passive-label 测试及布局提交 `e73940a62` 可交叉核对；
  不模拟组件事件复活不可达入口；策略解释从主图图例打开，主升浪单独检查11周期解读。
- 显示价格为两位小数，raw facts 保持精度。保留 `anchor_price`、`data-reference-price`、owner、known_at 与 sequence 断言。
- 副图夹具的9月时间不属于止于8月的主图，造成 ready 但空白。先新增同物理合约/Segment/Bar 对齐测试并观察失败，
  再修复三个周期、三个策略下四种可见副图的数据时间；补齐趋势转折的合法响应，不调整真实算法。
- SuBing旧Event没有formula/alignment事实时显示“未记录”，不补造版本或六周期同向；当前六周期选择器需要进入视觉基线。
- 详情公共夹具显式返回持久化参考不可用，不让未mock请求落到本机API代理。专项测试可以覆盖此缺省fixture。

- 同步苏冰 canonical 中与六周期 Event/Scope 读取冲突的旧尾句：历史参考不支持不等于预警未启用，未改变任何启用状态。

独立Review无Confirmed Issue。记录行仅验证两位展示价；同Bar属性、Hint原始事实和夹具关联仍验证精确值，
不宣称记录行提供已不存在的四位原价展示入口。

消息错误空态不是旧断言失配：保留原断言，修复 `MarketHomeMessages.vue` 的条件，错误时不显示“暂无消息”；
Newow筛选不受其他预警读取错误影响，已有记录仍按原逻辑保留。

全量OpenSpec严格校验另发现基线已有一项缺少标准Scenario（`requirements.24`），已在未修改基线复现；
仅给原有正式D1/W1条款补充“未知缺口整体fail closed”的既有规则示例，未修改正文规则或启用状态。

首页质量提示经 canonical 复核为必须保留，不作为过期文案删除：新卡片复用 `marketHomeQualityNotice`，
已证实缺价后重热和未知历史缺口使用不同提示；保留报价但不合成涨跌幅。
旧固定表头来自已替换的表格结构，现验证卡片列表滚动/焦点/无溢出，不声称导航固定；
`PROJECT_SOURCE.md` 的表头称谓同步为当前排序菜单。

## 视觉更新依据

逐张读取旧/新图后，仅更新对应快照，保留原像素容差：两位价格、当前副图及可见柱形、折叠菜单、
原始ReferenceTrade区与分合约曲线断开、当前布局与独立11周期弹窗。11周期截图使用新名称，移除无消费者的旧解释截图。
苏冰桌面变化为新增5分/周线入口；窄屏变化为六周期筛选、旧Event的“未记录”和原始事实不推断版本。
没有通过增加容差、skip、重试或固定等待隐藏失败。

## 验证

所有浏览器运行使用候选工作区独占端口、proxy `127.0.0.1:1` 和route fixtures；不访问生产API。
调查期间的中断、端口占用和失败输出不计为通过。完整首轮暴露搜索框切换竞态，
等待旧首页退出、新详情页及目录就绪后再操作；独立重复5次通过。两个返回首页用例按返回前后边界精确要求1次capability GET，重复3轮共6项通过。

- `node --test apps/quant-web/tests/*.test.ts`：1129 passed、3 skipped。质量提示恢复后，3个旧单元夹具因遗漏API必需的 `reason_codes` 失败；补齐空数组后全量重新通过，不放宽生产输入合同。
- `pnpm -C apps/quant-web build`：能力生成产物检查、类型、Vite和bundle topology通过；保留既有chunk体积提示。
- `openspec validate --specs --strict --no-interactive`：11 passed。结构修复前的缺Scenario错误已在独立基线复现。
- `pytest tests/engineering/test_repository_hygiene.py tests/engineering/test_canonical_consistency.py tests/engineering/test_secret_scan.py -q -p no:cacheprovider`：34 passed。
- 全部改动 `.mjs` 的 `node --check`、改动路径secret scan、`git diff --check` 通过。
- 独立Review发现的返回请求统计遗漏与副图位置覆盖变宽已修复；最终无Confirmed Issue，精确原价保留边界已注明。

- `PLAYWRIGHT_PORT=5196 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs --output /private/tmp/guiyi-e2e-alignment-accepted-results`：201项，194 passed、7 skipped、0 failed；正常像素校验与默认timeout，未使用快照更新、ignore或重试。
- 7个默认skip包含3项隔离预览与4项真实后端只读验收；前者另以 `PLAYWRIGHT_CANDIDATE_PREVIEW=1 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/candidate-preview.spec.mjs --output /private/tmp/guiyi-e2e-alignment-preview-results` 实测3 passed。四项真实后端保持未运行，不能由fixture结果替代。
- 四项新增/恢复的两宽质量提示先红后绿，最终Home33 passed；实际截图 `/private/tmp/guiyi-home-quality-1440.png`、`/private/tmp/guiyi-home-quality-390.png` 由主代理复核，提示可读且不裁切。

日志位于 `/private/tmp/guiyi-e2e-alignment-accepted.log`、同前缀 `web-unit-accepted.log`、`build-final.log`、`openspec-final.log`；均为本地临时输出，稳定复现入口见 `TESTING.md`。
交付只至develop；不发布、不切换Runtime、不发送通知、不写生产数据。本任务合入后可通过普通Git revert回滚，无migration或生产数据回滚步骤。
