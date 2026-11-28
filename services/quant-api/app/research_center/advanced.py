"""Only published snapshots and explicit historical Run configurations enter V0.2."""

from app.backtest_center.codec import digest
from app.backtest_center.experiments import ExperimentRequest, validate_experiment_windows
from app.backtest_center.contracts import RunConfig, admission_code
from app.backtest_center.store import RunStore
from app.backtest_center.worker import Settings
from app.research_center.inputs import ResearchError, publication_identity


def verified_task(store, task_id, kind):
    row = store.get(task_id)
    if not row or row["status"] != "SUCCEEDED" or row["result"]["source"]["kind"] != kind:
        raise ResearchError("RESEARCH_ADVANCED_SOURCE_INELIGIBLE")
    return row


def panel_input(store, config):
    records = [verified_task(store, member, "factor") for member in config.members]
    first = records[0]["result"]
    samples, references = [], []
    products = set()
    calendars = []
    for record in records:
        source = record["result"]["source"]
        key = ("feature", "frequency", "formula_version")
        if any(source[item] != first["source"][item] for item in key) or record["result"]["policy"] != first["policy"]:
            raise ResearchError("RESEARCH_PANEL_POLICY_MISMATCH")
        if source["product"] in products:
            raise ResearchError("RESEARCH_PANEL_REQUIRES_DISTINCT_PRODUCTS")
        products.add(source["product"])
        identifier = str(record["id"])
        references.append({"task_id": identifier, "result_digest": record["result_digest"], **source})
        parent = store.frozen_input(record)
        calendars.append(set(parent.get("trading_days", [])))
        samples.extend({**row, "member": identifier} for row in parent["samples"])
    if len(samples) > 24000:
        raise ResearchError("RESEARCH_ADVANCED_SAMPLE_BUDGET_EXCEEDED")
    return {
        "source": {"kind": "panel", "member_ids": [str(value) for value in config.members], "members": references},
        "policy": {"version": "synchronized_rank_ic_v1", "hac_lag": config.hac_lag,
                   "cohort": "complete_members_same_decision_and_label_clock",
                   "daily_grouping": "trading_day"},
        "coverage": {"rows": len(samples), "members": len(records)},
        "trading_days": sorted(set.intersection(*calendars)),
        "samples": samples,
    }


def event_input(store, config):
    row = verified_task(store, config.member, "event")
    parent = store.frozen_input(row)
    return {
        "source": {"kind": "event_test", "member_id": str(config.member), "result_digest": row["result_digest"],
                   "event_source": parent["source"]},
        "policy": {"version": "paired_daily_purged_event_v1", "hac_lag": config.hac_lag,
                   "overlap": "earliest_anchor_then_skip_inclusive_label_window"},
        "coverage": {"events": len(parent["samples"]), "source_exclusions": parent["coverage"]["excluded"]},
        "trading_days": parent.get("trading_days", []),
        "samples": parent["samples"],
    }


def owner_path(request):
    store = getattr(request.app.state, "backtest_store", None)
    return (store.path if store is not None else Settings.local().path).resolve(strict=True)


def run_binding(path, native):
    return digest({"owner": digest(str(path)), "run_id": native["run_id"], "result_digest": native["result_digest"],
                   "configuration": native["config"], "snapshot": native["snapshot"]})


def search_input(request, config):
    path = owner_path(request)
    reader = RunStore.open_reader(path)
    native = reader.research_publication(config.base_run_id)
    base = RunConfig.model_validate(native["config"])
    if (
        admission_code(base) is not None or base.contract_selection != "physical"
        or native["snapshot"].get("engine", {}).get("name") != "rqalpha-plus"
    ):
        raise ResearchError("RESEARCH_SEARCH_RUN_INELIGIBLE")
    folds = [fold.model_dump(mode="json") for fold in config.folds]
    trial = create_request(base, config.choices[:config.budget], folds, "discovery-check")
    return {
        "source": {"kind": "search", "run_id": config.base_run_id, "run_digest": native["result_digest"],
                   "publication_identity": publication_identity(native),
                   "run_binding": run_binding(path, native)},
        "policy": {"version": "optuna_finite_delay_grid_v1", "budget": config.budget, "seed": config.seed,
                   "choices": config.choices, "folds": folds, "total_native_run_limit": len(trial.folds) * (config.budget + 1)},
        "base_config": base.model_dump(mode="json"),
        "coverage": {"folds": len(trial.folds), "budget": config.budget},
        "samples": [],
    }


def verified_search_owner(request, result):
    owner = owner_path(request)
    reader = RunStore.open_reader(owner)
    source = reader.research_publication(result["source"]["run_id"])
    if run_binding(owner, source) != result["source"]["run_binding"]:
        raise ResearchError("RESEARCH_SEARCH_ORIGINAL_RUN_CHANGED")
    return owner, reader


def create_request(base, delays, folds, key):
    initial = base.model_dump(mode="json")
    configurations = [{**initial, "parameters": {**initial["parameters"], "execution_delay_minutes": value}}
                      for value in delays]
    request = ExperimentRequest.model_validate({
        "request_key": key, "kind": "oos" if len(folds) == 1 else "walk_forward",
        "axes": ["parameters"], "configs": configurations, "folds": folds,
    })
    validate_experiment_windows(request)
    return request
