"""Bounded candidate-only Chrome observations; no service, provider or data mutation.

Rendering is offline. ``capture`` is explicit and requires the frozen first-batch
preflight. Every response and screenshot is evidence pending independent review;
this module never declares visual or product acceptance.
"""

from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlencode

from .context import Candidate, FREQUENCIES, MODES, instant, need
from .evidence import EvidenceStore
from .stages import require_stage
from .preflight import read_preview

RESOURCES = Path(__file__).parent / "browser"


def _candidate(value: dict | Candidate) -> Candidate:
    return value if isinstance(value, Candidate) else Candidate.from_mapping(value)


def _config(
    candidate: Candidate, scenario: str, frequency: str, mode: str, screenshot_dir: Path
) -> dict:
    allowed = (
        FREQUENCIES
        if scenario == "minute"
        else ("1d", "1w")
        if scenario == "legacy"
        else ("5m",)
    )
    need(
        scenario in ("minute", "legacy", "cancel")
        and frequency in allowed
        and mode in MODES,
        "CAPTURE_SCENARIO_INVALID",
    )
    need(scenario != "cancel" or mode == "trend", "CANCEL_SCENARIO_INVALID")
    root = EvidenceStore(Path(screenshot_dir).absolute())
    data = candidate.to_mapping()
    strategy = "oscillation" if mode == "oscillation" else "trend"
    query = dict(
        symbol=candidate.product,
        view="newow",
        strategy=strategy,
        frequency=frequency,
        series_kind="actual_dominant",
    )
    if mode == "dual":
        query["newow_mode"] = "dual"
    label = f"{scenario}-{frequency}-{mode}"
    shots = {
        name: str(root.path(f"{label}-{name}.png"))
        for name in ("main", "curve", "earlier")
    }
    need(
        all(not Path(path).exists() for path in shots.values()),
        "PRESERVE_CAPTURE_SCREENSHOTS",
    )
    data.update(
        as_of=instant(candidate.as_of).isoformat(),
        scenario=scenario,
        frequency=frequency,
        mode=mode,
        task_key=candidate.task_sha256,
        target_url=candidate.web_origin + "/market/chart?" + urlencode(query),
        shot_main=shots["main"],
        shot_curve=shots["curve"],
        shot_earlier=shots["earlier"],
    )
    return data


def render_scenario(
    candidate: dict | Candidate,
    scenario: str,
    frequency: str,
    mode: str,
    screenshot_dir: Path,
) -> str:
    """Build one reviewed static scenario; JSON is the only dynamic source injection."""
    context = _candidate(candidate)
    config = _config(context, scenario, frequency, mode, screenshot_dir)
    source = (RESOURCES / (scenario + ".js")).read_text()
    need(source.startswith("async page=>{\n"), "BROWSER_RESOURCE_INVALID")
    observer = (RESOURCES / "observer.js").read_text().strip()
    header = (
        "const CONFIG = "
        + json.dumps(config, ensure_ascii=True, allow_nan=False)
        + ";\n"
        "const PRODUCT=CONFIG.product,FREQUENCY=CONFIG.frequency,MODE=CONFIG.mode;\n"
        "const EXPECTED_CODE=CONFIG.code_sha,EXPECTED_WEB_CODE=CONFIG.web_code_sha??CONFIG.code_sha;\n"
        "const CODE=EXPECTED_CODE,WEB_CODE=EXPECTED_WEB_CODE,ASOF=CONFIG.as_of;\n"
        "const TARGET=CONFIG.target_url,SHOTMAIN=CONFIG.shot_main,SHOTCURVE=CONFIG.shot_curve,SHOT=CONFIG.shot_main;\n"
        "const XHR_INIT=(" + observer + ");\n"
    )
    return source.replace("async page=>{\n", "async page=>{\n" + header, 1)


def render_capture(
    candidate: dict | Candidate, frequency: str, mode: str, screenshot_dir: Path
) -> str:
    return render_scenario(candidate, "minute", frequency, mode, screenshot_dir)


def _parse_result(stdout: str) -> dict:
    try:
        result = stdout.split("### Result\n", 1)[1].split("\n### ", 1)[0]
        body = json.loads(result)
        need(isinstance(body, dict), "CLI_RESULT_NOT_OBJECT")
        return body
    except (ValueError, IndexError, TypeError):
        return dict(status="BLOCKED", code="CLI_RESULT_UNAVAILABLE")


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _scene_observed(candidate: Candidate, scenario: str, observed: dict) -> bool:
    """Require an actual identified terminal capture, never an empty CLI object."""
    identity = observed.get("identity", {})
    if scenario == "legacy":
        api, web = identity, observed.get("webIdentity", {})
    else:
        api, web = identity.get("api", {}), identity.get("web", {})
        if observed.get("identity_valid") is not True:
            return False
    try:
        if not all(
            isinstance(value, dict)
            and value.get("code_sha") == code
            and instant(value["as_of"]) == instant(candidate.as_of)
            and value.get("mode") == "local_candidate_readonly"
            and value.get("realtime") is False
            for value, code in (
                (api, candidate.code_sha),
                (web, candidate.web_code_sha or candidate.code_sha),
            )
        ):
            return False
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    if web.get("candidate_origin") != candidate.api_origin:
        return False
    if scenario == "minute":
        return bool(
            observed.get("responses")
            and observed.get("full_capture")
            and observed.get("earlier_capture")
            and observed.get("final")
            and not observed.get("pageErrors")
        )
    if scenario == "legacy":
        return bool(
            observed.get("responses")
            and observed.get("full")
            and observed.get("before")
            and observed.get("returned")
            and not observed.get("bodyErrors")
            and not observed.get("pageErrors")
        )
    return bool(
        observed.get("pendingAtSwitch")
        and observed.get("returnedChart")
        and observed.get("snapshot_recovery")
        and observed.get("final")
    )


def capture(
    candidate: dict | Candidate, output_dir: Path, cli_path: Path, session: str
) -> dict:
    """Run 12 combined minute views + 6 legacy views + one real recovery scene.

    Failed/unknown observations are saved and stop the remaining scenes. The
    exclusive start record prevents a second invocation from silently replaying
    an interrupted collection. Each intentional conflict is a read-only GET.
    """
    context = _candidate(candidate)
    store = EvidenceStore(Path(output_dir).absolute())
    for filename in ("collection-start.json", "collection-observations.json"):
        if store.path(filename).exists():
            raise FileExistsError(filename)
    proof = store.read("preflight-check.json")
    need(
        proof.get("task_sha256") == context.task_sha256
        and proof.get("status") == "PASS",
        "CAPTURE_PREFLIGHT_IDENTITY",
    )
    checks = proof.get("checks", {}).copy()
    require_stage("capture", checks, context)
    checks["context"] = context.frozen_check()
    require_stage("capture", checks, context)
    legacy = store.read("legacy-expected-identities.json")
    need(legacy == checks["legacy"], "LEGACY_PREFLIGHT_CHANGED")
    executable = Path(cli_path)
    need(
        executable.is_absolute()
        and executable.is_file()
        and os.access(executable, os.X_OK),
        "BROWSER_CLI_EXECUTABLE_REQUIRED",
    )
    executable = executable.resolve()
    need(
        isinstance(session, str)
        and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", session) is not None,
        "BROWSER_SESSION_INVALID",
    )
    fresh_preview = read_preview(context)
    require_stage("capture", dict(checks, preview=fresh_preview), context)
    capture_root = store.path("browser")
    need(not capture_root.exists(), "PRESERVE_CAPTURE_DIRECTORY")
    # The exclusive directory also protects screenshots written by Playwright.
    capture_root.mkdir(mode=0o700)
    store.write("capture-preview-check.json", fresh_preview)
    resources = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(RESOURCES.glob("*.js"))
    }
    resources["collection.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    store.write(
        "collection-start.json",
        dict(
            context.proof(),
            status="STARTED",
            scene_count=19,
            tool_resource_sha256=resources,
            provider_calls=0,
            production_writes=0,
            operations="candidate-only GET and actual UI controls; no retry or service launch",
        ),
    )
    rows: list[dict[str, Any]] = []
    scenarios = [("minute", f, m) for f in FREQUENCIES for m in MODES]
    scenarios += [("legacy", f, m) for f in ("1d", "1w") for m in MODES]
    scenarios += [("cancel", "5m", "trend")]
    for number, (scenario, frequency, mode) in enumerate(scenarios):
        label = f"{scenario}-{frequency}-{mode}"
        code = render_scenario(context, scenario, frequency, mode, capture_root)
        failure = None
        try:
            result = subprocess.run(
                [str(executable), "-s=" + session, "run-code", code],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            stdout, stderr = result.stdout, result.stderr
            exit_code = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = _text(error.stdout), _text(error.stderr)
            exit_code, failure = None, "CLI_TIMEOUT_NO_REPLAY"
        except OSError:
            stdout, stderr = "", ""
            exit_code, failure = None, "CLI_INVOCATION_FAILED_NO_REPLAY"
        cli_ref = store.write(
            "browser/" + label + "-cli.json",
            dict(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                failure=failure,
                browser_script=code,
                browser_script_sha256=hashlib.sha256(code.encode()).hexdigest(),
            ),
        )
        observed = _parse_result(stdout)
        failed = (
            failure is not None
            or exit_code != 0
            or observed.get("status") in ("BLOCKED", "NOT_RUN")
            or bool(observed.get("errors"))
            or bool(observed.get("bodyReadErrors"))
            or not _scene_observed(context, scenario, observed)
        )
        # Success only means data was observed; offline/visual acceptance is separate.
        row = dict(
            scenario=scenario,
            frequency=frequency,
            mode=mode,
            code_sha=context.code_sha,
            web_code_sha=context.web_code_sha or context.code_sha,
            task_sha256=context.task_sha256,
            as_of=context.as_of,
            product=context.product,
            status="BLOCKED" if failed else "OBSERVED_NEEDS_VISUAL_REVIEW",
            observed=observed,
            cli=cli_ref,
            visual_review="NOT_RUN",
            browser_script_sha256=hashlib.sha256(code.encode()).hexdigest(),
            failure=failure,
        )
        raw = store.write("browser/" + label + ".json", row)
        images = []
        for kind in ("main", "curve", "earlier"):
            name = "browser/" + label + "-" + kind + ".png"
            if store.path(name).is_file():
                images.append(store.reference(name))
        summary = {k: v for k, v in row.items() if k != "observed"}
        summary.update(raw=raw, images=images)
        rows.append(summary)
        store.write(f"collection-progress/{number:02d}.json", summary)
        if failed:
            break
    result = dict(
        context.proof(),
        status="OBSERVED_NEEDS_VISUAL_REVIEW"
        if len(rows) == 19 and all(r["status"] != "BLOCKED" for r in rows)
        else "BLOCKED",
        readonly=True,
        provider_calls=0,
        production_writes=0,
        rows=rows,
        expected_scene_count=19,
        completed_scene_count=len(rows),
        visual_review="NOT_RUN",
        no_automatic_replay=True,
    )
    store.write("collection-observations.json", result)
    return result
