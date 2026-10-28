"""Read SH2701 October case via existing MDS; no download or trading inference."""
import argparse
from datetime import date, datetime, UTC
import hashlib
import json
from pathlib import Path

from lms405_replay import read_local
from lms405_alignment_audit import daytime_extrema


def extrema_with_times(bars):
    """Price extrema of the explicitly selected completed endpoints only."""
    ordered = sorted(bars, key=lambda b: b.bar_end)
    if not ordered:
        return dict(bar_count=0, high=None, low=None, first_bar_end=None,
                    last_bar_end=None, high_bar_ends=[], low_bar_ends=[])
    hi = max(b.high for b in ordered)
    lo = min(b.low for b in ordered)
    return dict(bar_count=len(ordered), high=str(hi), low=str(lo),
                first_bar_end=ordered[0].bar_end.isoformat(),
                last_bar_end=ordered[-1].bar_end.isoformat(),
                high_bar_ends=[b.bar_end.isoformat() for b in ordered if b.high == hi],
                low_bar_ends=[b.bar_end.isoformat() for b in ordered if b.low == lo])


def summarize_scopes(bars, sessions_by_day, publication_minute):
    """Use authoritative resolved Session metadata, never infer a new session clock.

    Publication seconds are unknown. Exclude the entire publication minute's
    closing Bar, even if it could have completed before the actual post.
    """
    if publication_minute.tzinfo is None or publication_minute.second or publication_minute.microsecond:
        raise ValueError('PUBLICATION_MINUTE_REQUIRED')
    assigned = {d: [] for d in sessions_by_day}
    seen = set()
    for bar in bars:
        matches = [(day, item) for day, items in sessions_by_day.items() for item in items
                   if item.window.start < bar.bar_end <= item.window.end]
        if (len(matches) != 1 or matches[0][0] != bar.trading_day
                or bar.bar_end in seen):
            raise ValueError('BAR_SESSION_IDENTITY_UNPROVEN')
        seen.add(bar.bar_end)
        assigned[bar.trading_day].append((bar, matches[0][1].is_night))
    output = {}
    for day, values in sorted(assigned.items()):
        selected = [b for b, _ in values]
        output[day.isoformat()] = dict(
            sessions=[dict(name=s.name, is_night=s.is_night,
                           start=s.window.start.isoformat(), end=s.window.end.isoformat())
                      for s in sessions_by_day[day]],
            full_trading_day=extrema_with_times(selected),
            night=extrema_with_times([b for b, night in values if night]),
            day=extrema_with_times([b for b, night in values if not night]),
        )
        if day == publication_minute.date():
            output[day.isoformat()]['completed_before_publication_minute'] = extrema_with_times(
                [b for b in selected if b.bar_end < publication_minute])
    return output


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
    from app.market_data.session_clock import resolved_session_windows_for_trading_day
    report = dict(contract='SH2701', frequency='1m', window=['2026-10-26', '2026-10-27'],
                  observed_at=datetime.now(UTC).isoformat(), source_period='UNKNOWN',
                  executable=False, fill=None, performance=None,
                  purpose='PRICE_PATH_ONLY_NOT_AUTHOR_SIGNAL_PERIOD')
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=120):
            market = build_market_data_service(session)
            result = read_local(market, 'sh', 'SH2701', '1m',
                                date(2026, 10, 26), date(2026, 10, 27))
            bars = result.bars
            exchange = market.catalog.exchange_for_symbol('sh')
            sessions = {day: resolved_session_windows_for_trading_day(
                session, exchange=exchange, symbol='sh', trading_day=day)
                for day in (date(2026, 10, 26), date(2026, 10, 27))}
            scoped = summarize_scopes(bars, sessions, datetime.fromisoformat('2026-10-27T10:18:00+08:00'))
            payload = [dict(bar_end=b.bar_end.isoformat(), open=str(b.open), high=str(b.high),
                            low=str(b.low), close=str(b.close)) for b in bars]
            # Results remain unpublished until the read-only transaction exits successfully.
            complete = dict(status='WINDOW_READABLE', bar_count=len(bars),
                            scope_version='lms405-sh-authoritative-session-v1',
                            publication_minute='2026-10-27T10:18:00+08:00',
                            publication_time_kind='CURRENT_VISIBLE_POST_MINUTE_NOT_ACTION_TIME',
                            publication_bar_rule='bar_end < publication_minute',
                            scoped_extrema=scoped,
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
