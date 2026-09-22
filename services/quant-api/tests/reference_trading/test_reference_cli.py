from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from io import StringIO
import json

import pytest

from app.guiyi_cli.main import _execution_is_readonly, _parse_error_is_readonly, build_parser, main
from app.guiyi_cli.reference_commands import run_reference_command, strict_json_loads
from app.reference_trading.planning import plan_to_dict
from tests.reference_trading.test_bootstrap import Reader, _plan


def test_reference_domain_readonly_classification_covers_apply_and_parse_errors() -> None:
    parser = build_parser()
    plan = parser.parse_args(["reference", "plan", "--request", "request.json", "--output", "plan.json"])
    dry_build = parser.parse_args([
        "reference", "build", "--plan", "plan.json",
        "--expected-plan-hash", "a" * 64,
    ])
    apply_build = parser.parse_args([
        "reference", "build", "--plan", "plan.json",
        "--expected-plan-hash", "a" * 64, "--apply",
    ])

    assert _execution_is_readonly(plan) is True
    assert _execution_is_readonly(dry_build) is True
    assert _execution_is_readonly(apply_build) is False
    assert _parse_error_is_readonly(["reference", "advance", "--apply"]) is False
    assert _parse_error_is_readonly(["reference", "resume"]) is True


def test_reference_cli_dispatches_without_touching_data_domain_attributes() -> None:
    calls = []

    def runner(args):
        calls.append((args.reference_command, args.apply))
        return {"status": "dry_run", "readonly": True}

    stdout = StringIO()
    stderr = StringIO()
    code = main(
        ["reference", "advance", "--plan", "plan.json", "--expected-plan-hash", "a" * 64],
        reference_command_runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert calls == [("advance", False)]
    assert json.loads(stdout.getvalue())["status"] == "dry_run"
    assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    "payload",
    (
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
    ),
)
def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(payload: str) -> None:
    with pytest.raises(ValueError, match="REFERENCE_JSON_INVALID"):
        strict_json_loads(payload)


def test_apply_flag_is_not_accepted_on_plan_command() -> None:
    stderr = StringIO()
    code = main(
        ["reference", "plan", "--request", "r.json", "--output", "p.json", "--apply"],
        stdout=StringIO(), stderr=stderr,
    )
    assert code == 2
    assert json.loads(stderr.getvalue())["readonly"] is True


def test_build_without_apply_only_validates_plan_file_and_never_touches_service(
    tmp_path,
) -> None:
    plan = _plan(Reader())
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan_to_dict(plan)), encoding="utf-8")

    class ExplodingService:
        def __getattr__(self, name):
            raise AssertionError(f"dry-run touched service method {name}")

    payload = run_reference_command(
        Namespace(
            reference_command="build",
            plan=str(path),
            expected_plan_hash=plan.plan_hash,
            apply=False,
        ),
        service=ExplodingService(),
    )

    assert payload == {
        "schema_version": 1,
        "command": "reference.build",
        "status": "planned",
        "readonly": True,
        "plan_hash": plan.plan_hash,
        "stream_count": 1,
    }


def test_plan_output_refuses_existing_file_without_overwrite(tmp_path) -> None:
    plan = _plan(Reader())
    stream = plan.streams[0].request
    output = tmp_path / "plan.json"
    output.write_text("owned", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "operation": "build",
        "streams": [{
            "identity": {
                "strategy_code": stream.identity.strategy_code,
                "formula_versions": list(stream.identity.formula_versions),
                "profile_id": stream.identity.profile_id,
                "reference_model_version": stream.identity.reference_model_version,
                "futures_adaptation_version": stream.identity.futures_adaptation_version,
                "product": stream.identity.product,
                "frequency": stream.identity.frequency,
                "series_kind": stream.identity.series_kind,
                "recording_mode": stream.identity.recording_mode.value,
                "observation_policy_version": stream.identity.observation_policy_version,
            },
            "since": stream.since.isoformat(),
            "through": stream.through.isoformat(),
            "as_of": stream.as_of.isoformat(),
        }],
        "budget": {
            "max_streams": plan.budget.max_streams,
            "max_input_bars": plan.budget.max_input_bars,
            "max_elapsed_seconds": plan.budget.max_elapsed_seconds,
            "max_input_bytes": plan.budget.max_input_bytes,
        },
        "batch_size": plan.batch_size,
    }), encoding="utf-8")

    class Planner:
        def plan(self, _request):
            return plan

    with pytest.raises(ValueError, match="REFERENCE_OUTPUT_EXISTS"):
        run_reference_command(
            Namespace(
                reference_command="plan",
                request=str(request),
                output=str(output),
            ),
            planner=Planner(),
        )
    assert output.read_text(encoding="utf-8") == "owned"


def test_build_apply_dispatches_to_execute_not_a_nonexistent_build_method(tmp_path) -> None:
    plan = _plan(Reader())
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan_to_dict(plan)), encoding="utf-8")
    calls = []

    @dataclass(frozen=True)
    class Result:
        status = "completed"

    class Service:
        def execute(self, found_plan, expected_hash):
            calls.append((found_plan.plan_hash, expected_hash))
            return Result()

    payload = run_reference_command(
        Namespace(
            reference_command="build",
            plan=str(path),
            expected_plan_hash=plan.plan_hash,
            apply=True,
        ),
        service=Service(),
    )

    assert payload["status"] == "completed"
    assert calls == [(plan.plan_hash, plan.plan_hash)]


def test_reference_execution_error_is_redacted_by_cli_boundary() -> None:
    def runner(_args):
        raise OSError("SENSITIVE_TEST_SENTINEL")

    stdout = StringIO()
    stderr = StringIO()
    code = main(
        ["reference", "advance", "--plan", "plan.json", "--expected-plan-hash", "a" * 64],
        reference_command_runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    payload = json.loads(stderr.getvalue())
    assert payload["error"]["code"] == "CLI_INTERNAL_ERROR"
    assert "SENSITIVE_TEST_SENTINEL" not in stderr.getvalue()
    assert stdout.getvalue() == ""
