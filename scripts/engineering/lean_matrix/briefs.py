"""Minimal, document-intake scoped role briefs and inert rendering."""

from __future__ import annotations

import html
from collections.abc import Mapping

from .contracts import DocumentIntakeV1, RoleBriefV1
from .digests import canonical_json, semantic_digest
from .errors import LeanMatrixError


ROLES = frozenset({"implementer", "reviewer", "specialist"})


def intake_digest(intake: DocumentIntakeV1) -> str:
    """Digest a trusted intake without reparsing it through an untrusted boundary."""
    if not isinstance(intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "intake must be a trusted DocumentIntakeV1")
    return semantic_digest(intake.to_dict())


def _specialist_roster(
    intake: DocumentIntakeV1,
    specialist_contexts: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    declared = tuple(dict.fromkeys(intake.execution_plan.dispatch.specialists))
    if len(declared) != len(intake.execution_plan.dispatch.specialists):
        raise LeanMatrixError("invalid_specialists", "specialist domains must be unique")
    if len(declared) > 2:
        raise LeanMatrixError(
            "split_required", "a third independent specialist domain requires a separate delivery split",
        )
    if not isinstance(specialist_contexts, Mapping):
        raise LeanMatrixError("invalid_specialist_contexts", "specialist_contexts must be a mapping")
    if set(specialist_contexts) != set(declared):
        raise LeanMatrixError(
            "specialist_roster_mismatch",
            "specialist contexts must exactly match the trusted execution-plan domains",
        )
    roster: list[tuple[str, str]] = []
    for domain in declared:
        context = specialist_contexts[domain]
        if not isinstance(domain, str) or not domain.strip() or not isinstance(context, str) or not context.strip():
            raise LeanMatrixError(
                "invalid_specialist_contexts", "specialist domains and contexts must be non-blank strings",
            )
        roster.append((domain, context))
    context_ids = [context for _, context in roster]
    if len(set(context_ids)) != len(context_ids):
        raise LeanMatrixError(
            "specialist_identity_collision", "independent specialist domains require independent contexts",
        )
    return tuple(roster)


def _report_path(
    intake: DocumentIntakeV1,
    *,
    role: str,
    specialist_domain: str | None,
    context_id: str,
    round_number: int,
) -> str:
    root = (
        f".ai/lean-matrix/{intake.execution_plan_digest.removeprefix('sha256:')}/"
        f"{intake_digest(intake).removeprefix('sha256:')}"
    )
    if role == "implementer":
        return f"{root}/handoffs/implementer/{context_id}/round-{round_number}/handoff-report.json"
    if role == "reviewer":
        return f"{root}/reviews/{context_id}/round-{round_number}/final-decision.json"
    assert specialist_domain is not None
    return (
        f"{root}/handoffs/specialists/{specialist_domain}/{context_id}/"
        "round-0/handoff-report.json"
    )


def _selected_context(
    intake: DocumentIntakeV1,
    *,
    role: str,
    specialist_domain: str | None,
) -> tuple[str, ...]:
    """Expose stable identifiers only; document bodies and plan history stay absent."""
    values = [
        canonical_json({"field": "task_id", "value": intake.task_id}),
        canonical_json({"field": "delivery_mode", "value": intake.delivery_mode}),
        canonical_json({"field": "role", "value": role}),
    ]
    if specialist_domain is not None:
        values.append(canonical_json({"field": "specialist_domain", "value": specialist_domain}))
    return tuple(values)


def build_role_brief(
    intake: DocumentIntakeV1,
    *,
    role: str,
    context_id: str,
    implementer_context_id: str,
    reviewer_context_id: str,
    specialist_contexts: Mapping[str, str],
    round_number: int,
    original_implementer_context_id: str,
    specialist_domain: str | None = None,
    predecessor_decision_digest: str | None = None,
    round_zero_brief: RoleBriefV1 | None = None,
) -> RoleBriefV1:
    """Build one brief after validating the complete independent-role roster."""
    if not isinstance(intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "intake must be a trusted DocumentIntakeV1")
    if role not in ROLES:
        raise LeanMatrixError("invalid_role", "role must be implementer, reviewer, or specialist")
    roster = _specialist_roster(intake, specialist_contexts)
    if implementer_context_id == reviewer_context_id:
        raise LeanMatrixError(
            "role_identity_collision", "implementer and reviewer contexts must differ",
        )
    roster_context_ids = tuple(context for _, context in roster)
    if len({implementer_context_id, reviewer_context_id, *roster_context_ids}) != 2 + len(roster):
        raise LeanMatrixError(
            "specialist_identity_collision",
            "specialist contexts must differ from implementer and reviewer contexts",
        )
    if role == "specialist":
        by_domain = dict(roster)
        if specialist_domain not in by_domain or by_domain[specialist_domain] != context_id:
            raise LeanMatrixError(
                "specialist_context_mismatch",
                "specialist role, domain, and context must match the trusted roster",
            )
    elif specialist_domain is not None:
        raise LeanMatrixError("invalid_specialist_identity", "only specialist briefs accept a domain")
    payload: dict[str, object] = {
        "schema_version": 1,
        "intake_digest": intake_digest(intake),
        "execution_plan_digest": intake.execution_plan_digest,
        "role": role,
        "specialist_domain": specialist_domain,
        "context_id": context_id,
        "implementer_context_id": implementer_context_id,
        "reviewer_context_id": reviewer_context_id,
        "original_implementer_context_id": original_implementer_context_id,
        "specialist_contexts": [
            {"domain": domain, "context_id": context}
            for domain, context in roster
        ],
        "round": round_number,
        "selected_context": list(
            _selected_context(intake, role=role, specialist_domain=specialist_domain),
        ),
        "trusted_allowed_paths": list(intake.execution_plan.scope.allowed_paths),
        "trusted_forbidden_paths": list(intake.execution_plan.scope.forbidden_paths),
        "acceptance_criteria": list(intake.execution_plan.validation.required_checks),
        "report_path": _report_path(
            intake,
            role=role,
            specialist_domain=specialist_domain,
            context_id=context_id,
            round_number=round_number,
        ),
        "predecessor_decision_digest": predecessor_decision_digest,
    }
    return RoleBriefV1.from_mapping(
        payload,
        document_intake=intake,
        round_zero_brief=round_zero_brief,
    )


def _quoted(value: object) -> str:
    rendered = canonical_json(value)
    return html.escape(rendered, quote=True).translate(str.maketrans({"`": "&#96;"}))


def render_role_brief_markdown(brief: RoleBriefV1) -> str:
    """Render contract values as quoted data, never executable Markdown instructions."""
    if not isinstance(brief, RoleBriefV1):
        raise LeanMatrixError("invalid_role_brief", "brief must be a trusted RoleBriefV1")
    validated = brief
    lines = [
        "# Lean Matrix Role Brief",
        "",
        "## Stable identity",
        "",
        f"- Intake digest: <code>{_quoted(validated.intake_digest)}</code>",
        f"- Role: <code>{_quoted(validated.role)}</code>",
        f"- Specialist domain: <code>{_quoted(validated.specialist_domain)}</code>",
        f"- Context: <code>{_quoted(validated.context_id)}</code>",
        f"- Round: <code>{_quoted(validated.round)}</code>",
        f"- Report path: <code>{_quoted(validated.report_path)}</code>",
        "",
        "## Selected context",
        "",
    ]
    lines.extend(f"- <code>{_quoted(value)}</code>" for value in validated.selected_context)
    lines.extend(["", "## Trusted scope", ""])
    lines.extend(f"- Allowed: <code>{_quoted(value)}</code>" for value in validated.trusted_allowed_paths)
    lines.extend(f"- Forbidden: <code>{_quoted(value)}</code>" for value in validated.trusted_forbidden_paths)
    lines.extend(["", "## Acceptance", ""])
    lines.extend(f"- <code>{_quoted(value)}</code>" for value in validated.acceptance_criteria)
    lines.extend(["", "## Predecessor decision", ""])
    lines.append(f"- Digest: <code>{_quoted(validated.predecessor_decision_digest)}</code>")
    return "\n".join(lines) + "\n"
