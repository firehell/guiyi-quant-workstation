"""Exclusive evidence index and pure offline 19-scene audit; no closure promotion."""

from __future__ import annotations
import hashlib
from .context import Candidate, FREQUENCIES, MODES, need
from .evidence import EvidenceStore
from .audit import validate_full_capture, validate_index
from .checks import functional_checks, validate_earlier, validate_recovery
from .stages import require_stage

SCENES = tuple(
    [("minute", f, m) for f in FREQUENCIES for m in MODES]
    + [("legacy", f, m) for f in ("1d", "1w") for m in MODES]
    + [("cancel", "5m", "trend")]
)


def _collection(candidate: Candidate, store: EvidenceStore) -> dict:
    body = store.read("collection-observations.json")
    need(
        body.get("task_sha256") == candidate.task_sha256
        and body.get("status") == "OBSERVED_NEEDS_VISUAL_REVIEW"
        and body.get("readonly") is True
        and body.get("provider_calls") == body.get("production_writes") == 0,
        "COLLECTION_IDENTITY_OR_FAILURE",
    )
    rows = body.get("rows", [])
    need(
        tuple((r.get("scenario"), r.get("frequency"), r.get("mode")) for r in rows)
        == SCENES,
        "EXACT_SCENE_MATRIX",
    )
    need(
        all(
            r.get("task_sha256") == candidate.task_sha256
            and r.get("status") == "OBSERVED_NEEDS_VISUAL_REVIEW"
            and r.get("visual_review") == "NOT_RUN"
            for r in rows
        ),
        "COLLECTION_ROWS_IDENTITY",
    )
    return body


def build_index(candidate: Candidate, store: EvidenceStore) -> dict:
    collection = _collection(candidate, store)
    checks = store.read("preflight-check.json")["checks"]
    require_stage("capture", checks, candidate)
    require_stage(
        "capture",
        dict(checks, preview=store.read("capture-preview-check.json")),
        candidate,
    )
    evidence = []
    seen = set()

    def add(name, kind, expected=None):
        current = store.reference(name)
        if expected is not None:
            need(
                all(current[k] == expected[k] for k in ("path", "sha256", "bytes")),
                "COLLECTION_EVIDENCE_CHANGED",
            )
        need(name not in seen, "DUPLICATE_INDEX_PATH")
        seen.add(name)
        evidence.append(dict(kind=kind, **current))

    for name in (
        "candidate.json",
        "context-check.json",
        "legacy-expected-identities.json",
        "preflight-check.json",
        "collection-start.json",
        "collection-observations.json",
        "capture-preview-check.json",
    ):
        add(name, "context")
    for row in collection["rows"]:
        label = f"{row['scenario']}-{row['frequency']}-{row['mode']}"
        need(
            row["raw"]["path"] == f"browser/{label}.json"
            and row["cli"]["path"] == f"browser/{label}-cli.json",
            "SCENE_EVIDENCE_PATH",
        )
        add(row["raw"]["path"], "raw", row["raw"])
        add(row["cli"]["path"], "cli", row["cli"])
        cli = store.read(row["cli"]["path"])
        need(
            isinstance(cli.get("browser_script"), str)
            and hashlib.sha256(cli["browser_script"].encode()).hexdigest()
            == row.get("browser_script_sha256")
            == cli.get("browser_script_sha256"),
            "ACTUAL_SCRIPT_HASH_CHANGED",
        )
        required = (
            {"main", "curve", "earlier"}
            if row["scenario"] == "minute"
            else {"main", "curve"}
            if row["scenario"] == "legacy"
            else {"main"}
        )
        need(
            {r["path"] for r in row["images"]}
            == {f"browser/{label}-{kind}.png" for kind in required},
            "ACTUAL_SCENE_SCREENSHOTS_REQUIRED",
        )
        for ref in row["images"]:
            add(ref["path"], "screenshot", ref)
    return candidate.proof(
        evidence=evidence,
        scene_count=19,
        visual_review="PENDING_INDEPENDENT_REVIEW",
        scope="candidate read-only observations; source manifests and closure require independent evidence",
        provider_calls=0,
        production_writes=0,
    )


def audit_bundle(candidate: Candidate, store: EvidenceStore) -> dict:
    index = store.read("evidence-index.json")
    validate_index(candidate, store, index)
    # Rebuild all declarations to reject missing evidence or a substituted index.
    need(index == build_index(candidate, store), "INDEX_DECLARATION_CHANGED")
    from .legacy_checks import validate_legacy

    expected = store.read("legacy-expected-identities.json")
    rows = []
    need(
        all(
            set(expected["rows"][f].get("base_identities", {}))
            == {"trend", "oscillation"}
            for f in ("1d", "1w")
        ),
        "EXACT_NATIVE_BASE_IDENTITIES_REQUIRED",
    )
    for row in _collection(candidate, store)["rows"]:
        raw = store.read(row["raw"]["path"])
        need(
            all(
                raw.get(k) == row.get(k)
                for k in (
                    "scenario",
                    "frequency",
                    "mode",
                    "task_sha256",
                    "code_sha",
                    "product",
                    "as_of",
                    "status",
                )
            ),
            "RAW_SCENE_IDENTITY",
        )
        observed = raw["observed"]
        f = row["frequency"]
        m = row["mode"]
        scenario = row["scenario"]
        if scenario == "minute":
            proof = dict(
                functional=functional_checks(candidate, f, m, observed),
                full=validate_full_capture(candidate, observed["full_capture"], f, m),
                earlier=validate_earlier(candidate, f, m, observed["earlier_capture"]),
            )
        elif scenario == "legacy":
            proof = validate_legacy(candidate, expected, f, m, observed)
        else:
            proof = validate_recovery(candidate, observed)
        rows.append(dict(scenario=scenario, frequency=f, mode=m, checks=proof))
    return dict(
        candidate.proof(),
        status="NUMERICAL_PASS_VISUAL_PENDING",
        rows=rows,
        scene_count=19,
        visual_review="PENDING_INDEPENDENT_REVIEW",
        candidate_closure=False,
        source_manifest_independent_review="REQUIRED",
        provider_calls=0,
        production_writes=0,
        note="Offline calculations and identity gates passed; screenshots, source manifests and closure are separate.",
    )
