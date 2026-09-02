from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.market_home_overview import (
    MarketHomeAuthorityIdentity,
    MarketHomeItem,
    MarketHomeOverviewService,
    MarketHomeOverviewSnapshot,
    MarketHomeSectorSummary,
    MarketHomeSummary,
)
from app.market_data.market_home_projection import (
    MarketHomeProjection,
    MarketHomeProjectionError,
    MarketHomeProjectionStore,
    market_home_response,
)
from app.market_data.product_taxonomy import ProductTaxonomyEntry


TARGET = date(2026, 9, 2)
IDENTITY = MarketHomeAuthorityIdentity(TARGET, "a" * 64)


class _Service:
    def __init__(
        self,
        *,
        identity: MarketHomeAuthorityIdentity = IDENTITY,
        identities: tuple[MarketHomeAuthorityIdentity, ...] | None = None,
        snapshot: MarketHomeOverviewSnapshot | None = None,
    ) -> None:
        self.identity = identity
        self.identities = identities
        self.snapshot_value = snapshot or _snapshot()
        self.identity_calls = 0
        self.snapshot_calls = 0

    def authority_identity(self) -> MarketHomeAuthorityIdentity:
        self.identity_calls += 1
        if self.identities is not None:
            index = min(self.identity_calls - 1, len(self.identities) - 1)
            return self.identities[index]
        return self.identity

    def snapshot(self) -> MarketHomeOverviewSnapshot:
        self.snapshot_calls += 1
        return self.snapshot_value


def _snapshot(*, as_of: date = TARGET) -> MarketHomeOverviewSnapshot:
    return MarketHomeOverviewSnapshot(
        status="ready",
        target_as_of=as_of,
        data_as_of=as_of,
        freshness="fresh",
        active_count=1,
        participant_count=1,
        stale_count=0,
        unavailable_count=0,
        summary=MarketHomeSummary(
            price_up_count=1,
            price_down_count=0,
            price_flat_count=0,
            daily_up_count=1,
            daily_down_count=0,
            daily_neutral_count=0,
            daily_unavailable_count=0,
            aligned_up_count=1,
            aligned_down_count=0,
        ),
        items=(
            MarketHomeItem(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2701",
                dominant_mapping_date=as_of,
                data_as_of=as_of,
                close=Decimal("1234.5"),
                price_change_1d=Decimal("0.0125"),
                price_change_5d=None,
                volume_ratio20=Decimal("1.3"),
                oi_change_1d=Decimal("0.02"),
                atr14_percentile252=None,
                daily_trend="up",
                weekly_trend="up",
                reason_codes=("price_up", "periods_aligned_up"),
            ),
        ),
        sectors=(
            MarketHomeSectorSummary(
                sector="black",
                active_count=1,
                participant_count=1,
                median_price_change_1d=Decimal("0.0125"),
            ),
        ),
    )


def _authority_service(
    products: tuple[str, ...],
    taxonomy: dict[str, ProductTaxonomyEntry],
) -> MarketHomeOverviewService:
    return MarketHomeOverviewService(
        market_data=object(),  # type: ignore[arg-type]
        products=products,
        taxonomy=taxonomy,
        latest_complete_day=lambda _products: TARGET,
    )


def test_authority_identity_is_deterministic_and_uses_existing_target_authority() -> None:
    taxonomy = {
        "jm": ProductTaxonomyEntry(name="焦煤", sector="black"),
        "rb": ProductTaxonomyEntry(name="螺纹钢", sector="steel"),
    }
    service = _authority_service(("jm", "rb"), taxonomy)

    first = service.authority_identity()
    second = service.authority_identity()

    assert first.target_as_of == TARGET
    assert first.authority_digest == second.authority_digest
    assert len(first.authority_digest) == 64


def test_authority_digest_changes_with_product_order_or_taxonomy() -> None:
    taxonomy = {
        "jm": ProductTaxonomyEntry(name="焦煤", sector="black"),
        "rb": ProductTaxonomyEntry(name="螺纹钢", sector="steel"),
    }
    baseline = _authority_service(("jm", "rb"), taxonomy).authority_identity()
    reordered = _authority_service(("rb", "jm"), taxonomy).authority_identity()
    renamed = _authority_service(
        ("jm", "rb"),
        {
            **taxonomy,
            "jm": ProductTaxonomyEntry(name="焦煤主力", sector="black"),
        },
    ).authority_identity()
    resectored = _authority_service(
        ("jm", "rb"),
        {
            **taxonomy,
            "jm": ProductTaxonomyEntry(name="焦煤", sector="other"),
        },
    ).authority_identity()

    assert len(
        {
            baseline.authority_digest,
            reordered.authority_digest,
            renamed.authority_digest,
            resectored.authority_digest,
        }
    ) == 4


def test_projection_store_round_trip_preserves_wire_types(tmp_path: Path) -> None:
    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    payload = market_home_response(_snapshot())

    store.publish(
        IDENTITY,
        payload,
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    restored = store.load(IDENTITY)

    assert restored is not None
    assert restored == payload
    raw = path.read_text(encoding="utf-8")
    assert '"close":"1234.5"' in raw
    assert '"price_change_5d":null' in raw


def test_projection_store_missing_symlink_empty_oversize_and_corrupt_are_misses(
    tmp_path: Path,
) -> None:
    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    assert store.load(IDENTITY) is None

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path.symlink_to(target)
    assert store.load(IDENTITY) is None
    path.unlink()

    path.write_text("", encoding="utf-8")
    assert store.load(IDENTITY) is None

    path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    assert store.load(IDENTITY) is None

    path.write_text("{bad json", encoding="utf-8")
    assert store.load(IDENTITY) is None


def test_projection_store_deeply_nested_json_is_a_miss(tmp_path: Path) -> None:
    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    path.write_text("[" * 10_000 + "]" * 10_000, encoding="utf-8")

    assert store.load(IDENTITY) is None


def test_projection_store_rejects_schema_target_digest_and_payload_identity_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    payload = market_home_response(_snapshot())
    store.publish(
        IDENTITY,
        payload,
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )

    valid = path.read_text(encoding="utf-8")
    assert store.load(MarketHomeAuthorityIdentity(TARGET, "b" * 64)) is None
    assert store.load(MarketHomeAuthorityIdentity(date(2026, 9, 1), "a" * 64)) is None

    path.write_text(valid.replace('"schema_version":1', '"schema_version":2'), encoding="utf-8")
    assert store.load(IDENTITY) is None

    path.write_text(
        valid.replace('"data_as_of":"2026-09-02"', '"data_as_of":"2026-09-01"'),
        encoding="utf-8",
    )
    assert store.load(IDENTITY) is None


def test_projection_store_rejects_unknown_fields_and_bad_envelope_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    payload = market_home_response(_snapshot())
    store.publish(
        IDENTITY,
        payload,
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    valid = json.loads(path.read_text(encoding="utf-8"))

    for mutate in (
        lambda value: value.update(unexpected=True),
        lambda value: value["payload"].update(unexpected=True),
        lambda value: value.update(generated_at="2026-09-02T09:00:00"),
        lambda value: value.update(authority_digest="A" * 64),
        lambda value: value.update(target_as_of="not-a-date"),
    ):
        candidate = json.loads(json.dumps(valid))
        mutate(candidate)
        path.write_text(json.dumps(candidate), encoding="utf-8")

        assert store.load(IDENTITY) is None


def test_projection_store_rejects_coerced_json_types(tmp_path: Path) -> None:
    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    store.publish(
        IDENTITY,
        market_home_response(_snapshot()),
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    valid = json.loads(path.read_text(encoding="utf-8"))

    for mutate in (
        lambda value: value.update(generated_at=1_788_329_600),
        lambda value: value["payload"].update(active_count="1"),
        lambda value: value["payload"]["items"][0].update(close=1234.5),
    ):
        candidate = json.loads(json.dumps(valid))
        mutate(candidate)
        path.write_text(json.dumps(candidate), encoding="utf-8")

        assert store.load(IDENTITY) is None


def test_projection_store_rejects_symlink_parent_on_publish(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (canonical_root / ".derived").symlink_to(outside, target_is_directory=True)
    store = MarketHomeProjectionStore(
        canonical_root / ".derived" / "market-home-overview.json"
    )

    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_WRITE_FAILED",
    ):
        store.publish(
            IDENTITY,
            market_home_response(_snapshot()),
            generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        )

    assert not tuple(outside.iterdir())


def test_projection_read_hit_does_not_call_expensive_snapshot(tmp_path: Path) -> None:
    store = MarketHomeProjectionStore(tmp_path / "market-home-overview.json")
    payload = market_home_response(_snapshot())
    store.publish(
        IDENTITY,
        payload,
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    service = _Service()
    projection = MarketHomeProjection(service=service, store=store)

    assert projection.read() == payload
    assert service.identity_calls == 1
    assert service.snapshot_calls == 0


def test_projection_read_miss_uses_existing_compute_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "market-home-overview.json"
    service = _Service()
    projection = MarketHomeProjection(
        service=service,
        store=MarketHomeProjectionStore(path),
    )

    response = projection.read()

    assert response == market_home_response(_snapshot())
    assert service.snapshot_calls == 1
    assert not path.exists()


def test_projection_refresh_rejects_identity_race_without_publishing(tmp_path: Path) -> None:
    path = tmp_path / "market-home-overview.json"
    service = _Service(snapshot=_snapshot(as_of=date(2026, 9, 3)))
    projection = MarketHomeProjection(
        service=service,
        store=MarketHomeProjectionStore(path),
    )

    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_IDENTITY_CHANGED",
    ):
        projection.refresh()

    assert not path.exists()


def test_projection_refresh_rejects_same_day_authority_digest_race(
    tmp_path: Path,
) -> None:
    path = tmp_path / "market-home-overview.json"
    service = _Service(
        identities=(
            IDENTITY,
            MarketHomeAuthorityIdentity(TARGET, "b" * 64),
        )
    )
    projection = MarketHomeProjection(
        service=service,
        store=MarketHomeProjectionStore(path),
    )

    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_IDENTITY_CHANGED",
    ):
        projection.refresh()

    assert service.identity_calls == 2
    assert not path.exists()


def test_projection_publish_replace_failure_preserves_last_good_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.market_data.market_home_projection as module

    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    payload = market_home_response(_snapshot())
    generated_at = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    store.publish(IDENTITY, payload, generated_at=generated_at)
    before = path.read_bytes()

    def fail_replace(_source, _target, **_kwargs) -> None:
        raise OSError("private replacement detail")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_WRITE_FAILED",
    ):
        store.publish(IDENTITY, payload, generated_at=generated_at)

    assert path.read_bytes() == before
    assert not tuple(tmp_path.glob(".market-home-overview.json.*.tmp"))


def test_projection_store_rejects_parent_symlink_swapped_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.market_data.market_home_projection as module

    canonical_root = tmp_path / "canonical"
    parent = canonical_root / ".derived"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    store = MarketHomeProjectionStore(parent / "market-home-overview.json")
    real_open = module.os.open
    swapped = False

    def swap_parent(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == parent and flags & module.os.O_DIRECTORY and not swapped:
            swapped = True
            parent.rmdir()
            parent.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", swap_parent)

    assert store.load(IDENTITY) is None
    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_WRITE_FAILED",
    ):
        store.publish(
            IDENTITY,
            market_home_response(_snapshot()),
            generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        )
    assert not tuple(outside.iterdir())


def test_invalidation_requires_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.market_data.market_home_projection as module

    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    store.publish(
        IDENTITY,
        market_home_response(_snapshot()),
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("fsync")

    monkeypatch.setattr(module.os, "fsync", fail_fsync)
    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_INVALIDATION_FAILED",
    ):
        store.invalidate()

    assert not path.exists()


def test_publish_fsyncs_directory_after_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.market_data.market_home_projection as module

    path = tmp_path / "market-home-overview.json"
    store = MarketHomeProjectionStore(path)
    steps: list[str] = []
    real_fsync = module.os.fsync
    real_replace = module.os.replace

    def record_fsync(descriptor: int) -> None:
        steps.append("fsync")
        real_fsync(descriptor)

    def record_replace(source, target, **kwargs) -> None:
        steps.append("replace")
        real_replace(source, target, **kwargs)

    monkeypatch.setattr(module.os, "fsync", record_fsync)
    monkeypatch.setattr(module.os, "replace", record_replace)
    store.publish(
        IDENTITY,
        market_home_response(_snapshot()),
        generated_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )

    assert steps == ["fsync", "replace", "fsync"]
