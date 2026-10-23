"""Single-instance lock for the daily collector.

Two collectors running at once is not merely wasteful. It draws throttling from the
free endpoints — which is how symbols get lost — and it lets two processes write the
same partition file concurrently. Both were observed during development.

The lock is a PID file created with O_EXCL. A lock whose owning process is gone is
treated as stale and reclaimed, so a machine that was hard-powered-off mid-run does
not silently stop collecting.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    """Raised when another collector instance holds the lock."""


def _process_alive(pid: int) -> bool:
    """True if a process with this PID exists and we may signal it."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but is owned by another user; treat as alive rather than stealing it.
        return True
    return True


def _read_owner(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


@contextmanager
def single_instance(path: Path) -> Iterator[None]:
    """Hold an exclusive collector lock for the duration of the block.

    Raises AlreadyRunning if a live instance holds it. Always releases on exit,
    including on error, so a crashed run does not block the next scheduled one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        owner = _read_owner(path)
        if owner is not None and _process_alive(owner):
            raise AlreadyRunning(
                f"Another collector is running (pid {owner}, lock {path})"
            ) from None
        # Stale lock from a killed or crashed run: reclaim it.
        path.unlink(missing_ok=True)
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    try:
        os.write(handle, str(os.getpid()).encode())
        os.close(handle)
        yield
    finally:
        if _read_owner(path) == os.getpid():
            path.unlink(missing_ok=True)


__all__ = ["AlreadyRunning", "single_instance"]
