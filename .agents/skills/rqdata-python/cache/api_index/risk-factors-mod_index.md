# API Index for risk-factors-mod.md

## Summary

- Source File: risk-factors-mod.md
- Total APIs: 7

## API Definitions (Sorted by Line Number)

| API Name | Description | Line Range |
|----------|-------------|------------|
| `get_factor_exposure` | 获取一组股票的因子暴露度<br/>获取一组股票的因子暴露度数据，支持按时间范围、行业分类和风险模型查询风格因子及行业因子暴露度。例如可获取 momentum、beta、book_to_price 等风格因子暴露度，也包括银行、计算机、环保等行业因子暴露度。 | 279-336 |
| `get_descriptor_exposure` | 获取一组股票的细分风格因子暴露度<br/>获取一组股票的细分风格因子暴露度数据，支持按时间范围、行业分类和风险模型查询。例如可获取 earnings_growth、cash_earnings_to_price_ratio、sales_growth 等细分风格因子暴露度。 | 337-391 |
| `get_stock_beta` | 获取个股相对于某个基准的贝塔<br/>获取个股相对于指定基准指数的贝塔数据，支持按时间范围、行业分类和风险模型查询。例如基准指数可选沪深 300、上证 50、中证 500，也支持中证 800 和中证全指。 | 392-432 |
| `get_factor_return` | 获取因子收益率<br/>获取因子收益率数据，支持按时间范围、股票池、行业分类和风险模型查询。例如可获取全市场、沪深 300、中证 500 等股票池的因子收益率，也支持 implicit 和 explicit 两种计算方法。 | 433-477 |
| `get_specific_return` | 获取个股特异收益率<br/>获取个股特异收益率数据，支持按时间范围、行业分类和风险模型查询单只或多只股票。例如可查询 600705.XSHG 的特异收益率，也可获取 600705.XSHG、600100.XSHG 等股票在 `sws_2021` 或 `citics_2019` 分类下的数据。 | 478-543 |
| `get_factor_covariance` | 获取因子协方差矩阵<br/>获取指定日期的因子协方差矩阵数据，支持不同预测期限、行业分类和风险模型。例如预测期限可选日度、月度、季度，也支持 `sws_2021` 和 `citics_2019` 行业分类下的因子协方差矩阵。 | 544-642 |
| `get_specific_risk` | 获取一组股票的特异波动率<br/>获取一组股票的特异波动率数据，支持按时间范围、预测期限、行业分类和风险模型查询。例如可获取单只股票或多只股票的特异波动率，也支持日度、月度、季度三种预测期限。 | 643-708 |

