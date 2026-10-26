"""Native execution-only instrument, margin, fee budget and book validation."""

from datetime import datetime, timedelta
from decimal import Decimal
import re
from zoneinfo import ZoneInfo
from .. import htdy_account_execution as a
from ..htdy_account_execution.codec import digest
from .model import Contract, valid


def decimal(value, positive=False):
    if type(value) not in (str, int, float, Decimal):
        raise ValueError("NATIVE_FACT_NUMBER_INVALID")
    result = Decimal(str(value))
    if (
        not result.is_finite()
        or abs(result) > Decimal("1e30")
        or (result <= 0 if positive else result < 0)
    ):
        raise ValueError("NATIVE_FACT_NUMBER_INVALID")
    return result


def native_product_id(product, exchange):
    """CTP query scope only; actual physical identity still requires bind_contract."""
    if not isinstance(product, str) or re.fullmatch(r"[A-Z]{1,3}", product) is None:
        raise ValueError("AUTHORITATIVE_PRODUCT_INVALID")
    if exchange in ("CZCE", "CFFEX"):
        return product
    if exchange in ("SHFE", "DCE", "INE", "GFEX"):
        return product.lower()
    raise ValueError("NATIVE_PRODUCT_EXCHANGE_UNSUPPORTED")


def bind_contract(canonical, exchange, rows, now, until, trading_day):
    bare = canonical.split(".")[0]
    match = re.fullmatch(r"([A-Z]{1,3})(\d{4})", bare)
    if match is None:
        raise ValueError("AUTHORITATIVE_FOUR_DIGIT_CONTRACT_REQUIRED")
    product, month = match.groups()
    year = 2000 + int(month[:2])
    month = int(month[2:])
    selected = [
        r
        for r in rows
        if r["ExchangeID"] == exchange
        and r["ProductID"].upper() == product
        and r["DeliveryYear"] == year
        and r["DeliveryMonth"] == month
    ]
    if len(selected) != 1:
        raise ValueError("NATIVE_CONTRACT_LIFECYCLE_AMBIGUOUS")
    row = selected[0]
    if (
        row["ProductClass"] != "1"
        or row["IsTrading"] != 1
        or row["OpenDate"] > trading_day
        or row["ExpireDate"] < trading_day
        or row["StartDelivDate"] <= trading_day
    ):
        raise ValueError("NATIVE_CONTRACT_NOT_TRADABLE")
    if row["MinLimitOrderVolume"] != 1 or row["MaxLimitOrderVolume"] < 1:
        raise ValueError("ONE_LOT_ORDER_UNSUPPORTED")
    return Contract(
        canonical,
        row["InstrumentID"],
        exchange,
        "ctp-instrument:" + digest(row),
        now,
        until,
    ), row


def quote_from_native_batch(binding, rows, trading_day, received_at):
    """Select one exact physical identity from an already completed native batch."""
    selected = [
        row for row in rows
        if row["InstrumentID"] == binding.native and row["ExchangeID"] == binding.exchange
    ]
    if not selected:
        raise ValueError("NATIVE_BOOK_TARGET_MISSING")
    if len(selected) != 1:
        raise ValueError("NATIVE_BOOK_TARGET_AMBIGUOUS")
    return quote_from_native(binding, selected[0], trading_day, received_at)


def quote_from_native(binding, row, trading_day, received_at):
    if (row["InstrumentID"], row["ExchangeID"], row["TradingDay"]) != (
        binding.native,
        binding.exchange,
        trading_day,
    ):
        raise ValueError("NATIVE_BOOK_IDENTITY")
    if type(row["UpdateMillisec"]) is not int or not 0 <= row["UpdateMillisec"] <= 999:
        raise ValueError("NATIVE_BOOK_MILLISECOND")
    event = datetime.strptime(
        row["ActionDay"] + row["UpdateTime"], "%Y%m%d%H:%M:%S"
    ).replace(
        tzinfo=ZoneInfo("Asia/Shanghai"), microsecond=row["UpdateMillisec"] * 1000
    )
    if not event <= received_at or (received_at - event).total_seconds() > 5:
        raise ValueError("NATIVE_BOOK_STALE")
    for k in ("BidVolume1", "AskVolume1"):
        if type(row[k]) is not int or row[k] < 0:
            raise ValueError("NATIVE_BOOK_QUANTITY")
    return a.Quote(
        binding.canonical,
        received_at,
        received_at + timedelta(seconds=3),
        "simnow-execution-book:" + digest((row, received_at)),
        decimal(row["BidPrice1"], True),
        decimal(row["AskPrice1"], True),
        row["BidVolume1"],
        row["AskVolume1"],
        decimal(row["LowerLimitPrice"], True),
        decimal(row["UpperLimitPrice"], True),
    )


def execution_input(binding, instrument, margin, commission, quote, session, now):
    valid(binding.at, binding.valid_until, now)
    for row in (margin, commission):
        if (
            row["InstrumentID"] != binding.native
            or row["ExchangeID"] != binding.exchange
            or row["BrokerID"] != "9999"
        ):
            raise ValueError("NATIVE_RATE_IDENTITY")
    if margin["HedgeFlag"] != "1" or margin["IsRelative"] != 0:
        raise ValueError("ABSOLUTE_SPECULATIVE_MARGIN_REQUIRED")
    if decimal(margin["LongMarginRatioByVolume"]) or decimal(
        margin["ShortMarginRatioByVolume"]
    ):
        raise ValueError("PER_LOT_MARGIN_PROFILE_UNSUPPORTED")
    mult = decimal(instrument["VolumeMultiple"], True)
    tick = decimal(instrument["PriceTick"], True)
    price = max(quote.bid, quote.ask)
    budget = price * mult * decimal(commission["OpenRatioByMoney"]) + decimal(
        commission["OpenRatioByVolume"]
    )
    source = "ctp-execution-instrument:" + digest(
        (binding.source_id, margin, commission, quote.source_id)
    )
    return a.ExecutionInput(
        a.Instrument(
            re.match(r"[A-Z]+", binding.canonical)[0],
            binding.canonical,
            now,
            binding.valid_until,
            source,
            tick,
            mult,
            decimal(margin["LongMarginRatioByMoney"], True),
            decimal(margin["ShortMarginRatioByMoney"], True),
            budget,
        ),
        session,
        quote,
    )
