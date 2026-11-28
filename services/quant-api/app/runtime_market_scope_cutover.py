"""Promote an archived Tick scope on the same Redis without rewriting its journal."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.market_data.after_market import _evidence_hash
from app.market_data.catalog import MarketCatalog
from app.market_data.day_preparation import catalog_day_fingerprint, catalog_day_ready
from app.market_data.domain import normalize_contract_for_symbol
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.market_archive import current_retained_receipt, verified_retained_cleanup
from app.market_data.market_foundation_scope import formal_tick_initial_day, require_formal_tick_binding
from app.market_data.observation_stream import TTL_SECONDS, ObservationStream, _text
from app.market_data.operational_universe import load_operational_products
from app.market_data.product_retirement import RS_RETIREMENT_SCOPE_DELTA
from app.market_data.session_clock import session_windows_for_trading_day
from app.market_data.storage import CanonicalMonthlyStore
from app.runtime_cohort import _resolution_source, continuous_services, registry, require
from app.runtime_deployment import owner_process_matches
from app.runtime_handover import _read, _write, owner_lock_available, read_service_state, request_drain
from app.runtime_identity import launchd_environments, read_launchd_service
from app.runtime_market_cohort_host import _bound_operational_products, _redis
from app.runtime_market_source_handover import _journal_snapshot, redis_instance
from app.runtime_market_direct_start import MarketDirectStartHost, _KIND, _validate_plan

_ARCHIVE_REQUIRED = "MARKET_SCOPE_CUTOVER_ARCHIVE_UNPROVEN"
_JOURNAL_REQUIRED = "MARKET_SCOPE_CUTOVER_JOURNAL_UNPROVEN"
_OWNER_REQUIRED = "MARKET_SCOPE_CUTOVER_OWNER_UNPROVEN"
_QUIET_REQUIRED = "MARKET_SCOPE_CUTOVER_QUIET_WINDOW_UNPROVEN"
_SCOPE_CAS = """
local active, retained = redis.call('GET', KEYS[1]), redis.call('GET', KEYS[2])
if active ~= ARGV[1] or retained or redis.call('GET', KEYS[3]) ~= ARGV[3]
    or redis.call('GET', KEYS[4]) ~= ARGV[4] then return 0 end
for index = 5, 7, 2 do
    local arg = index == 5 and 4 or 6
    local last = redis.call('XREVRANGE', KEYS[index], '+', '-', 'COUNT', 1)
    local count = tonumber(ARGV[arg + 1])
    if #last ~= 1 or last[1][1] ~= ARGV[arg] or redis.call('XLEN', KEYS[index]) ~= count
        or redis.call('HLEN', KEYS[index + 1]) ~= count then return 0 end
end
local ttl = redis.call('PTTL', KEYS[1])
if ttl <= 0 then return 0 end
redis.call('SET', KEYS[2], active, 'EX', ARGV[8])
redis.call('SET', KEYS[1], ARGV[2], 'KEEPTTL')
return 1
"""


def prior_tick_scope(products):
    return tuple(sorted(set(products) | RS_RETIREMENT_SCOPE_DELTA))


def archived_tick_frontier(client, archive_root, *, day, products, archive_commit, now):
    """Pin terminal cursors and original stream/index bytes without changing their TTLs."""
    store = RedisLiveStore(client)
    receipt = current_retained_receipt(archive_root, now=now)
    cleanup = verified_retained_cleanup(store, archive_root, day=day, products=products, now=now)
    require(receipt is not None and receipt.trading_day == day and set(receipt.revisions) == set(products)
            and cleanup is not None and cleanup["code_commit"] == archive_commit
            and cleanup["canonical_readback"] == receipt.revisions
            and cleanup["rank1_matches_snapshot"] is True
            and cleanup["formal_rank1_sha256"] == cleanup["snapshot_sha256"], _ARCHIVE_REQUIRED)
    streams, subscriptions = _tick_journals(client, day, products)
    require(_evidence_hash(subscriptions) == cleanup["formal_rank1_sha256"], _ARCHIVE_REQUIRED)
    return {"archive": receipt.identity, "archive_commit": archive_commit, "prior_day": day.isoformat(),
            "rank1_sha256": cleanup["formal_rank1_sha256"], "streams": streams}


def _tick_journals(client, day, products):
    subscriptions = {}
    allowed = set(products)
    deadline = monotonic() + 30

    def check_budget():
        require(monotonic() < deadline, "MARKET_SCOPE_CUTOVER_JOURNAL_TIMEOUT")

    def validate(kind, event):
        parts = event.channel.split(":")
        require(event.source_generation is not None and len(parts) == 4 and parts[:2] == ["live", "bar"]
                and parts[2] in allowed, _JOURNAL_REQUIRED)
        product, frequency = parts[2:]
        contract = event.data.get("contract")
        require(isinstance(contract, str) and normalize_contract_for_symbol(product, contract) == contract,
                _JOURNAL_REQUIRED)
        if kind == "source":
            snapshot = event.data.get("subscription_snapshot")
            require(frequency == "1m" and isinstance(snapshot, dict) and set(snapshot) == allowed
                    and snapshot.get(product) == contract, _JOURNAL_REQUIRED)
            previous = subscriptions.setdefault(event.trading_day, snapshot)
            require(snapshot == previous, _JOURNAL_REQUIRED)
        else:
            snapshot = subscriptions.get(event.trading_day, {})
            require(snapshot.get(product) == contract and event.confirmed_at is not None, _JOURNAL_REQUIRED)

    streams = {
        kind: _journal_snapshot(
            ObservationStream(client, kind=kind), day, consumers,
            retain=lambda _: None, check_budget=check_budget, validate_event=validate,
        )
        for kind, consumers in (("source", ("live",)), ("completed", ()))
    }
    return streams, subscriptions[day]


class JournalPreservingMarketStartHost(MarketDirectStartHost):
    """Use the direct-start install/CAS flow with an already archived, drained Tick namespace."""

    def __init__(self, prior=None):
        super().__init__()
        self.prior = prior

    def _check_old(self, previous):
        require(previous is not None, _OWNER_REQUIRED)
        products = load_operational_products()
        require(_bound_operational_products(previous) == prior_tick_scope(products)
                and set(prior_tick_scope(products)) - set(products) == RS_RETIREMENT_SCOPE_DELTA,
                "MARKET_SCOPE_CUTOVER_PREDECESSOR_UNPROVEN")
        services = previous.services
        require(not services["alert"].enabled and "home-projection" in services
                and not services["home-projection"].enabled, _OWNER_REQUIRED)
        market = services["after-market"]
        require(market.enabled and all(
            services[name].enabled and (services[name].root, services[name].commit, services[name].generation)
            == (market.root, market.commit, market.generation)
            for name in ("api", "web", "market-feed", "live", "reference-worker")
        ), _OWNER_REQUIRED)
        self.verify_release(Path(market.root), market.tag, market.commit)
        if self.prior is not None:
            require(self.prior["archive_commit"] == market.commit, _ARCHIVE_REQUIRED)
        return market.commit

    def _retained(self, settings, *, day, archive_commit):
        database, canonical = self._storage(settings)
        products = prior_tick_scope(load_operational_products())
        with _redis(settings["REDIS_URL"]) as client:
            require_formal_tick_binding(client, database, canonical)
            initial = formal_tick_initial_day(client)
            require(initial is not None and initial <= day, _JOURNAL_REQUIRED)
            proof = archived_tick_frontier(client, self.directory / "market-foundation",
                                          day=day, products=products, archive_commit=archive_commit, now=self.now())
            return {**proof, "initial_day": initial.isoformat(), "redis_instance": redis_instance(client)}

    def _previous_start(self):
        if self.prior is None:
            previous = self.bindings()
            archive_commit = self._check_old(previous)
            pointer = _read(self.directory / "cohort-release.json") or {}
            require(pointer.get("kind") == _KIND and pointer.get("phase") == "switched", _OWNER_REQUIRED)
            previous_sha = pointer.get("plan_sha256")
        else:
            previous, archive_commit = None, self.prior["archive_commit"]
            previous_sha = self.prior["previous_plan"]
        require(isinstance(previous_sha, str) and re.fullmatch(r"[a-f0-9]{64}", previous_sha) is not None,
                _OWNER_REQUIRED)
        source = self.directory / "market-direct-start-attempts" / previous_sha / "plan.json"
        _, old_plan = _resolution_source(source)
        _validate_plan(old_plan)
        require(old_plan["plan_sha256"] == previous_sha
                and old_plan["config_sha256"] == self.settings()[1]
                and registry(old_plan["new"]).services["after-market"].commit == archive_commit
                and (previous is None or registry(old_plan["new"]) == previous), _OWNER_REQUIRED)
        return previous_sha, archive_commit, old_plan

    def authority(self, settings, root, day):
        previous_sha, archive_commit, old_plan = self._previous_start()
        with _redis(settings["REDIS_URL"]) as client:
            source = ObservationStream(client, kind="source")
            completed = ObservationStream(client, kind="completed")
            prior_day = source.registered_day("live")
            require(day > prior_day and not client.exists(
                RedisLiveStore._subscription_key(day), source.key(day), source.identity_key(day),
                source.cursor_key("live", day), completed.key(day), completed.identity_key(day),
            ), _JOURNAL_REQUIRED)
        proof = self._retained(settings, day=prior_day, archive_commit=archive_commit)
        require(proof["redis_instance"] == old_plan["target_instance"]
                and proof["initial_day"] == old_plan["day"], _JOURNAL_REQUIRED)
        super_proof = super().authority(settings, root, day)
        require(super_proof["prior_day"] == proof["prior_day"], _ARCHIVE_REQUIRED)
        return {**super_proof, "retained_tick": {**proof, "previous_plan": previous_sha}}

    def target_instance(self, settings, authority):
        return authority["retained_tick"]["redis_instance"]

    def _check_retained(self, plan, settings):
        archived = plan["authority"]["retained_tick"]
        proof = self._retained(settings, day=date.fromisoformat(archived["prior_day"]),
                               archive_commit=archived["archive_commit"])
        require(proof == {k: v for k, v in archived.items() if k != "previous_plan"}, _JOURNAL_REQUIRED)

    def prepare_retained_scope(self, previous, plan, settings, attempt):
        self._check_old(previous)
        self._check_retained(plan, settings)
        old = previous.services
        wanted = tuple(old[name] for name in continuous_services(previous) if old[name].enabled)
        drains_path = attempt / "scope-drains.json"
        drains = _read(drains_path) or {}
        exits_path = attempt / "scope-exits.json"
        exits = _read(exits_path) or {}
        # Read-only warmup first, even if a preceding attempt was interrupted.
        candidate = registry(plan["new"]).services["market-feed"]
        database, canonical = self._storage(settings)
        with _redis(settings["REDIS_URL"]) as client:
            binding = require_formal_tick_binding(client, database, canonical)
        self._prove_staged_warmup(candidate, settings, binding, direct=True)

        pending = []
        for service in wanted:
            name = service.service
            if name in exits:
                continue
            state = read_service_state(name, runtime_dir=self.directory)
            loaded = self.loaded(service, allow_idle=True)
            require(state is not None and loaded is not None and str(state.get("pid")) == str(loaded)
                    and state.get("generation") == service.generation, _OWNER_REQUIRED)
            output = read_launchd_service(service.label, root=Path(service.root))
            require(output is not None and any(env.get("GUIYI_RUNTIME_ENV") == str(self.target_config)
                    for env in launchd_environments(output)), _OWNER_REQUIRED)
            control = _read(self.directory / f"{name}.handover.json") or {}
            reserved = drains.get(name)
            if reserved is not None and control.get("generation") == service.generation:
                require(control.get("phase") == "drain" and control.get("request_id") == reserved,
                        _OWNER_REQUIRED)
                continue
            require(state.get("phase") == "active" and owner_process_matches(state, service)
                    and not (control.get("phase") == "drain" and control.get("generation") == service.generation),
                    _OWNER_REQUIRED)
            pending.append(service)

        for service in pending:
            name = service.service

            def remember(identifier):
                drains[name] = identifier
                _write(drains_path, drains)

            request_drain(name, generation=service.generation, runtime_dir=self.directory,
                          before_install=remember, request_id=drains.get(name))

        for service in wanted:
            name = service.service
            if name in exits:
                require(self.definition_absent(service), "MARKET_SCOPE_CUTOVER_EXIT_UNKNOWN")
                self._await_old_absent(service, int(exits[name]), deadline=min(self.deadline, monotonic() + 20))
                continue
            while monotonic() < self.deadline:
                state = read_service_state(name, runtime_dir=self.directory) or {}
                loaded = self.loaded(service, allow_idle=True)
                if (loaded is not None and state.get("phase") == "parked"
                        and str(state.get("pid")) == str(loaded) and state.get("generation") == service.generation
                        and owner_lock_available(name, runtime_dir=self.directory)):
                    break
                sleep(0.1)
            else:
                require(False, "MARKET_SCOPE_CUTOVER_DRAIN_TIMEOUT")
            self.launch("disable", f"gui/{os.getuid()}/{service.label}")
            exits[name] = int(loaded)
            _write(exits_path, exits)  # No repeat of a bootout with unknown effects.
            self._bootout_old_once(service, loaded, deadline=min(self.deadline, monotonic() + 30))
        self._check_retained(plan, settings)

    def stage(self, plan, settings, *, may_exist):
        # All data and cursor state remain in place.
        self._check_retained(plan, settings)

    def verify_staged(self, plan, settings):
        self._check_retained(plan, settings)

    def read_target(self, plan, *, bound):
        settings, observed_hash = self.settings()
        require(observed_hash == plan["config_sha256"], "MARKET_DIRECT_START_CONFIG_DRIFT")
        if bound:
            database, canonical = self._storage(settings)
            with _redis(settings["REDIS_URL"]) as client:
                require_formal_tick_binding(client, database, canonical)
                initial = formal_tick_initial_day(client)
                require(redis_instance(client) == plan["target_instance"] and initial is not None
                        and initial.isoformat() == plan["authority"]["retained_tick"]["initial_day"], _JOURNAL_REQUIRED)
            return "bound"
        self._check_retained(plan, settings)
        return "retained"

    def _ready_on_target(self, plan, settings, args, *, feed):
        new = registry(plan["new"])
        modes = {}
        with _redis(settings["REDIS_URL"]) as client:
            require(redis_instance(client) == args["expected_instance"], _JOURNAL_REQUIRED)
            require_formal_tick_binding(client, args["database"], args["canonical"])
            for name in continuous_services(new):
                if not new.services[name].enabled or name == "market-feed" and not feed:
                    continue
                binding = new.services[name]
                state = read_service_state(name, runtime_dir=self.directory)
                if not (state and state.get("phase") == "active" and state.get("ready") is True
                        and state.get("generation") == binding.generation
                        and owner_process_matches(state, binding)
                        and not owner_lock_available(name, runtime_dir=self.directory)
                        and 0 <= (self.now() - datetime.fromisoformat(state["at"])).total_seconds() <= 30):
                    return None
                if name == "market-feed" and not self._feed_closed_healthy(
                    binding, state, {**plan["authority"], "mode": "closed_idle"}, redis=client,
                ):
                    return None
                if name in ("market-feed", "live"):
                    closed = state.get("proof", {}).get("closed_cleaned") or {}
                    if (closed.get("status") != "CLOSED_CLEANED"
                            or closed.get("trading_day") != plan["authority"]["prior_day"]):
                        return None
                if name == "reference-worker" and state.get("proof", {}).get("reference_receipts") != "waiting_archive":
                    return None
                modes[name] = "active"
        return modes

    def verify_scope_api(self, plan):
        def get(path, query=None):
            url = "http://127.0.0.1:8000" + path
            if query:
                url += "?" + urlencode(query)
            try:
                with urlopen(url, timeout=5) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                with error:
                    return error.code, json.load(error)

        products = set(plan["authority"]["subscriptions"])
        status, directory = get("/api/v1/market/product-directory")
        actual = [row["product"].lower() for row in directory["items"]]
        require(status == 200 and set(actual) == products and len(actual) == len(products),
                "MARKET_SCOPE_CUTOVER_API_DIRECTORY_DRIFT")
        version_status, health = get("/api/health")
        require(version_status == 200 and health.get("version") == registry(plan["new"]).services["api"].tag[1:],
                "MARKET_SCOPE_CUTOVER_API_VERSION_DRIFT")
        end = (self.now() - timedelta(minutes=1)).isoformat()
        scope = {"symbol": "rs", "frequency": "1d", "series_kind": "actual_dominant"}
        for path, query in (
            ("/api/v1/market/bars/page", {**scope, "before": end, "limit": 1}),
            ("/api/v1/market/indicators/chart-window", {**scope, "first": end, "last": end,
                                                     "count": 1, "studies": "ema10"}),
        ):
            code, payload = get(path, query)
            require(code == 409 and payload.get("detail", {}).get("code") == "PRODUCT_RETIRED",
                    "MARKET_SCOPE_CUTOVER_API_RETIREMENT_UNPROVEN")
        return {"api_version": health["version"], "products": len(products), "rs": "PRODUCT_RETIRED"}

    def start_new(self, plan, *, verify_running_only):
        super().start_new(plan, verify_running_only=verify_running_only)
        if not verify_running_only:
            settings, _ = self.settings()
            self._check_retained(plan, settings)
        return self.verify_scope_api(plan)



def _retained_subscription_key(day):
    return f"live:scope-cutover:{day.isoformat()}:prior-subscriptions"


def _same_day_tick_proof(client, day, subscriptions):
    source = ObservationStream(client, kind="source")
    require(source.registered_day("live") == day, _JOURNAL_REQUIRED)
    key = RedisLiveStore._subscription_key(day)
    active, retained = client.mget(key, _retained_subscription_key(day))
    original = retained if retained is not None else active
    require(isinstance(original, (bytes, str)), _JOURNAL_REQUIRED)
    mapping = json.loads(original)
    prior_products = prior_tick_scope(subscriptions)
    require(isinstance(mapping, dict) and tuple(sorted(mapping)) == prior_products
            and {p: mapping[p] for p in subscriptions} == subscriptions
            and (retained is None or active is not None and json.loads(active) == subscriptions),
            _JOURNAL_REQUIRED)
    streams, journal_mapping = _tick_journals(client, day, prior_products)
    require(journal_mapping == mapping, _JOURNAL_REQUIRED)
    original = _text(original)
    proof = {"selection_sha256": sha256(original.encode()).hexdigest(),
             "prior_subscription_json": original, "streams": streams}
    return proof, original, retained is not None


def _commit_same_day_selection(client, day, subscriptions, old_proof, *, may_exist):
    proof, original, staged = _same_day_tick_proof(client, day, subscriptions)
    require(proof == old_proof, _JOURNAL_REQUIRED)
    if staged:
        require(may_exist, _JOURNAL_REQUIRED)
        return
    source = ObservationStream(client, kind="source")
    completed = ObservationStream(client, kind="completed")
    source_row = proof["streams"]["source"][day.isoformat()]
    completed_row = proof["streams"]["completed"][day.isoformat()]
    keys = (
        RedisLiveStore._subscription_key(day), _retained_subscription_key(day),
        source.registration_key("live"), source.cursor_key("live", day),
        source.key(day), source.identity_key(day), completed.key(day), completed.identity_key(day),
    )
    require(client.eval(
        _SCOPE_CAS, len(keys), *keys, original,
        json.dumps(subscriptions, sort_keys=True, separators=(",", ":")),
        day.isoformat(), source_row["tail"], source_row["count"],
        completed_row["tail"], completed_row["count"], 2 * TTL_SECONDS,
    ) == 1, _JOURNAL_REQUIRED)


class QuietWindowMarketStartHost(JournalPreservingMarketStartHost):
    """Switch the remaining sessions of the registered day without rewriting received observations."""

    def authority(self, settings, root, day):
        previous_sha, archive_commit, old_plan = self._previous_start()
        products = load_operational_products()
        old_products = prior_tick_scope(products)
        now = self.now()
        with self._catalog_session(settings) as (session, canonical):
            resolver = MarketPhaseResolver(session)
            market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
            require(catalog_day_ready(session, products, day), _QUIET_REQUIRED)
            phases, windows, subscriptions, upcoming = {}, {}, {}, []
            observed_prefix = False
            close = timedelta(seconds=60)
            for product in old_products:
                phase = resolver.resolve(product, now)
                # The retiring product is still relevant to the predecessor's
                # quiescence, even though its public market endpoints are gone.
                starts = session_windows_for_trading_day(
                    session, exchange=market.catalog.exchange_for_symbol(product), symbol=product, trading_day=day,
                )
                future = [window for window in starts if window.start > now]
                require(phase.phase is MarketPhase.CLOSED and phase.trading_day in (None, day)
                        and future and phase.next_session_start == future[0].start
                        and future[0].start > now + timedelta(seconds=660)
                        and all(window.start > now or window.end + close < now
                                for window in starts), _QUIET_REQUIRED)
                next_phase = resolver.resolve(product, future[0].start)
                require(next_phase.phase is MarketPhase.TRADING and next_phase.trading_day == day
                        and next_phase.current_session == future[0], _QUIET_REQUIRED)
                observed_prefix |= any(window.end < now for window in starts)
                if product in products:
                    phases[product] = {"phase": phase.phase.value}
                    windows[product] = [[v.start.isoformat(), v.end.isoformat()] for v in starts]
                    subscriptions[product] = market.dominant_segment_for_day(product, day).contract
                upcoming.append(future[0].start)
            require(observed_prefix, _QUIET_REQUIRED)
            facts = catalog_day_fingerprint(session, products, day)
        proof, staged = self._quiet_proof(settings, day, subscriptions)
        require(proof["redis_instance"] == old_plan["target_instance"]
                and proof["initial_day"] == old_plan["day"]
                and (self.prior is not None or not staged), _JOURNAL_REQUIRED)
        return {"prior_day": day.isoformat(), "first_session": min(upcoming).isoformat(),
                "subscriptions": subscriptions, "phases": phases, "sessions_sha256": _evidence_hash(windows),
                "catalog_sha256": facts, "mode": "closed_idle",
                "retained_tick": {**proof, "previous_plan": previous_sha, "archive_commit": archive_commit,
                                  "quiet_window": True}}

    def _quiet_proof(self, settings, day, subscriptions):
        database, canonical = self._storage(settings)
        with _redis(settings["REDIS_URL"]) as client:
            require_formal_tick_binding(client, database, canonical)
            initial = formal_tick_initial_day(client)
            require(initial is not None and initial <= day, _JOURNAL_REQUIRED)
            proof, _, staged = _same_day_tick_proof(client, day, subscriptions)
            return {**proof, "initial_day": initial.isoformat(),
                    "redis_instance": redis_instance(client)}, staged

    def _check_retained(self, plan, settings, *, staged=None):
        authority = plan["authority"]
        previous = authority["retained_tick"]
        proof, selected = self._quiet_proof(settings, date.fromisoformat(plan["day"]), authority["subscriptions"])
        require(proof == {key: previous[key] for key in proof}
                and (staged is None or selected is staged), _JOURNAL_REQUIRED)
        return selected

    def stage(self, plan, settings, *, may_exist):
        self._check_retained(plan, settings)
        authority = plan["authority"]
        previous = authority["retained_tick"]
        with _redis(settings["REDIS_URL"]) as client:
            require(redis_instance(client) == plan["target_instance"], _JOURNAL_REQUIRED)
            _commit_same_day_selection(
                client, date.fromisoformat(plan["day"]), authority["subscriptions"],
                {key: previous[key] for key in ("selection_sha256", "prior_subscription_json", "streams")}, may_exist=may_exist,
            )

    def verify_staged(self, plan, settings):
        self._check_retained(plan, settings, staged=True)

    def read_target(self, plan, *, bound):
        settings, observed_hash = self.settings()
        require(observed_hash == plan["config_sha256"], "MARKET_DIRECT_START_CONFIG_DRIFT")
        if not bound:
            return "scope_staged" if self._check_retained(plan, settings) else "retained"
        database, canonical = self._storage(settings)
        authority = plan["authority"]
        day = date.fromisoformat(plan["day"])
        with _redis(settings["REDIS_URL"]) as client:
            require_formal_tick_binding(client, database, canonical)
            initial = formal_tick_initial_day(client)
            retained = client.get(_retained_subscription_key(day))
            prior = authority["retained_tick"]
            require(redis_instance(client) == plan["target_instance"]
                    and initial == date.fromisoformat(prior["initial_day"])
                    and RedisLiveStore(client).subscriptions(day) == authority["subscriptions"]
                    and ObservationStream(client, kind="source").registered_day("live") == day
                    and retained is not None and _text(retained) == prior["prior_subscription_json"],
                    _JOURNAL_REQUIRED)
        return "bound"

    def _ready_on_target(self, plan, settings, args, *, feed):
        authority = plan["authority"]
        window = {**authority, "window_end": authority["first_session"]}
        if not self._active_target_ready({**plan, "authority": window}, settings, args, feed=feed):
            return None
        return True

    def start_new(self, plan, *, verify_running_only):
        # For the quiet window, no replayed or synthetic minute can establish
        # that intake is already live. The published subscription is read back.
        proof = super().start_new(plan, verify_running_only=verify_running_only)
        return {**proof, "activation_mode": "same_day_quiet_window", "subscriptions": proof["products"]}
