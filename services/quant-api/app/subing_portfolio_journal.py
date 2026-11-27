"""Ingest complete, prepared minute batches into the independent model journal."""

from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
import re

from app.market_data.aggregation import SessionWindow, expected_intraday_ends
from app.market_data.live_market import live_bar_channel
from app.market_data.research_inputs import load_execution_facts
from app.market_data.observation_stream import ObservationEnvelope
from app.subing_model.account import decode_execution, encode_execution
from app.subing_model.pipeline import bar
from app.subing_model.store import digest
from app.subing_model.worker import ROOT, code_hashes
from guiyi_quant.subing_inputs import StrategyBar
from guiyi_quant.subing_one_lot import PORTFOLIO_PRODUCTS, EXPANDED_PORTFOLIO_PRODUCTS, portfolio_policy
from guiyi_quant.subing_one_lot.portfolio import Portfolio

LEGACY_KIND = "subing_portfolio_minute_journal_v1"
KIND = "subing_portfolio_minute_journal_v2"
KNOWLEDGE_POLICY = "strict_after_pending_and_current_facts_capture_v1"
SCHEDULE_FIELDS = ("previous", "first_open", "day_end", "next_open")


def source_hashes():
    core = ROOT / "packages/quant-core/guiyi_quant/subing_one_lot"
    journal = Path(__file__).resolve()
    worker = journal.with_name("subing_portfolio_worker.py")
    return {
        **code_hashes(),
        **{str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in (journal, worker, journal.with_name("subing_portfolio_supervision.py"),
                journal.with_name("subing_portfolio_paths.py"), ROOT / "packages/quant-core/guiyi_quant/trading_universe.py")},
        **{
            str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(core.glob("*.py"))
        },
    }


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("PORTFOLIO_NAIVE_TIME")
    return result


@dataclass(frozen=True)
class PreparedObservation:
    envelope: ObservationEnvelope
    execution_facts: dict
    technical: dict
    structure: dict
    chart: dict | None = None


def encode_minute(product, prepared, context, at, day, observed_at):
    event = prepared.envelope
    minute = bar(event.data)
    contract = context["contract"]
    if (
        not re.fullmatch(r"[0-9]+-[0-9]+", event.stream_id)
        or event.channel != live_bar_channel(product, "1m")
        or event.trading_day != day
        or minute.trading_day != day
        or minute.bar_end != at
        or event.data["contract"] != contract
        or event.confirmed_at is None
        or not at <= event.confirmed_at <= observed_at
        or event.source_observed_at > observed_at
        or event.raw_received_at is not None
        and event.raw_received_at > observed_at
    ):
        raise ValueError("PORTFOLIO_COMPLETED_OBSERVATION_INVALID")
    if stamp(prepared.execution_facts["captured_at"]) > observed_at:
        raise ValueError("PORTFOLIO_EXECUTION_FACTS_NOT_KNOWN")
    opens = [
        stamp(start)
        for start, end in context["sessions"]
        if stamp(start) < at <= stamp(end)
    ]
    if len(opens) != 1:
        raise ValueError("PORTFOLIO_SESSION_INVALID")
    strategy_bar = StrategyBar(
        product=product,
        physical_contract=contract,
        frequency="1m",
        bar_end=at,
        trading_day=day,
        open=minute.open,
        high=minute.high,
        low=minute.low,
        close=minute.close,
        volume=minute.volume,
        open_interest=minute.open_interest,
        source_identity=event.observation_id,
        confirmed_at=event.confirmed_at,
        session_open_at=opens[0],
        session_close_at=stamp(context["day_end"]),
    )
    executions, _ = load_execution_facts(
        prepared.execution_facts,
        product=product,
        bars=[strategy_bar],
    )
    structure = prepared.structure
    for source in (
        structure.get("boundary_at"),
        (structure.get("hourly") or {}).get("at"),
    ):
        if source is not None and stamp(source) > at:
            raise ValueError("PORTFOLIO_STRUCTURE_FROM_FUTURE")
    chart = prepared.chart
    if chart is not None and stamp(chart["at"]) != at:
        raise ValueError("PORTFOLIO_CHART_TIME_INVALID")
    return dict(
        **({"chart": chart} if chart is not None else {}),
        execution=encode_execution(executions[0]),
        execution_facts=dict(
            captured_at=prepared.execution_facts["captured_at"],
            payload_sha256=digest(prepared.execution_facts),
            **{key: prepared.execution_facts.get(key) for key in (
                "capture_version", "time_semantics", "fee_policy_version", "fee_assumption", "plan_hash")},
        ),
        technical=prepared.technical,
        structure=structure,
        producer_stream_id=event.stream_id,
    )


class PortfolioJournal:
    """Adapter for the existing ModelStore compare-and-append contract."""

    def __init__(self, store, run_id, identity):
        self.products = tuple(identity["policy"].get("products", PORTFOLIO_PRODUCTS))
        if identity["kind"] not in (KIND, LEGACY_KIND) or identity["policy"] != portfolio_policy(self.products):
            raise ValueError("PORTFOLIO_JOURNAL_IDENTITY_INVALID")
        if identity["code_hashes"] != source_hashes():
            raise ValueError("PORTFOLIO_CODE_IDENTITY_CHANGED")
        self.store, self.run_id, self.identity = store, run_id, identity
        self.started_at = stamp(identity["started_at"])
        self.portfolio = Portfolio([], run_id, products=self.products)
        self.contract_inputs = {}
        self.events = {}
        self.charts = {}
        self.sequence = 0
        self.contexts = None
        self.contexts_by_day = {}
        self.calendar_ends = ()
        self.expected_by_minute = {}
        self.day = None
        self.failed = False

    @staticmethod
    def create(store, run_id, started_at, *, products=EXPANDED_PORTFOLIO_PRODUCTS):
        if products != EXPANDED_PORTFOLIO_PRODUCTS:
            raise ValueError("PORTFOLIO_ACTIVE_SCOPE_RETIRED")
        identity = dict(
            kind=KIND,
            execution_knowledge_policy=KNOWLEDGE_POLICY,
            policy=portfolio_policy(products),
            started_at=started_at.isoformat(),
            code_hashes=source_hashes(),
        )
        journal = PortfolioJournal(store, run_id, identity)
        store.create(run_id, identity, journal.projection())
        return PortfolioJournal.restore(store, run_id)

    @staticmethod
    def restore(store, run_id):
        row, events = store.load(run_id)
        journal = PortfolioJournal(store, run_id, row["identity"])
        for payload in events:
            journal.apply(payload)
        if journal.sequence != row["sequence"] or journal.projection() != row["state"]:
            raise ValueError("PORTFOLIO_RESTART_PARITY_FAILED")
        return journal

    def projection(self):
        if self.failed:
            raise ValueError("PORTFOLIO_RESTORE_REQUIRED")
        return dict(kind=self.identity["kind"], sequence=self.sequence, result=self.portfolio.snapshot(),
                    **({"charts": self.charts} if self.charts else {}))

    def _next_minute(self, day, contexts):
        if day == self.day:
            if contexts is not None:
                raise ValueError("PORTFOLIO_DUPLICATE_SESSION_CONTEXT")
        else:
            if contexts is None or set(contexts) != set(self.products):
                raise ValueError("PORTFOLIO_SESSION_SCOPE_INCOMPLETE")
            if self.day is not None and (
                day <= self.day
                or self.portfolio.last_at != self.calendar_ends[-1]
                or any(
                    row["previous"] != self.day.isoformat()
                    or stamp(row["first_open"])
                    != stamp(self.contexts[product]["next_open"])
                    for product, row in contexts.items()
                )
            ):
                raise ValueError("PORTFOLIO_DAY_CONTINUITY_UNPROVEN")
            expected = {}
            for product, context in contexts.items():
                ends = [stamp(end) for end in context["expected_1m"]]
                windows = tuple(
                    SessionWindow(stamp(start), stamp(end))
                    for start, end in context["sessions"]
                )
                if (
                    not ends
                    or not windows
                    or tuple(ends) != expected_intraday_ends(windows, "1m")
                    or stamp(context["first_open"]) != windows[0].start
                    or stamp(context["day_end"]) != windows[-1].end
                    or stamp(context["next_open"]) <= windows[-1].end
                ):
                    raise ValueError("PORTFOLIO_SESSION_ENDPOINTS_INVALID")
                for end in ends:
                    expected.setdefault(end, set()).add(product)
            self.day, self.contexts = day, contexts
            self.contexts_by_day[day] = contexts
            self.calendar_ends = tuple(sorted(expected))
            self.expected_by_minute = expected
        previous = self.portfolio.last_at or self.started_at
        index = bisect_right(self.calendar_ends, previous)
        return self.calendar_ends[index] if index < len(self.calendar_ends) else None

    def apply(self, payload):
        if self.failed:
            raise ValueError("PORTFOLIO_RESTORE_REQUIRED")
        try:
            self._apply(payload)
        except Exception:
            self.failed = True
            raise

    def _apply(self, payload):
        day = date.fromisoformat(payload["day"])
        at = stamp(payload["minute"])
        if payload["event_id"] != f"portfolio:{day}:{at.astimezone(UTC).isoformat()}":
            raise ValueError("PORTFOLIO_BATCH_IDENTITY_INVALID")
        observed_at = stamp(payload["observed_at"])
        if self._next_minute(day, payload.get("contexts")) != at:
            raise ValueError("PORTFOLIO_MINUTE_GAP")
        rows = payload["rows"]
        if set(rows) != self.expected_by_minute[at]:
            raise ValueError("PORTFOLIO_BATCH_INCOMPLETE")
        if len({row["producer_stream_id"] for row in rows.values()}) != len(rows):
            raise ValueError("PORTFOLIO_SOURCE_ID_CONFLICT")
        batch = []
        for product, row in rows.items():
            x = decode_execution(row["execution"])
            contract = x.bar.physical_contract
            context = self.contexts[product]
            if x.bar.product != product or contract != context["contract"]:
                raise ValueError("PORTFOLIO_BATCH_CONTRACT_MISMATCH")
            schedule = {field: context[field] for field in SCHEDULE_FIELDS}
            if contract not in self.contract_inputs:
                inputs = (
                    {at: x},
                    {at.isoformat(): row["structure"]},
                    {str(day): schedule},
                )
                self.portfolio.register(product, *inputs)
                self.contract_inputs[contract] = inputs
            else:
                bars, structures, schedules = self.contract_inputs[contract]
                if at in bars:
                    raise ValueError("PORTFOLIO_BATCH_DUPLICATE_MINUTE")
                schedules[str(day)] = schedule
                bars[at], structures[at.isoformat()] = x, row["structure"]
            if chart := row.get("chart"):
                points = self.charts.setdefault(contract, [])
                points.append(chart)
                del points[:-128]
            batch.append((x, row["technical"]))
        if self.identity["kind"] == KIND:
            self.apply_current_knowledge(rows, day, observed_at)
        self.portfolio.step_batch(batch, observed_at=observed_at)
        self.sequence += 1
        self.events[payload["event_id"]] = digest(payload)

    def apply_current_knowledge(self, rows, day, observed_at):
        # Old marks remain visible with their true as-of time. They cannot
        # finance fresh portfolio risk until a real current-day mark/fact arrives.
        for contract, account in self.portfolio.accounts.items():
            mark = self.portfolio.marks.get(contract)
            if account.layers and (mark is None or mark.bar.trading_day != day):
                self.portfolio.unproven_marks.add(contract)
        for product, row in rows.items():
            known = stamp(row["execution_facts"]["captured_at"])
            if known > observed_at:
                raise ValueError("PORTFOLIO_EXECUTION_FACTS_NOT_KNOWN")
            account = self.portfolio.accounts[self.contexts[product]["contract"]]
            contract = self.contexts[product]["contract"]
            self.portfolio.unproven_marks.discard(contract)
            if account.model.pending and account.pending_known_at is not None:
                account.pending_known_at = max(account.pending_known_at, known)


    def submit(self, day, at, observed_at, prepared, *, contexts=None):
        """Commit only after the whole minute is proven and applied in memory."""
        if self.failed:
            raise ValueError("PORTFOLIO_RESTORE_REQUIRED")
        if at.utcoffset() is None or observed_at.utcoffset() is None:
            raise ValueError("PORTFOLIO_NAIVE_TIME")
        event_id = f"portfolio:{day}:{at.astimezone(UTC).isoformat()}"
        if self.identity["code_hashes"] != source_hashes():
            self.failed = True
            raise ValueError("PORTFOLIO_CODE_IDENTITY_CHANGED")
        session = contexts if contexts is not None else self.contexts_by_day.get(day)
        if session is None:
            raise ValueError("PORTFOLIO_SESSION_SCOPE_INCOMPLETE")
        payload = deepcopy(
            dict(
                event_id=event_id,
                day=day.isoformat(),
                minute=at.isoformat(),
                observed_at=observed_at.isoformat(),
                contexts=contexts,
                rows={
                    product: encode_minute(
                        product, row, session[product], at, day, observed_at
                    )
                    for product, row in prepared.items()
                },
            )
        )
        previous = self.events.get(event_id)
        if previous is not None:
            if digest(payload) != previous:
                raise ValueError("PORTFOLIO_EVENT_CONFLICT")
            return False
        sequence = self.sequence
        self.apply(payload)
        try:
            if not self.store.append(self.run_id, payload, self.projection(), sequence):
                raise ValueError("PORTFOLIO_CONCURRENT_WRITER")
        except Exception:
            self.failed = True
            raise
        return True
