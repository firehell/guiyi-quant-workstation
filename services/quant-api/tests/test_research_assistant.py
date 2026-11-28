from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.research_center import assistant
from app.research_center.inputs import ResearchError


def test_allowlist_and_counterexamples_do_not_disclose_native_amounts(monkeypatch):
    identity = uuid4()
    official = {
        "source": {"kind": "backtest", "qualification": "TRIAL", "account": "private-id"},
        "trades": {"closed": 2, "losses": 1},
        "coverage": {"settlement_days": 2},
        "policy": {"initial_equity": "100000.00"},
        "performance": {"cumulative": 0.02, "max_drawdown": 0.01, "daily_win_rate": 0.5},
        "native": {"daily_cash": "98765"},
        "notes": "private journal text",
    }
    task = {"id": identity, "status": "SUCCEEDED", "result": official, "result_digest": "A", "input_digest": "B"}
    samples = [
        {"record_type": "settlement", "equity": "99000", "native_order_id": "sensitive123"},
        {"record_type": "settlement", "equity": "102000"},
    ]
    store = SimpleNamespace(get=lambda _: task, frozen_input=lambda _: {"samples": samples})
    monkeypatch.setattr(assistant, "local_model_config", lambda: {
        "GUIYI_RESEARCH_GGUF_SHA256": "x", "GUIYI_RESEARCH_LLAMA_SHA256": "y"})
    packet = assistant.assistant_input(store, SimpleNamespace(question="样本有哪些反例？", evidence=[identity]))
    assert packet["samples"][1]["facts"]["losing_trading_days"] == 1
    assert all(value not in repr(packet) for value in ("private-id", "98765", "sensitive123", "private journal text"))
    task["result"] = {"source": {"kind": "case"}, "body": "raw account"}
    with pytest.raises(ResearchError, match="EVIDENCE_INELIGIBLE"):
        assistant.assistant_input(store, SimpleNamespace(question="样本有哪些反例？", evidence=[identity]))


def test_validated_report_is_research_draft_and_refuses_out_of_scope_actions():
    cfg = {"model_sha256": "model", "runner_sha256": "runner"}
    packet = {"policy": cfg, "samples": [{"ref": "S1"}, {"ref": "C1"}]}
    draft = {"summary": "出现亏损交易。", "hypothesis": "按市场状态分组复核。", "limitations": "窗口有限。",
             "evidence_refs": ["S1", "C1"], "next_analysis": "test_robustness"}
    result = assistant.check_report(packet, {"assistant": draft, "model": cfg})
    assert result["assistant"]["hypothesis_status"] == "DRAFT"
    for unsafe, reason in (
        ({"next_analysis": "activate_shadow"}, "TOOL_NOT_ALLOWED"),
        ({"evidence_refs": ["S1", "C99"]}, "CITATION_INVALID"),
        ({"evidence_refs": ["S1", "S1"]}, "CITATION_INVALID"),
        ({"order": 1}, "OUTPUT_SCHEMA_INVALID"),
        ({"summary": "？？？"}, "TEXT_INVALID"),
        ({"limitations": "数字\u200b损坏"}, "TEXT_INVALID"),
        ({"summary": "无法解码\ufffd"}, "TEXT_INVALID"),
    ):
        with pytest.raises(ResearchError, match=reason):
            assistant.check_report(packet, {"assistant": {**draft, **unsafe}, "model": cfg})
    packet["samples"].extend([{"ref": "S2"}, {"ref": "C2"}])
    with pytest.raises(ResearchError, match="CITATION_INVALID"):
        assistant.check_report(packet, {"assistant": {**draft, "evidence_refs": ["S1", "C2"]}, "model": cfg})


def test_advanced_counterexamples_use_only_the_published_estimand():
    result = {"source": {"kind": "panel"}, "advanced": {
        "estimand": "daily_mean_of_complete_cross_section_rank_ic",
        "estimate": {"mean": -0.25, "n": 2, "interval": None, "reason": "INCOMPLETE"},
        "daily_observations": {"2026-01-01": -0.5, "2026-01-02": 0.0},
        "excluded": {"INCOMPLETE_CROSS_SECTION": 1},
    }}
    summary, counter = assistant.read_statistics(result, [{"label": "5"}, {"label": "8"}])
    assert summary["excluded"] == {"INCOMPLETE_CROSS_SECTION": 1}
    assert counter == {"estimand": result["advanced"]["estimand"], "searched_days": 2, "adverse_days": 1, "zero_days": 1}
    result["advanced"]["daily_observations"] = {}
    assert assistant.read_statistics(result, [{"label": "-300"}])[1]["adverse_days"] is None


def test_followup_keeps_exact_citations_and_run_digest():
    report, source = uuid4(), uuid4()
    selected = SimpleNamespace(assistant_id=report, evidence_task_id=source)
    report_result = {
        "source": {"kind": "assistant", "evidence": [{"task_id": str(source), "result_digest": "proof",
                                                     "refs": ["S1", "C1"]}]},
        "assistant": {"evidence_refs": ["S1", "C1"]},
    }
    records = {
        report: {"status": "SUCCEEDED", "result": report_result, "result_digest": "report"},
        source: {"status": "SUCCEEDED", "result_digest": "proof", "result": {
            "source": {"kind": "backtest", "run_id": "owner-run", "digest": "frozen-run",
                       "publication_identity": "config-and-snapshot"}
        }},
    }
    mode = SimpleNamespace(kind="search")
    payload = {"source": {"run_id": "owner-run", "run_digest": "frozen-run",
                          "publication_identity": "config-and-snapshot"}}
    store = SimpleNamespace(get=records.get)
    assert assistant.followup_origin(store, selected, mode, payload) == {
        "task_id": str(report), "result_digest": "report", "evidence_task_id": str(source), "evidence_digest": "proof"}
    payload["source"]["publication_identity"] = "same-result-different-configuration"
    with pytest.raises(ResearchError, match="FOLLOWUP_NOT_REGISTERED"):
        assistant.followup_origin(store, selected, mode, payload)
    report_result["assistant"]["evidence_refs"] = ["S2", "C2"]
    with pytest.raises(ResearchError, match="FOLLOWUP_NOT_CITED"):
        assistant.followup_origin(store, selected, mode, payload)
