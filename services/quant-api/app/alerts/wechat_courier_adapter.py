"""Hardened exact-target seam for pinned WeChat-Courier.

This is the only module allowed to import the upstream GUI automation module.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from types import ModuleType
from typing import TextIO
import unicodedata


_REQUIRED_EXPORTS = (
    "activate_wechat",
    "make_search_results_screenshot",
    "ocr_boxes",
    "search_result_row_click_point",
    "click_point",
    "make_safety_screenshot",
    "make_title_screenshot",
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


class AdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


def _safe_unlink(path: object) -> None:
    try:
        Path(path).unlink(missing_ok=True)  # type: ignore[arg-type]
    except (OSError, TypeError, ValueError):
        pass


def _validate_search_result(upstream: ModuleType, target: str) -> None:
    screenshot: object | None = None
    try:
        screenshot, point_box = upstream.make_search_results_screenshot(
            "guiyi-wechat-courier-search"
        )
        boxes = upstream.ocr_boxes(screenshot)
        if not isinstance(boxes, list):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        texts: list[str] = []
        for box in boxes:
            if not isinstance(box, dict) or not isinstance(box.get("text"), str):
                raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
            texts.append(box["text"])
        selected = boxes[select_unique_search_box(texts, target)]
        point = upstream.search_result_row_click_point(selected, point_box)
        if (
            not isinstance(point, tuple)
            or len(point) != 2
            or any(type(value) is not int for value in point)
        ):
            raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED")
        upstream.click_point(point[0], point[1])
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
    finally:
        if screenshot is not None:
            _safe_unlink(screenshot)


def _safety_text_is_clean(value: str) -> bool:
    normalized = normalize_chat_name(value)
    return not any(normalize_chat_name(term) in normalized for term in _SAFETY_REJECT_TERMS)


def _validate_title_attempt(upstream: ModuleType, target: str, attempt: int) -> None:
    screenshots: list[object] = []
    try:
        safety = upstream.make_safety_screenshot(f"guiyi-wechat-courier-safety-{attempt}")
        screenshots.append(safety)
        title = upstream.make_title_screenshot(f"guiyi-wechat-courier-title-{attempt}")
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
        for screenshot in screenshots:
            _safe_unlink(screenshot)


def _verify_target(
    upstream: ModuleType,
    target: str,
    *,
    open_search_ui: Callable[[ModuleType, str], None],
    sleep: Callable[[float], None],
) -> None:
    try:
        upstream.activate_wechat()
        open_search_ui(upstream, target)
        _validate_search_result(upstream, target)
        sleep(1.0)
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("WECHAT_GROUP_TARGET_UNVERIFIED") from None
    for attempt in range(1, 4):
        try:
            _validate_title_attempt(upstream, target, attempt)
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
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID")
    action = payload.get("action")
    expected_keys = (
        {"action", "target_chat", "upstream_root"}
        if action == "verify"
        else {"action", "target_chat", "text", "upstream_root"}
    )
    if (
        action not in {"verify", "send"}
        or set(payload) != expected_keys
        or not _valid_private_text(payload.get("target_chat"))
        or not isinstance(payload.get("upstream_root"), str)
        or (action == "send" and not _valid_message_text(payload.get("text")))
    ):
        raise AdapterError("WECHAT_COURIER_DEPENDENCY_INVALID")
    private_output = io.StringIO()
    with redirect_stdout(private_output), redirect_stderr(private_output):
        upstream = _load_upstream(Path(payload["upstream_root"]))
        _verify_target(
            upstream,
            payload["target_chat"],
            open_search_ui=open_search_ui,
            sleep=sleep,
        )
        if action == "send":
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
