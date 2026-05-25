import threading
from typing import Any

_lock = threading.Lock()
_progress_log: list[dict[str, Any]] = []
_progress_complete: bool = False
_progress_error: str | None = None


def reset_progress() -> None:
    global _progress_complete, _progress_error
    with _lock:
        _progress_log.clear()
        _progress_complete = False
        _progress_error = None


def emit_progress(step: str, status: str, progress: int) -> None:
    global _progress_complete, _progress_error
    event: dict[str, Any] = {"step": step, "status": status, "progress": progress}
    with _lock:
        _progress_log.append(event)
        if progress >= 100:
            _progress_complete = True
            if status == "error":
                _progress_error = step


def get_current_progress() -> dict[str, Any]:
    with _lock:
        return {
            "steps": list(_progress_log),
            "complete": _progress_complete,
            "error": _progress_error,
        }
