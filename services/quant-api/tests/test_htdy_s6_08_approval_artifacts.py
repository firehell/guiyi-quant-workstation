from __future__ import annotations

from copy import deepcopy
import json

import pytest


def _deployment_facts(tmp_path):
    return {
        "source": {
            "root": str(tmp_path / "源码"),
            "branch": "codex/v1-htdy-step34-completion",
            "commit": "1" * 40,
            "tree": "2" * 40,
            "tracked_clean": True,
            "uv_lock_sha256": "3" * 64,
        },
        "runtime": {
            "root": str(tmp_path / "运行时"),
            "current_commit": "4" * 40,
            "current_tree": "5" * 40,
            "tracked_clean": True,
        },
        "database_revision": "20260721_0025",
        "s6_07_final_receipt": {
            "path": str(tmp_path / "completion_receipt.json"),
            "sha256": "6" * 64,
        },
        "launchd": {
            "label": "com.guiyi.quant-runtime-scheduler",
            "plist_sha256": "7" * 64,
        },
        "runtime_flags": {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        },
        "output": {
            "root": str(tmp_path / "证据"),
            "device": 42,
        },
    }


def test_three_packet_chain_is_hash_bound_and_has_no_fake_receipt(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_approval_artifacts import (
        build_approval_bundle,
        build_code_only_deployment_packet,
        build_s6_07_code_rebind_packet,
        verify_approval_bundle,
        verify_code_only_deployment_packet,
        verify_s6_07_code_rebind_packet,
    )

    facts = _deployment_facts(tmp_path)
    deployment = build_code_only_deployment_packet(facts)
    verify_code_only_deployment_packet(
        deployment,
        approval_hash=deployment["packet_hash"],
        current_facts=facts,
    )
    rebind = build_s6_07_code_rebind_packet(
        deployment_packet=deployment,
        target_runtime_commit=facts["source"]["commit"],
        s6_07_final_receipt=facts["s6_07_final_receipt"],
    )
    verify_s6_07_code_rebind_packet(
        rebind,
        approval_hash=rebind["packet_hash"],
        deployment_packet=deployment,
        current_s6_07_final_receipt=facts["s6_07_final_receipt"],
    )
    service_parent = {
        "schema_version": 3,
        "packet_hash": "8" * 64,
        "bindings": {
            "deployment_packet_sha256": deployment["packet_hash"],
            "s6_07_rebind_packet_sha256": rebind["packet_hash"],
        },
    }
    bundle = build_approval_bundle(
        deployment_packet_path=tmp_path / "deployment_packet.json",
        deployment_packet=deployment,
        rebind_packet_path=tmp_path / "s6_07_rebind_packet.json",
        rebind_packet=rebind,
        service_parent_packet_path=tmp_path / "service_parent_packet.json",
        service_parent_packet=service_parent,
    )
    verify_approval_bundle(
        bundle,
        deployment_packet=deployment,
        rebind_packet=rebind,
        service_parent_packet=service_parent,
    )

    assert "deployment_receipt" not in json.dumps(
        service_parent,
        sort_keys=True,
    )
    assert deployment["allowed_operations"] == [
        "fast_forward_runtime_to_exact_target_commit",
        "purge_nonvenv_python_bytecode",
        "sync_dependency_lock",
        "restart_live_runtime_scheduler",
    ]
    assert rebind["reruns_archive"] is False
    assert rebind["modifies_historical_receipt"] is False
    assert bundle["status"] == "approval_required"


def test_packet_verifiers_reject_runtime_or_dependency_drift(tmp_path) -> None:
    from app.services.htdy_s6_08_approval_artifacts import (
        build_code_only_deployment_packet,
        build_s6_07_code_rebind_packet,
        verify_code_only_deployment_packet,
        verify_s6_07_code_rebind_packet,
    )

    facts = _deployment_facts(tmp_path)
    deployment = build_code_only_deployment_packet(facts)
    drift = deepcopy(facts)
    drift["runtime"]["current_commit"] = "9" * 40
    with pytest.raises(RuntimeError, match="deployment_fact_drift"):
        verify_code_only_deployment_packet(
            deployment,
            approval_hash=deployment["packet_hash"],
            current_facts=drift,
        )

    rebind = build_s6_07_code_rebind_packet(
        deployment_packet=deployment,
        target_runtime_commit=facts["source"]["commit"],
        s6_07_final_receipt=facts["s6_07_final_receipt"],
    )
    receipt_drift = {
        **facts["s6_07_final_receipt"],
        "sha256": "a" * 64,
    }
    with pytest.raises(RuntimeError, match="s6_07_receipt_drift"):
        verify_s6_07_code_rebind_packet(
            rebind,
            approval_hash=rebind["packet_hash"],
            deployment_packet=deployment,
            current_s6_07_final_receipt=receipt_drift,
        )


def test_create_only_json_supports_unicode_path_and_refuses_overwrite(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_approval_artifacts import (
        write_json_create_only,
    )

    path = tmp_path / "审批证据" / "packet.json"
    write_json_create_only(path, {"status": "approval_required"})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "status": "approval_required"
    }
    with pytest.raises(RuntimeError, match="create_only_path_exists"):
        write_json_create_only(path, {"status": "overwritten"})
