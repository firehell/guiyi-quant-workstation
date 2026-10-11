# 首页日周策略卡（2026-10-09）

首页行情区以策略卡为主，保留品种搜索、板块筛选、报价与排序。趋势、震荡分别显示 D1/W1 状态；展开后各自选择周期，查看四阶段、目标价、吸筹价、参考成本、目标空间、最近动作与数据截止时间。标题进入趋势日线，图表入口保留策略与周期，返回恢复页面状态。

视觉现场参考牛哇首页 v3.3.74 的白色圆角卡片、状态配色和空仓→建仓→持有→清仓轨道。未复制私有准确率、排名、服务端 phase 或缺价时的乘数猜测。

只读 `/api/v1/market/newow/home-cards?products=rb` 最多接受12个唯一品种；前端每请求一个品种、最多两请求并发，使用现有日周快照解析、reader、回放、缓存与资源门。每个周期单独失败，过期请求不能覆盖新状态。完整 replay 在图表分页前投影参考成本，要求同一物理合约、Segment、计算段和 eligible BUILD；不创建成交或仓位。

价格使用现有 chart_legend 的版本化 HHV/LLV10 投影；目标空间为 `(target-reference_current)/reference_current*100`，保留负值。参考当前价来自同一 Canonical 周期，最新报价时间独立显示。预热/缺价隐藏策略状态、价格和成本。响应保留公式、输入哈希、source、owner 和快照身份，`page_parity=true/executable=false`。

候选能力 v34 修正已有 D1/W1 候选响应与前端旧 v9 校验不一致的问题；产品、周期和候选阶段不变，v9 历史契约保持严格，正式 v33 能力不变。

验证：

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow/test_home_cards.py services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_candidate_preview.py`：397 passed。
- 在 `apps/quant-web` 执行 `npm run build` 和 `node --test tests/marketHome*.test.ts tests/newowHomeCards.test.ts tests/candidatePreview.test.ts tests/newowProductTypes.test.ts tests/newowCapabilities.test.ts tests/newowExplanationPanel.test.ts`：构建通过、180 passed（包含并发远端集成后的相关回归）。
- secret scan：0 findings；独立审查允许集成 develop。
- 只读真实 RB/I 接口返回200，四组日周事实 ready；黑色系5张卡片完成真实页面读取，包含 SF 日线建仓/周线清仓。桌面和390px手机无横向溢出，独立周期切换、图表导航和返回恢复通过。

限制：首次 Canonical 冷读取较慢，RB约29秒、I在并发下约61秒，前端逐卡显示进度。本次没有把60品种并发测试当作60品种真实页面逐值验收，也没有发布或切换 Runtime。
