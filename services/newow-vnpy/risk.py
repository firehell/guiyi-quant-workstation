"""Explicit, versioned fixture trading limits and conservative account budget."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from guiyi_quant.simnow_execution.model import Contract as NativeContractBinding

from gateway import aware, contract_product, identity, lots, money
from recovery import active
from store import account_key


@dataclass(frozen=True, slots=True)
class RiskLimits:
    revision: str
    margin_cap: Decimal
    daily_loss_cap: Decimal
    account_age: timedelta
    quote_age: timedelta
    signal_age: timedelta
    batch_delay: timedelta

    def __post_init__(self):
        for value in (self.margin_cap, self.daily_loss_cap):
            money(value)
            if not value:
                raise ValueError('P5_RISK_LIMIT_MISSING')
        if (not self.revision or min(self.account_age, self.quote_age, self.batch_delay) <= timedelta(0)
                or self.batch_delay >= self.signal_age or self.signal_age >= timedelta(minutes=5)):
            raise ValueError('P5_RISK_LIMIT_MISSING')


@dataclass(frozen=True, slots=True)
class ContractPolicy:
    product: str
    exchange: str
    contract: str
    native_symbol: str
    maximum_lots: int
    multiplier: Decimal
    tick: Decimal
    margin_rate: Decimal
    fee_ceiling: Decimal
    native_binding: NativeContractBinding | None = None

    def __post_init__(self):
        identity(self.exchange, self.contract)
        lots(self.maximum_lots, minimum=1)
        for value in (self.multiplier, self.tick, self.margin_rate, self.fee_ceiling):
            money(value)
        binding = self.native_binding
        if (self.product.lower() != contract_product(self.contract)
                or binding is not None and (binding.canonical, binding.native, binding.exchange) != (
                    self.contract, self.native_symbol, self.exchange,
                )
                or binding is None and self.native_symbol.upper() != self.contract
                or not self.multiplier or not self.tick or not 0 < self.margin_rate <= 1):
            raise ValueError('P5_CONTRACT_POLICY_INVALID')
        object.__setattr__(self, 'product', self.product.lower())


@dataclass(frozen=True, slots=True)
class HostConfig:
    alias: str
    market_generation: str
    limits: RiskLimits | None
    fixture_send_enabled: bool = False
    isolated_capacity: bool = False
    market_age: timedelta = timedelta(seconds=30)

    def __post_init__(self):
        account_key(self.alias)
        if (not self.market_generation or type(self.fixture_send_enabled) is not bool
                or type(self.isolated_capacity) is not bool or self.market_age <= timedelta(0)):
            raise ValueError('P5_CONFIG_INVALID')


@dataclass(frozen=True, slots=True)
class ManagementPermit:
    """A bounded offline approval for reducing an existing contract obligation."""

    reference: str
    revision: str
    product: str
    exchange: str
    contract: str
    trading_day: date
    session: tuple[datetime, datetime]
    approved_at: datetime
    expires_at: datetime
    maximum_close_lots: int

    def __post_init__(self):
        identity(self.exchange, self.contract)
        lots(self.maximum_close_lots, minimum=1)
        start, end = map(aware, self.session)
        if (not self.reference or not self.revision or self.product.lower() != contract_product(self.contract)
                or type(self.trading_day) is not date or not start <= aware(self.approved_at) <
                aware(self.expires_at) <= end):
            raise ValueError('P5_MANAGEMENT_PERMIT_INVALID')
        object.__setattr__(self, 'product', self.product.lower())


def timestamp(value):
    return aware(datetime.fromisoformat(value))


def fresh(now, observed, age):
    return 0 <= (now - observed).total_seconds() <= age.total_seconds()


def account_fresh(state, now):
    return (state['status'] == 'READY' and state['verified_until']
            and timestamp(state['native']['as_of']) <= now <= timestamp(state['verified_until']))


def budget(state, limits: RiskLimits | None):
    funds = state['native']['account']
    reserved = sum((Decimal(i['reserved']) for i in state['intents'].values() if active(i)), Decimal(0))
    available = Decimal(funds['available'])
    margin = Decimal(funds['margin'])
    return {
        'available': available, 'margin': margin, 'reserved': reserved,
        'buying_power': None if limits is None else min(available, limits.margin_cap - margin) - reserved,
        'daily_loss': Decimal(funds['daily_loss']),
    }
