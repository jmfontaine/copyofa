from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from copyofa.cli import main

if TYPE_CHECKING:
    from collections.abc import Callable

    Run = Callable[..., "Outcome"]


@dataclass(frozen=True)
class Outcome:
    code: int | str | None
    out: str
    err: str


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> Run:
    """Run the command line and capture its exit code and output."""

    def _run(*args: str | os.PathLike[str]) -> Outcome:
        try:
            code: int | str | None = main([os.fspath(arg) for arg in args])
        except SystemExit as exit_info:
            code = exit_info.code
        captured = capsys.readouterr()
        return Outcome(code, captured.out, captured.err)

    return _run


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Map every entry under root to its content and modification time."""
    result = {}
    for directory, dirs, files in os.walk(root):
        for name in files + dirs:
            path = Path(directory, name)
            if path.is_symlink():
                content = os.fsencode(path.readlink())
            elif path.is_file() and os.access(path, os.R_OK):
                content = path.read_bytes()
            else:
                content = b""
            result[str(path.relative_to(root))] = (content, path.lstat().st_mtime_ns)
    return result


requires_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads files regardless of their permissions",
)
