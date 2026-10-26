"""The portions compare locates, from generated signals with known answers (ADR 0006).

Each case builds track B from pieces of track A, so every expected portion is known:
its range of A, its offset, and where its boundaries may fall.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soxr
from conftest import DISC, RATE, SECTOR_FRAMES, synthetic_disc, write_audio

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Run, StandIn

    MakeSet = Callable[[Callable[[Path], None]], Path]

SECOND = RATE
BOUNDARY_FRAMES = 32
"""How far a boundary may be from the expected frame (AC1)."""
BLOCK_FRAMES = 2048
FLOOR_DBFS = -80


def noise(seconds: float, seed: int) -> np.ndarray:
    """Stereo Gaussian noise below 16 kHz, about -20 dBFS, as floats.

    Band-limited, so that resampling to 48 kHz and back keeps all of it.
    """
    frames = round(seconds * RATE)
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.standard_normal((frames, 2)), axis=0)
    spectrum[np.fft.rfftfreq(frames, 1 / RATE) > 16000] = 0
    samples = np.fft.irfft(spectrum, frames, axis=0)
    return samples * (0.1 / samples.std())


def quantized(samples: np.ndarray, bits: int) -> np.ndarray:
    """Round float samples to integers of a depth, as write_audio takes them."""
    scale = 1 << (bits - 1)
    return np.clip(np.round(samples * scale), -scale, scale - 1).astype(np.int32)


A = quantized(noise(40, seed=1), 16) / 32768
"""Track A: 40 s, exactly representable at 16 bits."""
X = quantized(noise(20, seed=2), 16) / 32768
"""Audio that A does not hold."""


@dataclass(frozen=True)
class Expected:
    """An expected primary portion: its range of A and its offset.

    A boundary may fall anywhere in its zone, given as a range of A's frames.
    """

    start: int
    end: int
    offset: int
    start_zone: tuple[int, int] | None = None
    end_zone: tuple[int, int] | None = None

    def zone(self, edge: str) -> tuple[int, int]:
        frame = self.start if edge == "start" else self.end
        given = self.start_zone if edge == "start" else self.end_zone
        return given if given is not None else (frame, frame)


def fade(samples: np.ndarray, frames: int, *, out: bool) -> np.ndarray:
    ramp = np.linspace(0, 1, frames)[:, None]
    faded = samples.copy()
    if out:
        faded[-frames:] *= ramp[::-1]
    else:
        faded[:frames] *= ramp
    return faded


def block_powers(samples: np.ndarray, start: int, stop: int) -> np.ndarray:
    """Return the mean power over the block starting at each frame of [start, stop)
    that holds a whole block."""
    power = np.square(samples[start:stop]).mean(axis=1)
    running = np.concatenate(([0.0], np.cumsum(power)))
    return (running[BLOCK_FRAMES:] - running[:-BLOCK_FRAMES]) / BLOCK_FRAMES


def floor_crossings(faded: np.ndarray, start: int, stop: int) -> tuple[int, int]:
    """Return where a block's mean power first reaches -80 dBFS in [start, stop),
    and where the last block that reaches it ends."""
    loud = np.flatnonzero(block_powers(faded, start, stop) >= 10 ** (FLOOR_DBFS / 10))
    return start + int(loud[0]), start + int(loud[-1]) + BLOCK_FRAMES


def _crossfade() -> tuple[np.ndarray, list[Expected]]:
    frames = 3 * SECOND
    ramp = np.linspace(0, np.pi / 2, frames)[:, None]
    mixed = A[15 * SECOND : 18 * SECOND] * np.cos(ramp) + A[
        25 * SECOND : 28 * SECOND
    ] * np.sin(ramp)
    b = np.concatenate([A[: 15 * SECOND], mixed, A[28 * SECOND :]])
    return b, [
        Expected(0, 18 * SECOND, 0, end_zone=(15 * SECOND, 18 * SECOND)),
        Expected(
            25 * SECOND,
            len(A),
            -10 * SECOND,
            start_zone=(25 * SECOND, 28 * SECOND),
        ),
    ]


def _fades() -> tuple[np.ndarray, list[Expected]]:
    b = np.concatenate(
        [
            fade(A[: 20 * SECOND], 3 * SECOND, out=False),
            fade(A[20 * SECOND :], 8 * SECOND, out=True),
        ]
    )
    # A fade's boundary is where the faded audio crosses the evidence floor.
    start, _ = floor_crossings(b, 0, 3 * SECOND)
    _, end = floor_crossings(b, len(b) - 8 * SECOND, len(b))
    return b, [
        Expected(
            0,
            len(A),
            0,
            start_zone=(start - BLOCK_FRAMES, start + BLOCK_FRAMES),
            end_zone=(end - BLOCK_FRAMES, end + BLOCK_FRAMES),
        )
    ]


def _silence() -> tuple[np.ndarray, list[Expected]]:
    lead, trail = np.zeros((5 * SECOND // 2, 2)), np.zeros((4 * SECOND, 2))
    return np.concatenate([lead, A, trail]), [Expected(0, len(A), len(lead))]


EDITS: dict[str, Callable[[], tuple[np.ndarray, list[Expected]]]] = {
    "cut": lambda: (
        np.concatenate([A[: 15 * SECOND], A[20 * SECOND :]]),
        [
            Expected(0, 15 * SECOND, 0),
            Expected(20 * SECOND, len(A), -5 * SECOND),
        ],
    ),
    "insert": lambda: (
        np.concatenate([A[: 15 * SECOND], X[: 5 * SECOND], A[15 * SECOND :]]),
        [
            Expected(0, 15 * SECOND, 0),
            Expected(15 * SECOND, len(A), 5 * SECOND),
        ],
    ),
    "repeat": lambda: (
        np.concatenate([A[: 20 * SECOND], A[12 * SECOND :]]),
        [
            Expected(0, 20 * SECOND, 0),
            Expected(12 * SECOND, len(A), 8 * SECOND),
        ],
    ),
    "silence": _silence,
    "fades": _fades,
    "crossfade": _crossfade,
    "shift": lambda: (A[54413:], [Expected(54413, len(A), -54413)]),
    "replacement": lambda: (
        np.concatenate(
            [A[: 20 * SECOND], X[: 3 * SECOND // 10], A[20 * SECOND + 13230 :]]
        ),
        [
            Expected(0, 20 * SECOND, 0),
            Expected(20 * SECOND + 13230, len(A), 0),
        ],
    ),
    "inverted polarity": lambda: (-A, [Expected(0, len(A), 0)]),
}

TRANSFORMS = ["16-bit", "48 kHz", "24-bit", "-1.5 dB"]


def write_b(source: Path, b: np.ndarray, transform: str) -> None:
    """Write track B as the transform makes it."""
    if transform == "16-bit":
        write_audio(source / "b.flac", quantized(b, 16), 16, "FLAC")
    elif transform == "48 kHz":
        resampled = soxr.resample(b, RATE, 48000, quality="VHQ")
        write_audio(source / "b.flac", quantized(resampled, 24), 24, "FLAC", 48000)
    elif transform == "24-bit":
        write_audio(source / "b.flac", quantized(b, 24), 24, "FLAC")
    else:
        write_audio(source / "b.flac", quantized(b * 10 ** (-1.5 / 20), 24), 24, "FLAC")


def compare_signals(
    run: Run, make_set: MakeSet, a: np.ndarray, b: Callable[[Path], None]
) -> tuple[int | str | None, dict[str, Any]]:
    """Compare track A, written as 16-bit FLAC, with track B as b writes it."""
    first = make_set(
        lambda source: write_audio(source / "a.flac", quantized(a, 16), 16, "FLAC")
    )
    second = make_set(b)
    outcome = run(
        "compare",
        first / "data/Album/a.flac",
        next((second / "data/Album").iterdir()),
        "--json",
    )
    return outcome.code, json.loads(outcome.out) if outcome.out else {}


def primaries(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in report["measurements"]["portions"] if p["rank"] == "primary"]


def assert_found(report: dict[str, Any], expected: list[Expected]) -> None:
    """Assert the primary portions are exactly the expected ones."""
    found = primaries(report)
    assert len(found) == len(expected), [(p["a"], p["offset"]["frames"]) for p in found]
    for portion, wanted in zip(
        found, sorted(expected, key=lambda e: e.start), strict=True
    ):
        assert portion["offset"]["frames"] == wanted.offset
        start = portion["a"]["start_frame"]
        end = start + portion["a"]["frames"]
        for edge, frame in (("start", start), ("end", end)):
            low, high = wanted.zone(edge)
            assert low - BOUNDARY_FRAMES <= frame <= high + BOUNDARY_FRAMES, (
                edge,
                frame,
                (low, high),
            )
        assert portion["b"] == {
            "start_frame": start + wanted.offset,
            "frames": end - start,
        }


# KLUDGE: the brief's AC1 places a fade's boundary within one block of where the
# faded audio crosses -80 dBFS, but ADR 0006's ends (a gain fitted over the eight
# blocks inside the edge) put a linear fade's boundary about 6,500 frames inside
# the fade, where the faded audio is still about 26 dB above that floor. Remove
# the mark when the brief's criterion or the method changes so that they agree.
FADES_DISAGREE = pytest.mark.xfail(
    strict=True, reason="AC1's fade criterion disagrees with ADR 0006's ends"
)


@pytest.mark.parametrize("transform", TRANSFORMS)
@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(edit, marks=FADES_DISAGREE) if edit == "fades" else edit
        for edit in EDITS
    ],
)
def test_compare_finds_the_portions_of_an_edit(
    run: Run, make_set: MakeSet, edit: str, transform: str
) -> None:
    b, expected = EDITS[edit]()

    code, report = compare_signals(
        run, make_set, A, lambda source: write_b(source, b, transform)
    )

    assert code == 0
    assert "absent" not in report["measurements"]
    assert_found(report, expected)


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_compare_keeps_a_fade_inside_one_portion(
    run: Run, make_set: MakeSet, transform: str
) -> None:
    b, _ = _fades()

    code, report = compare_signals(
        run, make_set, A, lambda source: write_b(source, b, transform)
    )

    # What ADR 0006 gives today: one portion, at the exact offset, whose ends lie
    # inside the fades.
    assert code == 0
    [portion] = report["measurements"]["portions"]
    assert portion["offset"]["frames"] == 0
    start = portion["a"]["start_frame"]
    assert 0 <= start < 3 * SECOND
    assert len(A) - 8 * SECOND < start + portion["a"]["frames"] <= len(A)


def repeated(section: np.ndarray, second: np.ndarray) -> np.ndarray:
    """B holding a section of A, then other audio, then a second copy."""
    return np.concatenate(
        [
            X[: 5 * SECOND],
            section,
            X[5 * SECOND : 10 * SECOND],
            second,
            X[10 * SECOND : 15 * SECOND],
        ]
    )


def test_compare_ranks_a_noisy_copy_as_an_alternate(
    run: Run, make_set: MakeSet
) -> None:
    section = A[5 * SECOND : 15 * SECOND]
    hiss = quantized(noise(10, seed=3), 16) / 32768 / 10  # 20 dB below the section
    b = repeated(section, section + hiss)

    code, report = compare_signals(
        run, make_set, A[: 20 * SECOND], lambda source: write_b(source, b, "16-bit")
    )

    assert code == 0
    portions = report["measurements"]["portions"]
    assert [p["rank"] for p in portions] == ["primary", "alternate"]
    exact, noisy = portions
    assert exact["offset"]["frames"] == 0
    assert noisy["offset"]["frames"] == 15 * SECOND
    for portion in portions:
        start = portion["a"]["start_frame"]
        assert abs(start - 5 * SECOND) <= BOUNDARY_FRAMES
        assert abs(start + portion["a"]["frames"] - 15 * SECOND) <= BOUNDARY_FRAMES
    assert noisy["block_gain_residual_db"] == pytest.approx(-20, abs=1)
    assert noisy["block_gain_residual_db"] > exact.get("block_gain_residual_db", -200)


def test_compare_gives_two_exact_copies_as_two_primaries(
    run: Run, make_set: MakeSet
) -> None:
    section = A[5 * SECOND : 15 * SECOND]

    code, report = compare_signals(
        run,
        make_set,
        A[: 20 * SECOND],
        lambda source: write_b(source, repeated(section, section), "16-bit"),
    )

    assert code == 0
    portions = report["measurements"]["portions"]
    assert [p["rank"] for p in portions] == ["primary", "primary"]
    assert sorted(p["offset"]["frames"] for p in portions) == [0, 15 * SECOND]
    for portion in portions:
        assert portion["absent"] == {
            "block_gain_residual_db": (
                "A minus B after the per-block gains is zero throughout the portion"
            )
        }


@pytest.mark.parametrize(
    ("a", "b", "reason"),
    [
        (A[: 10 * SECOND], X[: 10 * SECOND], "no portion was found"),
        (A[: 3 * SECOND], A[: 3 * SECOND], "track A is shorter than one window of 5 s"),
        (
            A[: 10 * SECOND],
            A[: 4 * SECOND],
            "track B is shorter than one window of 5 s",
        ),
    ],
    ids=["unrelated", "A shorter than a window", "B shorter than a window"],
)
def test_compare_finds_no_portion(
    run: Run, make_set: MakeSet, a: np.ndarray, b: np.ndarray, reason: str
) -> None:
    # At 24 bits, B's Audio Digest differs from A's even for the same audio.
    code, report = compare_signals(
        run, make_set, a, lambda source: write_b(source, b, "24-bit")
    )

    assert code == 0
    measurements = report["measurements"]
    assert (
        report["inputs"]["a"]["audio_digest"] != report["inputs"]["b"]["audio_digest"]
    )
    assert measurements["portions"] == []
    assert measurements["absent"] == {"portions": reason}
    # With no portion, all of each track is unmatched.
    for name, samples in (("a", a), ("b", b)):
        [unmatched] = measurements["unmatched"][name]
        assert (unmatched["start_frame"], unmatched["frames"]) == (0, len(samples))


def test_compare_places_an_end_where_the_tracks_stop(
    run: Run, make_set: MakeSet
) -> None:
    # Two windows of the coarse search exactly, so that the core of the portion
    # reaches the end of both tracks. B loses its last 100 frames, too few for the
    # block holding them to refute the match: only the end's placement to the frame
    # leaves them out.
    frames = 2 * round(5 * SECOND / 16) * 16
    b = A[:frames].copy()
    b[-100:] = 0

    code, report = compare_signals(
        run, make_set, A[:frames], lambda source: write_b(source, b, "16-bit")
    )

    assert code == 0
    assert_found(report, [Expected(0, frames - 100, 0)])


def test_compare_finds_a_quiet_portion_among_loud_audio(
    run: Run, make_set: MakeSet
) -> None:
    # The quiet copy of A is 55 dB below the rest of B.
    b = np.concatenate([X, A[: 10 * SECOND] * 10 ** (-55 / 20)])

    code, report = compare_signals(
        run, make_set, A[: 10 * SECOND], lambda source: write_b(source, b, "24-bit")
    )

    assert code == 0
    assert_found(report, [Expected(0, 10 * SECOND, len(X))])


def test_compare_finds_a_portion_at_a_low_sample_rate(
    run: Run, make_set: MakeSet
) -> None:
    # At 256 Hz, a window of 5 s holds fewer frames than one block.
    samples = np.random.default_rng(4).integers(
        -20000, 20000, (6 * 256, 2), dtype=np.int32
    )
    first = make_set(
        lambda source: write_audio(source / "a.wav", samples, 16, "WAV", 256)
    )
    second = make_set(
        lambda source: write_audio(source / "b.wav", samples << 8, 24, "WAV", 256)
    )

    outcome = run(
        "compare", first / "data/Album/a.wav", second / "data/Album/b.wav", "--json"
    )

    assert outcome.code == 0, outcome.err
    [portion] = json.loads(outcome.out)["measurements"]["portions"]
    assert portion["a"] == {"start_frame": 0, "frames": 6 * 256}
    assert portion["offset"]["frames"] == 0


def test_compare_finds_no_portion_where_a_window_holds_no_decimated_frame(
    run: Run, make_set: MakeSet
) -> None:
    samples = np.random.default_rng(5).integers(-20000, 20000, (12, 2), dtype=np.int32)
    first = make_set(
        lambda source: write_audio(source / "a.wav", samples, 16, "WAV", 1)
    )
    second = make_set(
        lambda source: write_audio(source / "b.wav", samples << 8, 24, "WAV", 1)
    )

    outcome = run(
        "compare", first / "data/Album/a.wav", second / "data/Album/b.wav", "--json"
    )

    assert outcome.code == 0, outcome.err
    measurements = json.loads(outcome.out)["measurements"]
    assert measurements["portions"] == []
    assert measurements["absent"] == {"portions": "no portion was found"}


def level_dbfs(samples: np.ndarray) -> float:
    """The mean power of all samples of all channels, in dB relative to full scale."""
    return 10 * math.log10(float(np.mean(np.square(samples))))


def test_compare_reports_the_audio_only_one_track_holds(
    run: Run, make_set: MakeSet
) -> None:
    shared = A[: 10 * SECOND]
    only_a = X[: 3 * SECOND] / 4
    only_b = X[5 * SECOND : 8 * SECOND] / 2
    silence = np.zeros((2 * SECOND, 2))

    code, report = compare_signals(
        run,
        make_set,
        np.concatenate([shared, only_a]),
        lambda source: write_b(
            source, np.concatenate([silence, shared, only_b]), "16-bit"
        ),
    )

    assert code == 0
    measurements = report["measurements"]
    [portion] = measurements["portions"]
    assert portion["offset"]["frames"] == 2 * SECOND
    assert portion["a"]["start_frame"] == 0
    end = portion["a"]["frames"]
    assert abs(end - 10 * SECOND) <= BOUNDARY_FRAMES
    [in_a] = measurements["unmatched"]["a"]
    assert in_a == {
        "start_frame": end,
        "frames": 13 * SECOND - end,
        "digitally_silent": False,
        "level_dbfs": pytest.approx(level_dbfs(only_a), abs=0.05),
    }
    assert measurements["unmatched"]["b"] == [
        {"start_frame": 0, "frames": 2 * SECOND, "digitally_silent": True},
        {
            "start_frame": 2 * SECOND + end,
            "frames": 13 * SECOND - end,
            "digitally_silent": False,
            "level_dbfs": pytest.approx(level_dbfs(only_b), abs=0.05),
        },
    ]


def test_compare_gives_identical_audio_one_portion_without_a_search(
    run: Run, make_set: MakeSet
) -> None:
    # Shorter than one window: identical audio still gets its portion.
    samples = quantized(A[: 2 * SECOND], 16)
    first = make_set(lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"))
    second = make_set(lambda source: write_audio(source / "b.wav", samples, 16, "WAV"))

    outcome = run(
        "compare", first / "data/Album/a.flac", second / "data/Album/b.wav", "--json"
    )

    assert outcome.code == 0, outcome.err
    measurements = json.loads(outcome.out)["measurements"]
    assert measurements["identical_audio"] is True
    [portion] = measurements["portions"]
    assert {key: portion[key] for key in ("rank", "a", "b", "offset", "absent")} == {
        "rank": "primary",
        "a": {"start_frame": 0, "frames": 2 * SECOND},
        "b": {"start_frame": 0, "frames": 2 * SECOND},
        "offset": {"frames": 0, "seconds": 0.0},
        "absent": {"block_gain_residual_db": "the audio is identical"},
    }
    for values in [portion["downmix"], *portion["channels"]]:
        assert values["correlation"] == 1
        assert values["gain_db"] == 0
        assert values["absent"] == {
            "residual_db": "the audio is identical",
            "residual_windows": "the audio is identical",
        }
    assert measurements["unmatched"] == {"a": [], "b": []}
    assert "absent" not in measurements


def long_tracks() -> dict[str, Any]:
    """DISC with a second track of six seconds."""
    tracks = [dict(track) for track in DISC["tracks"]]
    tracks[1]["frames"] = 450 * SECTOR_FRAMES
    return {"tracks": tracks}


def test_compare_finds_a_track_of_an_acquired_set(
    run: Run,
    make_set: MakeSet,
    make_acquired_set: Callable[..., Path],
    redumper: StandIn,
) -> None:
    acquired = make_acquired_set(**long_tracks())
    data = synthetic_disc(redumper.config).tracks[1]
    track = np.frombuffer(data, dtype="<i2").reshape(-1, 2).astype(np.int32)
    lead = quantized(X[:12345], 16)
    album = make_set(
        lambda source: write_audio(
            source / "02.flac", np.concatenate([lead, track]), 16, "FLAC"
        )
    )

    outcome = run(
        "compare", acquired, album / "data/Album/02.flac", "--track-a", "2", "--json"
    )

    assert outcome.code == 0, outcome.err
    measurements = json.loads(outcome.out)["measurements"]
    [portion] = measurements["portions"]
    assert portion["offset"]["frames"] == 12345
    assert portion["a"] == {"start_frame": 0, "frames": len(track)}
    assert measurements["unmatched"]["a"] == []
    [lead_in] = measurements["unmatched"]["b"]
    assert (lead_in["start_frame"], lead_in["frames"]) == (0, 12345)


def test_compare_finds_a_track_in_its_disc_image(
    run: Run, make_acquired_set: Callable[..., Path]
) -> None:
    acquired = make_acquired_set(**long_tracks())
    record = json.loads((acquired / "copyofa/acquisition-record.json").read_bytes())
    recorded = record["tracks"][1]

    outcome = run(
        "compare",
        acquired,
        acquired / "data/disc.scram.flac",
        "--track-a",
        "2",
        "--json",
    )

    assert outcome.code == 0, outcome.err
    portions = json.loads(outcome.out)["measurements"]["portions"]
    [portion] = [p for p in portions if p["rank"] == "primary"]
    assert portion["a"] == {"start_frame": 0, "frames": recorded["frame_count"]}
    assert portion["b"] == {
        "start_frame": recorded["first_frame"],
        "frames": recorded["frame_count"],
    }
