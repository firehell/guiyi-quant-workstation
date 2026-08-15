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

- [ ] **Step 1: Write failing tests for executable and version validation**

Add tests equivalent to:

```python
import pytest

from app.alerts.wechat_peekaboo import (
    parse_peekaboo_version,
    validate_peekaboo_executable,
)


def test_validate_peekaboo_executable_accepts_name_and_absolute_binary() -> None:
    assert validate_peekaboo_executable("peekaboo") == "peekaboo"
    assert validate_peekaboo_executable("/opt/homebrew/bin/peekaboo") == "/opt/homebrew/bin/peekaboo"


@pytest.mark.parametrize(
    "value",
    ("", "../peekaboo", "bin/peekaboo", "/tmp/not-peekaboo", 123, None),
)
def test_validate_peekaboo_executable_rejects_uncontrolled_values(value: object) -> None:
    with pytest.raises(ValueError, match="^PEEKABOO_EXECUTABLE_INVALID$"):
        validate_peekaboo_executable(value)


def test_parse_peekaboo_version_extracts_stable_semver() -> None:
    assert parse_peekaboo_version("Peekaboo 3.9.8 (main/416247a)") == (3, 9, 8)


@pytest.mark.parametrize("text", ("", "Peekaboo dev", "4", "private raw output"))
def test_parse_peekaboo_version_rejects_unknown_output(text: str) -> None:
    with pytest.raises(ValueError, match="^PEEKABOO_VERSION_INVALID$"):
        parse_peekaboo_version(text)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wechat_peekaboo.py
```

Expected: FAIL because `app.alerts.wechat_peekaboo` does not exist.

- [ ] **Step 3: Implement executable and version parsing**

Implement the minimal contract:

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
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]
```

Do not add any logging of raw command output.

- [ ] **Step 4: Write failing tests for subprocess isolation and version gate**

Cover exactly these cases with injected `run_process` fakes:

```python
def test_supported_version_accepts_398() -> None: ...
def test_supported_version_rejects_397() -> None: ...
def test_supported_version_rejects_400() -> None: ...
def test_missing_binary_collapses_to_stable_error() -> None: ...
def test_timeout_collapses_to_stable_error_without_raw_text() -> None: ...
def test_nonzero_exit_collapses_to_stable_error_without_stderr() -> None: ...
def test_inspect_ui_uses_fixed_argv_and_parses_json() -> None: ...
def test_inspect_ui_rejects_non_object_json() -> None: ...
```

The fixed argv assertions must require:

```python
["peekaboo", "--version"]
["peekaboo", "inspect-ui", "--app", "WeChat", "--json"]
```

No call may use `shell=True`.

- [ ] **Step 5: Implement `PeekabooRunner`**

Use `subprocess.run` with an argv list, `capture_output=True`, `text=True`, `check=False`, and the configured timeout. Map failures as follows:

```text
FileNotFoundError                  -> WECHAT_PEEKABOO_UNAVAILABLE
subprocess.TimeoutExpired          -> WECHAT_TIMEOUT
unsupported parsed version        -> WECHAT_PEEKABOO_VERSION_UNSUPPORTED
nonzero inspect-ui result         -> WECHAT_UI_UNAVAILABLE
invalid/non-object JSON            -> WECHAT_PEEKABOO_RESPONSE_INVALID
```

`ensure_supported_version()` must call `peekaboo --version`, parse the first semantic version, and enforce:

```python
(3, 9, 8) <= version < (4, 0, 0)
```

`inspect_ui()` must call `ensure_supported_version()` first, then run the fixed `inspect-ui` argv. Never include stdout/stderr in exception text.

- [ ] **Step 6: Run tests, lint, and type checking**

Run:

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

- [ ] **Step 1: Verify/install Peekaboo and stop on unsupported versions**

On the Mac mini that runs WeChat:

```bash
command -v peekaboo || brew install steipete/tap/peekaboo
peekaboo --version
```

Expected today: `3.9.8` or another version satisfying `>=3.9.8,<4.0.0`.

If the result is `<3.9.8` or `>=4.0.0`, STOP. Do not silently adapt command names and do not continue the PoC until the design is revised for that version.

- [ ] **Step 2: Check macOS permissions without changing them automatically**

Run:

```bash
peekaboo permissions status --all-sources
```

Required for inspection: Screen Recording + Accessibility available to the actual host process Peekaboo reports. Event Synthesizing is not required for this read-only PoC; it will only matter later for background keyboard delivery.

If permissions are missing, use the normal System Settings / Peekaboo permission guidance manually, then re-run status. Do not script TCC changes.

- [ ] **Step 3: Confirm WeChat is logged in and capture the initial AX payload locally**

Create a private temp directory:

```bash
umask 077
mkdir -p /private/tmp/guiyi-wechat-poc
peekaboo inspect-ui --app WeChat --json \
  > /private/tmp/guiyi-wechat-poc/wechat-initial.json
```

Expected: exit 0 and valid JSON. Do not copy this file into the repository or paste its raw content into chat/issues/logs.

- [ ] **Step 4: Manually navigate to the intended target group without sending anything**

In WeChat.app, manually open the exact target ordinary group. Do not type a message and do not press Send/Return in the message composer.

Then capture a second private AX payload:

```bash
peekaboo inspect-ui --app WeChat --json \
  > /private/tmp/guiyi-wechat-poc/wechat-target-open.json
```

- [ ] **Step 5: Produce a privacy-safe structural summary**

Run this locally with the real group name supplied only through the shell environment:

```bash
WECHAT_GROUP_NAME='REAL_GROUP_NAME_HERE' python3 - <<'PY'
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

The printed summary must not contain the group name, contact names, messages, raw labels, or raw node contents.

- [ ] **Step 6: Manually open WeChat search, type the exact group name, but do not open/send**

Use normal WeChat UI manually to place the exact group name into search. This step is intentionally manual so P0 does not yet guess a search-control selector.

Capture:

```bash
peekaboo inspect-ui --app WeChat --json \
  > /private/tmp/guiyi-wechat-poc/wechat-search.json
```

Run the same recursive summary logic against `wechat-search.json` and record only:

```text
exact_target_nodes=<count>
text_input_nodes=<count>
role_counts=<counts only>
```

- [ ] **Step 7: Apply the PoC gate**

P0 passes only if all are true:

```text
Peekaboo version is >=3.9.8,<4.0.0
inspect-ui succeeds against WeChat.app
raw AX JSON is parseable
opening the target group exposes at least one exact target-title occurrence
opening the target group exposes at least one text-field/text-area candidate
searching the exact group exposes deterministic AX evidence for the target title
no message was sent
```

If any structural requirement fails, STOP. Do not add coordinate automation, OCR, image matching, or blind Return presses.

- [ ] **Step 8: Delete private raw inspection data**

After the non-private summary is captured:

```bash
rm -rf /private/tmp/guiyi-wechat-poc
```

Confirm the directory no longer exists.

---

### Task 3: Close the design review with evidence and prepare the production implementation handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-08-15-wechat-group-notification-design.md`
- Modify only if project-state facts materially changed: `STATUS.md`

**Interfaces:**
- Consumes: P0 pass/fail summary from Task 2.
- Produces: an amended, evidence-backed design spec that the later production implementation plan can rely on.

- [ ] **Step 1: Add the sender-interface review correction to the spec**

Clarify that production integration must change `AlertRuntime` from a concrete `WeComWebhookSender` constructor type to an `AlertSender` Protocol with the single contract:

```python
class AlertSender(Protocol):
    def send(self, event: AlertNotificationMessage) -> None: ...
```

`WeComWebhookSender` and the future `CompositeAlertSender` both satisfy that interface. This change is type/boundary cleanup only; it must not change Alert evaluation or Event semantics.

- [ ] **Step 2: Add the Peekaboo compatibility contract to the spec**

Record exactly:

```text
Supported Peekaboo: >=3.9.8,<4.0.0
Outside range: fail closed
Reason: v3.9.8 is the validated stable CLI contract; 4.0 changes interaction command surface/semantics and requires a separate compatibility review.
```

Also record that stable 3.9.8 provides `inspect-ui --app`, `set-value`, `perform-action`, and targeted background typing; these are the only interaction primitives eligible for the first production implementation unless the PoC proves a smaller subset is sufficient.

- [ ] **Step 3: Record only non-private P0 observations**

Add a short section such as:

```text
Mac mini / current WeChat PoC:
- Peekaboo version: <observed supported version>
- WeChat inspect-ui: PASS/FAIL
- exact target title exposed in AX: yes/no
- text input role exposed in AX: yes/no
- exact search result exposed in AX: yes/no
- real message sent: no
```

Do not record the real group name, contact names, chat content, raw UI tree, screenshots, or element values.

- [ ] **Step 4: Run documentation/repository checks**

Run:

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: no secret finding from this task; only intended spec/status changes remain.

- [ ] **Step 5: Commit the reviewed spec amendment**

```bash
git add docs/superpowers/specs/2026-08-15-wechat-group-notification-design.md
# Add STATUS.md only if it was legitimately updated with a durable project fact.
git commit -m "docs(alert): record WeChat Peekaboo PoC contract"
```

- [ ] **Step 6: Stop before production sender wiring**

Do **not** implement `WeChatGroupSender`, `CompositeAlertSender`, Runtime composition wiring, canary sending, or persistent automatic group notification in this P0 plan.

After a passing P0, write a new production implementation plan using the observed AX structure. That follow-up plan must cover TDD for exact target resolution, title re-verification, message-input targeting, background-first/focus-fallback behavior, channel failure isolation, and the separate real-notification Gate.
