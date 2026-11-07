"""Authoritative physical-prefix reads used by development model preparation."""
from dataclasses import asdict
from app.market_data.domain import BarFrequency,ContractTradingDayQuery
from app.market_data.new_subing_research import validate_series,payload_hash

def prefix(m,symbol,contract,frequency,through):
    freq=BarFrequency(frequency);cutoff=max(w.end for w in m.session_windows(symbol=symbol,trading_day=through))
    source=m.contract_source_evidence(symbol=symbol,contract=contract,frequency=freq,before=cutoff)
    expected=m.expected_contract_replay_endpoints(symbol=symbol,contract=contract,frequency=freq,trading_day=through,cutoff=cutoff)
    if not expected:raise ValueError('PHYSICAL_PREFIX_EMPTY')
    rows=m.query_contract_trading_days(ContractTradingDayQuery(symbol,contract,freq,expected[0][1],through))
    validate_series(rows,product=symbol,contract=contract,frequency=freq,expected=expected)
    if source!=m.contract_source_evidence(symbol=symbol,contract=contract,frequency=freq,before=cutoff):raise ValueError('SOURCE_CHANGED')
    return rows.bars,dict(source=source,hash=payload_hash([asdict(b) for b in rows.bars]))

