"""Read-only prerequisite checks; never resumes or creates native attempts."""

from .context import Candidate, need

REQUIRES = {
    "preflight": ("context", "legacy"),
    "capture": ("context", "legacy", "assets", "preview"),
    "audit": ("context", "capture"),
}


def require_stage(stage: str, checks: dict, candidate: Candidate | None = None) -> str:
    need(stage in REQUIRES, "UNKNOWN_STAGE")
    for name in REQUIRES[stage]:
        proof = checks.get(name, {})
        need(proof.get("status") == "PASS", "PREREQUISITE_NOT_VERIFIED:" + name)
        if candidate is not None:
            need(
                proof.get("product") == candidate.product
                and proof.get("code_sha") == candidate.code_sha
                and proof.get("task_sha256") == candidate.task_sha256
                and proof.get("as_of") == candidate.as_of,
                "PREREQUISITE_IDENTITY_MISMATCH:" + name,
            )
    if "legacy" in REQUIRES[stage]:
        rows = checks["legacy"].get("rows", {})
        need(
            set(rows) == {"1d", "1w"}
            and all(
                len(row.get("source_profiles", [])) == 2
                and row.get("source_formula_versions")
                and row.get("reference_model_version")
                for row in rows.values()
            ),
            "LEGACY_IDENTITIES_REQUIRED",
        )
    return "READY_TO_" + stage.upper()
