"""Disposable P6 harness. Only source-generated fixtures and one fixed P4 packet."""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
from threading import Event, Thread
from time import perf_counter, process_time, sleep
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import CanonicalBar
from app.market_data.live_market import _bar_payload, live_bar_channel
from app.market_data.newow.v2_completed import HistoricalAvailability, MarketWindow, PublishedObservation, from_historical_bar
from app.market_data.newow.v2_scope import Deployment, Scope
from app.market_data.observation_stream import ObservationEnvelope
from gateway import Account, Quote, SECTIONS, Snapshot, VeighNaOfflineGateway
from host import TradingHost
from risk import ContractPolicy, HostConfig, RiskLimits
from store import isolated_connection

D = Decimal
ZONE = ZoneInfo('Asia/Shanghai')
INTRADAY = ('5m', '15m', '30m', '60m')
FREQUENCIES = (*INTRADAY, '1d', '1w')
PERIOD_DAY = date(2026, 11, 24)
GENERATION = 'p6-synthetic-observation'
NATIVE_GENERATION = 'p6-synthetic-ctp'
PACKET_SHA = '22d79598a1336e625ab3b1c134dba00a1132fcd27e0a3b2a5c17daed0c8d2b30'


def native_now(day):
    return datetime.combine(day, time(9), ZONE)


def market(product, frequency, day, minutes=60):
    start = native_now(day)
    end = start + timedelta(minutes=minutes)
    contract = product.upper() + '2701'
    return MarketWindow(product, contract, product + ':synthetic-p6', 'synthetic-p6', day, frequency,
                        (SessionWindow(start, end),),
                        (day, end + timedelta(seconds=1)) if frequency == '1w' else None)


def input_bar(end, day):
    return CanonicalBar(end, day, D(100), D(100), D(100), D(100), D(30), D(3000), D(100))


def warm_input(host, window, end):
    moment = end + timedelta(seconds=2)
    item = from_historical_bar(input_bar(end, window.trading_day), window, revision='p6-fixture',
                               source_ref='p6-fixture:' + end.isoformat(),
                               availability=HistoricalAvailability(moment, 'p6-2s'),
                               as_of=moment, warmup=True)
    assert host.receive_completed(item, window, expected=end, now=moment) == 'ACCEPTED'


def feed(host, native, window, end):
    moment = end + timedelta(seconds=2)
    bar = input_bar(end, window.trading_day)
    if window.frequency.value in INTRADAY:
        envelope = ObservationEnvelope(
            f'{window.trading_day}:{window.contract}:{window.frequency.value}:{bar.bar_end.isoformat()}',
            window.trading_day, moment, live_bar_channel(window.product, window.frequency),
            _bar_payload(bar, contract=window.contract), True,
            stream_id='1-0', raw_received_at=moment, confirmed_at=moment,
        )
        return native.completed(envelope, window, generation=GENERATION, expected=end, now=moment)

    original = from_historical_bar(bar, window, revision='fixture-first-publication', source_ref='p6-fixture',
                                   availability=HistoricalAvailability(moment, 'p6-2s'),
                                   as_of=moment).payload.bar
    digest = hashlib.sha256(json.dumps(_bar_payload(bar, contract=window.contract),
                                      sort_keys=True).encode()).hexdigest()
    original = replace(original, source_bar_sha256=digest)
    publication = PublishedObservation('p6-fixture:' + end.isoformat(), digest, moment)

    from guiyi_quant.newow.product_identity import InputQualityPolicy

    class Reader:
        def forward_incremental_bar(self, **_):
            return original, InputQualityPolicy.V1

    return host.receive_publication(
        Reader(), window, generation=GENERATION, expected=end, now=moment, publication=publication,
        after=end - timedelta(minutes=1), prior_owner_segment_id=window.owner_segment_id,
        prior_calculation_segment_id=original.calculation_segment_id,
    )


def count_persisted(database, alias):
    with isolated_connection(database) as read:
        return dict(read.execute(
            'SELECT kind, count(*) FROM newow_p5.record WHERE account=%s GROUP BY kind',
            ('offline_fixture:' + alias,),
        ).fetchall())


def nearest(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1]


def resource_state(database):
    with isolated_connection(database) as read:
        pg = read.execute(
            'SELECT blks_read, blks_hit, tup_inserted, tup_updated, temp_bytes '
            'FROM pg_stat_database WHERE datname=current_database()'
        ).fetchone()
    return {'cpu_seconds': process_time(), 'max_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'pg_blks_read': pg[0], 'pg_blks_hit': pg[1], 'pg_tuples_inserted': pg[2],
            'pg_tuples_updated': pg[3], 'pg_temp_bytes': pg[4]}


def register_native(native, owner):
    from vnpy_ctp import api
    symbol = owner + '2701'
    native.native.td_api.onRspQryInstrument({
        'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'InstrumentName': 'P6 fixture',
        'ProductClass': api.THOST_FTDC_PC_Futures, 'VolumeMultiple': 10, 'PriceTick': 1.0,
        'MinLimitOrderVolume': 1, 'MaxLimitOrderVolume': 10,
    }, {'ErrorID': 0, 'ErrorMsg': ''}, 1, True)


def native_fill(native, owner, when):
    from vnpy_ctp import api
    day = when.strftime('%Y%m%d')
    symbol = owner + '2701'
    stamp = when.strftime('%H:%M:%S')
    order = {
        'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'TradingDay': day, 'FrontID': 7, 'SessionID': 13,
        'OrderRef': '42', 'OrderSysID': ' 000089', 'OrderStatus': api.THOST_FTDC_OST_AllTraded,
        'InsertDate': day, 'InsertTime': stamp, 'OrderPriceType': api.THOST_FTDC_OPT_LimitPrice,
        'TimeCondition': api.THOST_FTDC_TC_GFD, 'VolumeCondition': api.THOST_FTDC_VC_AV,
        'Direction': api.THOST_FTDC_D_Buy, 'CombOffsetFlag': api.THOST_FTDC_OFEN_Open, 'LimitPrice': 100,
        'VolumeTotalOriginal': 1, 'VolumeTraded': 1, 'OrderSubmitStatus': api.THOST_FTDC_OSS_Accepted,
        'StatusMsg': '',
    }
    trade = {
        'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'TradingDay': day, 'OrderSysID': ' 000089',
        'TradeID': '000101', 'TradeDate': day, 'TradeTime': stamp, 'Direction': api.THOST_FTDC_D_Buy,
        'OffsetFlag': api.THOST_FTDC_OFEN_Open, 'Price': 100, 'Volume': 1,
    }
    native.push_ctp('order', order, generation=NATIVE_GENERATION, sequence=1, known_at=when)
    native.push_ctp('trade', trade, generation=NATIVE_GENERATION, sequence=2, known_at=when)
    native.push_ctp('trade', trade.copy(), generation=NATIVE_GENERATION, sequence=3, known_at=when)


def launch_research(root, output, index, args):
    packet = Path(args.packet)
    assert hashlib.file_digest(packet.open('rb'), 'sha256').hexdigest() == PACKET_SHA
    reports = output / f'research-{index:03}.json'
    cmd = [args.research_python, '-B', str(root / 'services/newow-rqalpha/replay.py'),
           str(packet), PACKET_SHA, 'a' * 64, str(reports)]
    pythonpath = os.pathsep.join(str(root / part) for part in ('services/quant-api', 'packages/quant-core'))
    process = subprocess.Popen(cmd, env={'PYTHONPATH': pythonpath}, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    started = perf_counter()
    completion = {}
    def wait():
        completion['exit'] = process.wait()
        completion['seconds'] = perf_counter() - started
    watcher = Thread(target=wait, daemon=True)
    watcher.start()
    return process, reports, watcher, completion


def check_research(active):
    _, report, watcher, completion = active
    watcher.join(timeout=180)
    assert completion.get('exit') == 0
    data = json.loads(report.read_text())
    assert data['input_sha256'] == PACKET_SHA
    assert data['summary']['final_equity'] == '9765.07700000'
    assert data['summary']['fees'] == '4.92300000'
    assert data['summary']['fill_count'] == 8
    return {'wall_seconds': completion['seconds'], 'packet_sha256': PACKET_SHA}


def run(args):
    from vnpy.event import Event as VeighNaEvent

    root = Path(args.source)
    out = Path(args.output)
    out.mkdir()
    stocks = (root / 'data/universe/active_products.txt').read_text().split()
    products = tuple(sorted(stocks + (['qfa', 'qfb', 'qfc', 'qfd', 'qfe', 'qff', 'qfg', 'qfh', 'qfi', 'qfj']
                                      if args.market == 70 else [])))
    assert len(set(products)) == args.market
    owners = products[:args.owners]
    alias = 'p6-' + uuid4().hex
    database = os.environ['GUIYI_P5_ISOLATED_DATABASE']
    limits = RiskLimits('fixture-p6', D(10000), D(20), timedelta(hours=2),
                        timedelta(minutes=1), timedelta(seconds=45), timedelta(seconds=4))
    config = HostConfig(alias, GENERATION, limits, True, True)
    holder, problems = {}, []
    native = VeighNaOfflineGateway(
        on_event=lambda value, **scope: holder['host'].callback(value, **scope),
        on_error=lambda reason, **_: problems.append(reason),
        on_completed=lambda envelope, window, **scope: holder['host'].receive_observation(envelope, window, **scope),
        on_send=lambda _: '7_13_42',
    )
    barrier = Event()
    native.events.register('p6.barrier', lambda _: barrier.set())

    def drain():
        barrier.clear()
        native.events.put(VeighNaEvent('p6.barrier'))
        if not barrier.wait(timeout=60):
            raise RuntimeError('P6_NATIVE_QUEUE_CANNOT_DRAIN')

    recorded, backtests, active = [], [], None
    input_count = 0
    try:
        with TradingHost(database, config, native) as host, (out / 'batches.jsonl').open('x') as trace:
            holder['host'] = host
            now = native_now(PERIOD_DAY)
            read_id = host.begin_readback(generation=NATIVE_GENERATION, trading_day=PERIOD_DAY, started_at=now)
            host.activate(Scope('p6-fixture', products, tuple(Deployment(p, 'oscillation', '5m') for p in owners)),
                          expected_revision=None, supported=products)
            for product in owners:
                contract = product.upper() + '2701'
                host.register_policy(ContractPolicy(product, 'SHFE', contract, product + '2701',
                                                   1, D(10), D(1), D('.10'), D(0)))
            register_native(native, owners[0])
            drain()
            assert host.reconcile(Snapshot(alias, NATIVE_GENERATION, PERIOD_DAY, now, 0, tuple(sorted(SECTIONS)),
                                           Account(D(10000), D(110), D(0), D(0)), (), (), (), read_id))
            warm_streams = [(p, f) for p in products for f in FREQUENCIES if not args.smoke or p in owners and f == '5m']
            for i, (product, frequency) in enumerate(warm_streams):
                for offset in range(10, 1, -1):
                    day = PERIOD_DAY - timedelta(days=offset * 7)
                    window = market(product, frequency, day)
                    warm_input(host, window, window.endpoints[-1])
                if (i + 1) % 30 == 0:
                    print(f'warmup {i+1}/{len(warm_streams)}', flush=True)
            print('warmup complete', flush=True)
            before = resource_state(database)
            counts_before = count_persisted(database, alias)
            first_batch = perf_counter()
            callback_seconds = None

            def batch(cases, end, group, *, seal, ready_wall=None, enforce_cutoff=False):
                nonlocal input_count, active
                if args.parallel and active is None and group == 'synthetic-six-frequency-close':
                    active = launch_research(root, out, 0, args)
                research_alive_before = bool(active and active[0].poll() is None)
                started = ready_wall if ready_wall is not None else perf_counter()
                for product, frequency, day, length in cases:
                    status = feed(host, native, market(product, frequency, day, length), end)
                    if status != 'ACCEPTED':
                        raise RuntimeError(f'P6_INPUT_REJECTED {status} {frequency} {day.isoformat()}')
                if seal:
                    if enforce_cutoff:
                        sleep(max(0, 2.01 - (perf_counter() - started)))
                    host.advance(end + timedelta(seconds=5))
                input_count += len(cases)
                row = {'kind': group, 'end': end.isoformat(), 'inputs': len(cases),
                       'logical_decisions': len(cases) * 3, 'seconds': perf_counter() - started,
                       'research_alive_before': research_alive_before,
                       'research_alive_after': bool(active and active[0].poll() is None)}
                recorded.append(row)
                if group != 'representative-45m':
                    trace.write(json.dumps(row) + '\n')
                    trace.flush()
                if len(recorded) % 5 == 0:
                    print(f'completed {len(recorded)} batches; last {row["seconds"]:.3f}s', flush=True)

            # 45 market minutes, ten independently admitted shards per completion time.
            for minute in range(5, 46 if not args.smoke else 11, 5):
                end = now + timedelta(minutes=minute)
                frequencies = [f for f in INTRADAY if minute % int(f[:-1]) == 0]
                if minute == 5:
                    for product in owners:
                        host.quote(Quote('SHFE', product.upper() + '2701', PERIOD_DAY, NATIVE_GENERATION,
                                         end, D(99), D(100), D(90), D(110)))
                ready_wall = perf_counter()
                for shard in range(10):
                    cases = [(p, f, PERIOD_DAY, 60) for p in products[shard::10] for f in frequencies]
                    batch(cases, end, 'representative-45m', seal=shard == 9, ready_wall=ready_wall,
                          enforce_cutoff=minute == 5)
                for row in recorded[-10:]:
                    if minute == 5:
                        row['seconds'] = recorded[-1]['seconds']
                    trace.write(json.dumps(row) + '\n')
                trace.flush()
                if minute == 5 and native.sends:
                    assert len(native.sends) == 1 and native.sends[0]['request'][0] == owners[0].upper() + '2701'
                    started = perf_counter()
                    native_fill(native, owners[0], end + timedelta(seconds=6))
                    drain()
                    callback_seconds = perf_counter() - started
            for occurrence in range(args.peaks):
                day = date(2026, 11, 27) + timedelta(weeks=occurrence)
                close = native_now(day) + timedelta(minutes=5)
                cases = [(p, f, day, 5) for p in products for f in FREQUENCIES]
                batch(cases, close, 'synthetic-six-frequency-close', seal=True)

            drain()
            metrics = resource_state(database)
            after = count_persisted(database, alias)
            observations = [b['seconds'] for b in recorded]
            expected_fills = 1
            checks = dict(decisions=after['decisions'] - counts_before['decisions'] == input_count * 3,
                          inputs=after['inputs'] - counts_before['inputs'] == input_count,
                          callback_errors=not problems,
                          one_native_dispatch=len(native.sends) == 1 and callback_seconds is not None,
                          native_fills=len(host.store.projection('fills')['data']) == expected_fills,
                          native_watermark=host.status()['watermark'] == expected_fills * 3)
            result = {'market': args.market, 'owners': args.owners, 'concurrent_backtest': args.parallel,
                      'batches': len(recorded), 'peaks': args.peaks, 'representative_minutes': 10 if args.smoke else 45, 'smoke': args.smoke,
                      'order_sends': len(native.sends), 'native_fills': expected_fills,
                      'native_callback_drain_seconds': callback_seconds, 'checks': checks,
                      'p95_seconds': nearest(observations, .95), 'p99_seconds': nearest(observations, .99),
                      'worst_seconds': max(observations), 'elapsed_seconds': perf_counter() - first_batch,
                      'minimum_next_minute_slack_seconds': 60 - max(observations),
                      'timing_mode': 'accelerated market clock; staged first batch waits for real two-second opening cutoff',
                      'source': 'synthetic completed Market/P5 + real fixed P4 FU trial',
                      'before': before, 'after': metrics}
            if active:
                backtests.append(check_research(active))
                active = None
            result['research'] = backtests
            result['research_max_rss_bytes'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss if backtests else None
            (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
    finally:
        if active and active[0].poll() is None:
            active[0].terminate()
            active[0].wait(timeout=15)
        native.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', type=int, choices=[60, 70], required=True)
    parser.add_argument('--owners', type=int, choices=[16, 20], required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--parallel', action='store_true')
    parser.add_argument('--peaks', type=int, default=20)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--packet')
    parser.add_argument('--research-python')
    args = parser.parse_args()
    if (args.market, args.owners) not in {(60, 16), (70, 20)} or not 1 <= args.peaks <= 20:
        parser.error('invalid isolated capacity')
    run(args)
