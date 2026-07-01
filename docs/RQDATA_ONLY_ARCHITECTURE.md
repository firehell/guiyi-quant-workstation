1. 项目定位：
   本地运行的国内期货量化研究、回测、实时预警、人工观察和复盘工作站。

2. 项目不做：
   - 全自动实盘
   - AI 自动下单
   - 无人值守交易
   - 云端 SaaS
   - 直接接 CTP 下单
   - 直接接 TqSdk 下单
   - 信号扫描直接触发下单

3. RQData-only 总原则：
   - primary source = RQData
   - historical source = RQData
   - realtime source = RQData
   - research source = RQData
   - backtest source = Local Standard Parquet generated from RQData

4. 被移除的数据线：
   - 天勤历史下载数据线
   - 交易练习者数据线
   - TuShare / AKShare 期货分钟数据线
   - CTP / TqSdk 实盘或模拟盘下单线

5. 新主链路：
   RQData
   → Vendor Raw Layer
   → Canonical Data Layer
   → Local Standard Parquet
   → DuckDB
   → vn.py CTA BacktestingEngine
   → ResultConverter
   → PostgreSQL
   → FastAPI
   → Vue Web
   → K线复盘 / 信号提醒 / 人工观察 / 复盘

6. 实时数据链路：
   RQData realtime
   → realtime_staging
   → canonical bars_1m
   → aggregation 5m / 15m / 30m
   → indicator calculation
   → signal_events
   → notification_deliveries
   → 企业微信只读提醒
   → Web Signal Center
   → Review Note

7. 数据分层设计：
   - Vendor Raw Layer
   - Canonical Data Layer
   - Local Standard Parquet
   - DuckDB query layer
   - PostgreSQL business facts

8. 正式数据过滤规则：
   - source = rqdata / local_parquet
   - data_role = primary
   - quality_status != failed
   更严格时：
   - quality_status = passed

9. signal_events 和 notification_deliveries 设计原则。

10. Web 模块：
    - Data Center
    - Market Center
    - Backtest Center
    - Signal Center
    - Review Center
    - Ops Center
    - Strategy Lab
    - Research Governance

11. 天勤备用定位：
    天勤当前只作为 future backup provider，不是当前主链路、validation source、realtime source 或 trading provider。

12. 期权预留：
    当前不做期权主线，但保留 option instruments / chain / greeks / iv / pcr / skew 的未来扩展位置。

13. 敏感信息规则：
    文档、代码、任务文件不得包含账号、密码、Token、license、API Key、真实 webhook URL 或交易密钥。