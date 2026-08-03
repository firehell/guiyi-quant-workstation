#!/usr/bin/env python3
"""Run validated Lean Matrix contract commands from JSON input."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

# The CLI's contract is stdout/stderr only. Prevent Python's import machinery
# from creating an ignored __pycache__ beside repository modules.
sys.dont_write_bytecode = True

from lean_matrix.charter import SCHEMA_VERSION, render_charter  # noqa: E402
from lean_matrix.adapters import execute_action  # noqa: E402
from lean_matrix.briefs import build_role_brief  # noqa: E402
from lean_matrix.contracts import (  # noqa: E402
    DocumentIntakeV1,
    ExecutionPlanV1,
    HandoffReportV1,
    ReviewPackageV1,
    RoleBriefV1,
    TaskCharterV1,
    TransitionReceiptV1,
)
from lean_matrix.errors import LeanMatrixError  # noqa: E402
from lean_matrix.git_readonly import BASE_REF, resolve_base_sha  # noqa: E402
from lean_matrix.review_git import validate_worktree_clean  # noqa: E402
from lean_matrix.observing import observe_execution_plan  # noqa: E402
from lean_matrix.planning import build_execution_plan  # noqa: E402
from lean_matrix.rendering import render_execution_plan_markdown  # noqa: E402
from lean_matrix.transitions import propose_next_transition  # noqa: E402
from lean_matrix.workspace import (  # noqa: E402
    claim_transition,
    load_round_zero_implementer_brief,
    load_evidence,
    intake_workspace,
    plan_digest,
    record_transition,
    write_role_brief_files,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class LeanMatrixArgumentParser(argparse.ArgumentParser):
    """Route invalid command syntax through the stable JSON error contract."""

    def error(self, message: str) -> None:
        raise LeanMatrixError("invalid_cli_arguments", message)


def _read_input(input_name: str) -> object:
    try:
        if input_name == "-":
            binary_stdin = getattr(sys.stdin, "buffer", None)
            content = binary_stdin.read().decode("utf-8") if binary_stdin else sys.stdin.read()
        else:
            content = Path(input_name).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LeanMatrixError("invalid_input_encoding", "input must be UTF-8 encoded JSON") from exc
    except OSError as exc:
        raise LeanMatrixError("input_file_unavailable", str(exc)) from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LeanMatrixError("invalid_json", exc.msg) from exc


def render(raw: object) -> dict[str, object]:
    """Backward-compatible import alias for the schema-v1 Charter renderer."""
    return render_charter(raw)


def _blocked(error: LeanMatrixError) -> int:
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "error_type": error.error_type,
        "detail": error.detail,
    }), file=sys.stderr)
    return 2


def _specialist_context_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise LeanMatrixError(
                "invalid_specialist_context", "--specialist-context must use DOMAIN=CONTEXT",
            )
        domain, context = value.split("=", 1)
        if not domain or not context or domain in mapping:
            raise LeanMatrixError(
                "invalid_specialist_context", "specialist domain/context must be non-blank and unique",
            )
        mapping[domain] = context
    return mapping


def _specialist_evidence_pairs(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise LeanMatrixError(
                "invalid_specialist_evidence",
                "--specialist-evidence must use BRIEF_PATH=HANDOFF_PATH",
            )
        brief_path, handoff_path = value.split("=", 1)
        if not brief_path or not handoff_path:
            raise LeanMatrixError(
                "invalid_specialist_evidence", "specialist evidence paths must be non-blank",
            )
        pairs.append((brief_path, handoff_path))
    return pairs


def _load_review_inputs(args):  # noqa: ANN001, ANN202
    approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.approved_plan))
    intake = DocumentIntakeV1.from_mapping(
        _read_input(args.intake),
        repo_root=REPO_ROOT,
        approved_execution_plan=approved_plan,
    )
    raw_implementer = _read_input(args.implementer_brief)
    round_number = raw_implementer.get("round") if isinstance(raw_implementer, dict) else None
    round_zero = (
        load_round_zero_implementer_brief(REPO_ROOT, intake)
        if isinstance(round_number, int) and round_number > 0
        else None
    )
    implementer_brief = RoleBriefV1.from_mapping(
        raw_implementer,
        document_intake=intake,
        round_zero_brief=round_zero,
    )
    reviewer_brief = RoleBriefV1.from_mapping(
        _read_input(args.reviewer_brief),
        document_intake=intake,
        round_zero_brief=round_zero,
    )
    implementer_handoff = HandoffReportV1.from_mapping(
        _read_input(args.implementer_handoff), role_brief=implementer_brief,
    )
    specialist_evidence = []
    for brief_path, handoff_path in _specialist_evidence_pairs(args.specialist_evidence):
        specialist_brief = RoleBriefV1.from_mapping(
            _read_input(brief_path), document_intake=intake,
        )
        specialist_handoff = HandoffReportV1.from_mapping(
            _read_input(handoff_path), role_brief=specialist_brief,
        )
        specialist_evidence.append((specialist_brief, specialist_handoff))
    return (
        intake,
        implementer_brief,
        implementer_handoff,
        reviewer_brief,
        tuple(specialist_evidence),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = LeanMatrixArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=LeanMatrixArgumentParser)
    charter = subcommands.add_parser("charter")
    charter.add_argument("--input", required=True)
    charter.add_argument("--format", required=True, choices=("markdown", "json"))
    plan = subcommands.add_parser("plan")
    plan.add_argument("--charter", required=True)
    plan.add_argument("--format", required=True, choices=("markdown", "json"))
    intake_command = subcommands.add_parser("intake")
    intake_command.add_argument("--input", required=True)
    intake_command.add_argument("--approved-plan", required=True)
    intake_command.add_argument("--format", required=True, choices=("json",))
    observe = subcommands.add_parser("observe")
    observe.add_argument("--plan", required=True)
    observe.add_argument("--format", required=True, choices=("json",))
    next_command = subcommands.add_parser("next")
    next_command.add_argument("--plan", required=True)
    next_command.add_argument("--format", required=True, choices=("json",))
    apply_command = subcommands.add_parser("apply")
    apply_command.add_argument("--plan", required=True)
    apply_command.add_argument("--expected-transition", required=True)
    apply_command.add_argument("--expected-state-digest", required=True)
    apply_command.add_argument("--format", required=True, choices=("json",))
    apply_command.add_argument("--apply", action="store_true")
    brief_command = subcommands.add_parser("brief")
    brief_command.add_argument("--intake", required=True)
    brief_command.add_argument("--approved-plan", required=True)
    brief_command.add_argument("--role", required=True)
    brief_command.add_argument("--specialist-domain")
    brief_command.add_argument("--specialist-context", action="append", default=[])
    brief_command.add_argument("--context-id", required=True)
    brief_command.add_argument("--implementer-context-id", required=True)
    brief_command.add_argument("--reviewer-context-id", required=True)
    brief_command.add_argument("--original-implementer-context-id")
    brief_command.add_argument("--round", type=int, default=0)
    brief_command.add_argument("--predecessor-decision-digest")
    brief_command.add_argument("--output", required=True)
    review_package_command = subcommands.add_parser("review-package")
    review_package_command.add_argument("--intake", required=True)
    review_package_command.add_argument("--approved-plan", required=True)
    review_package_command.add_argument("--implementer-brief", required=True)
    review_package_command.add_argument("--implementer-handoff", required=True)
    review_package_command.add_argument("--reviewer-brief", required=True)
    review_package_command.add_argument("--specialist-evidence", action="append", default=[])
    review_package_command.add_argument("--format", required=True, choices=("json",))
    decision_command = subcommands.add_parser("decision")
    decision_command.add_argument("--intake", required=True)
    decision_command.add_argument("--approved-plan", required=True)
    decision_command.add_argument("--implementer-brief", required=True)
    decision_command.add_argument("--implementer-handoff", required=True)
    decision_command.add_argument("--reviewer-brief", required=True)
    decision_command.add_argument("--specialist-evidence", action="append", default=[])
    decision_command.add_argument("--package", required=True)
    decision_command.add_argument("--input", required=True)
    decision_command.add_argument("--format", required=True, choices=("json",))
    try:
        args = parser.parse_args(argv)
        if args.command == "charter":
            result = render_charter(_read_input(args.input))
            output = result["charter_markdown"] if args.format == "markdown" else result
        elif args.command == "plan":
            charter_contract = TaskCharterV1.from_mapping(_read_input(args.charter))
            base_sha = resolve_base_sha(REPO_ROOT)
            plan_contract = build_execution_plan(
                charter_contract, base_ref=BASE_REF, base_sha=base_sha,
            )
            result = plan_contract.to_dict()
            output = render_execution_plan_markdown(plan_contract) if args.format == "markdown" else result
        elif args.command == "intake":
            approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.approved_plan))
            output = DocumentIntakeV1.from_mapping(
                _read_input(args.input),
                repo_root=REPO_ROOT,
                approved_execution_plan=approved_plan,
            ).to_dict()
        elif args.command == "brief":
            approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.approved_plan))
            intake = DocumentIntakeV1.from_mapping(
                _read_input(args.intake),
                repo_root=REPO_ROOT,
                approved_execution_plan=approved_plan,
            )
            round_zero_brief = (
                load_round_zero_implementer_brief(REPO_ROOT, intake)
                if args.round > 0
                else None
            )
            original_implementer_context_id = (
                args.original_implementer_context_id
                if args.original_implementer_context_id is not None
                else (
                    round_zero_brief.implementer_context_id
                    if round_zero_brief is not None
                    else args.implementer_context_id
                )
            )
            brief = build_role_brief(
                intake,
                role=args.role,
                context_id=args.context_id,
                implementer_context_id=args.implementer_context_id,
                reviewer_context_id=args.reviewer_context_id,
                original_implementer_context_id=original_implementer_context_id,
                specialist_contexts=_specialist_context_mapping(args.specialist_context),
                round_number=args.round,
                specialist_domain=args.specialist_domain,
                predecessor_decision_digest=args.predecessor_decision_digest,
                round_zero_brief=round_zero_brief,
            )
            output = write_role_brief_files(
                REPO_ROOT,
                intake,
                brief,
                Path(args.output),
                round_zero_brief=round_zero_brief,
            )
        elif args.command == "review-package":
            from lean_matrix.review_packages import build_review_package

            (
                intake,
                implementer_brief,
                implementer_handoff,
                reviewer_brief,
                specialist_evidence,
            ) = _load_review_inputs(args)
            output = build_review_package(
                REPO_ROOT,
                intake,
                implementer_brief=implementer_brief,
                implementer_handoff=implementer_handoff,
                reviewer_brief=reviewer_brief,
                specialist_evidence=specialist_evidence,
            ).to_dict()
        elif args.command == "decision":
            (
                intake,
                implementer_brief,
                implementer_handoff,
                reviewer_brief,
                specialist_evidence,
            ) = _load_review_inputs(args)
            package = ReviewPackageV1.from_mapping(
                _read_input(args.package),
                repo_root=REPO_ROOT,
                document_intake=intake,
                implementer_brief=implementer_brief,
                implementer_handoff=implementer_handoff,
                reviewer_brief=reviewer_brief,
                specialist_evidence=specialist_evidence,
            )
            from lean_matrix.contracts import FinalDecisionV1

            validate_worktree_clean(REPO_ROOT, intake_workspace(REPO_ROOT, intake))
            output = FinalDecisionV1.from_mapping(
                _read_input(args.input), review_package=package,
            ).to_dict()
        else:
            plan_contract = ExecutionPlanV1.from_mapping(_read_input(args.plan))
            observed = observe_execution_plan(plan_contract, REPO_ROOT)
            if args.command == "observe":
                output = observed.state.to_dict()
            else:
                evidence = load_evidence(REPO_ROOT, plan_contract)
                proposal = propose_next_transition(
                    plan_contract,
                    observed,
                    attempted_actions=evidence.attempted_actions,
                    successful_actions=evidence.successful_actions,
                )
                if args.command == "next":
                    output = proposal.to_dict()
                else:
                    if args.expected_state_digest != observed.state.state_digest:
                        raise LeanMatrixError(
                            "expected_state_mismatch",
                            "current state digest does not match --expected-state-digest",
                        )
                    if args.expected_transition != proposal.transition_id:
                        raise LeanMatrixError(
                            "expected_transition_mismatch",
                            "current transition does not match --expected-transition",
                        )
                    if not args.apply:
                        output = proposal.to_dict()
                    else:
                        if plan_contract.external_gates:
                            raise LeanMatrixError(
                                "lane_three_apply_forbidden",
                                "plans with external Gates cannot use generic apply",
                            )
                        if not proposal.requires_apply:
                            raise LeanMatrixError(
                                "transition_not_applicable",
                                "the current proposal has no executable local transition",
                            )
                        claim_transition(REPO_ROOT, plan_contract, proposal)
                        execution = execute_action(plan_contract, proposal.action, REPO_ROOT)
                        after = observe_execution_plan(plan_contract, REPO_ROOT)
                        execution_error = execution.error_type
                        if execution_error is None and after.state.state_digest == observed.state.state_digest:
                            execution_error = "transition_state_unchanged"
                        receipt = TransitionReceiptV1.from_mapping({
                            "transition_id": proposal.transition_id,
                            "plan_digest": plan_digest(plan_contract),
                            "before_state_digest": observed.state.state_digest,
                            "after_state_digest": after.state.state_digest,
                            "command_digests": [execution.command_digest],
                            "exit_codes": [execution.exit_code],
                            "result": "PASS" if execution_error is None else "FAIL",
                            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        })
                        record_transition(
                            REPO_ROOT,
                            plan_contract,
                            proposal,
                            receipt,
                            error_type=execution_error,
                        )
                        if execution_error:
                            raise LeanMatrixError(
                                execution_error,
                                "local transition failed or its external result is uncertain; inspect before retrying",
                            )
                        output = receipt.to_dict()
    except LeanMatrixError as exc:
        return _blocked(exc)
    if getattr(args, "format", None) == "markdown":
        print(output, end="")
    else:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
