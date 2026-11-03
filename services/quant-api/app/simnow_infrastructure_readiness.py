"""Read-only market admission for the one operator-interruption recovery."""

from datetime import UTC, datetime
from hashlib import sha256
import json
import re
from time import monotonic, sleep


def recovery_window(day, now, *, redis=None):
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
    from app.market_data.operational_universe import load_operational_products
    from app.runtime_bindings import read_bindings, registry_path
    from app.runtime_handover import (
        read_service_state,
        owner_lock_available,
        _read,
        _path,
        runtime_directory,
    )
    from app.runtime_deployment import owner_process_matches
    from app.redis_connections import get_redis_connection
    from app.simnow_takeover_window import authoritative_window

    def require(value):
        if not value:
            raise ValueError("INFRASTRUCTURE_RECOVERY_MARKET_UNPROVEN")

    require(day == "20261104" and now.tzinfo is not None)
    window = authoritative_window(now, target_day=day)
    products = load_operational_products()
    require(len(products) == len(set(products)) == 60)
    with SessionLocal() as db, readonly_transaction(db, timeout_seconds=15):
        phases = {p: MarketPhaseResolver(db).resolve(p, now) for p in products}
    require(all(p.phase is not MarketPhase.UNKNOWN for p in phases.values()))
    active = {p for p, value in phases.items() if value.phase is MarketPhase.TRADING}
    require(
        active and all(phases[p].trading_day.strftime("%Y%m%d") == day for p in active)
    )
    bindings = read_bindings()
    require(bindings is not None and len(bindings.services) == 10)
    registry_raw = registry_path().read_bytes()
    names = ("market-feed", "live")

    def controls():
        result = {
            name: _read(_path(runtime_directory(), name, "handover.json"))
            for name in names
        }
        for name, value in result.items():
            require(
                value is None
                or (
                    set(value)
                    == {
                        "schema_version",
                        "service",
                        "generation",
                        "phase",
                        "request_id",
                    }
                    and value["schema_version"] == 1
                    and value["service"] == name
                    and value["generation"] == bindings.services[name].generation
                    and value["phase"] == "cancelled"
                    and type(value["request_id"]) is str
                    and re.fullmatch(r"[0-9a-f]{32}", value["request_id"]) is not None
                )
            )
        return result

    frozen_controls = controls()
    pids = {}
    completed = {}
    last_seen = {}
    waiting = False
    deadline = monotonic() + 3

    def fixed():
        require(
            read_bindings() == bindings
            and registry_path().read_bytes() == registry_raw
            and controls() == frozen_controls
        )

    def owners():
        nonlocal waiting
        stamps = []
        for name in names:
            state = read_service_state(name)
            binding = bindings.services[name]
            require(
                type(state) is dict
                and state.get("phase") == "active"
                and state.get("service") == name
                and state.get("generation") == binding.generation
                and type(state.get("pid")) is int
                and state["pid"] > 0
                and type(state.get("ready")) is bool
                and type(state.get("proof")) is dict
            )
            if name not in pids:
                pids[name] = state["pid"]
            require(
                state["pid"] == pids[name]
                and owner_process_matches(state, binding)
                and not owner_lock_available(name)
            )
            stamp = datetime.fromisoformat(state["at"])
            require(0 <= (datetime.now(UTC) - stamp).total_seconds() <= 30)
            require(name not in last_seen or stamp >= last_seen[name])
            last_seen[name] = stamp
            proof = state["proof"]
            require("failure_code" not in proof)
            if state["ready"]:
                if name == "live":
                    frontier = proof.get("input_read_frontier")
                    require(
                        type(frontier) is str
                        and len(frontier) <= 64
                        and re.fullmatch(r"[0-9]+-[0-9]+", frontier) is not None
                        and proof.get("trading_day") == "2026-11-04"
                    )
                    frontier = tuple(map(int, frontier.split("-")))
                    if name in completed:
                        require(frontier >= completed[name][1])
                    completed[name] = (stamp, frontier)
                else:
                    require(proof.get("cycle_ok") is True)
                    completed[name] = (stamp, None)
            else:
                # Only the exact normal poll-start marker is resampled. A
                # diagnostic, unknown proof or a replacement owner is terminal.
                require(proof == {})
                waiting = True
            stamps.append(stamp)
        return stamps

    def inputs():
        nonlocal waiting
        heartbeats = {
            name: json.loads(client.get(key) or "null")
            for name, key in (
                ("market-feed", "live:feed:heartbeat"),
                ("live", "live:heartbeat"),
            )
        }
        stamps = []
        for name, heartbeat in heartbeats.items():
            binding = bindings.services[name]
            require(type(heartbeat) is dict)
            stamp = datetime.fromisoformat(heartbeat["generated_at"])
            require(0 <= (datetime.now(UTC) - stamp).total_seconds() <= 30)
            stamps.append(stamp)
            require(
                heartbeat.get("available") is True
                and heartbeat.get("operational_count") == 60
                and heartbeat.get("metadata_preparation_error") is None
                and heartbeat.get("runtime_generation") == binding.generation
                and heartbeat.get("runtime_commit") == binding.commit
                and heartbeat.get("runtime_root") == binding.root
                and heartbeat.get("runtime_tag") == binding.tag
                and heartbeat.get("phase_by_product")
                == {p: v.phase.value for p, v in phases.items()}
            )
        require(heartbeats["market-feed"].get("input_failure") is None)
        pending = heartbeats["market-feed"].get("input_pending_count")
        require(type(pending) is int and pending >= 0)
        waiting = waiting or pending > 0
        coverage = heartbeats["live"].get("coverage", {})
        require(
            all(
                coverage.get(p, {}).get("state") == "ok"
                and coverage[p].get("trading_day") == "2026-11-04"
                and coverage[p].get("first_missing_bar_end") is None
                for p in active
            )
        )
        return pending == 0, stamps

    client = redis if redis is not None else get_redis_connection()
    try:
        while True:
            fixed()
            inputs()  # Explicit provider/coverage failures never enter a wait.
            stamps = owners()
            clear, input_stamps = inputs()
            fixed()
            final = datetime.now(UTC)
            require(
                all(
                    0 <= (final - stamp).total_seconds() <= 30
                    for stamp in (
                        *stamps,
                        *input_stamps,
                        *(v[0] for v in completed.values()),
                    )
                )
            )
            if len(completed) == 2 and clear:
                # A new normal poll may have started after the completed-cycle
                # proof. Recheck its owner identity without demanding a
                # simultaneous ready=True from both independent workers.
                owners()
                fixed()
                clear, input_stamps = inputs()
                final = datetime.now(UTC)
                require(
                    all(
                        0 <= (final - stamp).total_seconds() <= 30
                        for stamp in (
                            *input_stamps,
                            *(v[0] for v in completed.values()),
                        )
                    )
                )
                if clear:
                    require(not waiting or monotonic() <= deadline)
                    break
            remaining = deadline - monotonic()
            require(remaining > 0)
            sleep(min(0.05, remaining))
    finally:
        if redis is None:
            client.close()
    return {
        **{k: window[k] for k in ("trading_day", "sessions", "session_facts_sha256")},
        "active": True,
        "runtime_registry_sha256": sha256(registry_raw).hexdigest(),
    }
