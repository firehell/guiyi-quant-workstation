from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import subprocess

import pytest

import app.alerts.wechat_courier_adapter as adapter
from app.alerts.wechat_courier_adapter import (
    _capture_screen_rect,
    _prepare_home_chat_list,
    _validate_ocr_box,
    _validate_pinned_temp_directory,
    AdapterError,
    execute_adapter_action,
    normalize_chat_name,
    select_unique_chat_list_box,
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


def test_select_unique_chat_list_box_requires_exactly_one_normalized_match() -> None:
    assert select_unique_chat_list_box(["near-fixture-group-title", TARGET], TARGET) == 1

    for boxes in ([], [f"{TARGET}-near"], [TARGET, TARGET]):
        with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
            select_unique_chat_list_box(boxes, TARGET)


def _fake_upstream(
    source_root: Path,
    *,
    missing: str | None = None,
    boxes: list[str] | None = None,
    title: str = TARGET,
    safety: str = "clean-chat",
    send_failure: bool = False,
    geometry: tuple[float, float, float, float] = (0.1, 0.2, 0.3, 0.1),
    click_point: tuple[int, int] = (250, 384),
) -> Path:
    source_root.mkdir(parents=True)
    module_path = source_root / "wechat_courier.py"
    functions = {
        "activate_wechat": "def activate_wechat():\n    record('activate_wechat')\n",
        "get_wechat_window_rect": (
            "def get_wechat_window_rect():\n"
            "    record('get_wechat_window_rect')\n"
            "    return (100, 200, 1000, 800)\n"
        ),
        "get_wechat_window_name": (
            "def get_wechat_window_name():\n"
            "    record('get_wechat_window_name')\n"
            "    return '微信'\n"
        ),
        "ocr_boxes": (
            "def ocr_boxes(path):\n"
            "    record('ocr_boxes')\n"
            "    print(PRIVATE_RAW)\n"
            "    return [dict(item) for item in CHAT_BOXES]\n"
        ),
        "box_center_screen_point": (
            "def box_center_screen_point(box, point_box):\n"
            "    record('box_center_screen_point')\n"
            f"    return {click_point!r}\n"
        ),
        "click_point": "def click_point(x, y):\n    record('click_point')\n",
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
        f"CHAT_BOXES = {json.dumps([{'text': text, 'min_x': geometry[0], 'min_y': geometry[1], 'width': geometry[2], 'height': geometry[3]} for text in (boxes if boxes is not None else [TARGET])])}\n"
        f"SAFETY_TEXT = {safety!r}\n"
        f"TITLE_TEXT = {title!r}\n"
        "def record(name):\n"
        "    with LOG.open('a', encoding='utf-8') as handle: handle.write(name + '\\n')\n"
        + "\n".join(functions.values())
    )
    module_path.write_text(source, encoding="utf-8")
    return module_path


def _fixture_capture(
    source_root: Path,
    *,
    cleanup_failure: bool = False,
    observed: list[tuple[str, tuple[int, int, int, int]]] | None = None,
) -> Callable[[str, tuple[int, int, int, int]], Path]:
    count = 0

    def capture(prefix: str, box: tuple[int, int, int, int]) -> Path:
        nonlocal count
        count += 1
        if observed is not None:
            observed.append((prefix, box))
        path = source_root / f"{prefix}-{count}.png"
        if cleanup_failure and prefix == "home-list":
            path.mkdir()
        else:
            path.write_bytes(b"fixture")
        return path

    return capture


def test_screen_rect_capture_uses_fixed_bounded_argv_and_private_file(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def run_process(argv: list[str], **_kwargs: object):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"fixture")
        return subprocess.CompletedProcess(argv, 0, "", "")

    screenshot = _capture_screen_rect(
        "home-list",
        (100, 278, 490, 820),
        temp_root=tmp_path,
        run_process=run_process,
    )

    assert calls == [
        [
            "/usr/sbin/screencapture",
            "-x",
            "-R100,278,390,542",
            str(screenshot),
        ]
    ]
    assert screenshot.stat().st_mode & 0o777 == 0o600


def test_screen_rect_capture_timeout_removes_partial_private_file(tmp_path: Path) -> None:
    def run_process(argv: list[str], **_kwargs: object):
        Path(argv[-1]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(argv, 10.0)

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        _capture_screen_rect(
            "home-list",
            (100, 278, 490, 820),
            temp_root=tmp_path,
            run_process=run_process,
        )

    assert list(tmp_path.glob("*.png")) == []


def test_prepare_home_chat_list_only_exits_search_and_does_not_type_or_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def run_private_command(
        argv: list[str],
        *,
        input_text: str | None = None,
    ) -> None:
        calls.append((argv, input_text))

    monkeypatch.setattr(adapter, "_run_private_command", run_private_command)

    _prepare_home_chat_list(object())  # type: ignore[arg-type]

    assert len(calls) == 1
    argv, input_text = calls[0]
    assert argv[:2] == ["/usr/bin/osascript", "-e"]
    assert input_text is None
    script = argv[2]
    assert script.count("key code 53") == 2
    assert "keystroke" not in script
    assert "scroll" not in script.lower()
    assert "/usr/bin/pbcopy" not in argv


def test_pinned_temp_directory_rejects_path_identity_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned = tmp_path / "pinned"
    pinned.mkdir(mode=0o700)
    descriptor = os.open(pinned, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    monkeypatch.setenv("TMPDIR", str(pinned))
    monkeypatch.setenv("GUIYI_WECHAT_COURIER_TMP_FD", str(descriptor))
    class Python39Path:
        def __init__(self, value: str) -> None:
            self._path = Path(value)

        def is_absolute(self) -> bool:
            return self._path.is_absolute()

        def stat(self, **kwargs: object):
            if "follow_symlinks" in kwargs:
                raise TypeError("Python 3.9 Path.stat has no follow_symlinks")
            return self._path.stat()

        def __fspath__(self) -> str:
            return str(self._path)

    monkeypatch.setattr(adapter, "Path", Python39Path)
    try:
        _validate_pinned_temp_directory()
        held = tmp_path / "held"
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        pinned.rename(held)
        pinned.symlink_to(outside, target_is_directory=True)
        with pytest.raises(AdapterError, match="^WECHAT_COURIER_DEPENDENCY_INVALID$"):
            _validate_pinned_temp_directory()
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "geometry_value",
    (float("nan"), float("inf"), -0.1, 1.1),
)
def test_ocr_box_rejects_nonfinite_or_out_of_range_geometry(
    geometry_value: float,
) -> None:
    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        _validate_ocr_box(
            {
                "text": TARGET,
                "min_x": geometry_value,
                "min_y": 0.2,
                "width": 0.3,
                "height": 0.1,
            }
        )


def test_verify_selects_unique_target_from_visible_pinned_home_chats_without_search(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(
        source_root,
        boxes=["first-pinned-chat", TARGET, "another-pinned-chat"],
        click_point=(250, 384),
    )
    prepared: list[str] = []
    validations: list[tuple[Path, str]] = []
    captures: list[tuple[str, tuple[int, int, int, int]]] = []

    result = execute_adapter_action(
        {
            "action": "verify",
            "target_chat": TARGET,
            "upstream_root": str(source_root),
            "upstream_commit": PINNED_COMMIT,
        },
        prepare_home_chat_list=lambda _upstream: prepared.append("home"),
        capture_rect=_fixture_capture(source_root, observed=captures),
        sleep=lambda _seconds: None,
        validate_upstream=lambda root, commit: validations.append((root, commit)),
        validate_temp_directory=lambda: None,
    )

    assert result == {"status": "verified"}
    assert prepared == ["home"]
    assert validations == [(source_root, PINNED_COMMIT), (source_root, PINNED_COMMIT)]
    assert captures == [
        ("home-list", (160, 278, 450, 1000)),
        ("safety-1", (100, 235, 1100, 440)),
        ("title-1", (450, 200, 1080, 295)),
    ]
    assert capsys.readouterr() == ("", "")
    assert list(source_root.glob("*.png")) == []
    assert (source_root / "calls.log").read_text(encoding="utf-8").splitlines() == [
        "activate_wechat",
        "get_wechat_window_rect",
        "ocr_boxes",
        "box_center_screen_point",
        "click_point",
        "get_wechat_window_rect",
        "get_wechat_window_rect",
        "get_wechat_window_name",
        "ocr_image",
        "ocr_image",
    ]


@pytest.mark.parametrize(
    "boxes",
    ([], [f"{TARGET}-near"], [TARGET[:8], TARGET[8:]], [TARGET, TARGET]),
)
def test_home_chat_list_miss_near_match_or_ambiguity_fails_before_click(
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
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
        )
    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert "click_point" not in calls
    assert "paste_and_send_text" not in calls


@pytest.mark.parametrize(
    ("geometry", "click_point"),
    (
        ((0.8, 0.2, 0.3, 0.1), (142, 384)),
        ((0.1, 0.2, 0.3, 0.1), (99, 384)),
    ),
)
def test_invalid_ocr_geometry_or_out_of_bounds_point_fails_before_click(
    tmp_path: Path,
    geometry: tuple[float, float, float, float],
    click_point: tuple[int, int],
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, geometry=geometry, click_point=click_point)

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "verify",
                "target_chat": TARGET,
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
        )

    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert "click_point" not in calls
    assert "paste_and_send_text" not in calls


def test_title_failure_retries_only_read_only_ocr_three_times_and_cleans(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root, title=f"{TARGET}-near")
    captures: list[tuple[str, tuple[int, int, int, int]]] = []

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "verify",
                "target_chat": TARGET,
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root, observed=captures),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
        )

    assert list(source_root.glob("*.png")) == []
    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert [prefix for prefix, _box in captures].count("title-1") == 1
    assert [prefix for prefix, _box in captures].count("title-2") == 1
    assert [prefix for prefix, _box in captures].count("title-3") == 1
    assert calls.count("get_wechat_window_name") == 3
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
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
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
        prepare_home_chat_list=lambda _upstream: None,
        capture_rect=_fixture_capture(source_root),
        sleep=lambda _seconds: None,
        validate_upstream=_accept_fixture_upstream,
        validate_temp_directory=lambda: None,
    )

    assert result == {"status": "sent"}
    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls.count("paste_and_send_text") == 1
    assert calls[-1] == "paste_and_send_text"


def test_send_temp_path_swap_fails_before_physical_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root)
    pinned = tmp_path / "pinned"
    pinned.mkdir(mode=0o700)
    descriptor = os.open(pinned, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    monkeypatch.setenv("TMPDIR", str(pinned))
    monkeypatch.setenv("GUIYI_WECHAT_COURIER_TMP_FD", str(descriptor))

    def swap_temp_path(_upstream: object) -> None:
        held = tmp_path / "held"
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        pinned.rename(held)
        pinned.symlink_to(outside, target_is_directory=True)

    try:
        with pytest.raises(AdapterError, match="^WECHAT_COURIER_DEPENDENCY_INVALID$"):
            execute_adapter_action(
                {
                    "action": "send",
                    "target_chat": TARGET,
                    "text": "fixture-alert",
                    "upstream_root": str(source_root),
                    "upstream_commit": PINNED_COMMIT,
                },
                prepare_home_chat_list=swap_temp_path,
                capture_rect=_fixture_capture(source_root),
                sleep=lambda _seconds: None,
                validate_upstream=_accept_fixture_upstream,
            )
    finally:
        os.close(descriptor)

    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert "paste_and_send_text" not in calls


@pytest.mark.parametrize(
    "boxes",
    ([], [f"{TARGET}-near"], [TARGET[:8], TARGET[8:]], [TARGET, TARGET]),
)
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
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
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
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
        )

    calls = (source_root / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls.count("paste_and_send_text") == 1


def test_screenshot_cleanup_failure_aborts_before_send(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _fake_upstream(source_root)

    with pytest.raises(AdapterError, match="^WECHAT_GROUP_TARGET_UNVERIFIED$"):
        execute_adapter_action(
            {
                "action": "send",
                "target_chat": TARGET,
                "text": "fixture-alert",
                "upstream_root": str(source_root),
                "upstream_commit": PINNED_COMMIT,
            },
            prepare_home_chat_list=lambda _upstream: None,
            capture_rect=_fixture_capture(source_root, cleanup_failure=True),
            sleep=lambda _seconds: None,
            validate_upstream=_accept_fixture_upstream,
            validate_temp_directory=lambda: None,
        )

    calls = (source_root / "calls.log").read_text(encoding="utf-8")
    assert "paste_and_send_text" not in calls
