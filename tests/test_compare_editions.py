"""Comparisons of two editions, each the tracks of an Evidence Set (ADR 0009).

Each case cuts known audio into tracks, so every expected portion, segment and
correspondence is known; a boundary may fall within BOUNDARY_FRAMES of its frame.
"""

from __future__ import annotations

import json
import re
import weakref
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soxr
from conftest import RATE, requires_permissions, write_audio
from test_compare_portions import BOUNDARY_FRAMES, noise, quantized

from copyofa import comparator, inspector

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Run, StandIn

    MakeSet = Callable[[Callable[[Path], None]], Path]
    MakeAcquired = Callable[..., Path]

SECOND = RATE


def piece(seconds: int, seed: int) -> np.ndarray:
    """Stereo 16-bit noise, as integers, of whole seconds and so of whole sectors."""
    return quantized(noise(seconds, seed), 16)


P, Q, R, S = (piece(10, seed) for seed in (11, 12, 13, 14))
X = piece(2, 15)
"""Audio no other piece holds."""


def acquire(
    make_acquired_set: MakeAcquired, redumper: StandIn, tracks: list[np.ndarray]
) -> Path:
    """Acquire a disc whose tracks hold the given audio, in order."""
    name = f"audio-{len(list(redumper.directory.glob('audio-*')))}.raw"
    audio = np.concatenate(tracks).astype("<i2")
    (redumper.directory / name).write_bytes(audio.tobytes())
    return make_acquired_set(
        audio=name, tracks=[{"frames": len(track)} for track in tracks]
    )


def compare(run: Run, *arguments: str | Path) -> tuple[int | str | None, Any]:
    outcome = run("compare", *arguments, "--json")
    return outcome.code, json.loads(outcome.out) if outcome.out else None


def near(frame: int, expected: int) -> bool:
    return abs(frame - expected) <= BOUNDARY_FRAMES


def pairs(entries: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [(entry["a"]["position"], entry["b"]["position"]) for entry in entries]


def test_compare_follows_audio_across_moved_track_boundaries(
    run: Run, make_acquired_set: MakeAcquired, redumper: StandIn
) -> None:
    audio = np.concatenate([P, Q, R[: 4 * SECOND]])

    def cut(seconds: tuple[int, ...]) -> list[np.ndarray]:
        return [audio[s * SECOND : e * SECOND] for s, e in pairwise(seconds)]

    a = acquire(make_acquired_set, redumper, cut((0, 8, 16, 24)))
    b = acquire(make_acquired_set, redumper, cut((0, 7, 17, 24)))

    code, report = compare(run, a, b)

    assert code == 0
    assert report["scope"] == "editions"
    measurements = report["measurements"]
    assert "absent" not in measurements
    [portion] = measurements["portions"]
    assert portion["rank"] == "primary"
    assert portion["offset"]["frames"] == 0
    assert near(portion["a"]["start_frame"], 0)
    assert near(portion["a"]["frames"], 24 * SECOND)
    segments = portion["segments"]
    assert pairs(segments) == [(1, 1), (1, 2), (2, 2), (3, 2), (3, 3)]
    assert segments[1]["a"] == {
        "position": 1,
        "start_frame": 7 * SECOND,
        "frames": SECOND,
    }
    assert segments[1]["b"] == {"position": 2, "start_frame": 0, "frames": SECOND}
    assert segments[3]["a"] == {"position": 3, "start_frame": 0, "frames": SECOND}
    assert segments[3]["b"] == {
        "position": 2,
        "start_frame": 9 * SECOND,
        "frames": SECOND,
    }
    for segment in segments:
        assert segment["downmix"]["correlation"] == pytest.approx(1)
        assert segment["downmix"]["absent"]["residual_db"] == (
            "A minus B after the gain is zero throughout the segment"
        )
        assert len(segment["channels"]) == 2
    correspondences = measurements["correspondences"]
    assert pairs(correspondences) == pairs(segments)
    expected = [(7 / 8, 1), (1 / 8, 1 / 10), (1, 8 / 10), (1 / 8, 1 / 10), (7 / 8, 1)]
    for entry, (share_a, share_b) in zip(correspondences, expected, strict=True):
        assert entry["a"]["fraction"] == pytest.approx(share_a, abs=1e-3)
        assert entry["b"]["fraction"] == pytest.approx(share_b, abs=1e-3)
        assert "identical_audio" not in entry
    for name in ("a", "b"):
        assert sum(part["frames"] for part in measurements["unmatched"][name]) <= (
            2 * BOUNDARY_FRAMES
        )
        coverage = measurements["coverage"][name]
        assert coverage["frames"] == 24 * SECOND
        assert near(coverage["matched_frames"], 24 * SECOND)


@pytest.fixture
def inserted(make_acquired_set: MakeAcquired, redumper: StandIn) -> tuple[Path, Path]:
    """Edition A, P then Q; edition B, P with its start replaced, then R, then Q."""
    a = acquire(make_acquired_set, redumper, [P, Q])
    replaced = np.concatenate([X, P[2 * SECOND :]])
    b = acquire(make_acquired_set, redumper, [replaced, R[: 8 * SECOND], Q])
    return a, b


def test_compare_gives_the_tracks_one_edition_inserts_or_replaces(
    run: Run, inserted: tuple[Path, Path]
) -> None:
    code, report = compare(run, *inserted)

    assert code == 0
    measurements = report["measurements"]
    portions = measurements["portions"]
    assert [p["rank"] for p in portions] == ["primary", "primary"]
    first, second = portions
    assert first["offset"]["frames"] == 0
    assert near(first["a"]["start_frame"], 2 * SECOND)
    assert pairs(first["segments"]) == [(1, 1)]
    assert second["offset"]["frames"] == 8 * SECOND
    assert near(second["a"]["start_frame"], 10 * SECOND)
    assert pairs(second["segments"]) == [(2, 3)]
    assert measurements["sequences"]["b"] == [
        {"position": 1, "start_frame": 0, "frames": 10 * SECOND},
        {"position": 2, "start_frame": 10 * SECOND, "frames": 8 * SECOND},
        {"position": 3, "start_frame": 18 * SECOND, "frames": 10 * SECOND},
    ]
    [replaced, kept] = measurements["correspondences"]
    assert pairs([replaced, kept]) == [(1, 1), (2, 3)]
    assert replaced["a"]["fraction"] == pytest.approx(0.8, abs=1e-3)
    assert "identical_audio" not in replaced
    assert kept["identical_audio"] is True
    assert kept["a"]["fraction"] == pytest.approx(1, abs=1e-3)
    unmatched = measurements["unmatched"]
    assert [(part["position"], part["start_frame"]) for part in unmatched["a"]] == [
        (1, 0)
    ]
    assert near(unmatched["a"][0]["frames"], 2 * SECOND)
    assert [part["position"] for part in unmatched["b"]] == [1, 2]
    assert unmatched["b"][1]["start_frame"] == 0
    assert near(unmatched["b"][1]["frames"], 8 * SECOND)
    assert unmatched["b"][1]["level_dbfs"] == pytest.approx(-20, abs=1)


def test_compare_prints_an_edition_comparison(
    run: Run, inserted: tuple[Path, Path]
) -> None:
    a, b = inserted

    outcome = run("compare", a, b)

    assert outcome.code == 0, outcome.err
    lines = outcome.out.splitlines()
    assert lines[:4] == [
        f"Edition A: {a}, 2 tracks, 0:20.000",
        f"Edition B: {b}, 3 tracks, 0:28.000",
        "Common sample rate: 44100 Hz",
        "Portions: 2 primary, 0 alternate",
    ]
    duration = r"0:\d\d\.\d{3}"
    expected = [
        rf"Coverage of A: {duration} of 0:20\.000 found in B \(90\.0%\)",
        rf"Coverage of B: {duration} of 0:28\.000 found in A \(64\.3%\)",
        rf"A track 1: {duration} of 0:10\.000 found in B: track 1 {duration}",
        (
            rf"A track 2: {duration} of 0:10\.000 found in B: track 3 {duration}, "
            "identical audio"
        ),
        r"Unmatched in A, track 1: 0\.000-2\.00\d s, -\d+\.\d dBFS",
        r"Unmatched in B, track 1: 0\.000-2\.00\d s, -\d+\.\d dBFS",
        r"Unmatched in B, track 2: 0\.000-8\.000 s, -\d+\.\d dBFS",
    ]
    assert len(lines) == 4 + len(expected), lines
    for line, pattern in zip(lines[4:], expected, strict=True):
        assert re.fullmatch(pattern, line), (line, pattern)
    assert outcome.err.splitlines() == [
        *(
            f"Inspected edition A, track {n} of data/disc.scram.flac: interpreted"
            for n in (1, 2)
        ),
        *(
            f"Inspected edition B, track {n} of data/disc.scram.flac: interpreted"
            for n in (1, 2, 3)
        ),
    ]


def write_files(source: Path) -> None:
    """Q, then P, as 48 kHz files whose paths sort P first, beside a cover."""
    for name, audio in (("B.flac", P), ("a.flac", Q)):
        resampled = soxr.resample(audio / 32768, RATE, 48000, quality="VHQ")
        write_audio(source / name, quantized(resampled, 24), 24, "FLAC", 48000)
    (source / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0 not an image\n")


def test_compare_takes_an_imported_set_as_its_files_in_path_order(
    run: Run,
    make_acquired_set: MakeAcquired,
    redumper: StandIn,
    make_set: MakeSet,
) -> None:
    a = acquire(make_acquired_set, redumper, [P, Q])
    b = make_set(write_files)

    code, report = compare(run, a, b)

    assert code == 0
    edition = report["inputs"]["b"]
    assert [(t["position"], t["path"]) for t in edition["tracks"]] == [
        (1, "data/Album/B.flac"),
        (2, "data/Album/a.flac"),
    ]
    assert edition["excluded"] == [
        {
            "path": "data/Album/cover.jpg",
            "outcome": "not_interpreted",
            "reason": "no supported audio format was recognized",
        }
    ]
    assert report["method"]["common_sample_rate"] == RATE
    measurements = report["measurements"]
    assert measurements["sequences"]["b"][1] == {
        "position": 2,
        "start_frame": 10 * SECOND,
        "frames": 10 * SECOND,
    }
    correspondences = measurements["correspondences"]
    assert pairs(correspondences) == [(1, 1), (2, 2)]
    for entry in correspondences:
        assert entry["a"]["fraction"] == pytest.approx(1, abs=1e-3)
        assert "identical_audio" not in entry


def test_compare_keeps_the_rate_of_two_editions_at_48_khz(
    run: Run, make_set: MakeSet
) -> None:
    a = make_set(write_files)
    b = make_set(write_files)

    code, report = compare(run, a, b)

    assert code == 0
    assert report["method"]["common_sample_rate"] == 48000
    measurements = report["measurements"]
    for name in "ab":
        assert [entry["frames"] for entry in measurements["sequences"][name]] == [
            10 * 48000,
            10 * 48000,
        ]
        coverage = measurements["coverage"][name]
        assert coverage["frames"] == 20 * 48000
        assert near(coverage["matched_frames"], 20 * 48000)
    correspondences = measurements["correspondences"]
    assert pairs(correspondences) == [(1, 1), (2, 2)]
    assert all(entry["identical_audio"] for entry in correspondences)


def test_compare_omits_the_locations_of_editions(
    run: Run,
    make_acquired_set: MakeAcquired,
    redumper: StandIn,
    make_set: MakeSet,
    tmp_path: Path,
) -> None:
    a = acquire(make_acquired_set, redumper, [P, Q])
    b = make_set(write_files)

    code, report = compare(run, a, b, "--omit-locations")
    text = run("compare", a, b, "--omit-locations")

    assert code == 0
    assert report["omitted"] == ["/inputs/a/evidence_set", "/inputs/b/evidence_set"]
    assert "evidence_set" not in report["inputs"]["a"]
    assert "evidence_set" not in report["inputs"]["b"]
    assert str(tmp_path) not in json.dumps(report)
    assert text.out.splitlines()[:2] == [
        "Edition A: data/disc.scram.flac, 2 tracks, 0:20.000",
        "Edition B: 3 files, 2 tracks, 0:20.000",
    ]
    assert str(tmp_path) not in text.out


def test_compare_counts_audio_another_edition_repeats_once(
    run: Run, make_acquired_set: MakeAcquired, redumper: StandIn
) -> None:
    # As test_compare_gives_two_exact_copies_as_two_primaries builds it: B's track
    # holds the section of A's track twice, between audio A does not hold.
    before, after = np.split(R, 2)
    first, second, third = np.split(piece(15, seed=16), 3)
    a = acquire(make_acquired_set, redumper, [np.concatenate([before, S, after])])
    b = acquire(
        make_acquired_set,
        redumper,
        [np.concatenate([first, S, second, S, third])],
    )

    code, report = compare(run, a, b)

    assert code == 0
    measurements = report["measurements"]
    portions = measurements["portions"]
    assert [p["rank"] for p in portions] == ["primary", "primary"]
    assert sorted(p["offset"]["frames"] for p in portions) == [0, 15 * SECOND]
    coverage = measurements["coverage"]
    assert near(coverage["a"]["matched_frames"], 10 * SECOND)
    assert near(coverage["b"]["matched_frames"], 20 * SECOND)
    [entry] = measurements["correspondences"]
    assert pairs([entry]) == [(1, 1)]
    assert near(entry["a"]["matched_frames"], 10 * SECOND)
    assert entry["a"]["fraction"] == pytest.approx(0.5, abs=1e-3)
    assert near(entry["b"]["matched_frames"], 20 * SECOND)


@pytest.mark.parametrize(
    "case", ["file", "--track-a only", "--track-b only", "plain directory"]
)
def test_compare_refuses_a_set_root_beside_another_input(
    run: Run, make_set: MakeSet, tmp_path: Path, case: str
) -> None:
    first = make_set(write_files)
    second = make_set(write_files)
    plain = tmp_path / "plain"
    (plain / "data").mkdir(parents=True)
    arguments, root = {
        "file": ((first, second / "data/Album/a.flac"), first),
        "--track-a only": ((first, second, "--track-a", "1"), second),
        "--track-b only": ((first, second, "--track-b", "1"), first),
        "plain directory": ((first, plain), first),
    }[case]

    outcome = run("compare", *arguments)

    assert outcome.code == 2
    assert outcome.out == ""
    assert outcome.err == (
        f"copyofa: compare takes two tracks or two editions: {root} is the root of "
        "an Evidence Set given without a track number, but the other input is not a "
        "set root given without one. Give two set roots without track numbers to "
        "compare editions, or a track number with each set root to compare tracks.\n"
    )


def modify(root: Path) -> None:
    with (root / "data/Album/B.flac").open("r+b") as file:
        file.seek(-1, 2)
        last = file.read(1)
        file.seek(-1, 2)
        file.write(bytes([last[0] ^ 1]))


def unusable(root: Path) -> None:
    with (root / "manifest-sha256.txt").open("a") as file:
        file.write(f"{'0' * 64}  data/Album/added.flac\n")


def cover_only(source: Path) -> None:
    (source / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0 not an image\n")


FAILURES: dict[str, tuple[Callable[[Path], None], Callable[[Path], None], str]] = {
    "modified file": (
        write_files,
        modify,
        "the track at position 1 of edition B is not interpreted",
    ),
    "unusable baseline": (
        write_files,
        unusable,
        "edition B has no track: the Integrity Baseline is unusable",
    ),
    "no track": (cover_only, lambda _: None, "edition B has no track"),
}


@pytest.mark.parametrize("case", FAILURES)
def test_compare_gives_no_measurements_when_an_edition_cannot_be_measured(
    run: Run, make_set: MakeSet, case: str
) -> None:
    fill, change, reason = FAILURES[case]
    a = make_set(write_files)
    b = make_set(fill)
    change(b)

    code, report = compare(run, a, b)
    text = run("compare", a, b)

    assert code == 1
    assert "measurements" not in report
    assert "common_sample_rate" not in report["method"]
    assert report["absent"] == {"measurements": reason}
    assert text.code == 1
    assert text.out.splitlines()[-1] == f"Not compared: {reason}"


@requires_permissions
def test_compare_takes_a_set_root_that_cannot_be_searched_as_an_edition(
    run: Run, make_set: MakeSet
) -> None:
    a = make_set(write_files)
    b = make_set(write_files)
    b.chmod(0)
    try:
        code, report = compare(run, a, b)
    finally:
        b.chmod(0o755)

    # As verify does: the set's records cannot be read, so its edition has no track.
    assert code == 1
    assert report["scope"] == "editions"
    assert report["inputs"]["b"]["evidence_set"] == str(b)
    assert report["absent"] == {
        "measurements": "edition B has no track: the Integrity Baseline is unusable"
    }


def test_compare_keeps_no_track_of_an_edition_at_its_own_rate(
    make_set: MakeSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = make_set(write_files)
    b = make_set(
        lambda source: write_audio(
            source / "all.flac", np.concatenate([P, Q]), 16, "FLAC"
        )
    )
    originals: list[weakref.ref[np.ndarray]] = []
    resample = comparator._resample
    inspect_file = inspector.inspect_file

    def recording(audio: Any, rate: int) -> np.ndarray:
        if audio.rate != rate:
            originals.append(weakref.ref(audio.samples))
        return resample(audio, rate)

    def checking(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert all(original() is None for original in originals)
        return inspect_file(*args, **kwargs)

    monkeypatch.setattr(comparator, "_resample", recording)
    monkeypatch.setattr(inspector, "inspect_file", checking)

    report = comparator.compare(str(a), str(b))

    assert report["method"]["common_sample_rate"] == RATE
    assert len(originals) == 2
    assert all(original() is None for original in originals)
