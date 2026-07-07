# section_index

Source: `api-rqamsc.md`

| Level | Title | line_range | apis |
| --- | --- | --- | --- |
| `2` | `打开网页版 RQAMS` | `1-8` | `go` |
| `2` | `登录` | `9-25` | `init` |
| `2` | `工作空间` | `26-68` | `get_workspaces`, `choose_workspace`, `current_workspace` |
| `3` | `**获取所有工作空间信息**` | `33-46` | `get_workspaces` |
| `3` | `**指定一个工作空间**` | `47-56` | `choose_workspace` |
| `3` | `**获取当前工作空间**` | `57-68` | `current_workspace` |
| `2` | `产品管理` | `69-237` | `list_products`, `get_product`, `update_product`, `delete_product` |
| `3` | `**获取全部产品信息**` | `71-125` | `list_products` |
| `3` | `**获取单个产品信息**` | `126-182` | `get_product` |
| `3` | `**修改单个产品信息**` | `183-210` | `update_product` |
| `3` | `**删除单个产品**` | `211-237` | `delete_product` |
| `2` | `产品组管理` | `238-392` | `list_product_groups`, `get_product_group`, `update_product_group`, `delete_product_group` |
| `3` | `**获取全部产品组信息**` | `240-281` | `list_product_groups` |
| `3` | `**获取单个产品组信息**` | `282-321` | `get_product_group` |
| `3` | `**修改单个产品组信息**` | `322-372` | `update_product_group` |
| `3` | `**删除单个产品组**` | `373-392` | `delete_product_group` |
| `2` | `重算` | `393-417` | - |
| `3` | `产品或产品组重算` | `395-417` | - |
| `2` | `交易流水管理` | `418-921` | `insert_product_trades_v2`, `insert_product_trades`, `upload_product_settlement_trade_file`, `insert_product_settlement_trade_file`, `list_product_trades`, `get_product_trades`, `delete_product_trades_by_date`, `delete_product_trades`, `run_import_trades_server`, `parse_xuntou_to_df`, `parse_ctp_txt_to_df`, `parse_caitong_txt_to_df` |
| `3` | `**给产品导入交易流水_v2**` | `420-463` | `insert_product_trades_v2` |
| `3` | `**给产品导入交易流水_v1**` | `464-501` | `insert_product_trades` |
| `3` | `**给产品导入结算交易流水_v2**` | `502-555` | `upload_product_settlement_trade_file` |
| `3` | `**给产品导入结算交易流水_v1**` | `556-570` | `insert_product_settlement_trade_file` |
| `3` | `**获取产品的交易流水_v2**` | `571-604` | `list_product_trades` |
| `3` | `**获取产品的交易流水_v1**` | `605-622` | `get_product_trades` |
| `3` | `**按检索条件删除流水**` | `623-681` | `delete_product_trades_by_date` |
| `3` | `**删除产品的交易流水**` | `682-704` | `delete_product_trades` |
| `3` | `**交易流水文件自动化导入 AMS**` | `705-800` | `run_import_trades_server` |
| `3` | `**交易流水文件自定义导入 AMS**` | `801-834` | `parse_xuntou_to_df`, `parse_ctp_txt_to_df`, `parse_caitong_txt_to_df` |
| `3` | `**RQAlpha 回测流水自动导入 AMS 使用说明**` | `835-921` | - |
| `2` | `持仓单管理（DMA 场景） {#positions-statement-management}` | `922-1010` | `upload_positions_statement_file`, `get_positions_statement`, `delete_positions_statement` |
| `3` | `**给资产单元导入持仓单**` | `924-953` | `upload_positions_statement_file` |
| `3` | `**获取资产单元持仓单**` | `954-986` | `get_positions_statement` |
| `3` | `**删除资产单元持仓单**` | `987-1010` | `delete_positions_statement` |
| `2` | `估值表管理` | `1011-1225` | `list_inserted_valuation_reports`, `upload_valuation_reports`, `upload_valuation_reports_in_directories`, `delete_product_valuation_reports`, `download_product_valuation_reports`, `run_vr_importer` |
| `3` | `**查看产品已导入估值表信息**` | `1013-1049` | `list_inserted_valuation_reports` |
| `3` | `**给产品导入估值表_v2**` | `1050-1091` | `upload_valuation_reports` |
| `3` | `**给产品导入估值表_v1**` | `1092-1105` | - |
| `3` | `**上传估值表文件_v1**` | `1106-1120` | `upload_valuation_reports_in_directories` |
| `3` | `**删除产品已导入的估值表**` | `1121-1143` | `delete_product_valuation_reports` |
| `3` | `**下载已导入的估值表文件**` | `1144-1173` | `download_product_valuation_reports` |
| `3` | `**本地估值表文件自动化导入**` | `1174-1225` | `run_vr_importer` |
| `2` | `模拟交易` | `1226-1480` | `list_paper_trading`, `get_paper_trading`, `update_paper_trading`, `delete_paper_trading`, `recompute_paper_trading`, `upload_paper_trading_file`, `list_paper_trading_signals`, `delete_paper_trading_signals`, `get_paper_trading_signal_details` |
| `3` | `**获取所有模拟交易**` | `1228-1265` | `list_paper_trading` |
| `3` | `**获取单个产品的模拟交易配置**` | `1266-1283` | `get_paper_trading` |
| `3` | `**更新模拟交易配置**` | `1284-1309` | `update_paper_trading` |
| `3` | `**删除模拟交易配置**` | `1310-1329` | `delete_paper_trading` |
| `3` | `**重新计算模拟交易**` | `1330-1353` | `recompute_paper_trading` |
| `3` | `**上传模拟交易文件**` | `1354-1384` | `upload_paper_trading_file` |
| `3` | `**获取模拟交易信号列表**` | `1385-1415` | `list_paper_trading_signals` |
| `3` | `**删除模拟交易信号**` | `1416-1444` | `delete_paper_trading_signals` |
| `3` | `**获取模拟交易信号撮合详情**` | `1445-1480` | `get_paper_trading_signal_details` |
| `2` | `持仓及衍生指标` | `1481-1855` | `get_balance`, `get_indicators`, `get_indicators_series`, `get_asset_snapshot`, `get_balance_series`, `get_weekly_net_value_report` |
| `3` | `**获取产品或产品组单日头寸**` | `1483-1536` | `get_balance` |
| `3` | `**获取产品或产品组指标**` | `1537-1661` | `get_indicators` |
| `3` | `**获取产品或产品组时序指标**` | `1662-1709` | `get_indicators_series` |
| `3` | `**获取产品或产品组实时信息**` | `1710-1776` | `get_asset_snapshot` |
| `3` | `**获取产品或产品组头寸序列**` | `1777-1831` | `get_balance_series` |
| `3` | `**获取产品或产品组净值周度报告**` | `1832-1855` | `get_weekly_net_value_report` |
| `2` | `绩效归因` | `1856-1953` | `get_performance_attribution`, `get_returns_decomposition` |
| `3` | `**获取产品或产品组绩效归因**` | `1858-1923` | `get_performance_attribution` |
| `3` | `**获取产品或产品组收益拆解**` | `1924-1953` | `get_returns_decomposition` |
| `2` | `投资驾驶舱` | `1954-2378` | `get_investment_overview_summary_indicator`, `get_investment_overview_returns_series`, `get_investment_overview_asset_capital_size`, `get_investment_overview_asset_allocation`, `get_investment_overview_excess_correlation`, `get_investment_overview_returns_correlation` |
| `3` | `**批量获取产品或产品组概览指标**` | `1956-2102` | `get_investment_overview_summary_indicator` |
| `3` | `**批量获取产品或产品组回报趋势**` | `2103-2205` | `get_investment_overview_returns_series` |
| `3` | `**批量获取产品或产品组资产规模走势**` | `2206-2235` | `get_investment_overview_asset_capital_size` |
| `3` | `**批量获取产品或产品组资产配置**` | `2236-2273` | `get_investment_overview_asset_allocation` |
| `3` | `**批量获取产品或产品组超额收益相关性**` | `2274-2342` | `get_investment_overview_excess_correlation` |
| `3` | `**批量获取产品或产品组收益相关性**` | `2343-2378` | `get_investment_overview_returns_correlation` |
| `2` | `自定义基准管理` | `2379-2496` | `list_customized_benchmarks`, `create_customized_benchmark`, `get_customized_benchmark`, `update_customized_benchmark`, `delete_customized_benchmark` |
| `3` | `**查看自定义基准列表**` | `2381-2421` | `list_customized_benchmarks` |
| `3` | `**创建一个自定义基准**` | `2422-2435` | `create_customized_benchmark` |
| `3` | `**获取某个自定义基准信息**` | `2436-2453` | `get_customized_benchmark` |
| `3` | `**更新某个自定义基准信息**` | `2454-2476` | `update_customized_benchmark` |
| `3` | `**删除某个自定义基准**` | `2477-2496` | `delete_customized_benchmark` |
| `2` | `自定义合约管理` | `2497-2602` | `list_customized_instruments`, `create_customized_instrument`, `add_customized_instrument`, `get_customized_instrument_price`, `upload_customized_instrument_price`, `delete_customized_instrument` |
| `3` | `**查看自定义合约列表**` | `2499-2510` | `list_customized_instruments` |
| `3` | `**新增自定义合约_v2**` | `2511-2528` | `create_customized_instrument` |
| `3` | `**新增自定义合约_v1**` | `2529-2540` | `add_customized_instrument` |
| `3` | `**获取某个自定义合约价格**` | `2541-2561` | `get_customized_instrument_price` |
| `3` | `**上传更新某个自定义合约价格**` | `2562-2582` | `upload_customized_instrument_price` |
| `3` | `**删除某些自定义合约**` | `2583-2602` | `delete_customized_instrument` |
| `2` | `托管事件管理` | `2603-2699` | `list_custodian_events`, `insert_custodian_events`, `update_custodian_event`, `delete_custodian_events` |
| `3` | `**获取某个产品的托管事件列表**` | `2605-2626` | `list_custodian_events` |
| `3` | `**给某个产品增加托管事件**` | `2627-2651` | `insert_custodian_events` |
| `3` | `**修改产品下的一个托管事件**` | `2652-2676` | `update_custodian_event` |
| `3` | `**删除产品的一些托管事件**` | `2677-2699` | `delete_custodian_events` |
| `2` | `份额事件管理` | `2700-2794` | `list_unit_events`, `insert_unit_events`, `update_unit_event`, `delete_unit_events` |
| `3` | `**获取某个产品的份额事件列表**` | `2702-2724` | `list_unit_events` |
| `3` | `**给某个产品增加份额事件**` | `2725-2748` | `insert_unit_events` |
| `3` | `**修改产品下的一个份额事件**` | `2749-2771` | `update_unit_event` |
| `3` | `**删除产品的一些份额事件**` | `2772-2794` | `delete_unit_events` |
| `2` | `自定义指标管理` | `2795-2916` | `get_customized_indicators`, `upsert_customized_indicators`, `insert_customized_indicators`, `update_customized_indicators`, `delete_customized_indicators` |
| `3` | `**获取产品或产品组下的自定义指标**` | `2797-2857` | `get_customized_indicators` |
| `3` | `**创建或修改产品或产品组下的自定义指标**` | `2858-2878` | `upsert_customized_indicators` |
| `3` | `**创建产品或产品组下的自定义指标**` | `2879-2887` | `insert_customized_indicators` |
| `3` | `**修改产品或产品组下的自定义指标**` | `2888-2896` | `update_customized_indicators` |
| `3` | `**删除产品或产品组下的自定义指标**` | `2897-2916` | `delete_customized_indicators` |
| `2` | `交易分析` | `2917-3031` | `get_trading_analysis_list`, `get_single_trading_analysis` |
| `3` | `获取产品或产品组交易分析列表` | `2919-2952` | `get_trading_analysis_list` |
| `3` | `获取单个交易分析` | `2953-3031` | `get_single_trading_analysis` |
| `2` | `一些字段的取值参考` | `3032-3050` | - |
| `3` | `交易属性` | `3034-3050` | - |
| `2` | `一些关键的类` | `3051-3662` | - |
| `3` | `工作空间对象` | `3053-3070` | - |
| `3` | `产品对象` | `3071-3190` | - |
| `3` | `产品组对象` | `3191-3217` | - |
| `3` | `估值表对象` | `3218-3243` | - |
| `3` | `交易流水对象` | `3244-3272` | - |
| `3` | `交易流水来源` | `3273-3289` | - |
| `3` | `资产类型` | `3290-3344` | - |
| `3` | `交易类型` | `3345-3426` | - |
| `3` | `持仓方向` | `3427-3439` | - |
| `3` | `业绩归因模板对象` | `3440-3453` | - |
| `3` | `自定义基准对象` | `3454-3572` | - |
| `3` | `自定义基准成分权重对象` | `3573-3590` | - |
| `3` | `自定义合约对象` | `3591-3608` | - |
| `3` | `托管事件对象` | `3609-3632` | - |
| `3` | `份额事件对象` | `3633-3651` | - |
| `3` | `通用异常对象(exception, 可用于捕获处理对应异常)` | `3652-3662` | - |
