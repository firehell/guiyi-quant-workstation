# WeChat Group Notification Peekaboo PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, without sending any WeChat message, that the current Mac mini + WeChat.app can be inspected deterministically through Peekaboo and establish the exact compatibility boundary needed before wiring ordinary WeChat-group notifications into Alert Runtime.

**Architecture:** P0 does not touch Alert Runtime, WeCom fan-out, or real notification delivery. It adds only a reusable, side-effect-free Python wrapper around the Peekaboo CLI, then performs a local read-only/manual-navigation PoC against WeChat.app; production sender wiring is a separate follow-up plan after the real Accessibility structure is known.

**Tech Stack:** Python 3.13 stdlib, pytest, macOS 15+, WeChat.app, Peekaboo CLI 3.9.x.

## Global Constraints

- Supported Peekaboo contract for P0 is `>=3.9.8,<4.0.0`; any other version fails closed with `WECHAT_PEEKABOO_VERSION_UNSUPPORTED`.
- The version ceiling is intentional: Peekaboo 3.9.8 exposes `perform-action`, while the in-development 4.0 command surface renames/changes interaction commands.
- No OpenClaw Gateway, LLM, MCP, Hook, Frida, OCR, or image analysis is used.
- P0 must not send a WeChat message, press the final send action, invoke the existing real WeCom canary, enable/switch Alert Runtime, or mutate production DB/Scope.
- P0 must not modify `services/quant-api/app/alerts/runtime.py` or `services/quant-api/app/alerts/composition.py`; production fan-out is deferred until PoC evidence exists.
- Raw WeChat Accessibility JSON, screenshots, contact names, chat list contents, message contents, and the real target group name must not be committed or logged.
- Temporary inspection files must be created outside the repository with owner-only permissions and deleted after the privacy-safe summary is recorded.
- Do not automate macOS TCC changes. Missing Screen Recording / Accessibility / Event Synthesizing permissions are reported and handled manually.
- If the target chat title and a usable message-input control cannot be identified deterministically from Accessibility metadata, stop after P0 and revise the design; do not fall back to fixed coordinates.

---

## File Structure

- Create `services/quant-api/app/alerts/wechat_peekaboo.py` — fixed-argv Peekaboo subprocess wrapper, version gate, JSON decoding, stable sanitized errors.
- Create `services/quant-api/tests/test_alert_wechat_peekaboo.py` — unit tests for executable validation, version range, timeout/failure collapse, and JSON parsing.
- Modify `docs/superpowers/specs/2026-08-15-wechat-group-notification-design.md` only after the Mac PoC — record the reviewed sender-Protocol correction, Peekaboo compatibility range, and non-private observed Accessibility facts.

---

### Task 1: Build the side-effect-free Peekaboo runner

**Files:**
- Create: `services/quant-api/app/alerts/wechat_peekaboo.py`
- Test: `services/quant-api/tests/test_alert_wechat_peekaboo.py`

**Interfaces:**
- Produces: `PeekabooError(RuntimeError)` whose message is one stable public error code only.
- Produces: `validate_peekaboo_executable(value: object) -> str`.
- Produces: `parse_peekaboo_version(text: str) -> tuple[int, int, int]`.
- Produces: `PeekabooRunner(executable: str = "peekaboo", timeout_seconds: float = 8.0, run_process: ProcessRunner | None = None)`.
- Produces: `PeekabooRunner.ensure_supported_version() -> tuple[int, int, int]`.
- Produces: `PeekabooRunner.inspect_ui(app_name: str = "WeChat") -> Mapping[str, object]`.
- Later production code may reuse this module, but P0 does not import it from Alert Runtime.

- [ ] **Step 1: Write the failing executable/version tests**

Create `services/quant-api/tests/test_alert_wechat_peekaboo.py` with these initial tests:

```python
from __future__ import annotations

import pytest

from app.alerts.wechat_peekaboo import (
    parse_peekaboo_version,
    validate_peekaboo_executable,
)


def test_validate_peekaboo_executable_accepts_name_and_absolute_binary() -> None:
    assert validate_peekaboo_executable("peekaboo") == "peekaboo"
    assert (
        validate_peekaboo_executable("/opt/homebrew/bin/peekaboo")
        == "/opt/homebrew/bin/peekaboo"
    )


@pytest.mark.parametrize(
    "value",
    ("", "../peekaboo", "bin/peekaboo", "/tmp/not-peekaboo", 123, None),
)
def test_validate_peekaboo_executable_rejects_uncontrolled_values(
    value: object,
) -> None:
    with pytest.raises(ValueError, match="^PEEKABOO_EXECUTABLE_INVALID$"):
        validate_peekaboo_executable(value)


def test_parse_peekaboo_version_extracts_stable_semver() -> None:
    assert parse_peekaboo_version("Peekaboo 3.9.8 (main/416247a)") == (3, 9, 8)


@pytest.mark.parametrize(
    "text",
    ("", "Peekaboo dev", "4", "private raw output"),
)
def test_parse_peekaboo_version_rejects_unknown_output(text: str) -> None:
    with pytest.raises(ValueError, match="^PEEKABOO_VERSION_INVALID$"):
        parse_peekaboo_version(text)
```

- [ ] **Step 2: Run the focused test and verify it fails because the module is absent**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wechat_peekaboo.py
```

Expected: collection/import failure for `app.alerts.wechat_peekaboo`.

- [ ] **Step 3: Implement executable and version parsing**

Create `services/quant-api/app/alerts/wechat_peekaboo.py` with this base:

```python
from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
import re
import subprocess
from typing import Any


_MIN_VERSION = (3, 9, 8)
_MAX_VERSION_EXCLUSIVE = (4, 0, 0)
_VERSION_RE = re.compile(r"\b(\d+)\.(\d+)\.(\d+)\b")


class PeekabooError(RuntimeError):
    pass


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def validate_peekaboo_executable(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("PEEKABOO_EXECUTABLE_INVALID")
    normalized = value.strip()
    if not normalized:
        raise ValueError("PEEKABOO_EXECUTABLE_INVALID")
    path = Path(normalized)
    if path.name != "peekaboo":
        raise ValueError("PEEKABOO_EXECUTABLE_INVALID")
    if path.parent != Path(".") and not path.is_absolute():
        raise ValueError("PEEKABOO_EXECUTABLE_INVALID")
    return normalized


def parse_peekaboo_version(text: str) -> tuple[int, int, int]:
    match = _VERSION_RE.search(text)
    if match is None:
        raise ValueError("PEEKABOO_VERSION_INVALID")
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )
```

Do not add logging of raw stdout/stderr.

- [ ] **Step 4: Extend the tests with complete runner/error cases**

Append:

```python
import subprocess

from app.alerts.wechat_peekaboo import PeekabooError, PeekabooRunner


def _completed(
    args: list[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_supported_version_accepts_398_and_uses_fixed_argv() -> None:
    calls: list[list[str]] = []

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _completed(args, stdout="Peekaboo 3.9.8 (main/416247a)\n")

    runner = PeekabooRunner(run_process=run_process)

    assert runner.ensure_supported_version() == (3, 9, 8)
    assert calls == [["peekaboo", "--version"]]


@pytest.mark.parametrize(
    "version_text",
    ("Peekaboo 3.9.7\n", "Peekaboo 4.0.0\n"),
)
def test_supported_version_rejects_outside_range(version_text: str) -> None:
    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(args, stdout=version_text)

    with pytest.raises(
        PeekabooError,
        match="^WECHAT_PEEKABOO_VERSION_UNSUPPORTED$",
    ):
        PeekabooRunner(run_process=run_process).ensure_supported_version()


def test_missing_binary_collapses_to_stable_error() -> None:
    def run_process(_args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("private path")

    with pytest.raises(
        PeekabooError,
        match="^WECHAT_PEEKABOO_UNAVAILABLE$",
    ):
        PeekabooRunner(run_process=run_process).ensure_supported_version()


def test_timeout_collapses_to_stable_error() -> None:
    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, 8.0, output="private output")

    with pytest.raises(PeekabooError, match="^WECHAT_TIMEOUT$") as exc_info:
        PeekabooRunner(run_process=run_process).ensure_supported_version()

    assert "private output" not in str(exc_info.value)


def test_inspect_ui_uses_fixed_argv_and_parses_object_json() -> None:
    calls: list[list[str]] = []

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ["peekaboo", "--version"]:
            return _completed(args, stdout="Peekaboo 3.9.8\n")
        assert args == ["peekaboo", "inspect-ui", "--app", "WeChat", "--json"]
        return _completed(args, stdout='{"data":{"element_count":12}}')

    payload = PeekabooRunner(run_process=run_process).inspect_ui()

    assert payload == {"data": {"element_count": 12}}
    assert calls == [
        ["peekaboo", "--version"],
        ["peekaboo", "inspect-ui", "--app", "WeChat", "--json"],
    ]


def test_inspect_ui_nonzero_exit_does_not_leak_stderr() -> None:
    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args == ["peekaboo", "--version"]:
            return _completed(args, stdout="Peekaboo 3.9.8\n")
        return _completed(args, returncode=1, stderr="private chat data")

    with pytest.raises(PeekabooError, match="^WECHAT_UI_UNAVAILABLE$") as exc_info:
        PeekabooRunner(run_process=run_process).inspect_ui()

    assert "private chat data" not in str(exc_info.value)


def test_inspect_ui_rejects_non_object_json() -> None:
    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args == ["peekaboo", "--version"]:
            return _completed(args, stdout="Peekaboo 3.9.8\n")
        return _completed(args, stdout="[]")

    with pytest.raises(
        PeekabooError,
        match="^WECHAT_PEEKABOO_RESPONSE_INVALID$",
    ):
        PeekabooRunner(run_process=run_process).inspect_ui()
```

- [ ] **Step 5: Implement `PeekabooRunner` to satisfy the tests**

Add:

```python
class PeekabooRunner:
    def __init__(
        self,
        executable: str = "peekaboo",
        *,
        timeout_seconds: float = 8.0,
        run_process: ProcessRunner | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("WECHAT_TIMEOUT_INVALID")
        self._executable = validate_peekaboo_executable(executable)
        self._timeout_seconds = float(timeout_seconds)
        self._run_process = run_process or subprocess.run

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self._run_process(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError:
            raise PeekabooError("WECHAT_PEEKABOO_UNAVAILABLE") from None
        except subprocess.TimeoutExpired:
            raise PeekabooError("WECHAT_TIMEOUT") from None

    def ensure_supported_version(self) -> tuple[int, int, int]:
        completed = self._run([self._executable, "--version"])
        if completed.returncode != 0:
            raise PeekabooError("WECHAT_PEEKABOO_UNAVAILABLE")
        try:
            version = parse_peekaboo_version(completed.stdout)
        except ValueError:
            raise PeekabooError("WECHAT_PEEKABOO_VERSION_UNSUPPORTED") from None
        if not (_MIN_VERSION <= version < _MAX_VERSION_EXCLUSIVE):
            raise PeekabooError("WECHAT_PEEKABOO_VERSION_UNSUPPORTED")
        return version

    def inspect_ui(self, app_name: str = "WeChat") -> Mapping[str, object]:
        if app_name != "WeChat":
            raise ValueError("WECHAT_APP_INVALID")
        self.ensure_supported_version()
        completed = self._run(
            [self._executable, "inspect-ui", "--app", app_name, "--json"]
        )
        if completed.returncode != 0:
            raise PeekabooError("WECHAT_UI_UNAVAILABLE")
        try:
            payload: Any = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError):
            raise PeekabooError("WECHAT_PEEKABOO_RESPONSE_INVALID") from None
        if not isinstance(payload, dict):
            raise PeekabooError("WECHAT_PEEKABOO_RESPONSE_INVALID")
        return payload
```

Do not add retries, subprocess shells, raw-output logging, screenshots, or send/input actions in P0.

- [ ] **Step 6: Run focused tests, lint, and mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wechat_peekaboo.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/alerts/wechat_peekaboo.py \
  services/quant-api/tests/test_alert_wechat_peekaboo.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/alerts/wechat_peekaboo.py
```

Expected: all PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  services/quant-api/app/alerts/wechat_peekaboo.py \
  services/quant-api/tests/test_alert_wechat_peekaboo.py
git commit -m "feat(alert): add safe Peekaboo inspection runner"
```

---

### Task 2: Run the Mac mini read-only/manual-navigation WeChat Accessibility PoC

**Files:**
- No repository source changes during the inspection itself.
- Temporary local files only under `/private/tmp/guiyi-wechat-poc/`.

**Interfaces:**
- Consumes: `PeekabooRunner` from Task 1.
- Produces: a privacy-safe observation containing only version, permission readiness, structural role counts, exact-target occurrence counts, and whether a usable text-input control is visible.
- Explicitly does **not** produce or preserve raw Accessibility payloads.

- [ ] **Step 1: Verify/install Peekaboo and enforce the version range**

On the Mac mini that runs WeChat:

```bash
command -v peekaboo || brew install steipete/tap/peekaboo
peekaboo --version
```

Continue only if the parsed version satisfies `>=3.9.8,<4.0.0`. If the version is outside the range, STOP. Do not downgrade/upgrade automatically and do not silently translate 3.9.x commands to the 4.0 command surface.

- [ ] **Step 2: Check macOS permissions without scripting TCC changes**

```bash
peekaboo permissions status --all-sources
```

Required for inspection: Screen Recording and Accessibility granted to the actual host process reported by Peekaboo. Event Synthesizing is not required for this read-only PoC; it is relevant later for background keyboard delivery.

If permissions are missing, use normal System Settings / Peekaboo permission guidance manually and re-run the status command.

- [ ] **Step 3: Capture initial WeChat Accessibility JSON privately**

Ensure official WeChat.app is logged in, then:

```bash
umask 077
mkdir -p /private/tmp/guiyi-wechat-poc
peekaboo inspect-ui --app WeChat --json \
  > /private/tmp/guiyi-wechat-poc/wechat-initial.json
```

Expected: exit 0 and valid JSON. Never copy this raw file into the repository or external chat/issues/logs.

- [ ] **Step 4: Manually open the intended target group and capture its AX state**

Use WeChat normally to open the exact ordinary group. Do not type a message and do not press Return/Send in the composer.

```bash
peekaboo inspect-ui --app WeChat --json \
  > /private/tmp/guiyi-wechat-poc/wechat-target-open.json
```

- [ ] **Step 5: Supply the target group name without putting it in shell history**

```bash
read -r -s -p "Target WeChat group name: " WECHAT_GROUP_NAME
echo
export WECHAT_GROUP_NAME
```

The value remains local to the current shell and must not be written to the repository.

- [ ] **Step 6: Produce a privacy-safe structural summary for the opened chat**

```bash
python3 - <<'PY'
import json
import os
from collections import Counter
from pathlib import Path

path = Path('/private/tmp/guiyi-wechat-poc/wechat-target-open.json')
payload = json.loads(path.read_text(encoding='utf-8'))
target = os.environ['WECHAT_GROUP_NAME'].strip()

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

roles = Counter()
exact_target_nodes = 0
text_input_nodes = 0
for node in walk(payload):
    role = node.get('role') or node.get('role_description')
    if isinstance(role, str) and role:
        roles[role] += 1
    texts = [node.get(key) for key in ('title', 'label', 'description', 'value')]
    if any(isinstance(text, str) and text.strip() == target for text in texts):
        exact_target_nodes += 1
    role_text = str(role or '').lower()
    if 'textfield' in role_text or 'textarea' in role_text or 'text area' in role_text:
        text_input_nodes += 1

print({
    'exact_target_nodes': exact_target_nodes,
    'text_input_nodes': text_input_nodes,
    'role_counts': dict(sorted(roles.items())),
})
PY
```

The printed summary must contain counts/role names only. It must not print the group name, contact names, message text, labels, values, or the raw node tree.

- [ ] **Step 7: Manually search the exact group name and inspect search-result structure**

Use normal WeChat UI to open search and type the exact group name. Do not open a result through automation and do not send anything.

```bash
peekaboo inspect-ui --app WeChat --json \
  > /private/tmp/guiyi-wechat-poc/wechat-search.json
```

Run the same Python summary from Step 6 after changing only the path to `/private/tmp/guiyi-wechat-poc/wechat-search.json`. Record only the three printed summary fields.

- [ ] **Step 8: Apply the PoC gate**

P0 passes only if all statements are true:

```text
Peekaboo version is >=3.9.8,<4.0.0
permissions required for inspect-ui are granted to the reported host
inspect-ui succeeds against WeChat.app
raw AX JSON is parseable
opened target group exposes at least one exact target-title occurrence
opened target group exposes at least one text-field/text-area candidate
searching the exact group exposes deterministic AX evidence for the target title
no message was sent
```

If any structural requirement fails, STOP. Do not add coordinate automation, OCR, image matching, blind Return presses, or LLM computer-use.

- [ ] **Step 9: Delete private raw inspection data and shell variable**

```bash
rm -rf /private/tmp/guiyi-wechat-poc
unset WECHAT_GROUP_NAME
test ! -e /private/tmp/guiyi-wechat-poc
```

Expected: the test command exits 0.

---

### Task 3: Close the design review with evidence and prepare the production handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-08-15-wechat-group-notification-design.md`
- Modify `STATUS.md` only if the PoC result is judged a durable project-state fact rather than temporary development evidence.

**Interfaces:**
- Consumes: the privacy-safe P0 pass/fail summary from Task 2.
- Produces: an evidence-backed design spec that a later production implementation plan can use without guessing the current WeChat Accessibility contract.

- [ ] **Step 1: Add the sender-interface review correction to the spec**

State that production integration must replace the concrete `WeComWebhookSender` constructor type in `AlertRuntime` with the minimal protocol:

```python
class AlertSender(Protocol):
    def send(self, event: AlertNotificationMessage) -> None: ...
```

`WeComWebhookSender` and the future `CompositeAlertSender` satisfy this interface. This is a notification-boundary correction only and must not alter Rule evaluation, Event creation, idempotency, or notification-attempt semantics.

- [ ] **Step 2: Add the Peekaboo compatibility contract to the spec**

Record exactly:

```text
Supported Peekaboo: >=3.9.8,<4.0.0
Outside range: fail closed
Compatibility reason: v3.9.8 is the validated stable 3.9 CLI contract; 4.0 changes interaction command names/semantics and requires a separate compatibility review.
```

Also record that the validated 3.9.x primitives available for the later implementation are `inspect-ui --app`, `set-value`, `perform-action`, and target-resolved background typing/input. The later implementation should use the smallest subset proven necessary by the PoC.

- [ ] **Step 3: Record the non-private P0 observations**

Write the exact normalized Peekaboo version observed in Task 2 and the following booleans/count conclusions, without copying any private labels or values:

```text
WeChat inspect-ui: PASS or FAIL
exact target title exposed in AX: yes or no
text input role exposed in AX: yes or no
exact search-result title exposed in AX: yes or no
real message sent during PoC: no
```

Do not record the target group name, contact names, chat content, raw tree, screenshots, or message values.

- [ ] **Step 4: Run repository checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: no secret finding attributable to this task; only intended spec/status changes remain.

- [ ] **Step 5: Commit the spec amendment**

```bash
git add docs/superpowers/specs/2026-08-15-wechat-group-notification-design.md
# Stage STATUS.md only when it was legitimately updated with a durable fact.
git commit -m "docs(alert): record WeChat Peekaboo PoC contract"
```

- [ ] **Step 6: Stop before production sender wiring**

Do not implement `WeChatGroupSender`, `CompositeAlertSender`, Runtime composition wiring, canary sending, or persistent automatic group notification in this P0 plan.

After a passing P0, create a separate production implementation plan using the observed AX structure. That plan must include TDD for exact target resolution, title re-verification, message-input targeting, background-first/focus-fallback behavior, channel failure isolation, supported Peekaboo-version enforcement, and the separate real-notification Gate.
