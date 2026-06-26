from __future__ import annotations

from dataclasses import dataclass

from app.vnpy_integration.errors import SymbolMappingError
from app.vnpy_integration.settings import require_vnpy


VN_EXCHANGE_ALIASES = {
    "CFFEX": "CFFEX",
    "CZCE": "CZCE",
    "DCE": "DCE",
    "GFEX": "GFEX",
    "INE": "INE",
    "SHFE": "SHFE",
    "SSE": "SSE",
    "SZSE": "SZSE",
}


@dataclass(frozen=True)
class GuiyiSymbol:
    symbol: str
    exchange: str

    @property
    def vt_symbol(self) -> str:
        return to_vt_symbol(self.symbol, self.exchange)


def normalize_exchange(exchange: str) -> str:
    normalized = exchange.strip().upper()
    if not normalized:
        raise SymbolMappingError("exchange cannot be empty")
    if normalized not in VN_EXCHANGE_ALIASES:
        raise SymbolMappingError(f"Unsupported exchange for vn.py mapping: {exchange}")
    return VN_EXCHANGE_ALIASES[normalized]


def to_vt_symbol(symbol: str, exchange: str) -> str:
    normalized_symbol = symbol.strip()
    if not normalized_symbol:
        raise SymbolMappingError("symbol cannot be empty")
    return f"{normalized_symbol}.{normalize_exchange(exchange)}"


def from_vt_symbol(vt_symbol: str) -> GuiyiSymbol:
    parts = vt_symbol.strip().split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SymbolMappingError(f"Invalid vn.py vt_symbol: {vt_symbol}")
    return GuiyiSymbol(symbol=parts[0], exchange=normalize_exchange(parts[1]))


def to_vnpy_exchange(exchange: str) -> object:
    constant_module = require_vnpy("vnpy.trader.constant")
    exchange_name = normalize_exchange(exchange)
    try:
        return constant_module.Exchange[exchange_name]
    except KeyError as exc:
        raise SymbolMappingError(f"vn.py Exchange enum does not include: {exchange_name}") from exc
