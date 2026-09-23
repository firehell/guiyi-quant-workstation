from datetime import UTC, datetime

from types import SimpleNamespace

from app.reference_trading.inputs import (
    _newow_input_fingerprint,
    _newow_replay_fingerprints,
)


def test_reused_source_bar_has_distinct_calculation_input_identity() -> None:
    common = dict(
        source_bar_sha256="a" * 64,
        bar_end=datetime(2026, 6, 1, 7, tzinfo=UTC),
        physical_contract="BZ2607",
        owner_segment_id="owner-2607",
        quality_policy="strict",
    )
    first = _newow_input_fingerprint(**common, calculation_segment_id="calc-2607")
    reused = _newow_input_fingerprint(**common, calculation_segment_id="calc-2608")

    assert first != reused
    assert first == _newow_input_fingerprint(**common, calculation_segment_id="calc-2607")


def test_replay_fingerprints_are_prefix_stable_when_a_bar_is_reused_later() -> None:
    at = datetime(2026, 6, 1, 7, tzinfo=UTC)

    def item(source: str, calculation: str):
        return SimpleNamespace(
            source_bar_sha256=source,
            calculation_segment_id=calculation,
            bar=SimpleNamespace(
                bar_end=at, physical_contract="BZ2607", segment_id="owner-2607",
            ),
        )

    bars = (item("a" * 64, "calc-2607"), item("a" * 64, "calc-2608"),
            item("b" * 64, "calc-2608"))
    fingerprints = _newow_replay_fingerprints(bars, "strict")

    assert len(set(fingerprints)) == len(bars)
    assert _newow_replay_fingerprints(bars[:1], "strict") == fingerprints[:1]
    assert _newow_replay_fingerprints(bars[:2], "strict") == fingerprints[:2]
