"""Commit file outputs only after their writer completes successfully."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_output(destination: Path) -> Iterator[Path]:
    """Stage beside the destination for an atomic, same-filesystem replacement.

    Keep the extension so external encoders can select the correct container.
    The caller must close all handles before leaving the context (also on Windows).
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=destination.suffix, dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("rb") as completed:
            os.fsync(completed.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
