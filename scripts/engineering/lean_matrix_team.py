#!/usr/bin/env python3
"""Render validated, read-only Lean Matrix contracts from JSON input."""

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
from lean_matrix.contracts import ExecutionPlanV1, TaskCharterV1, TransitionReceiptV1  # noqa: E402
from lean_matrix.errors import LeanMatrixError  # noqa: E402
from lean_matrix.git_readonly import BASE_REF, resolve_base_sha  # noqa: E402
from lean_matrix.observing import observe_execution_plan  # noqa: E402
from lean_matrix.planning import build_execution_plan  # noqa: E402
from lean_matrix.rendering import render_execution_plan_markdown  # noqa: E402
from lean_matrix.transitions import propose_next_transition  # noqa: E402
from lean_matrix.workspace import claim_transition, load_evidence, plan_digest, record_transition  # noqa: E402


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = LeanMatrixArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=LeanMatrixArgumentParser)
    charter = subcommands.add_parser("charter")
    charter.add_argument("--input", required=True)
    charter.add_argument("--format", required=True, choices=("markdown", "json"))
    plan = subcommands.add_parser("plan")
    plan.add_argument("--charter", required=True)
    plan.add_argument("--format", required=True, choices=("markdown", "json"))
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
    if args.format == "markdown":
        print(output, end="")
    else:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
