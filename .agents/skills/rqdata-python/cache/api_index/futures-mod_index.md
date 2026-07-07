# API Index for futures-mod.md

## Summary

- Source File: futures-mod.md
- Total APIs: 14

## API Definitions (Sorted by Line Number)

| API Name | Description | Line Range |
|----------|-------------|------------|
| `futures.get_dominant` | 获取主力合约<br/>获取某一期货品种在一段时间内的主力合约数据。例如可查询主力、次主力、次次主力合约，也支持 `rule=0`、`rule=1`、`rule=2`、`rule=3` 等不同主力合约选取规则。 | 45-99 |
| `futures.get_contracts` | 获取期货可交易合约列表<br/>获取指定期货品种在指定日期可交易的合约列表，结果按到期月份排序。 | 100-128 |
| `futures.get_dominant_price` | 获取期货主力连续合约行情数据<br/>获取期货主力连续合约行情数据，支持日线、分钟线和 tick 级别数据。例如可按 `pre`、`none` 等复权方式查询，也支持 `prev_close_spread`、`open_spread` 等不同平滑方法。 | 129-243 |
| `futures.get_ex_factor` | 获取期货主力连续合约复权因子<br/>获取期货主力连续合约复权因子数据。例如复权方法可选 `prev_close_spread`、`open_spread`、`prev_close_ratio`，也支持 `open_ratio`。 | 244-288 |
| `futures.get_contract_multiplier` | 获取期货品种合约乘数<br/>获取期货品种的合约乘数数据，支持按时间范围查询。 | 289-334 |
| `futures.get_exchange_daily` | 获取期货交易所日线数据<br/>获取期货交易所日线数据，支持按合约、时间范围和字段查询。 | 335-392 |
| `futures.get_continuous_contracts` | 获取期货当月等连续合约<br/>获取股指期货和商品期货的连续合约数据。例如类型可选 `front_month`、`next_month`，股指期货还支持 `current_quarter` 和 `next_quarter`。 | 393-456 |
| `futures.get_member_rank` | 获取期货会员持仓等排名情况<br/>获取期货某合约或品种的会员排名数据。例如可按成交量、持买仓量、持卖仓量查询排名，分别对应 `volume`、`long`、`short`。 | 457-564 |
| `futures.get_warehouse_stocks` | 获取期货仓单数据<br/>获取期货品种的注册仓单数据，支持按时间范围查询。 | 565-615 |
| `futures.get_basis` | 获取股指期货每日升贴水数据<br/>获取股指期货升贴水数据，支持日线、分钟线和 tick 级别查询。例如可查询每日升贴水数据，也支持分钟级和 tick 级升贴水数据。此处分红调整数据来源于[API-get_predicted_dividend_point](futures-mod.md#rqdata-API-futures-get_predicted_dividend_point)。 | 616-669 |
| `futures.get_current_basis` | 获取股指期货实时升贴水数据<br/>获取股指期货实时升贴水数据，计算逻辑与 `get_basis` 一致。此处分红调整数据来源于[API-get_predicted_dividend_point](futures-mod.md#rqdata-API-futures-get_predicted_dividend_point)，采用当日分红预测点位进行调整。 | 670-713 |
| `futures.get_trading_parameters` | 获取期货交易参数信息<br/>获取期货交易参数信息。例如可获取保证金、手续费、限仓等交易参数数据。<br/>::: tip 注意事项<br/>- start_date 和 end_date 需同时传入或同时不传入。当不传入 start_date , end_date 参数时，查询时间在交易日 T 日 6.30 pm 之前，返回 T 日的数据；查询时点在 6.30pm 之后，返回交易日 T+1 日的数据。 - 保证金、手续费数据提供范围为 2010.04 月至今；限仓数据各交易所提供范围见下方表格<br /> | 714-799 |
| `futures.get_roll_yield` | 获取商品期货展期收益率数据<br/>获取商品期货展期收益率数据。例如类型可选 `main_sub` 和 `near_main`，也支持不同主力合约选取规则。 | 800-846 |
| `futures.get_predicted_dividend_point` | 获取股指期货预测分红点位<br/>::: tip 计算逻辑说明<br/>$$分红点位_{T-t}=\sum(成分股每股分红金额/成分股股价_t)*成分股权重_t*指数收盘价_t$$ 其中，$t＜t_n ≤T$的成分股分红点位才会被计算在内，$t_n$是成分股$n$的除权除息日。<br/>此处，若公司已公布具体分红方案，则采用实际分红金融及除权除息日纳入计算。若公司未公布具体分红方案则会对其进行预测，分红金额的预测存在以下两种情况： (1) 若公司已公布分红预案或是决案，分红金额将采用已公布方案中的数据；<br> (2) 若未公布则按下述公式进行预测，净利润采用最新披露的年报/业绩快报/业绩预告用于计算，若无对应数据则为过去三年对应季度的平均值，股息支付率则始终为过去三年的平均值。 $$每股分红金额=预测分红季度净利润*过去三年平均股息支付率/预测日总股本$$ $$股息支付率=现金分红总额/净利润$$<br/>对于除权除息日的预测同样存在两种情况： (1) 若公司已公布分红预案或是决案，除权除息日为方案公布日+avg(gap)；<br> (2) 若未公布，则认为该年该股票分红情况同历史最近年度的分红情况一致.<br/>::: | 847-908 |

