"""Read SH2701 October case via existing MDS; no download or trading inference."""
import argparse
from datetime import date, datetime, UTC
import hashlib
import json
from pathlib import Path

from lms405_replay import read_local
from lms405_alignment_audit import daytime_extrema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('OUTPUT_ALREADY_EXISTS')
    if not args.env_file.is_file():
        parser.error('ENV_FILE_MISSING')
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    report = dict(contract='SH2701', frequency='1m', window=['2026-10-26', '2026-10-27'],
                  observed_at=datetime.now(UTC).isoformat(), source_period='UNKNOWN',
                  executable=False, fill=None, performance=None,
                  purpose='PRICE_PATH_ONLY_NOT_AUTHOR_SIGNAL_PERIOD')
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=120):
            result = read_local(build_market_data_service(session), 'sh', 'SH2701', '1m',
                                date(2026, 10, 26), date(2026, 10, 27))
            bars = result.bars
            payload = [dict(bar_end=b.bar_end.isoformat(), open=str(b.open), high=str(b.high),
                            low=str(b.low), close=str(b.close)) for b in bars]
            # Results remain unpublished until the read-only transaction exits successfully.
            complete = dict(status='WINDOW_READABLE', bar_count=len(bars),
                            input_ohlc_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                            coverage=[v.isoformat() for v in result.coverage] if result.coverage else None,
                            calendar_day_extrema={d: daytime_extrema(bars, date.fromisoformat(d))
                                                  for d in ('2026-10-26', '2026-10-27')})
        report.update(complete)
    except MarketDataError as exc:
        report.update(status='BLOCKED', reason=exc.code)
    except Exception as exc:
        report.update(status='BLOCKED', reason='LOCAL_READ_UNVERIFIED', error_type=type(exc).__name__)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(status=report['status'], bar_count=report.get('bar_count'),
                          reason=report.get('reason'))))


if __name__ == '__main__':
    main()
