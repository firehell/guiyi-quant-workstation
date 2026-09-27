# 牛哇 AI 分析：日周四组合

实现范围：按钮位于双策略后、火天大有前；点击才请求 `/market/newow/ai-analysis` 并打开原版风格弹窗。含加载/错误、重新回测、推荐说明、震荡/趋势两列日周指标卡、推荐边框、评分排行、知道了/采纳推荐、Escape/遮罩关闭与焦点恢复。采纳仅切换页面策略/周期，退出双策略，不更改正式策略或 Runtime；60m 不参与。

来源：2026-09-27重新获取并实看 v3.3.59 西部超导详情页。公开 HTML SHA256 `b12da74d89a7ac304d7479999d11f13ab53ced834a8472f937d78a0c1bd03709`。原页加载、六卡、评分、推荐及采纳切到趋势周线均观察到；原页函数 runOscBacktest/runTrendBacktest/scoreCombos 未调用大模型。鼠标自动化点击没有触发，键盘 Enter 完成原页及本地实际交互；组件事件另有测试。

公式与边界见手册第16节、OpenSpec `Independent AI page-analysis ranking v1`。独立版本与期货分段适配：`newow_ai_summary_ranking_page_v1` / `guiyi_newow_ai_segment_valuation_v1`。此分析包含各物理/质量段末收盘参考估值；现有 ReferenceTrade、融合和已完成交易收益不变。采用固定原AI请求窗口，非当前主图加载缓存长度；本地completed-only、期货分段及四组重新归一化均明确披露，不能声明股票六组全页一致或因果收益。

真实预览：开发 API 8012仅GET且依赖数据库事务强制 `READ ONLY`，Web 5186指向该API；正式8000/5173和Runtime仍未切换。JM截至2026-09-24的结果：

| 组合 | 累计参考收益 | 胜率 | 回撤百分点 | 次数 | 其中段末估值 | 分数 |
|---|---:|---:|---:|---:|---:|---:|
| 震荡周 | -2.52 | 33 | 24.88 | 6 | 6 | 0.0 |
| 震荡日 | 38.31 | 73 | 12.53 | 11 | 3 | 62.7 |
| 趋势周 | 60.21 | 100 | 7.10 | 4 | 2 | 85.0 |
| 趋势日 | 51.79 | 74 | 8.40 | 19 | 3 | 80.6 |

现场完成：趋势单策略→双策略→AI；重新回测先清空旧推荐/加载，再显示同一结果；采纳关闭弹窗并切为趋势周K，真实周线数据加载；Escape关闭、重新打开请求；弹窗截图 `outputs/newow-release-v1.10.38-20260927/ai-analysis-preview.png`。该四组/其中段末估值不代表四份可执行策略回测，较少样本的推荐已显示提醒。

现场共享计算槽繁忙时返回429；页面单独提示图表或融合参考仍在计算，手动重新回测后正常展示四组结果。传输异常仅保留安全错误码，不展示原始异常详情。

实际验证：
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/newow/test_ai_analysis.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_product_reader.py services/quant-api/tests/newow/test_page_comparator.py`：214 passed / 1 existing gated skip。
- `node --test tests/newowAiAnalysis.test.ts tests/newowFusionPanel.test.ts`：5 passed；完整 `npm test`：695 passed / 1 existing skip。
- `npm run build`：vue-tsc/Vite/bundle topology通过，既有 request.ts 静/动态导入提示仍在。
- 公共源oracle含6输入案例×2策略摘要和四组合评分；`node tools/build_newow_ai_oracle.mjs <冻结详情HTML> <冻结strategy-calc.js>`校验源hash再生成fixture，oracle SHA256 `71fada93d1d2a8d0edb5b28791ba2095afed20e7482ba64b64885ffc2ee35a83`。
- 独立Review发现并修复模式切换丢失截止点与分段身份未入摘要两个问题；复审19后端/2前端通过，允许集成develop。

未创建新tag/Release、未切换正式Runtime，60m与OOS/执行未纳入本次完成声明。
