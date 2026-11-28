"""Bounded research evidence tools and local inference configuration."""

from decimal import Decimal
import os
from pathlib import Path
import re
from unicodedata import category

from app.research_center.inputs import ResearchError

ASSISTANT_KINDS = frozenset({"backtest", "factor", "event", "panel", "event_test"})
CONFIG_KEYS = (
    "GUIYI_RESEARCH_LLAMA", "GUIYI_RESEARCH_GGUF",
    "GUIYI_RESEARCH_LLAMA_SHA256", "GUIYI_RESEARCH_GGUF_SHA256",
)


def local_model_config():
    values = {name: os.getenv(name, "") for name in CONFIG_KEYS}
    runner, model, runner_hash, model_hash = values.values()
    if (
        not all(Path(item).is_absolute() and Path(item).is_file() for item in (runner, model))
        or not os.access(runner, os.X_OK)
        or not all(re.fullmatch(r"[a-f0-9]{64}", item) for item in (runner_hash, model_hash))
    ):
        return {}
    return values


def read_statistics(result, rows):
    kind = result["source"]["kind"]
    if kind == "backtest":
        performance = result.get("performance") or {}
        trades = result["trades"]
        summary = {
            "sample_qualification": result["source"]["qualification"],
            "trading_days": result["coverage"]["settlement_days"],
            **{name: performance.get(name) for name in ("cumulative", "max_drawdown", "daily_win_rate")},
            "closed_trades": trades["closed"],
        }
        previous = Decimal(result["policy"]["initial_equity"])
        changes = []
        for row in rows:
            if row.get("record_type") != "settlement":
                continue
            equity = Decimal(row["equity"])
            changes.append(equity / previous - 1)
            previous = equity
        counter = {"searched_trading_days": len(changes), "losing_trading_days": sum(value < 0 for value in changes),
                   "losing_closed_trades": trades["losses"], "searched_closed_trades": trades["closed"]}
        return summary, counter
    if kind in ("panel", "event_test"):
        advanced = result["advanced"]
        estimate = advanced["estimate"]
        observations = list(advanced["daily_observations"].values())
        summary = {"estimand": advanced["estimand"], "day_estimate": estimate["mean"], "days": estimate["n"],
                   "interval": estimate["interval"], "inference_reason": estimate["reason"],
                   **{key: advanced[key] for key in ("eligible_cross_sections", "excluded", "accepted_events",
                       "purged_overlapping_events", "excluded_unpaired_days") if key in advanced}}
        return summary, {"estimand": advanced["estimand"], "searched_days": len(observations),
                         "adverse_days": sum(value < 0 for value in observations) if observations else None,
                         "zero_days": sum(value == 0 for value in observations) if observations else None}
    labels = [Decimal(str(row["label"])) for row in rows if row.get("label") is not None]
    summary = {"sample_count": len(labels), "research_only": True}
    if kind == "factor" and result.get("factor"):
        summary.update({key: result["factor"][key] for key in ("n", "spearman", "mean_label")})
    if kind == "event" and result.get("event"):
        summary.update(result["event"])
    counter = {"searched_observations": len(labels), "negative_labels": sum(value < 0 for value in labels)}
    return summary, counter


def assistant_input(store, selection):
    model = local_model_config()
    if not model:
        raise ResearchError("RESEARCH_LOCAL_MODEL_NOT_CONFIGURED")
    references, evidence, notes = [], [], []
    for index, identity in enumerate(selection.evidence, start=1):
        task = store.get(identity)
        if not task or task["status"] != "SUCCEEDED" or task["result"]["source"]["kind"] not in ASSISTANT_KINDS:
            raise ResearchError("RESEARCH_ASSISTANT_EVIDENCE_INELIGIBLE")
        source = task["result"]["source"]
        rows = [] if source["kind"] in ("panel", "event_test") else store.frozen_input(task)["samples"]
        if len(rows) > 8000:
            raise ResearchError("RESEARCH_ASSISTANT_SAMPLE_BUDGET")
        summary, counter = read_statistics(task["result"], rows)
        ref, counter_ref = f"S{index}", f"C{index}"
        evidence.extend([
            {"ref": ref, "tool": "read_statistics", "facts": summary},
            {"ref": counter_ref, "tool": "search_counterexamples", "facts": counter},
        ])
        references.append({"task_id": str(identity), "result_digest": task["result_digest"], "kind": source["kind"],
                           **{key: source[key] for key in ("member_id", "member_ids") if key in source},
                           **({"run_id": source["run_id"]} if source.get("publication_identity") else {}),
                           "input_digest": task["input_digest"], "refs": [ref, counter_ref]})
        notes.append({"ref": counter_ref, "search_scope": counter})
    return {
        "source": {"kind": "assistant", "evidence": references},
        "policy": {"version": "local_research_draft_v1", "model_sha256": model["GUIYI_RESEARCH_GGUF_SHA256"],
                   "runner_sha256": model["GUIYI_RESEARCH_LLAMA_SHA256"], "temperature": 0, "seed": 41,
                   "tools": ["read_statistics", "search_counterexamples", "save_hypothesis_draft",
                             "run_registered_analysis_on_operator_request"]},
        "coverage": {"source_tasks": len(references), "counterexamples": notes},
        "question": selection.question,
        "samples": evidence,
    }


def check_report(payload, output):
    report = output.get("assistant")
    if not isinstance(report, dict) or set(report) != {"summary", "hypothesis", "limitations", "evidence_refs", "next_analysis"}:
        raise ResearchError("RESEARCH_ASSISTANT_OUTPUT_SCHEMA_INVALID")
    for field in ("summary", "hypothesis", "limitations"):
        value = report[field]
        if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 240
                or any(category(char).startswith("C") or char == "\ufffd" for char in value)
                or not any(char.isalnum() for char in value)):
            raise ResearchError("RESEARCH_ASSISTANT_TEXT_INVALID")
    refs = report["evidence_refs"]
    allowed = {item["ref"] for item in payload["samples"]}
    if (
        not isinstance(refs, list) or not 2 <= len(refs) <= len(allowed)
        or any(not isinstance(ref, str) or ref not in allowed for ref in refs)
        or len(refs) != len(set(refs)) or not any(ref.startswith("S") and "C" + ref[1:] in refs for ref in refs)
    ):
        raise ResearchError("RESEARCH_ASSISTANT_CITATION_INVALID")
    if report["next_analysis"] not in ("review_coverage", "test_robustness", "review_backtest"):
        raise ResearchError("RESEARCH_ASSISTANT_TOOL_NOT_ALLOWED")
    model = output.get("model")
    if not isinstance(model, dict) or any(model.get(key) != payload["policy"][key]
                                         for key in ("model_sha256", "runner_sha256")):
        raise ResearchError("RESEARCH_ASSISTANT_MODEL_IDENTITY_MISMATCH")
    return {
        "assistant": {**report, "hypothesis_status": "DRAFT", "evidence_status": "RESEARCH_ONLY"},
        "model": {name: model[name] for name in ("model_sha256", "runner_sha256")},
    }


def followup_origin(store, selection, source, payload):
    report = store.get(selection.assistant_id)
    evidence = store.get(selection.evidence_task_id)
    if (not report or report["status"] != "SUCCEEDED" or report["result"]["source"]["kind"] != "assistant"
            or not evidence or evidence["status"] != "SUCCEEDED"):
        raise ResearchError("RESEARCH_ASSISTANT_FOLLOWUP_SOURCE_INVALID")
    evidence_source = evidence["result"]["source"]
    citations = report["result"]["assistant"]["evidence_refs"]
    binding = next((item for item in report["result"]["source"]["evidence"]
                    if item["task_id"] == str(selection.evidence_task_id)
                    and item["result_digest"] == evidence["result_digest"]
                    and set(item["refs"]) <= set(citations)), None)
    if not binding:
        raise ResearchError("RESEARCH_ASSISTANT_FOLLOWUP_NOT_CITED")
    matches = (
        source.kind == "search" and evidence_source["kind"] == "backtest"
        and payload["source"]["run_id"] == evidence_source["run_id"]
        and payload["source"]["run_digest"] == evidence_source["digest"]
        and bool(evidence_source.get("publication_identity"))
        and payload["source"]["publication_identity"] == evidence_source["publication_identity"]
        or source.kind == "event_test" and evidence_source["kind"] in ("event", "event_test")
        and str(source.member) == evidence_source.get("member_id", str(selection.evidence_task_id))
        or source.kind == "panel" and evidence_source["kind"] == "panel"
        and sorted(map(str, source.members)) == sorted(evidence_source["member_ids"])
    )
    if not matches:
        raise ResearchError("RESEARCH_ASSISTANT_FOLLOWUP_NOT_REGISTERED")
    return {"task_id": str(selection.assistant_id), "result_digest": report["result_digest"],
            "evidence_task_id": str(selection.evidence_task_id), "evidence_digest": evidence["result_digest"]}
