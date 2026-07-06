# RQData Readonly PoC Result

- mode: `readonly`
- writes_data: `False`
- writes_database: `False`
- writes_parquet: `False`

## Credential Sources

- `RQDATAC2_CONF`: `missing`
- `RQDATAC_CONF`: `present`
- `RQDATA_LICENSE_KEY`: `present`
- `RQDATA_USERNAME`: `missing`
- `RQDATA_PASSWORD`: `missing`
- `RQDATA_ADDR`: `missing`

## Capability Matrix

| capability | status | api_name | wrapper_name | error_type | sample_row_count | sample_columns | notes |
|---|---|---|---|---|---:|---|---|
| rqdatac_import | pass | import rqdatac |  |  | 1 | __version__ | version=3.2.5 |
| rqdata_auth_init | pass |  | RqDataClient |  | 0 |  |  |
| jm_contract_catalog | pass | all_instruments(type='Future') | RqDataClient.all_future_instruments |  | 5 | index, order_book_id, underlying_symbol, market_tplus, symbol, margin_rate, maturity_date, type, trading_code, exchange, product, contract_multiplier, round_lot, trading_hours, listed_date, industry_name, de_listed_date, underlying_order_book_id, start_delivery_date, end_delivery_date | inspect returned fields for JM/DCE support; script does not persist rows |
| dce_jm_contract_list | pass | futures.get_contracts | RqDataClient.listed_contracts |  | 5 | contract, date |  |
| historical_1d_sample | pass | futures.get_exchange_daily or get_price(frequency='1d') | RqDataClient.exchange_daily |  | 2 | order_book_id, date, open, close, high, low, total_turnover, volume, settlement, prev_settlement, open_interest |  |
| historical_1m_sample | pass | get_price(frequency='1m') | RqDataClient.contract_bars |  | 5 | order_book_id, datetime, trading_date, open_interest, low, high, close, open, total_turnover, volume |  |
| frequency_5m_direct | pass | get_price(frequency='5m') | RqDataClient.contract_bars |  | 5 | order_book_id, datetime, trading_date, open_interest, low, high, close, open, total_turnover, volume | pass means direct API shape is available; row quality is not certified by this PoC |
| frequency_15m_direct | pass | get_price(frequency='15m') | RqDataClient.contract_bars |  | 5 | order_book_id, datetime, trading_date, open_interest, low, high, close, open, total_turnover, volume | pass means direct API shape is available; row quality is not certified by this PoC |
| frequency_30m_direct | pass | get_price(frequency='30m') | RqDataClient.contract_bars |  | 5 | order_book_id, datetime, trading_date, open_interest, low, high, close, open, total_turnover, volume | pass means direct API shape is available; row quality is not certified by this PoC |
| frequency_1h_direct | pass | get_price(frequency='60m') | RqDataClient.contract_bars |  | 5 | order_book_id, datetime, trading_date, open_interest, low, high, close, open, total_turnover, volume | pass means direct API shape is available; row quality is not certified by this PoC |
| trading_calendar | pass | get_trading_dates | RqDataClient.trading_dates |  | 2 | value |  |
| trading_sessions | pass | get_trading_hours/get_trading_periods | RqDataClient.trading_periods |  | 0 |  |  |
| dominant_mapping | pass | futures.get_dominant | RqDataClient.dominant_contracts |  | 2 | date, dominant |  |
| continuous_contracts | pass | futures.get_continuous_contracts | RqDataClient.continuous_contracts |  | 0 |  |  |
| ex_factor | pass | futures.get_ex_factor | RqDataClient.ex_factor |  | 0 | ex_date, ex_factor, ex_end_date, ex_cum_factor |  |
| contract_multiplier | pass | futures.get_contract_multiplier/all_instruments | RqDataClient.contract_multiplier |  | 1 | value |  |
| margin | pass | futures.get_trading_parameters | RqDataClient.trading_parameters |  | 2 | order_book_id, trading_date, long_margin_ratio, short_margin_ratio, commission_type, open_commission, close_commission, discount_rate, close_commission_today, non_member_limit_rate, client_limit_rate, non_member_limit, client_limit, min_order_quantity, max_order_quantity, min_margin_ratio | check long_margin_ratio/short_margin_ratio columns |
| commission | pass | futures.get_trading_parameters | RqDataClient.trading_parameters |  | 2 | order_book_id, trading_date, long_margin_ratio, short_margin_ratio, commission_type, open_commission, close_commission, discount_rate, close_commission_today, non_member_limit_rate, client_limit_rate, non_member_limit, client_limit, min_order_quantity, max_order_quantity, min_margin_ratio | check open_commission/close_commission columns |
| realtime_snapshot_or_bar | skipped |  |  |  | 0 |  | no existing safe realtime wrapper found; validate manually in a later dedicated task if needed |
| invalid_symbol_error | fail | get_price(frequency='1m') | RqDataClient.contract_bars | ValueError | 0 |  | pass means API returned a structured empty/non-empty response; fail records redacted exception type |
| unsupported_frequency_error | skipped |  |  |  | 0 |  | skipped to avoid unsafe probing beyond documented tiny readonly checks |

