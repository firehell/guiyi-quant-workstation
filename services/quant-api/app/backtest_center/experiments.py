"""Durable historical experiments over independently published backtest runs."""

from contextlib import closing
from datetime import UTC, date, datetime, time
from decimal import Decimal, DecimalException
import json
from pathlib import Path
import sqlite3
from typing import Annotated, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtest_center.codec import encode
from app.backtest_center.contracts import BacktestError, RunConfig
from app.backtest_center.plus_reconcile import ACCOUNT_BINARY_TOLERANCE

Axis = Literal["parameters", "strategy", "product", "frequency", "commission", "slippage"]
Metric = Literal["net_return", "max_drawdown"]
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "INSUFFICIENT"})
ENVIRONMENT_FIELDS = (
    "engine",
    "code_revision",
    "code_sha256",
    "data_revision",
    "qualification",
    "execution_policy",
    "roll_policy_version",
    "data_source",
    "cost_profile_id",
    "cost_rows_sha256",
)
AXIS_FIELDS = {
    "parameters": {"parameters"},
    "strategy": {"strategy_id", "formula_version", "profile_id"},
    "product": {"product", "contract"},
    "frequency": {"signal_frequency"},
    "commission": {"commission_multiplier"},
    "slippage": {"slippage_ticks"},
}
SHANGHAI = ZoneInfo("Asia/Shanghai")
# The admitted domestic futures profile settles after the day session and before the next auction.
SELECTION_CUTOFF_LOCAL = time(17)
MAX_ACTIVE_EXPERIMENTS = 8
SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    request_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    state TEXT NOT NULL
);
"""


class FoldConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train_warmup_start: date
    train_start: date
    train_end: date
    test_warmup_start: date
    test_start: date
    test_end: date

    @model_validator(mode="after")
    def chronology(self):
        if (
            not self.train_warmup_start < self.train_start <= self.train_end < self.test_start <= self.test_end
            or self.test_warmup_start >= self.test_start
        ):
            raise ValueError("EXPERIMENT_WINDOW_INVALID")
        return self


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: Annotated[str, Field(pattern=r"^[a-zA-Z0-9._:-]{1,100}$")]
    kind: Literal["comparison", "oos", "walk_forward"]
    axes: Annotated[list[Axis], Field(min_length=1, max_length=6)]
    configs: Annotated[list[RunConfig], Field(min_length=2, max_length=12)]
    metric: Metric = "net_return"
    folds: Annotated[list[FoldConfig], Field(max_length=8)] = Field(default_factory=list)

    @model_validator(mode="after")
    def budget_and_order(self):
        low, high = {"comparison": (0, 0), "oos": (1, 1), "walk_forward": (2, 8)}[self.kind]
        if not low <= len(self.folds) <= high or len(self.axes) != len(set(self.axes)):
            raise ValueError("EXPERIMENT_PLAN_INVALID")
        if len(self.configs) * max(1, len(self.folds)) + len(self.folds) > 48:
            raise ValueError("EXPERIMENT_RUN_BUDGET_EXCEEDED")
        if any(
            left.test_end >= right.test_start or left.train_end >= right.train_end
            for left, right in zip(self.folds, self.folds[1:])
        ):
            raise ValueError("EXPERIMENT_FOLDS_OVERLAP_OR_UNORDERED")
        if len({encode(config.model_dump(mode="json", exclude={"sample_type"})) for config in self.configs}) != len(
            self.configs
        ):
            raise ValueError("EXPERIMENT_DUPLICATE_CONFIG")
        return self


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _connect(path: Path, *, readonly: bool = False):
    target = path.as_uri() + "?mode=ro" if readonly else path
    db = sqlite3.connect(target, timeout=5, isolation_level=None, uri=readonly)
    db.row_factory = sqlite3.Row
    return db


def _path(store) -> Path:
    return store.path.with_name(f"{store.path.name}.experiments.sqlite3")


def _member(experiment_id, config, *, phase, fold=None, candidate):
    return {
        "member_id": f"{experiment_id}:{fold or 0}:{phase}:{candidate}",
        "fold": fold,
        "phase": phase,
        "research_config": config,
        "run_id": None,
        "status": "PENDING",
        "diagnostic": None,
        "metrics": None,
        "snapshot": None,
    }


def _windows(config: dict, fold: dict, phase: str) -> dict:
    return {
        **config,
        "warmup_start": fold[f"{phase}_warmup_start"],
        "start": fold[f"{phase}_start"],
        "end": fold[f"{phase}_end"],
        "sample_type": "train" if phase == "train" else "oos",
    }


def _initial(request: ExperimentRequest) -> dict:
    definition = request.model_dump(mode="json", exclude={"request_key"})
    definition["tie_break"] = "submitted_candidate_order"
    experiment_id = uuid4().hex
    members = []
    folds = []
    if request.kind == "comparison":
        for candidate, config in enumerate(definition["configs"], 1):
            members.append(
                _member(experiment_id, {**config, "sample_type": "experiment"}, phase="comparison", candidate=candidate)
            )
    else:
        for number, fold in enumerate(definition["folds"], 1):
            fold_members = [
                _member(experiment_id, _windows(config, fold, "train"), phase="train", fold=number, candidate=candidate)
                for candidate, config in enumerate(definition["configs"], 1)
            ]
            # The same candidate must mean different settings inside the actual evaluation window.
            if len({encode(member["research_config"]) for member in fold_members}) != len(fold_members):
                raise BacktestError("EXPERIMENT_DUPLICATE_FOLD_CONFIG")
            for member in fold_members:
                RunConfig.model_validate(member["research_config"])
                RunConfig.model_validate(_windows(member["research_config"], fold, "test"))
            members.extend(fold_members)
            folds.append(
                {
                    **fold,
                    "fold": number,
                    "selection_cutoff": datetime.combine(
                        date.fromisoformat(fold["train_end"]), SELECTION_CUTOFF_LOCAL, SHANGHAI
                    ).isoformat(),
                    "selection_policy": "completed_training_settlement_only_v1",
                    "selection_valuation_at": None,
                    "selected_at": None,
                    "selected_member_id": None,
                    "test_member_id": None,
                    "boundary_policy": "settlement_mark_then_flat_start_v1",
                    "test_initial_position": "FLAT",
                    "test_initial_equity": None,
                    "status": "TRAINING",
                    "diagnostic": None,
                }
            )
    now = _now()
    return {
        "experiment_id": experiment_id,
        "kind": request.kind,
        "status": "QUEUED",
        "created_at": now,
        "updated_at": now,
        "definition": definition,
        "members": members,
        "folds": folds,
        "comparison": None,
        "evidence": None,
    }


def create_experiment(store, request: ExperimentRequest) -> dict:
    state = _initial(request)
    with closing(_connect(_path(store))) as db:
        db.execute(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT state FROM experiments WHERE request_key = ?", (request.request_key,)).fetchone()
        if existing:
            original = json.loads(existing["state"])
            if original["definition"] != state["definition"]:
                raise BacktestError("EXPERIMENT_REQUEST_KEY_CONFLICT")
            return original
        count = db.execute("SELECT COUNT(*) FROM experiments WHERE status IN ('QUEUED', 'RUNNING')").fetchone()[0]
        if count >= MAX_ACTIVE_EXPERIMENTS:
            raise BacktestError("EXPERIMENT_QUEUE_FULL")
        db.execute(
            "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                state["experiment_id"],
                request.kind,
                request.request_key,
                state["created_at"],
                state["updated_at"],
                state["status"],
                encode(state),
            ),
        )
        db.commit()
    return state


def read_experiment(store, experiment_id: str) -> dict | None:
    path = _path(store)
    if not path.is_file():
        return None
    with closing(_connect(path, readonly=True)) as db:
        row = db.execute("SELECT state FROM experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
    if not row:
        return None
    state = json.loads(row["state"])
    if state["kind"] == "comparison" and state["comparison"] and state["evidence"] is None:
        # Legacy comparisons have only their published member Runs. Apply the
        # settlement and coverage checks before exposing comparison evidence.
        for member in state["members"]:
            if member["status"] == "SUCCEEDED":
                _observe(store, member)
        _compare(state)
    return state


def list_experiments(store, *, kind: str | None, limit: int, offset: int) -> dict:
    path = _path(store)
    if not path.is_file():
        return {"items": [], "total": 0}
    with closing(_connect(path, readonly=True)) as db:
        db.execute("BEGIN")
        total = db.execute("SELECT COUNT(*) FROM experiments WHERE kind = ? OR ? IS NULL", (kind, kind)).fetchone()[0]
        rows = db.execute(
            "SELECT experiment_id, kind, status, created_at, updated_at FROM experiments "
            "WHERE kind = ? OR ? IS NULL ORDER BY created_at DESC, experiment_id DESC LIMIT ? OFFSET ?",
            (kind, kind, limit, offset),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total}


def _decimal(value) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("NONFINITE_EVALUATION")
    return amount


def _curve(run: dict, result: dict) -> list[dict]:
    """Validate the native daily sequence itself instead of trusting its aggregate metrics."""
    config = run["config"]
    start, end = date.fromisoformat(config["start"]), date.fromisoformat(config["end"])
    report = result["report"]
    expected = report["evaluation_trading_days"]
    snapshot_days = run["snapshot"].get("evaluation_trading_days")
    rows = result["equity"]
    evaluation_days = set(expected)
    settlements = [row for row in report["native_settlements"] if row["trading_day"] in evaluation_days]
    if (
        not expected
        or snapshot_days != expected
        or [row["trading_day"] for row in rows] != expected
        or [row["trading_day"] for row in settlements] != expected
    ):
        raise ValueError("EVALUATION_COVERAGE_UNPROVEN")
    curve = []
    previous_day = None
    initial = _decimal(config["initial_capital"])
    if (
        initial <= 0
        or _decimal(report["evaluation_initial_equity"]) != initial
        or report["evaluation_initial_position"] != "FLAT"
    ):
        raise ValueError("EVALUATION_BASELINE_INVALID")
    opening = datetime.fromisoformat(report["first_evaluation_session_open"])
    if opening.utcoffset() is None:
        raise ValueError("EVALUATION_SESSION_CLOCK_INVALID")
    for row, settlement in zip(rows, settlements, strict=True):
        day = date.fromisoformat(row["trading_day"])
        valuation = datetime.fromisoformat(row["at"])
        native_at = datetime.fromisoformat(settlement["at"])
        if (
            not start <= day <= end
            or previous_day is not None
            and day <= previous_day
            or valuation.utcoffset() is None
            or valuation.astimezone(SHANGHAI).date() != day
            or valuation.astimezone(SHANGHAI).time() < time(15)
            or valuation <= opening
            or native_at != valuation
        ):
            raise ValueError("EVALUATION_VALUATION_OUTSIDE_WINDOW")
        equity = _decimal(row["equity"])
        native_equity = _decimal(settlement["after"]["native_equity"]["repr"])
        if abs(equity - native_equity) > ACCOUNT_BINARY_TOLERANCE:
            raise ValueError("EVALUATION_SETTLEMENT_EQUITY_MISMATCH")
        curve.append(
            {"trading_day": day.isoformat(), "valuation_at": valuation.isoformat(), "wealth": equity / initial}
        )
        previous_day = day
    if not curve:
        raise ValueError("EVALUATION_COVERAGE_UNPROVEN")
    return curve


def _statistics(curve: list[dict]) -> dict:
    peak = previous = Decimal(1)
    max_drawdown = Decimal(0)
    daily_returns = []
    for row in curve:
        wealth = row["wealth"]
        peak = max(peak, wealth)
        max_drawdown = max(max_drawdown, 1 - wealth / peak)
        if previous > 0:
            daily_returns.append(wealth / previous - 1)
        previous = wealth
    volatility = None
    if len(daily_returns) == len(curve) and len(daily_returns) >= 2:
        mean = sum(daily_returns) / len(daily_returns)
        volatility = str((sum((value - mean) ** 2 for value in daily_returns) / (len(daily_returns) - 1)).sqrt())
    return {
        "net_return": str(curve[-1]["wealth"] - 1),
        "max_drawdown": str(max_drawdown),
        "trading_days": len(curve),
        "positive_days": sum(value > 0 for value in daily_returns) if len(daily_returns) == len(curve) else None,
        "daily_return_volatility": volatility,
        "last_valuation_at": curve[-1]["valuation_at"],
    }


def _contract_digest(member: dict) -> str | None:
    name = member["research_config"]["contract"] + ".h5"
    return member["snapshot"].get("data_files", {}).get(name)


def _observe(store, member):
    run = store.get(member["run_id"])
    if run is None:
        member.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_RUN_UNREADABLE")
        return
    member.update(status=run["status"], diagnostic=run.get("diagnostic"))
    if run["status"] != "SUCCEEDED":
        return
    member["snapshot"] = run.get("snapshot")
    try:
        if any(run["config"].get(key) != value for key, value in member["research_config"].items()):
            raise ValueError("EVALUATION_CONFIGURATION_MISMATCH")
        if not _contract_digest(member) or not all(
            member["snapshot"].get(key)
            for key in ("data_revision", "input_sha256", "engine", "code_revision", "code_sha256", "execution_policy")
        ):
            raise ValueError("EVALUATION_IDENTITY_UNPROVEN")
        result = store.result(member["run_id"])
        metrics = _statistics(_curve(run, result))
        report = result["report"]
        position = report["terminal_position"]
        if position is not None and (
            position["contract"] != member["research_config"]["contract"]
            or datetime.fromisoformat(position["marked_at"]) != datetime.fromisoformat(metrics["last_valuation_at"])
            or _decimal(position["quantity"]) <= 0
            or _decimal(position["mark_price"]) <= 0
        ):
            raise ValueError("EVALUATION_TERMINAL_POSITION_INVALID")
        metrics["trade_count"] = result["summary"]["metrics"]["trade_count"]["value"]
        member["metrics"] = metrics
        member["first_evaluation_session_open"] = report["first_evaluation_session_open"]
        member["terminal_position"] = position
    except (DecimalException, KeyError, TypeError, ValueError, AttributeError):
        member.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_EVALUATION_FACTS_INSUFFICIENT")


def _differences(members: list[dict], axes: list[Axis]) -> list[str]:
    varied = set().union(*(AXIS_FIELDS[axis] for axis in axes))
    conflicts = []
    for field in sorted(set().union(*(member["research_config"].keys() for member in members)) - varied):
        if len({encode(member["research_config"].get(field)) for member in members}) > 1:
            conflicts.append(field)
    successful = [member for member in members if member["status"] == "SUCCEEDED"]
    for field in ENVIRONMENT_FIELDS:
        if len({encode(member["snapshot"].get(field)) for member in successful}) > 1:
            conflicts.append(field)
    # Within one selected physical contract and window, candidates must see the same native slice.
    slices = {}
    versions = {}
    for member in successful:
        config = member["research_config"]
        key = tuple(config[field] for field in ("contract", "warmup_start", "start", "end"))
        slices.setdefault(key, set()).add(member["snapshot"]["input_sha256"])
        versions.setdefault(config["contract"], set()).add(_contract_digest(member))
    if any(len(values) != 1 for values in slices.values()):
        conflicts.append("input_sha256")
    if any(len(values) != 1 for values in versions.values()):
        conflicts.append("physical_contract_data")
    if len({tuple(member["snapshot"]["evaluation_trading_days"]) for member in successful}) > 1:
        conflicts.append("evaluation_trading_days")
    return conflicts


def _ranking(members: list[dict], metric: Metric) -> list[str]:
    sign = -1 if metric == "net_return" else 1
    return [
        member["member_id"] for member in sorted(members, key=lambda item: sign * _decimal(item["metrics"][metric]))
    ]


def _select(state: dict):
    definition = state["definition"]
    for fold in state["folds"]:
        if fold["status"] != "TRAINING":
            continue
        candidates = [
            member for member in state["members"] if member["fold"] == fold["fold"] and member["phase"] == "train"
        ]
        if any(member["status"] not in TERMINAL for member in candidates):
            continue
        differences = _differences(candidates, definition["axes"])
        fold["condition_differences"] = differences
        if differences or any(member["status"] != "SUCCEEDED" for member in candidates):
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TRAINING_NOT_COMPARABLE")
            continue
        cutoff = datetime.fromisoformat(fold["selection_cutoff"])
        latest_valuation = max(datetime.fromisoformat(item["metrics"]["last_valuation_at"]) for item in candidates)
        if latest_valuation > cutoff:
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TRAINING_SETTLEMENT_AFTER_CUTOFF")
            continue
        selected_id = _ranking(candidates, definition["metric"])[0]
        selected = next(member for member in candidates if member["member_id"] == selected_id)
        config = _windows(selected["research_config"], fold, "test")
        member = _member(state["experiment_id"], config, phase="test", fold=fold["fold"], candidate=1)
        state["members"].append(member)
        fold.update(
            status="SELECTED",
            selected_at=_now(),
            selected_member_id=selected_id,
            selection_valuation_at=selected["metrics"]["last_valuation_at"],
            latest_training_valuation_at=latest_valuation.isoformat(),
            training_boundary_position=selected["terminal_position"],
            test_member_id=member["member_id"],
            test_initial_equity=config["initial_capital"],
        )


def _comparison_evidence(state: dict) -> dict:
    return {
        "experiment_id": state["experiment_id"],
        "kind": "comparison",
        "status": state["status"],
        "scope": "historical_research",
        "comparison": state["comparison"],
        "run_ids": [member["run_id"] for member in state["members"] if member["run_id"]],
    }


def _compare(state):
    members, definition = state["members"], state["definition"]
    if any(member["status"] not in TERMINAL for member in members):
        return
    successful = [member for member in members if member["status"] == "SUCCEEDED"]
    differences = _differences(members, definition["axes"])
    comparable = not differences and len(successful) == len(members)
    state["comparison"] = {
        "comparable": comparable,
        "condition_differences": differences,
        "metric": definition["metric"],
        "ranked_member_ids": _ranking(successful, definition["metric"]) if comparable else [],
        "failed_members": len(members) - len(successful),
    }
    state["status"] = "SUCCEEDED" if comparable else "INSUFFICIENT"
    state["evidence"] = _comparison_evidence(state)


def _validation(store, state):
    _select(state)
    members = {member["member_id"]: member for member in state["members"]}
    for fold in state["folds"]:
        if fold["status"] != "SELECTED":
            continue
        test, trained = members[fold["test_member_id"]], members[fold["selected_member_id"]]
        if test["status"] == "SUCCEEDED":
            same_environment = all(
                test["snapshot"].get(field) == trained["snapshot"].get(field) for field in ENVIRONMENT_FIELDS
            )
            cutoff = datetime.fromisoformat(fold["selection_cutoff"])
            first_test_session = datetime.fromisoformat(test["first_evaluation_session_open"])
            if not same_environment or _contract_digest(test) != _contract_digest(trained):
                fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TRAIN_TEST_INPUT_DRIFT")
            elif cutoff >= first_test_session:
                fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TRAIN_TEST_CLOCK_OVERLAP")
            else:
                fold.update(status="SUCCEEDED", first_test_session_open=first_test_session.isoformat())
        elif test["status"] in TERMINAL:
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TEST_RESULT_INSUFFICIENT")
    if any(fold["status"] not in TERMINAL for fold in state["folds"]):
        return

    curve = []
    environment = None
    contract_digests = {}
    for fold in state["folds"]:
        if fold["status"] != "SUCCEEDED":
            continue
        test = members[fold["test_member_id"]]
        observed = tuple(test["snapshot"].get(field) for field in ENVIRONMENT_FIELDS)
        contract = test["research_config"]["contract"]
        contract_digest = _contract_digest(test)
        if (environment is not None and environment != observed) or contract_digests.get(
            contract, contract_digest
        ) != contract_digest:
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_FOLD_ENVIRONMENT_DRIFT")
            continue
        try:
            portion = _curve(store.get(test["run_id"]), store.result(test["run_id"]))
        except (DecimalException, KeyError, TypeError, ValueError, AttributeError):
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TEST_CURVE_UNREADABLE")
            continue
        if curve and curve[-1]["trading_day"] >= portion[0]["trading_day"]:
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_TEST_VALUATIONS_OVERLAP")
            continue
        baseline = curve[-1]["wealth"] if curve else Decimal(1)
        if baseline <= 0:
            fold.update(status="INSUFFICIENT", diagnostic="EXPERIMENT_CHAIN_BASELINE_DEPLETED")
            continue
        environment = observed
        contract_digests[contract] = contract_digest
        curve.extend({**point, "wealth": baseline * point["wealth"], "fold": fold["fold"]} for point in portion)

    missing = [fold["fold"] for fold in state["folds"] if fold["status"] != "SUCCEEDED"]
    state["status"] = "INSUFFICIENT" if missing else "SUCCEEDED"
    state["evidence"] = {
        "experiment_id": state["experiment_id"],
        "kind": state["kind"],
        "status": state["status"],
        "missing_folds": missing,
        "scope": "historical_research",
        "aggregation": "chain_linked_daily_post_settlement_returns_flat_start_v1",
        "metrics": _statistics(curve) if curve else None,
        "curve": [{**point, "wealth": str(point["wealth"])} for point in curve],
        "folds": state["folds"],
        "run_ids": [member["run_id"] for member in state["members"] if member["run_id"]],
    }


def _advance(store, state):
    state["status"] = "RUNNING"
    for member in state["members"]:
        if member["status"] in TERMINAL:
            continue
        if member["run_id"] is None:
            try:
                run = store.submit(f"experiment:{member['member_id']}", member["research_config"])
            except BacktestError as exc:
                if exc.code in {"BACKTEST_QUEUE_FULL", "BACKTEST_RUN_QUEUE_FULL", "BACKTEST_SUBMIT_UNKNOWN"}:
                    break
                member.update(status="FAILED", diagnostic=exc.code)
                continue
            member["run_id"] = run["run_id"]
        _observe(store, member)
    if state["kind"] == "comparison":
        _compare(state)
    else:
        _validation(store, state)


def advance_experiments(store) -> None:
    """Advance plans on the bounded research worker. Readers never dispatch work."""
    path = _path(store)
    if not path.is_file():
        return
    with closing(_connect(path)) as db:
        ids = db.execute(
            "SELECT experiment_id FROM experiments WHERE status IN ('QUEUED', 'RUNNING') ORDER BY created_at",
        ).fetchall()
    for row in ids:
        with closing(_connect(path)) as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute(
                "SELECT state, status FROM experiments WHERE experiment_id = ?", (row["experiment_id"],)
            ).fetchone()
            if record is None or record["status"] in TERMINAL:
                continue
            state = json.loads(record["state"])
            _advance(store, state)
            if encode(state) != record["state"]:
                state["updated_at"] = _now()
                db.execute(
                    "UPDATE experiments SET state = ?, status = ?, updated_at = ? WHERE experiment_id = ?",
                    (encode(state), state["status"], state["updated_at"], state["experiment_id"]),
                )
                db.commit()
