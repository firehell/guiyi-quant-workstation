# Su Bing EMA21 vn.py Draft

This package contains the V1 draft of the Su Bing EMA21 trend strategy for the
Guiyi Quant research workflow.

## Purpose

- Provide a vn.py `CtaTemplate` compatible strategy class.
- Keep all parameters explicit and validated.
- Produce signal direction, signal reason, and trade note fields for later review.
- Stay inside the research and backtesting boundary.

## Logic

The strategy processes completed bars in `on_bar`.

- `close > EMA21` marks a long environment.
- `close < EMA21` marks a short environment.
- MACD uses DIF and DEA with golden cross / death cross checks.
- The zero-axis filter currently requires `abs(DIF) <= ATR`.
- ATR controls stop reference and R multiple target reference.
- Volume confirmation uses `volume_window` and `volume_multiplier`.
- `allow_long` and `allow_short` independently enable each side.

The draft records intent through:

- `last_signal`
- `signal_reason`
- `trade_note`
- `stop_price`
- `take_profit_price`

## Boundary

This draft does not connect to brokers or external data clients. It does not
read account fields. It does not place broker-facing instructions. Execution,
matching, costs, slippage, and fills are left to the future vn.py backtest
adapter stage.

## Files

- `vnpy_strategy.py`: vn.py strategy draft and indicator logic.
- `config_schema.py`: parameter dataclass and validation.
- `default_params.json`: default parameter template.
- `review_tags.json`: review and signal reason tags.
