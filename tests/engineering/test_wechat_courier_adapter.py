from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.alerts.wechat_courier_adapter import (
    AdapterError,
    execute_adapter_action,
    normalize_chat_name,
    select_unique_search_box,
    title_matches_exact_target,
)


TARGET = "fixture-group-title"
PINNED_COMMIT = "981bd14e238302b2a0e206cb5f28e8e2505bb874"


def _accept_fixture_upstream(_root: Path, _commit: str) -> None:
    return None


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("归一量化", "归一量化"),
        (" 归一  量化 ", "归一量化"),
        ("ＡＢＣ Group", "ABCGroup"),
    ),
)
def test_normalize_chat_name_removes_only_spacing_after_nfkc(
    value: str,
    expected: str,
) -> None:
    assert normalize_chat_name(value) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    (
        ("归一量化", True),
        ("归一 量化", True),
        ("归一量化(4)", True),
        ("归一量化（4）", True),
        ("归一量化(0)", False),
        ("归一量化测试", False),
        ("测试归一量化", False),
        ("归一量化测试（4）", False),
    ),
)
def test_title_match_accepts_only_exact_target_and_positive_member_suffix(
    title: str,
    expected: bool,
) -> None:
    assert title_matches_exact_target(title, "归一量化") is expected


def test_select_unique_search_box_requires_exactly_one_normalized_match() -> None:
    assert select_unique_search_box(["near-fixture-group-title", TARGET], TARGET) == 1

    for boxes in ([], [f"{TARGET}-near"], [TARGET, TARGET]):
        with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
            select_unique_search_box(boxes, TARGET)


def _fake_upstream(
    source_root: Path,
    *,
    missing: str | None = None,
    boxes: list[str] | None = None,
    title: str = TARGET,
    safety: str = "clean-chat",
    send_failure: bool = False,
    cleanup_failure: bool = False,
) -> Path:
    source_root.mkdir(parents=True)
    module_path = source_root / "wechat_courier.py"
    functions = {
        "activate_wechat": "def activate_wechat():\n    record('activate_wechat')\n",
        "make_search_results_screenshot": (
            "def make_search_results_screenshot(prefix):\n"
            "    record('make_search_results_screenshot')\n"
            "    path = make_shot('search')\n"
            "    return path, (0.0, 0.0, 100.0, 100.0)\n"
        ),
        "ocr_boxes": (
            "def ocr_boxes(path):\n"
            "    record('ocr_boxes')\n"
            "    print(PRIVATE_RAW)\n"
            "    return [dict(item) for item in SEARCH_BOXES]\n"
        ),
        "search_result_row_click_point": (
            "def search_result_row_click_point(box, point_box):\n"
            "    record('search_result_row_click_point')\n"
            "    return (42, 84)\n"
        ),
        "click_point": "def click_point(x, y):\n    record('click_point')\n",
        "make_safety_screenshot": (
            "def make_safety_screenshot(prefix):\n"
            "    record('make_safety_screenshot')\n"
            "    return make_shot('safety')\n"
        ),
        "make_title_screenshot": (
            "def make_title_screenshot(prefix):\n"
            "    record('make_title_screenshot')\n"
            "    return make_shot('title')\n"
        ),
        "ocr_image": (
            "def ocr_image(path):\n"
            "    record('ocr_image')\n"
            "    print(PRIVATE_RAW)\n"
            "    return SAFETY_TEXT if 'safety' in path.name else TITLE_TEXT\n"
        ),
        "paste_and_send_text": (
            "def paste_and_send_text(text):\n"
            "    record('paste_and_send_text')\n"
            + ("    raise RuntimeError('private send failure')\n" if send_failure else "")
        ),
    }
    if missing is not None:
        functions.pop(missing)
    source = (
        "from pathlib import Path\n"
        f"ROOT = Path({str(source_root)!r})\n"
        "LOG = ROOT / 'calls.log'\n"
        f"PRIVATE_RAW = {TARGET!r}\n"
        f"SEARCH_BOXES = {json.dumps([{'text': text, 'min_x': 0.1, 'min_y': 0.2, 'width': 0.3, 'height': 0.1} for text in (boxes if boxes is not None else [TARGET])])}\n"
        f"SAFETY_TEXT = {safety!r}\n"
        f"TITLE_TEXT = {title!r}\n"
        f"CLEANUP_FAILURE = {cleanup_failure!r}\n"
        "SHOT_COUNT = 0\n"
        "def record(name):\n"
        "    with LOG.open('a', encoding='utf-8') as handle: handle.write(name + '\\n')\n"
        "def make_shot(name):\n"
        "    global SHOT_COUNT\n"
        "    SHOT_COUNT += 1\n"
        "    path = ROOT / f'{name}-{SHOT_COUNT}.png'\n"
        "    if CLEANUP_FAILURE and name == 'search': path.mkdir()\n"
        "    else: path.write_bytes(b'fixture')\n"
        "    return path\n"
        + "\n".join(functions.values())
    )
    module_path.write_text(source, encoding="utf-8")
    return module_path


def test_verify_uses_exact_private_seam_cleans_screenshots_and_never_sends(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root)
    opened: list[str] = []
    validations: list[tuple[Path, str]] = []

    result = execute_adapter_action(
        {
            "action": "verify",
            "target_chat": TARGET,
            "upstream_root": str(source_root),
            "upstream_commit": PINNED_COMMIT,
        },
        open_search_ui=lambda _upstream, target: opened.append(target),
        sleep=lambda _seconds: None,
        validate_upstream=lambda root, commit: validations.append((root, commit)),
    )

    assert result == {"status": "verified"}
    assert opened == [TARGET]
    assert validations == [(source_root, PINNED_COMMIT), (source_root, PINNED_COMMIT)]
    assert capsys.readouterr() == ("", "")
    assert list(source_root.glob("*.png")) == []
    assert (source_root / "calls.log").read_text(encoding="utf-8").splitlines() == [
        "activate_wechat",
        "make_search_results_screenshot",
        "ocr_boxes",
        "search_result_row_click_point",
        "click_point",
        "make_safety_screenshot",
        "make_title_screenshot",
        "ocr_image",
        "ocr_image",
    ]


@pytest.mark.parametrize("boxes", ([], [f"{TARGET}-near"], [TARGET, TARGET]))
def test_search_miss_near_match_or_ambiguity_fails_before_click(
    tmp_path: Path,
    boxes: list[str],
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, boxes=boxes)

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "verify",
                "target_chat": TARGET,
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            open_search_ui=lambda _upstream, _target: None,
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
        )
    calls = (source_root / "calls.log").read_text(encoding="utf-8")
    assert "click_point" not in calls
    assert "paste_and_send_text" not in calls


def test_title_failure_retries_only_read_only_ocr_three_times_and_cleans(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, title=f"{TARGET}-near")

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "verify",
                "target_chat": TARGET,
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            open_search_ui=lambda _upstream, _target: None,
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
        )

    assert list(source_root.glob("*.png")) == []
    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls.count("make_title_screenshot") == 3
    assert "paste_and_send_text" not in calls


def test_missing_exact_upstream_export_fails_dependency_closed(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, missing="ocr_boxes")

    with pytest.raises(AdapterError, match="^WECHAT_COURIER_DEPENDENCY_INVALID$"):
        execute_adapter_action(
            {
                "action": "verify",
                "target_chat": TARGET,
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            open_search_ui=lambda _upstream, _target: None,
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
        )


def test_send_verifies_then_calls_physical_send_exactly_once(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root)

    result = execute_adapter_action(
        {
            "action": "send",
            "target_chat": TARGET,
            "text": "fixture-alert",
            "upstream_root": str(source_root),
            "upstream_commit": PINNED_COMMIT,
        },
        open_search_ui=lambda _upstream, _target: None,
        sleep=lambda _seconds: None,
        validate_upstream=_accept_fixture_upstream,
    )

    assert result == {"status": "sent"}
    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls.count("paste_and_send_text") == 1
    assert calls[-1] == "paste_and_send_text"


@pytest.mark.parametrize("boxes", ([], [f"{TARGET}-near"], [TARGET, TARGET]))
def test_send_target_verification_failure_calls_no_send(
    tmp_path: Path,
    boxes: list[str],
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, boxes=boxes)

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "send",
                "target_chat": TARGET,
                "text": "fixture-alert",
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            open_search_ui=lambda _upstream, _target: None,
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
        )

    calls = (source_root / "calls.log").read_text(encoding="utf-8")
    assert "paste_and_send_text" not in calls


def test_send_primitive_failure_is_not_retried(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, send_failure=True)

    with pytest.raises(AdapterError, match="^WECHAT_COURIER_SEND_FAILED$"):
        execute_adapter_action(
            {
                "action": "send",
                "target_chat": TARGET,
                "text": "fixture-alert",
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            open_search_ui=lambda _upstream, _target: None,
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
        )

    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls.count("paste_and_send_text") == 1


def test_screenshot_cleanup_failure_aborts_before_send(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, cleanup_failure=True)

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "send",
                "target_chat": TARGET,
                "text": "fixture-alert",
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            open_search_ui=lambda _upstream, _target: None,
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
        )

    calls = (source_root / "calls.log").read_text(encoding="utf-8")
    assert "paste_and_send_text" not in calls
