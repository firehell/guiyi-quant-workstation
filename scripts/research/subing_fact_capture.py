"""Shared encoding and exclusive file creation for SuBing execution facts."""
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any


class FactsCaptureError(ValueError):
    def __init__(self,code: str):
        self.code=code
        super().__init__(code)


def normalize_rows(frame: Any, contract: str, expected_days: list[str], fields: list[str]) -> list[dict]:
    if frame is None or frame.empty:
        raise FactsCaptureError('EXECUTION_FACTS_MISSING')
    reset=frame.reset_index() if 'order_book_id' not in frame.columns else frame
    result=[]
    for row in reset.to_dict(orient='records'):
        if row.get('order_book_id')!=contract:
            raise FactsCaptureError('PROVIDER_CONTRACT_MISMATCH')
        key='trading_date' if 'trading_date' in row else ('date' if 'date' in row else 'datetime')
        day=date.fromisoformat(str(row[key])[:10]).isoformat()
        values={'date':day}
        for field in fields:
            value=row[field]
            if field in ('commission_type','trade_unit','price_unit'):
                if not isinstance(value,str) or not value.strip():
                    raise FactsCaptureError('EXECUTION_FACTS_MISSING')
                values[field]=value
            else:
                number=Decimal(str(value))
                if not number.is_finite() or number<0:
                    raise FactsCaptureError('EXECUTION_FACTS_MISSING')
                values[field]=str(number)
        result.append(values)
    days=[r['date'] for r in result]
    if len(days)!=len(set(days)) or sorted(days)!=expected_days:
        raise FactsCaptureError('PROVIDER_DATE_COVERAGE_MISMATCH')
    return sorted(result,key=lambda r:r['date'])


def instrument_payload(instrument: Any, contract: str) -> dict:
    if instrument is None or instrument.order_book_id!=contract:
        raise FactsCaptureError('PROVIDER_CONTRACT_MISMATCH')
    tick=instrument.tick_size
    tick=tick() if callable(tick) else tick
    multiplier=instrument.contract_multiplier
    tick,multiplier=Decimal(str(tick)),Decimal(str(multiplier))
    if not tick.is_finite() or not multiplier.is_finite() or tick<=0 or multiplier<=0:
        raise FactsCaptureError('EXECUTION_FACTS_MISSING')
    return {'order_book_id':contract,'tick_size':str(tick),'contract_multiplier':str(multiplier)}


def _write(path: Path,value: object) -> None:
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>32*1024*1024:
        raise FactsCaptureError('PROVIDER_RESPONSE_BUDGET_EXCEEDED')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
