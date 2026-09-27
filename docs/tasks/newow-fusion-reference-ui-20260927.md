# 双策略融合参考展示统一

按owner截图，将双策略下方表格主体改为与趋势/震荡一致的策略收益率走势和回测操盘提醒。
复用同一scoped CSS与精确十进制曲线/回撤校验；融合内核、API、配对与零成本页面参考口径不变。
融合来源、OPEN浮动、换月/数据中断、近三月期初已有均保留，三组独立统计/配对规则收进详情。
收益窗口只影响曲线/指标，近三月记录与主图独立；曲线定位的旧记录单独标识“近三个月外”。
完整记录逐笔累计必须匹配权威摘要；记录截断或事实不一致时不绘制完整曲线，不推造融合理论值。

实际验证：
- 前端完整测试：693 passed / 1 skipped；最终定向newowFusionPanel/newowReferenceCurve/NewowReferencePanel：27 passed。
- vue-tsc/Vite/bundle topology与git diff --check通过，既有request.ts静/动态import提示仍在。
- 真实8000只读API配合5186预览，JM D1融合普通累计232.9628（显示232.96%）、76笔，胜率69.7%、最大回撤3.69%；OPEN浮动-4.52%独立展示。
- 键盘Enter实际切换近3月：13.49%、5笔；切回全部：232.96%、76笔，提醒卡片不随之替换。
- 鼠标自动化点击存在屏幕/DOM坐标偏差，未作为现场鼠标验收；键盘与组件事件验证通过。
- 截图：outputs/newow-release-v1.10.38-20260927/fusion-reference-ui-preview.png。

实现已在develop，预览地址http://127.0.0.1:5186；正式5173仍是v1.10.38，未创建新tag/Release或替换正式Runtime。
