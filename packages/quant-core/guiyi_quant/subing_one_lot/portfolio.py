"""Shared-capital coordinator for completed-close one-lot paper execution."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import groupby

from guiyi_quant.subing_inputs import ExecutionBar
from guiyi_quant.subing_decision import REGIME_PROFILE, _wire

from . import EXPANDED_PORTFOLIO_PRODUCTS, PORTFOLIO_POLICY, build_engine, portfolio_policy

D = Decimal
INITIAL_CASH = D(PORTFOLIO_POLICY["initial_cash"])
DAY_BUDGET = D(PORTFOLIO_POLICY["daily_loss_budget"])
MARGIN_FRACTION = D(PORTFOLIO_POLICY["margin_fraction"])


@dataclass(frozen=True)
class Segment:
    product: str
    executions: tuple[ExecutionBar, ...]
    observations: dict[datetime, dict]
    structures: dict[str, dict]
    schedule: dict


def required_margin(mark, facts, side):
    ratio = facts.long_margin_ratio if side == "LONG" else facts.short_margin_ratio
    return max(mark, facts.prev_settlement) * facts.multiplier * ratio


def opening_quote(mark, facts, side, slippage_ticks=1):
    slippage = facts.tick_size * slippage_ticks
    entry = mark + slippage * (1 if side == "LONG" else -1)
    cost = slippage * facts.multiplier + facts.fees.amount(
        "open", entry, facts.multiplier
    )
    return entry, cost


class Portfolio:
    def __init__(self, segments, run_id, *, products=EXPANDED_PORTFOLIO_PRODUCTS):
        self.products = products
        self.policy = portfolio_policy(products)
        self.slippage_ticks = 1
        self.run_id = run_id
        self.accounts = {}
        self.last_observed_at = None
        self.marks = {}
        self.active_contracts = {}
        self.failed = False
        self.last_at = None
        self.day = None
        self.day_start = INITIAL_CASH
        self.halted = False
        self.exit_owed = set()
        self.unproven_marks = set()
        self.admission_rejections = {}
        self.risk_records = []
        self.daily = {}
        for segment in segments:
            xs = segment.executions
            self.register(
                segment.product,
                {x.bar.bar_end: x for x in xs},
                segment.structures,
                segment.schedule,
            )

    def register(self, product, bars, structures, schedule):
        first = min(bars.values(), key=lambda x: x.bar.bar_end)
        contract = first.bar.physical_contract
        if contract in self.accounts or product not in self.products:
            raise ValueError("PORTFOLIO_SEGMENT_IDENTITY_INVALID")
        if any(x.bar.product != product for x in bars.values()):
            raise ValueError("PORTFOLIO_PRODUCT_MISMATCH")
        module, _, _ = build_engine(
            bars,
            schedule,
            structures=structures,
            execution_model="completed_close",
            portfolio=True,
            portfolio_products=self.products,
        )
        account = module.AccountEngine(
            contract,
            product,
            first.facts.multiplier,
            f"{self.run_id}:{contract}",
            slippage_ticks=self.slippage_ticks,
            live=True,
            regime_research_profile=REGIME_PROFILE,
        )
        if account.model.regime != "UNKNOWN":
            first_day = first.bar.trading_day.isoformat()
            account.model.regime_since = datetime.fromisoformat(
                schedule[first_day]["first_open"]
            )
        account.portfolio_finance = self.finance
        self.accounts[contract] = account

    def equity(self):
        return INITIAL_CASH + sum(
            (
                account.equity(self.marks[contract].bar.close) - INITIAL_CASH
                for contract, account in self.accounts.items()
                if contract in self.marks
            ),
            D(0),
        )

    def reserved_finance(self, excluding=None):
        total = D(0)
        costs = D(0)
        for contract, account in self.accounts.items():
            if contract == excluding or contract not in self.marks:
                continue
            x = self.marks[contract]
            pending = account.model.pending
            if account.layers:
                total += required_margin(x.bar.close, x.facts, account.model.side)
            elif (
                pending
                and pending["kind"] == "OPEN"
                and not pending["cancel_requested"]
            ):
                side = pending["side"]
                entry, cost = opening_quote(x.bar.close, x.facts, side, self.slippage_ticks)
                total += required_margin(entry, x.facts, side)
                costs += cost
        return total, costs

    def mark_risk(self, at):
        if not self.halted and self.equity() - self.day_start <= -DAY_BUDGET:
            self.halted = True
            self.exit_owed.update(c for c, a in self.accounts.items() if a.layers)
            self.risk_records.append(
                dict(
                    at=at,
                    day=self.day,
                    reason="PORTFOLIO_DAILY_LOSS",
                    equity=self.equity(),
                    day_start=self.day_start,
                )
            )

    def finance(self, account, mark, facts, side):
        contract = account.contract
        at = self.marks[contract].bar.bar_end
        self.mark_risk(at)
        entry, cost = opening_quote(mark, facts, side, self.slippage_ticks)
        margin, reserved_cost = self.reserved_finance(excluding=contract)
        prospective_equity = self.equity() - cost - reserved_cost
        margin_limit = prospective_equity * MARGIN_FRACTION
        reason = None
        if self.halted or contract in self.exit_owed:
            reason = "PORTFOLIO_DAILY_LOSS"
        elif self.unproven_marks:
            reason = "PORTFOLIO_VALUATION_UNPROVEN"
        elif prospective_equity - self.day_start <= -DAY_BUDGET:
            reason = "PORTFOLIO_OPEN_COST_EXCEEDS_DAY_BUDGET"
        elif margin + required_margin(entry, facts, side) > margin_limit:
            reason = "PORTFOLIO_MARGIN_LIMIT"
        self.admission_rejections[contract] = reason
        return reason is None, self.halted or contract in self.exit_owed

    def step_batch(self, rows, *, observed_at=None):
        if self.failed:
            raise ValueError("PORTFOLIO_REPLAY_REQUIRED")
        try:
            self._step_batch(rows, observed_at)
        except Exception:
            # A later child may fail after an earlier child has applied this batch.
            # The entire in-memory projection is then unusable.
            self.failed = True
            raise

    def _step_batch(self, rows, observed_at):
        if not rows:
            raise ValueError("PORTFOLIO_EMPTY_BATCH")
        timestamp = rows[0][0].bar.bar_end
        if self.last_at is not None and timestamp <= self.last_at:
            raise ValueError("PORTFOLIO_BATCH_OUT_OF_ORDER")
        observed_at = timestamp if observed_at is None else observed_at
        if (
            observed_at.utcoffset() is None
            or observed_at < timestamp
            or self.last_observed_at is not None
            and observed_at < self.last_observed_at
        ):
            raise ValueError("PORTFOLIO_OBSERVATION_TIME_INVALID")
        day = rows[0][0].bar.trading_day
        if any(
            x.bar.bar_end != timestamp
            or x.bar.trading_day != day
            or not timestamp <= x.bar.confirmed_at <= observed_at
            for x, _ in rows
        ):
            raise ValueError("PORTFOLIO_BATCH_IDENTITY_INVALID")
        if len({x.bar.physical_contract for x, _ in rows}) != len(rows):
            raise ValueError("PORTFOLIO_DUPLICATE_CONTRACT")
        if self.day != day:
            if self.day is not None and day < self.day:
                raise ValueError("PORTFOLIO_SESSION_REGRESSION")
            self.day, self.day_start, self.halted = day, self.equity(), False
        # A former main contract without a fresh physical mark cannot finance new risk.
        for execution, _ in rows:
            previous = self.active_contracts.get(execution.bar.product)
            if (
                previous
                and previous != execution.bar.physical_contract
                and self.accounts[previous].layers
            ):
                self.unproven_marks.add(previous)
        for execution, _ in rows:
            self.marks[execution.bar.physical_contract] = execution
        self.mark_risk(timestamp)

        def order(row):
            x, _ = row
            account = self.accounts[x.bar.physical_contract]
            pending = account.model.pending
            return (
                not (pending and pending["kind"] == "CLOSE"),
                self.products.index(x.bar.product),
            )

        for execution, technical in sorted(rows, key=order):
            contract, product = execution.bar.physical_contract, execution.bar.product
            account = self.accounts[contract]
            previous = self.active_contracts.setdefault(product, contract)
            if previous != contract:
                old = self.accounts[previous]
                if old.layers or old.model.pending or previous in self.exit_owed:
                    if not any(
                        r.get("contract") == contract
                        and r["reason"] == "ROLLOVER_INTERRUPTED"
                        for r in self.risk_records
                    ):
                        self.risk_records.append(
                            dict(
                                at=timestamp,
                                contract=contract,
                                reason="ROLLOVER_INTERRUPTED",
                            )
                        )
                    continue
                account.model.loss_streak = old.model.loss_streak
                account.model.loss_pause_day = old.model.loss_pause_day
                account.model.loss_pause_at = old.model.loss_pause_at
                self.active_contracts[product] = contract
            account.step(execution, technical, observed_at=observed_at)
            if not account.layers:
                self.exit_owed.discard(contract)
                self.unproven_marks.discard(contract)
            latest = account.model.chain[-1]
            reason = self.admission_rejections.get(contract)
            if reason and any(a["kind"] == "REJECT" for a in latest["actions"]):
                self.risk_records.append(
                    dict(at=timestamp, contract=contract, reason=reason)
                )
        self.last_at = timestamp
        self.last_observed_at = observed_at
        self.mark_risk(timestamp)
        self.daily[day.isoformat()] = dict(
            day_start=self.day_start,
            equity=self.equity(),
            margin=self.reserved_finance()[0],
            halted=self.halted,
        )

    def snapshot(self):
        if self.failed:
            raise ValueError("PORTFOLIO_REPLAY_REQUIRED")
        accounts = {}
        for contract, account in self.accounts.items():
            if account.last is None:
                continue
            row = account.snapshot(include_journal=False)
            row["latest_decision"] = account.model.chain[-1] if account.model.chain else None
            row["decisions_with_actions"] = [
                x for x in account.model.chain if x["actions"]
            ]
            accounts[contract] = row
        cash = INITIAL_CASH + sum(
            (a.cash - INITIAL_CASH for a in self.accounts.values()), D(0)
        )
        return _wire(
            dict(
                policy=self.policy,
                equity=self.equity(),
                cash=cash,
                margin=self.reserved_finance()[0],
                pending_exit_contracts=sorted(self.exit_owed),
                valuation_unproven=sorted(self.unproven_marks),
                risk_records=self.risk_records,
                daily=self.daily,
                accounts=accounts,
                auto_order=False,
            )
        )


def replay(segments, run_id, *, on_batch=None):
    portfolio = Portfolio(segments, run_id)
    rows = sorted(
        (
            (x, segment.observations[x.bar.bar_end])
            for segment in segments
            for x in segment.executions
        ),
        key=lambda row: row[0].bar.bar_end,
    )
    for _, batch in groupby(rows, key=lambda row: row[0].bar.bar_end):
        portfolio.step_batch(list(batch))
        if on_batch is not None:
            on_batch(portfolio)
    return portfolio.snapshot()
