"""Comparisons of audio whose speed differs, from generated signals (ADR 0010).

Track B is track A resampled by soxr at its VHQ quality, so its speed ratio, B's
frames per frame of A minus one, is known, and so is where its audio starts.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soxr
from conftest import DAMAGED_ERRORS, RATE, signal, write_audio
from test_compare_editions import P, Q, acquire, cover_only, near, pairs, write_files
from test_compare_portions import compare_signals, noise, primaries, quantized, write_b

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Run, StandIn

    MakeSet = Callable[[Callable[[Path], None]], Path]

SECOND = RATE
STORED_6 = Path(__file__).parent / "reports" / "comparison-6"
"""Version 6 comparison Reports that compare printed in v0.9.0's method, before ADR
0010, kept as they were; tests/test_view.py lists them."""

A = quantized(noise(150, seed=21), 16) / 32768
"""Track A: 150 s, exactly representable at 16 bits."""


def stretched(samples: np.ndarray, ppm: float) -> np.ndarray:
    """Return audio played at another speed: ppm more frames per frame, minus one."""
    return soxr.resample(samples, RATE, RATE * (1 + ppm * 1e-6), quality="VHQ")


@pytest.mark.parametrize(
    ("ppm", "residual_db"),
    [(10, -30), (-100, -30), (10_000, -20), (-41_667, -20)],
    ids=["+10 ppm", "-100 ppm", "+1 %", "-41,667 ppm"],
)
def test_compare_finds_a_track_at_another_speed(
    run: Run, make_set: MakeSet, ppm: int, residual_db: float
) -> None:
    code, report = compare_signals(
        run, make_set, A, lambda source: write_b(source, stretched(A, ppm), "24-bit")
    )

    assert code == 0
    [portion] = primaries(report)
    assert portion["a"]["frames"] >= 0.99 * len(A)
    assert portion["speed_ratio_ppm"] == pytest.approx(ppm, abs=0.2)
    assert portion["block_gain_residual_db"] <= residual_db
    # B's audio starts where A's does, and runs ppm longer.
    start = portion["a"]["start_frame"]
    assert portion["offset"]["frames"] == pytest.approx(start * ppm * 1e-6, abs=0.5)
    assert portion["offset"]["seconds"] == portion["offset"]["frames"] / RATE
    assert portion["b"]["frames"] == pytest.approx(
        portion["a"]["frames"] * (1 + ppm * 1e-6), abs=1
    )
    for values in [portion["downmix"], *portion["channels"]]:
        assert values["correlation"] > 0.99
        assert values["residual_db"] <= residual_db


def test_compare_prints_the_speed_ratio_of_a_portion(
    run: Run, make_set: MakeSet
) -> None:
    first = make_set(
        lambda source: write_audio(source / "a.flac", quantized(A, 16), 16, "FLAC")
    )
    second = make_set(lambda source: write_b(source, stretched(A, 10), "24-bit"))

    outcome = run("compare", first / "data/Album/a.flac", second / "data/Album/b.flac")

    assert outcome.code == 0, outcome.err
    [line] = [line for line in outcome.out.splitlines() if line.startswith("Portion")]
    found = re.fullmatch(
        r"Portion 1, primary: A [\d.-]+ s, B [\d.-]+ s, offset [+-][\d.]+ frames "
        r"\([+-]\d\.\d{3} s\), speed ratio ([+-]\d+\.\d\d) ppm, "
        r"correlation 1\.000, residual \(one gain\) -\d+\.\d dB",
        line,
    )
    assert found is not None, line
    assert float(found[1]) == pytest.approx(10, abs=0.2)


LEADS = (2205, 6615, 4410, 8820)
"""The frames of silence before each track of edition B, so that each starts at its
own offset from A's."""
SPEEDS = (0, 10, -100, 0)
"""The speed ratio of each track of edition B against A's, in ppm."""


def drifting_editions(make_set: MakeSet) -> tuple[Path, Path]:
    """Edition A, four tracks of 60 s; edition B, the same tracks after LEADS frames of
    silence, its second and third at the speeds of SPEEDS.

    Silence, unlike other audio, never matches a frame of A by chance, so no portion
    runs past its track by a few frames into the next one.
    """
    tracks = [quantized(noise(60, seed=seed), 16) for seed in (31, 32, 33, 34)]

    def write_a(source: Path) -> None:
        for number, track in enumerate(tracks, start=1):
            write_audio(source / f"{number:02}.flac", track, 16, "FLAC")

    def write_b(source: Path) -> None:
        for number, (track, ppm, lead) in enumerate(
            zip(tracks, SPEEDS, LEADS, strict=True), start=1
        ):
            audio = track / 32768
            if ppm:
                audio = stretched(audio, ppm)
            audio = np.concatenate([np.zeros((lead, 2)), audio])
            write_audio(source / f"{number:02}.flac", quantized(audio, 24), 24, "FLAC")

    return make_set(write_a), make_set(write_b)


@pytest.fixture
def drifting(make_set: MakeSet) -> tuple[Path, Path]:
    return drifting_editions(make_set)


def test_compare_follows_tracks_of_editions_that_drift(
    run: Run, drifting: tuple[Path, Path]
) -> None:
    outcome = run("compare", *drifting, "--json")

    assert outcome.code == 0, outcome.err
    report = json.loads(outcome.out)
    measurements = report["measurements"]
    portions = primaries(report)
    assert len(portions) == 4
    sequences = measurements["sequences"]
    for portion, ppm, lead, track in zip(
        portions, SPEEDS, LEADS, sequences["a"], strict=True
    ):
        assert portion["speed_ratio_ppm"] == pytest.approx(ppm, abs=0.2)
        assert near(portion["a"]["start_frame"], track["start_frame"])
        assert near(portion["a"]["frames"], 60 * SECOND)
        [segment] = portion["segments"]
        position = track["position"]
        assert (segment["a"]["position"], segment["b"]["position"]) == (
            position,
            position,
        )
        assert segment["speed_ratio_ppm"] == portion["speed_ratio_ppm"]
        # Each segment's own offset, within its two tracks: B's lead.
        start = segment["a"]["start_frame"]
        assert near(start, 0)
        offset = segment["offset"]["frames"]
        assert offset == pytest.approx(lead + start * ppm * 1e-6, abs=0.5)
        if ppm == 0:
            assert offset == lead
            assert isinstance(offset, int)
        assert near(segment["b"]["start_frame"], lead)
        assert segment["b"]["frames"] == pytest.approx(
            segment["a"]["frames"] * (1 + ppm * 1e-6), abs=1
        )
        if ppm:
            assert segment["downmix"]["residual_db"] <= -30
        else:
            assert "residual_db" not in segment["downmix"]  # Identical samples.
    correspondences = measurements["correspondences"]
    assert pairs(correspondences) == [(1, 1), (2, 2), (3, 3), (4, 4)]
    for entry in correspondences:
        assert entry["a"]["fraction"] >= 0.99
    for name in "ab":
        coverage = measurements["coverage"][name]
        assert coverage["matched_frames"] >= 0.99 * coverage["frames"]


def test_compare_prints_the_speed_ratio_of_each_track_of_an_edition(
    run: Run, drifting: tuple[Path, Path]
) -> None:
    outcome = run("compare", *drifting)

    assert outcome.code == 0, outcome.err
    lines = [line for line in outcome.out.splitlines() if line.startswith("A data")]
    assert len(lines) == 4
    duration = r"\d:\d\d\.\d{3}"
    for number, (line, ppm) in enumerate(zip(lines, SPEEDS, strict=True), start=1):
        path = re.escape(f"data/Album/{number:02}.flac")
        ratio = r" at [+-]\d+\.\d\d ppm" if ppm else ""
        assert re.fullmatch(
            rf"A {path}: {duration} of 1:00\.000 found in B: {path} {duration}" + ratio,
            line,
        ), line
        if ppm:
            found = float(line.rsplit(" at ", 1)[1].removesuffix(" ppm"))
            assert found == pytest.approx(ppm, abs=0.2)


def test_compare_finds_no_portion_between_unrelated_editions(
    run: Run, make_set: MakeSet
) -> None:
    def fill(seeds: tuple[int, int]) -> Callable[[Path], None]:
        def write(source: Path) -> None:
            for number, seed in enumerate(seeds, start=1):
                track = quantized(noise(30, seed=seed), 16)
                write_audio(source / f"{number:02}.flac", track, 16, "FLAC")

        return write

    a, b = make_set(fill((41, 42))), make_set(fill((43, 44)))

    outcome = run("compare", a, b, "--json")

    assert outcome.code == 0, outcome.err
    measurements = json.loads(outcome.out)["measurements"]
    assert measurements["portions"] == []
    assert measurements["absent"] == {"portions": "no portion was found"}
    assert measurements["correspondences"] == []


@pytest.fixture
def compared(
    run: Run,
    make_set: MakeSet,
    make_acquired_set: Callable[..., Path],
    redumper: StandIn,
    damaged_set: Path,
    tmp_path: Path,
) -> Callable[[str], tuple[Path, dict[str, Any]]]:
    """Have compare print a Report of a case of STORED_6, from the same inputs."""

    def _compared(name: str) -> tuple[Path, dict[str, Any]]:
        code = 0
        if name == "damaged_tracks":
            arguments: tuple[str | Path, ...] = (
                damaged_set,
                damaged_set,
                "--track-a",
                "1",
                "--track-b",
                "2",
            )
        elif name == "files":
            samples = signal(6 * RATE, 2, 16, seed=23)
            sets = [
                make_set(
                    lambda source: write_audio(source / "a.flac", samples, 16, "FLAC")
                )
                for _ in range(2)
            ]
            arguments = tuple(path / "data/Album/a.flac" for path in sets)
        elif name == "editions_measured":
            arguments = (
                acquire(make_acquired_set, redumper, [P, Q]),
                make_set(write_files),
            )
        elif name == "editions_damaged":
            damaged = make_acquired_set(code=1, errors=DAMAGED_ERRORS)
            arguments = (damaged, damaged)
        else:
            assert name == "editions_not_measured"
            arguments = (make_set(write_files), make_set(cover_only))
            code = 1
        outcome = run("compare", *arguments, "--json")
        assert outcome.code == code, outcome.err
        path = tmp_path / f"{name}.json"
        path.write_text(outcome.out, encoding="utf-8")
        return path, json.loads(outcome.out)

    return _compared


def same_speed(entry: dict[str, Any]) -> dict[str, Any]:
    """Check that a portion or segment of version 7 is at a ratio of 0 with an
    integer offset; return it as version 6 gives it."""
    assert entry["speed_ratio_ppm"] == 0
    assert isinstance(entry["offset"]["frames"], int)
    earlier = {key: value for key, value in entry.items() if key != "speed_ratio_ppm"}
    if "segments" in entry:
        earlier["segments"] = [
            {
                key: value
                for key, value in same_speed(segment).items()
                if key != "offset"
            }
            for segment in entry["segments"]
        ]
    return earlier


def assert_equal(found: Any, expected: Any, path: str = "") -> None:
    """Assert two JSON values are equal, numbers to within rounding."""
    if isinstance(expected, dict):
        assert isinstance(found, dict), path
        assert found.keys() == expected.keys(), path
        for key, value in expected.items():
            assert_equal(found[key], value, f"{path}/{key}")
    elif isinstance(expected, list):
        assert isinstance(found, list), path
        assert len(found) == len(expected), path
        for index, (item, value) in enumerate(zip(found, expected, strict=True)):
            assert_equal(item, value, f"{path}/{index}")
    elif isinstance(expected, float):
        assert math.isclose(found, expected, rel_tol=1e-9, abs_tol=1e-12), path
    else:
        assert found == expected, path
        assert type(found) is type(expected), path


@pytest.mark.parametrize("name", sorted(path.stem for path in STORED_6.glob("*.json")))
def test_compare_measures_audio_at_one_speed_as_version_6(
    compared: Callable[[str], tuple[Path, dict[str, Any]]], name: str
) -> None:
    _, report = compared(name)
    stored = json.loads((STORED_6 / f"{name}.json").read_text(encoding="utf-8"))

    assert (report["format_version"], stored["format_version"]) == (7, 6)
    assert report["scope"] == stored["scope"]
    assert report.get("absent") == stored.get("absent")
    if "measurements" not in stored:
        assert "measurements" not in report
        return
    measurements = dict(report["measurements"])
    measurements["portions"] = [same_speed(p) for p in measurements["portions"]]
    assert_equal(measurements, stored["measurements"])
