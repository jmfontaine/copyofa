"""How an edition comparison holds the audio of its editions (brief 0009).

An edition comparison holds the decoded audio a step needs, a track of each edition
at most, not both editions whole; what it holds otherwise grows with its longest
track. It keeps the decoded audio in temporary files, which it removes however it
ends.
"""

from __future__ import annotations

import errno
import gc
import json
import tempfile
import tracemalloc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from conftest import RATE, write_audio
from test_compare_editions import cover_only
from test_compare_portions import noise, quantized
from test_compare_speed import stretched

from copyofa import comparator, locator

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Run

    MakeSet = Callable[[Callable[[Path], None]], Path]

SECOND = RATE
TRACK_SECONDS = 30
"""The length of each track of the editions whose comparisons are measured."""
GROWTH = 1.4
"""The most an edition comparison's peak may grow when each edition doubles (AC2)."""


def edition(make_set: MakeSet, tracks: list[np.ndarray]) -> Path:
    """Import an edition of the given tracks, as 16-bit FLAC files in order."""

    def fill(source: Path) -> None:
        for number, track in enumerate(tracks, 1):
            write_audio(source / f"{number:02}.flac", track, 16, "FLAC")

    return make_set(fill)


def editions(make_set: MakeSet, count: int, ppm: int) -> tuple[Path, Path]:
    """Edition A, count tracks of noise; edition B, the same audio played ppm faster,
    cut into as many tracks."""
    tracks = [quantized(noise(TRACK_SECONDS, seed), 16) for seed in range(count)]
    if ppm:
        played = quantized(stretched(np.concatenate(tracks) / 32768, ppm), 16)
        cuts = [round(len(played) * index / count) for index in range(1, count)]
        return edition(make_set, tracks), edition(make_set, np.split(played, cuts))
    return edition(make_set, tracks), edition(make_set, tracks)


def peak(a: Path, b: Path) -> tuple[int, dict[str, Any]]:
    """Compare two editions; return the peak memory tracemalloc traces, NumPy's
    arrays included, and the Report."""
    tracemalloc.start()
    try:
        report = comparator.compare(str(a), str(b))
        return tracemalloc.get_traced_memory()[1], report
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("ppm", [0, 10_000], ids=["same speed", "+1 %"])
def test_an_edition_comparison_holds_what_its_longest_track_needs(
    make_set: MakeSet, ppm: int
) -> None:
    peaks = []
    for count in (2, 4):
        a, b = editions(make_set, count, ppm)
        found, report = peak(a, b)
        # One portion, at B's speed, spans every track of both editions.
        (portion,) = report["measurements"]["portions"]
        assert portion["speed_ratio_ppm"] == pytest.approx(ppm, abs=1)
        assert {
            (segment["a"]["position"], segment["b"]["position"])
            for segment in portion["segments"]
        } >= {(position, position) for position in range(1, count + 1)}
        peaks.append(found)

    two, four = peaks
    assert four <= GROWTH * two, f"{two / 1e6:.0f} MB, then {four / 1e6:.0f} MB"


def test_an_edition_comparison_keeps_no_audio_once_it_ends(make_set: MakeSet) -> None:
    # One track each, matched, so that each edition holds its track and its
    # downmix to the end.
    track = quantized(noise(TRACK_SECONDS, 1), 16)
    a, b = edition(make_set, [track]), edition(make_set, [track])
    held = len(track) * 2 * 4
    gc.collect()
    gc.disable()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        report = comparator.compare(str(a), str(b))
        kept = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
        gc.enable()

    assert report["measurements"]["portions"]
    assert kept < held / 4, f"{kept / 1e6:.1f} MB kept"


@dataclass(frozen=True)
class Temporaries:
    """The temporary files compare creates, and the directory they go to."""

    directory: Path
    files: list[Any]

    def assert_none_remains(self) -> None:
        assert self.files, "compare created no temporary file"
        assert all(file.closed for file in self.files)
        assert list(self.directory.iterdir()) == []


@pytest.fixture
def temporaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Temporaries:
    """Make an empty directory the one temporary files go to, and record each
    temporary file compare creates."""
    directory = tmp_path / "temporary"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    created = Temporaries(directory, [])
    make = tempfile.TemporaryFile

    def recording(*args: Any, **kwargs: Any) -> Any:
        file = make(*args, **kwargs)
        created.files.append(file)
        return file

    monkeypatch.setattr(tempfile, "TemporaryFile", recording)
    return created


def short_editions(make_set: MakeSet) -> tuple[Path, Path]:
    tracks = [quantized(noise(8, seed), 16) for seed in (1, 2)]
    return edition(make_set, tracks), edition(make_set, tracks[::-1])


def test_compare_leaves_no_temporary_file_after_a_comparison(
    run: Run, make_set: MakeSet, temporaries: Temporaries
) -> None:
    a, b = short_editions(make_set)

    outcome = run("compare", a, b, "--json")

    assert outcome.code == 0, outcome.err
    temporaries.assert_none_remains()


def test_compare_leaves_no_temporary_file_after_a_failed_comparison(
    run: Run, make_set: MakeSet, temporaries: Temporaries
) -> None:
    a, _ = short_editions(make_set)
    b = make_set(cover_only)

    outcome = run("compare", a, b, "--json")

    assert outcome.code == 1, outcome.err
    temporaries.assert_none_remains()


def test_compare_leaves_no_temporary_file_when_canceled(
    run: Run,
    make_set: MakeSet,
    temporaries: Temporaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = short_editions(make_set)

    def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(locator, "locate", interrupted)
    outcome = run("compare", a, b, "--json")

    assert outcome.code == 130
    assert outcome.out == ""
    temporaries.assert_none_remains()


def test_compare_measures_an_edition_holding_a_track_without_frames(
    run: Run, make_set: MakeSet
) -> None:
    first, second = (quantized(noise(8, seed), 16) for seed in (1, 2))
    tracks = [first, np.zeros((0, 2), np.int32), second]

    def fill(source: Path) -> None:
        for number, track in enumerate(tracks, 1):
            write_audio(source / f"{number}.wav", track, 16, "WAV")

    a = make_set(fill)

    outcome = run("compare", a, a, "--json")

    assert outcome.code == 0, outcome.err
    measurements = json.loads(outcome.out)["measurements"]
    assert [entry["frames"] for entry in measurements["sequences"]["a"]] == [
        len(first),
        0,
        len(second),
    ]
    assert measurements["coverage"]["a"]["matched_frames"] == len(first) + len(second)


def test_compare_fails_when_it_cannot_write_the_decoded_audio(
    run: Run, make_set: MakeSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = short_editions(make_set)

    class Full:
        """A temporary file on a full disk."""

        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> Full:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def tell(self) -> int:
            return 0

        def write(self, _: object) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tempfile, "TemporaryFile", Full)
    outcome = run("compare", a, b, "--json")

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.splitlines()[-1] == (
        "copyofa: cannot hold the decoded audio in a temporary file: "
        "[Errno 28] No space left on device"
    )


@pytest.mark.parametrize("channels", range(1, 10))
def test_a_downmix_is_the_mean_of_the_channels_to_the_bit(channels: int) -> None:
    """The downmix compare reads back from its temporary file is the one it took as
    the mean of each frame's channels, so the Reports stay the same."""
    rng = np.random.default_rng(channels)
    shape = (100_000, channels)
    samples = np.ldexp(
        rng.uniform(-1, 1, shape), rng.integers(-160, 128, shape)
    ).astype(np.float32)
    samples[::5] = -0.0
    samples[1::9, 0] = -0.0
    samples[2::11, -1] = np.inf
    expected = samples.mean(axis=1, dtype=np.float64)

    downmix = comparator._downmix(samples)

    assert downmix.tobytes() == expected.tobytes()


@pytest.mark.parametrize("frames", [1, 7, 129, 65_537, 400_003])
@pytest.mark.parametrize("channels", [1, 2, 6])
def test_a_level_is_the_mean_square_of_the_range_to_the_bit(
    frames: int, channels: int
) -> None:
    """Compare reads an unmatched range in pieces to take its level, and gets the
    value it took from a float64 copy of the whole range, so the Reports stay the
    same."""
    rng = np.random.default_rng(frames * channels)
    samples = rng.uniform(-1, 1, (frames + 5, channels)).astype(np.float32)
    expected = float(np.mean(np.square(samples[3:-2], dtype=np.float64)))

    def read(first: int, last: int) -> np.ndarray:
        return samples[first:last].copy()

    assert comparator._power(read, channels, 3, frames + 3) == expected
