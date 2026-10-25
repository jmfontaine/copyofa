from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soundfile

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
RATE = 44100


def signal(frames: int, channels: int, bits: int, seed: int = 1) -> np.ndarray:
    """Return random integer samples of the given depth, shaped (frames, channels)."""
    high = 1 << (bits - 1)
    rng = np.random.default_rng(seed)
    return rng.integers(-high, high, size=(frames, channels), dtype=np.int32)


def write_audio(
    path: Path,
    samples: np.ndarray,
    bits: int,
    container: str,
    rate: int = RATE,
    title: str | None = None,
    **options: Any,
) -> None:
    """Write integer samples as FLAC, WAV or WAVEX at the given depth."""
    subtype = (
        f"PCM_{bits}" if bits > 8 else "PCM_S8" if container == "FLAC" else "PCM_U8"
    )
    with soundfile.SoundFile(
        path,
        "w",
        rate,
        samples.shape[1],
        subtype,
        format=container,
        **options,
    ) as file:
        if title is not None:
            file.title = title
        # libsndfile takes 32-bit integers at full scale.
        file.write(samples << (32 - bits))


@pytest.fixture
def make_set(run: Run, tmp_path: Path) -> Callable[[Callable[[Path], None]], Path]:
    """Import a delivery that a function writes into a fresh source directory."""
    count = 0

    def _make_set(fill: Callable[[Path], None]) -> Path:
        nonlocal count
        count += 1
        source = tmp_path / f"source-{count}" / "Album"
        source.mkdir(parents=True)
        fill(source)
        destination = tmp_path / f"set-{count}"
        outcome = run("import", source, "--to", destination)
        assert outcome.code == 0, outcome.err
        return destination

    return _make_set
