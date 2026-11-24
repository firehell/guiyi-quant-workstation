from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import os
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture
def scenario():
    database = os.getenv('GUIYI_P5_ISOLATED_DATABASE')
    if not database:
        pytest.skip('explicit P5 isolated PostgreSQL required')
    from app.market_data.aggregation import SessionWindow
    from app.market_data.domain import CanonicalBar
    from app.market_data.live_market import _bar_payload, live_bar_channel
    from app.market_data.newow.v2_completed import HistoricalAvailability, MarketWindow, from_historical_bar
    from app.market_data.newow.v2_scope import Deployment, Scope
    from app.market_data.observation_stream import ObservationEnvelope

    from gateway import SECTIONS, Account, FixtureGateway, Quote, Snapshot
    from host import TradingHost
    from risk import ContractPolicy, HostConfig, RiskLimits

    class Scenario:
        D = Decimal
        day = date(2026, 11, 24)
        start = datetime.combine(day, time(9), tzinfo=ZoneInfo('Asia/Shanghai'))
        signal_end = start + timedelta(minutes=50)
        generation = 'fixture-native-1'
        limits = RiskLimits('fixture-risk-v1', Decimal(10000), Decimal(20), timedelta(hours=2),
                            timedelta(minutes=1), timedelta(seconds=45), timedelta(seconds=4))

        def __init__(self):
            self.database = database
            self.gateway = FixtureGateway()
            self.config = HostConfig('p5-' + uuid4().hex, 'fixture-market-1', self.limits, True, True)

        @contextmanager
        def host(self, reset=False):
            if reset:
                self.__init__()
            with TradingHost(self.database, self.config, self.gateway) as host:
                host.begin_readback(generation=self.generation, trading_day=self.day)
                yield host

        def snapshot(self, *, at=None, sections=tuple(sorted(SECTIONS)), cash='110', margin='0',
                     loss='0', through=0, positions=(), orders=(), fills=(), account=True):
            return Snapshot(self.config.alias, self.generation, self.day, at or self.start, through, sections,
                            Account(Decimal(10000), Decimal(cash), Decimal(margin), Decimal(loss)) if account else None,
                            positions, orders, fills)

        def scope(self, products, revision='r1', frequency='5m', strategy='oscillation'):
            return Scope(revision, tuple(products), tuple(Deployment(p, strategy, frequency) for p in products))

        def policy(self, product, *, maximum_lots=1, contract=None):
            contract = contract or f'{product}2701'
            return ContractPolicy(product, 'SHFE', contract, contract.lower(), maximum_lots,
                                  Decimal(10), Decimal(1), Decimal('0.10'), Decimal(0))

        def market(self, product, *, freq='5m', contract=None):
            contract = contract or f'{product}2701'
            return MarketWindow(product.lower(), contract, f'{product.lower()}:{contract}', 'fixture-rank1', self.day, freq,
                                (SessionWindow(self.start, self.start + timedelta(hours=3)),))

        def bar(self, when, price='100'):
            return CanonicalBar(when, self.day, *(Decimal(price) for _ in range(4)), Decimal(1), None, Decimal(2))

        def warm(self, host, market, count=9):
            for end in market.endpoints[:count]:
                available = end + timedelta(seconds=1)
                item = from_historical_bar(self.bar(end), market, revision='fixture-canonical', source_ref=f'bar-{end}',
                                           availability=HistoricalAvailability(available, 'fixture-clock'),
                                           as_of=available, warmup=True)
                host.receive_completed(item, market, expected=end, now=available)

        def live(self, host, product, *, end=None, market=None, price='100', expected=None):
            market = market or self.market(product)
            end = end or self.signal_end
            available = end + timedelta(seconds=2)
            bar = self.bar(end, price)
            source = ObservationEnvelope(
                f'{self.day}:{market.contract}:{market.frequency.value}:{bar.bar_end.isoformat()}', self.day, available,
                live_bar_channel(market.product, market.frequency.value), _bar_payload(bar, contract=market.contract),
                True, stream_id='1-0', raw_received_at=available, confirmed_at=available,
            )
            receive = getattr(self.gateway, 'completed', host.receive_observation)
            return receive(source, market, generation=self.config.market_generation,
                           expected=expected or end, now=available)

        def quoted(self, host, product, *, at=None, contract=None):
            host.quote(Quote('SHFE', contract or f'{product}2701', self.day, self.generation,
                             at or self.signal_end, Decimal(99), Decimal(100), Decimal(90), Decimal(110)))

        def prepare_builds(self, host, products, *, cash='110', maximum_lots=1):
            host.activate(self.scope(products), expected_revision=None, supported=products)
            assert host.reconcile(self.snapshot(cash=cash))
            for product in products:
                host.register_policy(self.policy(product, maximum_lots=maximum_lots))
                self.warm(host, self.market(product))
                self.quoted(host, product)
            for product in products:
                assert self.live(host, product) == 'ACCEPTED'

    return Scenario()
