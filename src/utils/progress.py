import queue
import threading
from typing import Any

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []


def subscribe() -> "queue.Queue[dict[str, Any]]":
    q: queue.Queue = queue.Queue()
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: "queue.Queue[dict[str, Any]]") -> None:
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def emit_progress(step: str, status: str, progress: int) -> None:
    event: dict[str, Any] = {"step": step, "status": status, "progress": progress}
    with _lock:
        for q in list(_subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass
