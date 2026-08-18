"""Hardened exact-target seam for pinned WeChat-Courier.

This is the only module allowed to import the upstream GUI automation module.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import TextIO
import unicodedata


_REQUIRED_EXPORTS = (
    "activate_wechat",
    "get_wechat_window_rect",
    "get_wechat_window_name",
    "ocr_boxes",
    "search_result_row_click_point",
    "click_point",
    "ocr_image",
    "paste_and_send_text",
)
_SAFETY_REJECT_TERMS = (
    "AI搜索",
    "搜索网络结果",
    "全部",
    "文章",
    "视频",
    "相关搜索",
)
UpstreamValidator = Callable[[Path, str], None]
TempValidator = Callable[[], None]
PointBox = tuple[int, int, int, int]
CaptureRect = Callable[[str, PointBox], Path]


class AdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_pinned_temp_directory() -> None:
    try:
        descriptor_text = os.environ["GUIYI_WECHAT_COURIER_TMP_FD"]
        temp_text = os.environ["TMPDIR"]
        if re.fullmatch(r"[1-9][0-9]*", descriptor_text) is None:
            raise ValueError
        descriptor = int(descriptor_text)
        if descriptor < 3:
            raise ValueError
        temp_root = Path(temp_text)
        if not temp_root.is_absolute():
            raise ValueError
        held = os.fstat(descriptor)
        current = os.stat(temp_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(held.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or stat.S_IMODE(held.st_mode) != 0o700
            or held.st_uid != os.getuid()
            or held.st_dev != current.st_dev
            or held.st_ino != current.st_ino
        ):
            raise ValueError
    except (KeyError, OSError, ValueError):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID") from None


def normalize_chat_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return "".join(character for character in normalized if not character.isspace())


def title_matches_exact_target(ocr_line: str, target: str) -> bool:
    normalized_line = normalize_chat_name(ocr_line)
    normalized_target = normalize_chat_name(target)
    if not normalized_line or not normalized_target:
        return False
    return re.fullmatch(
        rf"{re.escape(normalized_target)}(?:\([1-9][0-9]*\))?",
        normalized_line,
    ) is not None


def select_unique_search_box(box_texts: Sequence[str], target: str) -> int:
    normalized_target = normalize_chat_name(target)
    matches = [
        index
        for index, text in enumerate(box_texts)
        if normalized_target and normalize_chat_name(text) == normalized_target
    ]
    if len(matches) != 1:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
    return matches[0]


def _validate_ocr_box(box: object) -> dict[str, object]:
    if not isinstance(box, dict) or set(box) != {
        "text",
        "min_x",
        "min_y",
        "width",
        "height",
    }:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
    if not isinstance(box["text"], str):
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
    geometry: list[float] = []
    for key in ("min_x", "min_y", "width", "height"):
        value = box[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        geometry.append(numeric)
    min_x, min_y, width, height = geometry
    if (
        not 0.0 <= min_x <= 1.0
        or not 0.0 <= min_y <= 1.0
        or not 0.0 < width <= 1.0
        or not 0.0 < height <= 1.0
        or min_x + width > 1.0
        or min_y + height > 1.0
    ):
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
    return box


def _load_upstream(upstream_root: Path) -> ModuleType:
    try:
        if not upstream_root.is_absolute():
            raise ValueError
        resolved_root = upstream_root.resolve(strict=True)
        module_path = (resolved_root / "wechat_courier.py").resolve(strict=True)
        module_path.relative_to(resolved_root)
        if not module_path.is_file():
            raise ValueError
        spec = importlib.util.spec_from_file_location(
            "guiyi_pinned_wechat_courier",
            module_path,
        )
        if spec is None or spec.loader is None:
            raise ValueError
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if any(not callable(getattr(module, name, None)) for name in _REQUIRED_EXPORTS):
            raise ValueError
        return module
    except Exception:
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID") from None


def _validate_upstream_identity(upstream_root: Path, expected_commit: str) -> None:
    commands = (
        ["/usr/bin/git", "-C", str(upstream_root), "rev-parse", "HEAD"],
        ["/usr/bin/git", "-C", str(upstream_root), "status", "--porcelain"],
    )
    try:
        results = [
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=10.0,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
            for command in commands
        ]
    except (OSError, subprocess.SubprocessError):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
    if (
        any(result.returncode != 0 for result in results)
        or results[0].stdout.strip() != expected_commit
        or results[1].stdout.strip()
    ):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID")


def _run_private_command(
    argv: list[str],
    *,
    input_text: str | None = None,
) -> None:
    try:
        result = subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError):
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
    if result.returncode != 0:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")


def _capture_screen_rect(
    prefix: str,
    point_box: PointBox,
    *,
    temp_root: Path | None = None,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Capture an exact screen rect without upstream Finder desktop-size lookup."""
    screenshot: Path | None = None
    try:
        if re.fullmatch(r"[a-z0-9-]+", prefix) is None:
            raise ValueError
        if len(point_box) != 4 or any(type(value) is not int for value in point_box):
            raise ValueError
        left, top, right, bottom = point_box
        width = right - left
        height = bottom - top
        if (
            not -32_768 <= left <= 32_768
            or not -32_768 <= top <= 32_768
            or not 1 <= width <= 16_384
            or not 1 <= height <= 16_384
        ):
            raise ValueError
        root = (temp_root or Path(tempfile.gettempdir())).resolve(strict=True)
        metadata = root.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
        ):
            raise ValueError
        screenshot = root / f"guiyi-wechat-courier-{prefix}-{time.time_ns()}.png"
        if screenshot.exists() or screenshot.is_symlink():
            raise ValueError
        result = run_process(
            [
                "/usr/sbin/screencapture",
                "-x",
                f"-R{left},{top},{width},{height}",
                str(screenshot),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10.0,
        )
        if result.returncode != 0:
            raise ValueError
        screenshot_metadata = screenshot.lstat()
        if (
            not stat.S_ISREG(screenshot_metadata.st_mode)
            or screenshot_metadata.st_size == 0
            or screenshot.is_symlink()
        ):
            raise ValueError
        screenshot.chmod(0o600)
        return screenshot
    except (OSError, subprocess.SubprocessError, ValueError):
        if screenshot is not None:
            try:
                screenshot.unlink(missing_ok=True)
            except OSError:
                pass
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None


def _open_search_ui(_upstream: ModuleType, target: str) -> None:
    _run_private_command(["/usr/bin/pbcopy"], input_text=target)
    _run_private_command(
        [
            "/usr/bin/osascript",
            "-e",
            """
tell application "System Events"
  key code 53
  delay 0.2
  key code 53
  delay 0.2
  keystroke "f" using command down
  delay 0.3
  keystroke "a" using command down
  delay 0.1
  keystroke "v" using command down
  delay 1.0
end tell
""",
        ]
    )


def _unlink_screenshot(path: object) -> bool:
    try:
        Path(path).unlink(missing_ok=True)  # type: ignore[arg-type]
        return True
    except (OSError, TypeError, ValueError):
        return False


def _window_rect(upstream: ModuleType) -> tuple[int, int, int, int]:
    try:
        value = upstream.get_wechat_window_rect()
        if (
            not isinstance(value, tuple)
            or len(value) != 4
            or any(type(item) is not int for item in value)
        ):
            raise ValueError
        x, y, width, height = value
        if width <= 300 or height <= 300:
            raise ValueError
        return x, y, width, height
    except Exception:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None


def _search_screenshot(
    upstream: ModuleType,
    capture_rect: CaptureRect,
) -> tuple[Path, PointBox]:
    x, y, width, height = _window_rect(upstream)
    right = x + int(min(max(390, width * 0.34), 540))
    bottom = y + min(height, 620)
    point_box = (x, y + 78, right, bottom)
    return capture_rect("search", point_box), point_box


def _region_screenshot(
    upstream: ModuleType,
    capture_rect: CaptureRect,
    region: str,
    attempt: int,
) -> Path:
    x, y, width, _height = _window_rect(upstream)
    if region == "safety":
        point_box = (x, y + 35, x + width, y + 240)
    elif region == "title":
        try:
            window_name = upstream.get_wechat_window_name()
        except Exception:
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
        if not isinstance(window_name, str):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        is_main_window = window_name in {"微信", "WeChat"}
        left = x if width < 850 and not is_main_window else x + max(280, int(width * 0.35))
        point_box = (left, y, x + width - 20, y + 95)
    else:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
    return capture_rect(f"{region}-{attempt}", point_box)


def _validate_search_result(
    upstream: ModuleType,
    target: str,
    capture_rect: CaptureRect,
) -> None:
    screenshot: object | None = None
    try:
        screenshot, point_box = _search_screenshot(upstream, capture_rect)
        boxes = upstream.ocr_boxes(screenshot)
        if not isinstance(boxes, list):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        texts: list[str] = []
        for box in boxes:
            texts.append(str(_validate_ocr_box(box)["text"]))
        selected = _validate_ocr_box(boxes[select_unique_search_box(texts, target)])
        point = upstream.search_result_row_click_point(selected, point_box)
        if (
            not isinstance(point, tuple)
            or len(point) != 2
            or any(type(value) is not int for value in point)
        ):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        left, top, right, bottom = point_box
        if not left <= point[0] < right or not top <= point[1] < bottom:
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        upstream.click_point(point[0], point[1])
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
    finally:
        if screenshot is not None and not _unlink_screenshot(screenshot):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")


def _safety_text_is_clean(value: str) -> bool:
    normalized = normalize_chat_name(value)
    return not any(normalize_chat_name(term) in normalized for term in _SAFETY_REJECT_TERMS)


def _validate_title_attempt(
    upstream: ModuleType,
    target: str,
    attempt: int,
    capture_rect: CaptureRect,
) -> None:
    screenshots: list[object] = []
    try:
        safety = _region_screenshot(upstream, capture_rect, "safety", attempt)
        screenshots.append(safety)
        title = _region_screenshot(upstream, capture_rect, "title", attempt)
        screenshots.append(title)
        safety_text = upstream.ocr_image(safety)
        title_text = upstream.ocr_image(title)
        if not isinstance(safety_text, str) or not isinstance(title_text, str):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        title_lines = [line.strip() for line in title_text.splitlines() if line.strip()]
        if (
            not _safety_text_is_clean(safety_text)
            or len(title_lines) != 1
            or not title_matches_exact_target(title_lines[0], target)
        ):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
    finally:
        cleanup_failed = False
        for screenshot in screenshots:
            cleanup_failed = not _unlink_screenshot(screenshot) or cleanup_failed
        if cleanup_failed:
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")


def _verify_target(
    upstream: ModuleType,
    target: str,
    *,
    open_search_ui: Callable[[ModuleType, str], None],
    capture_rect: CaptureRect,
    sleep: Callable[[float], None],
) -> None:
    try:
        upstream.activate_wechat()
        open_search_ui(upstream, target)
        _validate_search_result(upstream, target, capture_rect)
        sleep(1.0)
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
    for attempt in range(1, 4):
        try:
            _validate_title_attempt(upstream, target, attempt, capture_rect)
            return
        except AdapterError:
            if attempt < 3:
                sleep(0.6)
    raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")


def _valid_private_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and not any(unicodedata.category(character).startswith("C") for character in value)
    )


def _valid_message_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 65_536
        and all(
            character == "\n"
            or not unicodedata.category(character).startswith("C")
            for character in value
        )
    )


def execute_adapter_action(
    payload: object,
    *,
    open_search_ui: Callable[[ModuleType, str], None] = _open_search_ui,
    capture_rect: CaptureRect = _capture_screen_rect,
    sleep: Callable[[float], None] = time.sleep,
    validate_upstream: UpstreamValidator = _validate_upstream_identity,
    validate_temp_directory: TempValidator = _validate_pinned_temp_directory,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID")
    action = payload.get("action")
    expected_keys = (
        {"action", "target_chat", "upstream_root", "upstream_commit"}
        if action == "verify"
        else {"action", "target_chat", "text", "upstream_root", "upstream_commit"}
    )
    if (
        action not in {"verify", "send"}
        or set(payload) != expected_keys
        or not _valid_private_text(payload.get("target_chat"))
        or not isinstance(payload.get("upstream_root"), str)
        or not isinstance(payload.get("upstream_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", payload["upstream_commit"]) is None
        or (action == "send" and not _valid_message_text(payload.get("text")))
    ):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID")
    private_output = io.StringIO()
    with redirect_stdout(private_output), redirect_stderr(private_output):
        validate_temp_directory()
        upstream_root = Path(payload["upstream_root"])
        validate_upstream(upstream_root, payload["upstream_commit"])
        upstream = _load_upstream(upstream_root)
        validate_upstream(upstream_root, payload["upstream_commit"])
        _verify_target(
            upstream,
            payload["target_chat"],
            open_search_ui=open_search_ui,
            capture_rect=capture_rect,
            sleep=sleep,
        )
        if action == "send":
            validate_temp_directory()
            validate_upstream(upstream_root, payload["upstream_commit"])
            try:
                upstream.paste_and_send_text(payload["text"])
            except Exception:
                raise AdapterError("WECHAT_COURIER_SEND_FAILED") from None
            return {"status": "sent"}
    return {"status": "verified"}


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        raw = stdin.read(65_537)
        if len(raw) > 65_536:
            raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID")
        payload = json.loads(raw)
        result = execute_adapter_action(payload)
    except AdapterError as exc:
        print(
            json.dumps({"status": "failed", "error_code": exc.code}, separators=(",", ":")),
            file=stdout,
        )
        return 1
    except Exception:
        print(
            '{"status":"failed","error_code":"WECHAT_COURIER_DEPENDENCY_INVALID"}',
            file=stdout,
        )
        return 1
    print(json.dumps(result, separators=(",", ":")), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
