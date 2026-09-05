"""Product boundary validation, stable identities and independently owned cases."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.newow.product_contracts import (
    FeatureStatus,
    ProductBar,
    ProductIdentity,
    StrategyHint,
)
from guiyi_quant.newow.product_identity import (
    build_reference_trade_id,
    build_segment_id,
    build_signal_id,
)


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_product_combinations_and_profile(product_cases, strategy, frequency):
    case = product_cases.closed(strategy=strategy, frequency=frequency)
    assert case.identity.profile_id == f"newow_product_{strategy}_{frequency}_v1"
    assert case.identity.series_kind == "actual_dominant"
    assert all(bar.frequency == frequency for bar in case.bars)


@pytest.mark.parametrize(
    "changes",
    [
        {"strategy": "unknown"},
        {"frequency": "15m"},
        {"series_kind": "continuous"},
        {"product": ""},
        {"product": "RB"},
        {"formula_versions": ()},
        {"formula_versions": ("",)},
        {"formula_versions": "formula"},
        {"profile_id": "old-profile"},
    ],
)
def test_identity_rejects_invalid_contract(product_cases, changes):
    with pytest.raises(ValueError):
        replace(product_cases.closed().identity, **changes)


def test_formula_set_is_canonical_and_defensively_copied():
    formulas = ["formula-b", "formula-a"]
    identity = ProductIdentity("rb", "trend", "1d", formulas)
    formulas.append("mutated")
    assert identity.formula_versions == ("formula-a", "formula-b")
    assert identity == ProductIdentity("rb", "trend", "1d", ("formula-b", "formula-a"))


@pytest.mark.parametrize(
    "changes",
    [
        {"completed": False},
        {"bar_end": datetime(2026, 1, 5)},
        {"close": 100.0},
        {"close": Decimal("NaN")},
        {"close": Decimal("0")},
        {"high": Decimal("50")},
    ],
)
def test_product_bar_rejects_invalid_market_fact(product_cases, changes):
    with pytest.raises(ValueError):
        replace(product_cases.closed().bars[0].bar, **changes)


def test_product_bar_rejects_frequency_and_series(product_cases):
    bar = product_cases.closed().bars[0]
    for changes in ({"frequency": "15m"}, {"series_kind": "contract"}, {"bar": None}):
        with pytest.raises(ValueError):
            replace(bar, **changes)
    assert isinstance(bar, ProductBar)


@pytest.mark.parametrize("field", ["reference_price", "anchor_price"])
@pytest.mark.parametrize(
    "price",
    [
        100,
        100.0,
        "100",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("0"),
        Decimal("-1"),
    ],
)
def test_action_rejects_non_authoritative_price(product_cases, field, price):
    with pytest.raises(ValueError):
        replace(product_cases.closed().entry, **{field: price})


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "REDUCE"},
        {"sequence": -1},
        {"sequence": True},
        {"sequence": 0.5},
        {"bar_end": datetime(2026, 1, 5)},
        {"physical_contract": "rb2605"},
        {"segment_id": ""},
        {"trade_eligibility": "yes"},
    ],
)
def test_action_rejects_invalid_identity_fields(product_cases, changes):
    with pytest.raises(ValueError):
        replace(product_cases.closed().entry, **changes)


def test_identity_changes_only_with_identity_tuple(product_cases):
    case = product_cases.closed()
    entry = case.entry
    assert entry.signal_id == product_cases.closed(entry="99").entry.signal_id
    assert (
        entry.signal_id
        == replace(
            entry, anchor_price=Decimal("101"), source_marker_id="old:other"
        ).signal_id
    )
    changed_window = replace(
        case, window=replace(case.window, through=case.as_of + timedelta(days=1))
    )
    assert build_reference_trade_id(entry) == build_reference_trade_id(
        changed_window.entry
    )
    variants = [
        product_cases.closed(strategy="main_rise").entry,
        product_cases.closed(frequency="60m").entry,
        replace(entry, identity=replace(entry.identity, product="cu")),
        replace(
            entry, identity=replace(entry.identity, formula_versions=("formula-v2",))
        ),
        replace(entry, physical_contract="RB2610"),
        replace(
            entry,
            segment_id=build_segment_id(
                "rb", "RB2605", datetime(2026, 1, 6, tzinfo=UTC)
            ),
        ),
        replace(entry, bar_end=entry.bar_end + timedelta(hours=1)),
        replace(entry, kind="CLEAR"),
        replace(entry, sequence=1),
    ]
    assert len({entry.signal_id, *(a.signal_id for a in variants)}) == 10
    assert len(entry.signal_id) == 64
    assert build_reference_trade_id(entry) != build_reference_trade_id(variants[0])
    with pytest.raises(ValueError):
        build_reference_trade_id(case.exit)
    with pytest.raises(ValueError):
        build_reference_trade_id(product_cases.warmup_only_build().entry)


def test_utc_canonicalization_and_owner_reentry(product_cases):
    entry = product_cases.closed().entry
    local = entry.bar_end.astimezone(timezone(timedelta(hours=8)))
    assert replace(entry, bar_end=local).signal_id == entry.signal_id
    assert replace(entry, bar_end=local).bar_end.tzinfo == UTC
    start = datetime(2026, 1, 5, tzinfo=UTC)
    assert build_segment_id("rb", "RB2605", start) == build_segment_id(
        "rb",
        "RB2605",
        start.astimezone(timezone(timedelta(hours=8))),
    )
    assert build_segment_id("rb", "RB2605", start) != build_segment_id(
        "rb", "RB2605", start + timedelta(days=2)
    )
    with pytest.raises(ValueError):
        build_signal_id(
            entry.identity, "RB2605", entry.segment_id, datetime(2026, 1, 5), "BUILD", 0
        )


def test_signal_hash_matches_literal_canonical_identity(product_cases):
    # SHA-256 of the nine specified identity fields, independently encoded as
    # sorted compact JSON; catches adding price/profile/viewport or changing encoding.
    assert product_cases.closed().entry.signal_id == (
        "22c014979750b8e28939089ffe4886cb1c95b2f59e34d8fdcc8d2f79bb3117a1"
    )


def test_oscillation_same_bar_cannot_reverse_clear_build(product_cases):
    frame = product_cases.same_bar_rebuild().replay.frames[-1]
    clear, build = frame.actions
    with pytest.raises(ValueError):
        replace(frame, actions=(replace(build, sequence=0), replace(clear, sequence=1)))


def test_warmup_frame_cannot_claim_eligible_build(product_cases):
    frame = product_cases.warmup_only_build().replay.frames[0]
    with pytest.raises(ValueError):
        replace(
            frame, actions=(replace(frame.actions[0], trade_eligibility="ELIGIBLE"),)
        )


def test_hint_duplicates_are_idempotent_and_content_conflicts_fail(product_cases):
    frame = product_cases.closed().replay.frames[0]
    hint = make_hint(frame.actions[0])
    assert replace(frame, hints=(hint, replace(hint))).hints == (hint,)
    with pytest.raises(ValueError, match="CONFLICT"):
        replace(frame, hints=(hint, replace(hint, anchor_price=Decimal("98"))))


def test_replay_freezes_caller_collections(product_cases):
    case = product_cases.closed()
    values = [["reference", Decimal("100")]]
    frame = replace(case.replay.frames[0], main_values=values)
    values[0][1] = Decimal("1")
    assert frame.main_values == (("reference", Decimal("100")),)
    frames = list(case.replay.frames)
    replay = replace(case.replay, frames=frames)
    frames.clear()
    assert len(replay.frames) == 2


def test_duplicate_action_is_idempotent_but_conflict_fails(product_cases):
    case = product_cases.closed()
    replay = replace(case.replay, actions=(case.entry, replace(case.entry), case.exit))
    assert replay.actions == (case.entry, case.exit)
    with pytest.raises(ValueError, match="CONFLICT"):
        replace(
            case.replay,
            actions=(
                case.entry,
                replace(case.entry, reference_price=Decimal("101")),
                case.exit,
            ),
        )
    with pytest.raises(ValueError):
        replace(case.replay, actions=(case.exit, case.entry))


def make_hint(entry, **changes):
    values = dict(
        identity=entry.identity,
        physical_contract=entry.physical_contract,
        segment_id=entry.segment_id,
        bar_end=entry.bar_end,
        trading_day=entry.trading_day,
        kind="D1",
        known_at=entry.bar_end,
        anchor_price=Decimal("99"),
        source_marker_id="owned:hint",
    )
    return StrategyHint(**(values | changes))


def test_hint_has_separate_identity_and_no_quantity_effect(product_cases):
    entry = product_cases.closed().entry
    hint = make_hint(entry)
    assert hint.quantity_effect == "none"
    assert hint.sequence is None
    assert hint.hint_id != entry.signal_id
    assert make_hint(entry, anchor_price=Decimal("98")).hint_id == hint.hint_id
    for changes in (
        {"quantity_effect": "reduce"},
        {"known_at": datetime(2026, 1, 5)},
        {"known_at": entry.bar_end - timedelta(seconds=1)},
        {"anchor_price": 99.0},
        {"retrospective": True},
    ):
        with pytest.raises(ValueError):
            make_hint(entry, **changes)


@pytest.mark.parametrize(
    "status", ["warming", "unavailable", "not_applicable", "evidence_required"]
)
def test_feature_status_requires_reason_without_conflating_evidence(status):
    with pytest.raises(ValueError):
        FeatureStatus(status, "ACTIVE_CODE_VERIFIED")
    feature = FeatureStatus(status, "ACTIVE_CODE_VERIFIED", "owned:reason")
    assert feature.status == status
    assert feature.evidence_status == "ACTIVE_CODE_VERIFIED"
    with pytest.raises(ValueError):
        FeatureStatus("no_signal", "ACTIVE_CODE_VERIFIED")
    with pytest.raises(ValueError):
        FeatureStatus("ready", "UNKNOWN")


def test_factories_have_explicit_actions_and_completed_owned_bars(product_cases):
    case = product_cases.closed()
    assert [bar.bar.trading_day.isoformat() for bar in case.bars] == [
        "2026-01-05",
        "2026-01-06",
    ]
    assert [a.kind for a in case.replay.actions] == ["BUILD", "CLEAR"]
    assert [a.sequence for a in case.replay.actions] == [0, 0]
    assert case.exit.related_build_id == case.entry.signal_id
    assert case.entry.reference_price == Decimal("100")
    assert case.exit.reference_price == Decimal("110")
    hourly = product_cases.closed(frequency="60m")
    assert hourly.bars[0].bar.trading_day == hourly.bars[1].bar.trading_day
    assert hourly.bars[0].bar.bar_end < hourly.bars[1].bar.bar_end
    for factory in (
        product_cases.closed,
        product_cases.open,
        product_cases.interrupted,
        product_cases.same_bar_rebuild,
        product_cases.warmup_only_build,
    ):
        first, second = factory(), factory()
        assert first == second and first is not second
        assert first.identity is not second.identity
        assert first.bars[0] is not second.bars[0]
        assert first.replay is not second.replay
        assert all(
            bar.bar.completed and bar.bar.bar_end < first.as_of for bar in first.bars
        )
        assert first.as_of == datetime(2026, 1, 9, 16, tzinfo=UTC)
    opened = product_cases.open()
    assert opened.exit is None and [a.kind for a in opened.replay.actions] == ["BUILD"]
    interrupted = product_cases.interrupted()
    assert interrupted.bars[-1].bar.close == Decimal("90")
    assert interrupted.boundaries[0].old_segment_id == interrupted.entry.segment_id
    assert interrupted.boundaries[0].effective_at < interrupted.as_of
    assert interrupted.exit is None
    same_bar = product_cases.same_bar_rebuild().replay.actions
    assert [(a.kind, a.sequence) for a in same_bar] == [
        ("BUILD", 0),
        ("CLEAR", 0),
        ("BUILD", 1),
    ]
    assert same_bar[1].bar_end == same_bar[2].bar_end
    warmup = product_cases.warmup_only_build()
    assert not warmup.bars[0].bar.observation_eligible
    assert warmup.entry.trade_eligibility == "WARMUP_ONLY"
    assert warmup.exit.trade_eligibility == "NO_ELIGIBLE_ENTRY"


def test_replay_and_frames_are_immutable_and_validate_input(product_cases):
    case = product_cases.closed()
    actions = [case.entry, case.exit]
    replay = replace(case.replay, actions=actions)
    actions.clear()
    assert len(replay.actions) == 2
    assert replay.main_values[0] == (
        case.entry.bar_end,
        "BUILD",
        (("reference", Decimal("100")),),
        (case.entry,),
    )
    with pytest.raises(FrozenInstanceError):
        case.entry.reference_price = Decimal("1")
    with pytest.raises(ValueError):
        replace(case.replay.frames[0], main_state="REDUCE")
    with pytest.raises(ValueError):
        replace(
            case.replay, identity=product_cases.closed(strategy="main_rise").identity
        )
    with pytest.raises(ValueError):
        replace(case.replay, frames=tuple(reversed(case.replay.frames)))


def test_owner_boundary_requires_authoritative_source_and_aware_time(product_cases):
    boundary = product_cases.interrupted().boundaries[0]
    for changes in (
        {"source_identity": ""},
        {"effective_at": datetime(2026, 1, 7)},
        {"new_segment_id": boundary.old_segment_id},
    ):
        with pytest.raises(ValueError):
            replace(boundary, **changes)
