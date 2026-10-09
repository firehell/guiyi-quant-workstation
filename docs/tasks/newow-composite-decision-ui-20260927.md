# 日周综合决策展示与公开输入对照

日期：2026-09-27。实现基线：develop `ab2945e2765da4b03ad0e67c60b2b837cc891f37`。
范围：CDV2 日周解释、UI和交互；不开放60m、不写行情或账户、不切换正式Runtime。

## 研究依据

对照[复刻手册](../research/newow-v3.2.82/REPLICATION_MANUAL.md)、[原式卷第9节](../research/newow-v3.2.82/REPLICATION_MANUAL.md#s-4e9df33bc9)、用户截图及公开详情页实现。
本次重新读取 [CDV2公开脚本](https://www.v8848.cn/composite-decision-v2.js?v=3.3.59)，SHA256为 `68c634c05bddc7191de884a37ae5c8877dfd8416a43e53d93c66838ea8585fbb`，与既有内核来源一致。公开详情源的折叠默认、评分拆分、R/MM说明、第一行动原则及独立依据展开均已核对；不保存第三方完整脚本、HTML或原始行情到仓库。

使用四只股票公开日周响应（每只趋势/震荡×日/周，16次读取），最新数据端点2026-09-24。把同一份日周输入分别送入原版脚本和本地既有数值内核，total、R、MM及参考上限4/4一致；不含60分钟及J额外扣分，因此不能与原站完整三周期可见总分直接比较。

| 股票 | 趋势周/日 | 震荡周/日 | 日波动率 | 五分项：趋势/震荡/共振/方向/波动 | 总分 | R / MM | 参考上限 |
|---|---|---|---|---|---|---|---|
| 西部超导688122 | hold/hold | holding/cleared | 2.6% | 24/22/10/12/−3 | 65 | R2/MM4 | 30% |
| 江海股份002484 | wait/wait | holding/holding | 6.6% | 24/22/10/12/−8 | 60 | R2/MM3 | 30% |
| 盛科通信688702 | wait/hold | holding/cleared | 6.3% | 24/22/10/6/−8 | 54 | R2/MM1 | 30% |
| 国瓷材料300285 | hold/hold | cleared/cleared | 5.4% | 24/22/10/12/−8 | 60 | R2/MM1 | 30% |

这些样本覆盖回补窗口、趋势转蓝但震荡未清、周日背离和趋势多/震荡空。完整R0–R4、MM1–MM4及等待状态由既有内核测试与新增展示测试覆盖，不能把四样本称为全量原站验收。原站batch可把cross_age强制为0，且batch状态与详情K线末次信号不一定相同；归一期货适配仍使用同合约、同计算Segment的真实日K计龄，不为触发MM3/MM4伪造最新交叉。0根显示“最新一根”，不会显示“1根前”。

## 实现

- 数值内核、MM/R优先顺序、双轴仓位及原始阈值不改；仅增加 `guiyi_cdv2_daily_weekly_presentation_v1`。日周满分24+22+20+12=78，无分钟补分或100分归一化。
- 第一行动原则复用已有优先链。趋势双空、周空日多、周多日空、震荡退出等提示独立展示；缺失日周输入不产生可操作的正常确认。省略小时不作为小时确认。文案取消股票指数和固定股票配置假设，保留原始CDV2行动及参考强度，不把解释变成策略Gate。
- UI显示评分条、确定性、R/MM、第一行动提示、五项分数、共振说明和结论。整体默认折叠，记住偏好；“展开依据”独立控制波动率、四组日周状态/年龄、方向、扣分、来源和参考价格。身份切换取消请求、清空旧结果并收起依据；加载及失败信息在折叠时仍可见。
- 当前CDV2、状态摘要和主图价格均沿用各自来源。参考强度不是期货保证金、手数或账户持仓；没有新增模拟成交或账户行为。

## 验证与边界

- 后端：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/newow/test_cdv2_presentation.py services/quant-api/tests/newow/test_cdv2.py services/quant-api/tests/newow/test_composite_explanation.py services/quant-api/tests/newow/test_product_service.py`，187 passed。
- 前端：`node --test tests/newowDecisionV2Panel.test.ts tests/newowDecisionV2Presentation.test.ts tests/newowStatusCardPresentation.test.ts`，12 passed；`npm test`，703 passed、1 skipped；`npm run build`通过。
- Ruff定向检查通过；独立只读Review无Confirmed Issue，结论允许集成develop。
- `openspec validate newow-product-reference-trading --type spec --strict --no-interactive`通过；全仓spec检查9通过/1失败，未修改的reference-trading有两处Requirement位于Requirements主节外。本任务不顺手修订该合同。定向secret scan零发现，`git diff --check`通过。
- 本地5186/只读API8012真实JM日线显示54分、R1、0%，双趋势空仓警示和减仓观望结论；展开依据读到真实4.2%波动率、日周状态及年龄。截图在本地 `outputs/newow-composite-ui-20260927/`，不作为正式发布或Runtime验收。
- JM周视图现场也显示54分/R1/0%，同一已完成日周上下文保持一致；状态卡价格独立切为周线1763.5/1300，依据折叠在周期切换后关闭，未沿用日线价格。
- 原站实时浏览器操作遇连接超时，原站多股票的视觉验收未完成；多个状态的理解来自公开响应、原版源和用户截图。窄屏测试的浏览器视窗覆盖未实际生效，DOM仍为1280px，已恢复覆盖，因此不声称390px现场验收通过；响应CSS与行为单测不是窄屏截图证据。
- 正式8000/5173、Release、Runtime及数据写入均未涉及。60m后续补齐时必须按其真实事实输入验证，不能据本轮结果声称完整三周期已验收。
