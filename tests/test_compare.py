from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soundfile
import soxr
from conftest import RATE, requires_permissions, signal, snapshot, write_audio

import copyofa
from copyofa import comparator, inspector

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Outcome, Run

    MakeSet = Callable[[Callable[[Path], None]], Path]

MEASURED = ("correlation", "gain_db", "residual_db", "residual_windows")


def tones(rate: int, seconds: float, seed: int = 7) -> np.ndarray:
    """A band-limited stereo signal, below 8 kHz, that does not repeat.

    Defined as a sum of sines, so it can be sampled at any rate.
    """
    rng = np.random.default_rng(seed)
    frequencies = rng.uniform(50, 8000, size=(40, 2))
    phases = rng.uniform(0, 2 * np.pi, size=(40, 2))
    time = np.arange(round(rate * seconds))[:, None, None] / rate
    samples = np.sin(2 * np.pi * frequencies * time + phases).sum(axis=1)
    # A fixed scale, not the sampled peak, which depends on the rate.
    return samples * (0.9 / len(frequencies))


def compare(run: Run, a: Path, b: Path, *options: str) -> tuple[Outcome, dict]:
    outcome = run("compare", a, b, "--json", *options)
    report = json.loads(outcome.out) if outcome.out else {}
    return outcome, report


def two_sets(
    make_set: MakeSet, a: Callable[[Path], None], b: Callable[[Path], None]
) -> tuple[Path, Path]:
    return make_set(a) / "data/Album", make_set(b) / "data/Album"


@pytest.mark.parametrize("delay", [12345, -12345])
def test_compare_finds_the_exact_offset(
    run: Run, make_set: MakeSet, delay: int
) -> None:
    samples = signal(2 * RATE, 2, 16)
    delayed = np.vstack([np.zeros((abs(delay), 2), np.int32), samples])
    later, earlier = (delayed, samples) if delay > 0 else (samples, delayed)

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", earlier, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", later, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    measurements = report["measurements"]
    assert measurements["offset"] == {"frames": delay, "seconds": delay / RATE}
    assert measurements["overlap"] == {
        "a": {
            "start_frame": max(0, -delay),
            "frames": 2 * RATE,
            "fraction": 2 * RATE / len(earlier),
        },
        "b": {
            "start_frame": max(0, delay),
            "frames": 2 * RATE,
            "fraction": 2 * RATE / len(later),
        },
    }
    assert measurements["downmix"]["correlation"] == pytest.approx(1)


def test_compare_measures_gain_and_residual(run: Run, make_set: MakeSet) -> None:
    # Two and a half seconds, so the last residual window is half a second.
    samples = signal(5 * RATE // 2, 2, 16)

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", samples >> 1, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    measurements = report["measurements"]
    for values in [measurements["downmix"], *measurements["channels"]]:
        # B is A at half amplitude, so A is twice B: +6.02 dB.
        assert values["gain_db"] == pytest.approx(20 * math.log10(2), abs=0.01)
        assert values["residual_db"] < -60
        windows = values["residual_windows"]
        assert [(window["start_frame"], window["frames"]) for window in windows] == [
            (0, RATE),
            (RATE, RATE),
            (2 * RATE, RATE // 2),
        ]
        assert all(window["residual_db"] < -60 for window in windows)
    assert len(measurements["channels"]) == 2
    assert "identical_audio" not in measurements


def test_compare_reports_identical_audio(run: Run, make_set: MakeSet) -> None:
    samples = signal(RATE, 2, 16)

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.wav", samples, 16, "WAV"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.wav")

    assert outcome.code == 0, outcome.err
    inputs = report["inputs"]
    assert inputs["a"]["audio_digest"] == inputs["b"]["audio_digest"]
    measurements = report["measurements"]
    assert measurements["identical_audio"] is True
    assert measurements["offset"] == {"frames": 0, "seconds": 0.0}
    for values in [measurements["downmix"], *measurements["channels"]]:
        assert values["gain_db"] == 0
        assert values["correlation"] == 1
        assert "residual_db" not in values
        assert values["absent"] == {
            "residual_db": "the audio is identical",
            "residual_windows": "the audio is identical",
        }


def test_compare_resamples_to_the_lower_rate(run: Run, make_set: MakeSet) -> None:
    def fill_a(source: Path) -> None:
        soundfile.write(source / "a.flac", tones(48000, 3), 48000, subtype="PCM_24")

    def fill_b(source: Path) -> None:
        soundfile.write(source / "b.flac", tones(44100, 3), 44100, subtype="PCM_24")

    a, b = two_sets(make_set, fill_a, fill_b)
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    assert report["method"]["common_sample_rate"] == 44100
    measurements = report["measurements"]
    assert abs(measurements["offset"]["frames"]) <= 1
    assert measurements["downmix"]["correlation"] > 0.99


def test_compare_measures_lossy_audio(run: Run, make_set: MakeSet) -> None:
    samples = tones(RATE, 3)

    def fill_a(source: Path) -> None:
        soundfile.write(source / "a.flac", samples, RATE, subtype="PCM_16")

    def fill_b(source: Path) -> None:
        soundfile.write(
            source / "b.mp3", samples, RATE, format="MP3", subtype="MPEG_LAYER_III"
        )

    a, b = two_sets(make_set, fill_a, fill_b)
    outcome, report = compare(run, a / "a.flac", b / "b.mp3")

    assert outcome.code == 0, outcome.err
    assert report["measurements"]["downmix"]["correlation"] > 0.9
    assert "audio_digest" not in report["inputs"]["b"]


def test_compare_measures_unrelated_audio(run: Run, make_set: MakeSet) -> None:
    first, second = signal(RATE, 2, 16, seed=1), signal(RATE, 2, 16, seed=2)
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", first, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", second, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    assert abs(report["measurements"]["downmix"]["correlation"]) < 0.1


def test_compare_aligns_a_polarity_inversion(run: Run, make_set: MakeSet) -> None:
    # Halved, so that negating the 16-bit minimum stays in range.
    samples = signal(RATE, 2, 16) >> 1

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", -samples, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    measurements = report["measurements"]
    assert measurements["offset"]["frames"] == 0
    assert measurements["downmix"]["correlation"] == pytest.approx(-1)
    assert measurements["downmix"]["gain_db"] == pytest.approx(0, abs=1e-9)


def _reject_constant(name: str) -> Any:
    pytest.fail(f"the JSON holds {name}")


def test_compare_gives_undefined_values_as_absent(run: Run, make_set: MakeSet) -> None:
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", signal(RATE, 2, 16), 16, "FLAC"),
        lambda source: write_audio(
            source / "b.flac", np.zeros((RATE, 2), np.int32), 16, "FLAC"
        ),
    )
    outcome = run("compare", a / "a.flac", b / "b.flac", "--json")

    assert outcome.code == 0, outcome.err
    report = json.loads(outcome.out, parse_constant=_reject_constant)
    measurements = report["measurements"]
    reason = "no offset was found: the downmix of track B is zero throughout"
    assert measurements["absent"] == {"offset": reason, "overlap": reason}
    for values in [measurements["downmix"], *measurements["channels"]]:
        assert values == {"absent": dict.fromkeys(MEASURED, reason)}


def test_compare_gives_values_undefined_over_the_overlap_as_absent(
    run: Run, make_set: MakeSet
) -> None:
    # The left channels align the tracks; B's right channel is silent.
    samples = signal(RATE, 2, 16)
    silent_right = samples.copy()
    silent_right[:, 1] = 0

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", silent_right, 16, "FLAC"),
    )
    outcome = run("compare", a / "a.flac", b / "b.flac", "--json")

    assert outcome.code == 0, outcome.err
    report = json.loads(outcome.out, parse_constant=_reject_constant)
    left, right = report["measurements"]["channels"]
    assert left["correlation"] == 1
    assert right["absent"] == {
        "correlation": "track B is constant over the overlap",
        "gain_db": "track B is zero throughout the overlap",
        "residual_db": (
            "the gain is undefined: track B is zero throughout the overlap"
        ),
        "residual_windows": (
            "the gain is undefined: track B is zero throughout the overlap"
        ),
    }


def test_compare_gives_values_absent_for_identical_tracks_without_frames(
    run: Run, make_set: MakeSet
) -> None:
    track = make_set(
        lambda source: write_audio(
            source / "empty.wav", np.zeros((0, 2), np.int32), 16, "WAV"
        )
    )
    empty = track / "data/Album/empty.wav"

    outcome = run("compare", empty, empty, "--json")

    assert outcome.code == 0, outcome.err
    report = json.loads(outcome.out, parse_constant=_reject_constant)
    measurements = report["measurements"]
    assert measurements["identical_audio"] is True
    reason = "no offset was found: track A has no frames"
    assert measurements["absent"] == {"offset": reason, "overlap": reason}
    for values in [measurements["downmix"], *measurements["channels"]]:
        assert values == {"absent": dict.fromkeys(MEASURED, reason)}


def test_compare_downmix_only_for_different_channel_counts(
    run: Run, make_set: MakeSet
) -> None:
    stereo = signal(RATE, 2, 16) >> 1
    mono = stereo.sum(axis=1, keepdims=True, dtype=np.int32) >> 1

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", stereo, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", mono, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    measurements = report["measurements"]
    assert "channels" not in measurements
    assert measurements["absent"] == {
        "channels": "the tracks have different channel counts: 2 and 1"
    }
    assert measurements["downmix"]["correlation"] > 0.99


def test_compare_exits_2_for_a_track_outside_an_evidence_set(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> None:
    inside = make_set(
        lambda source: write_audio(source / "a.flac", signal(100, 1, 16), 16, "FLAC")
    )
    loose = tmp_path / "loose.flac"
    write_audio(loose, signal(100, 1, 16), 16, "FLAC")

    for a, b in [
        (inside / "data/Album/a.flac", loose),
        (inside / "data/Album/a.flac", inside / "bagit.txt"),
    ]:
        outcome = run("compare", a, b, "--json")
        assert outcome.code == 2
        assert outcome.out == ""
    assert "is not inside an Evidence Set" in run("compare", loose, loose).err
    assert (
        "is not under the data/ directory"
        in run("compare", inside / "data/Album/a.flac", inside / "bagit.txt").err
    )


def test_compare_exits_2_without_two_tracks(run: Run) -> None:
    outcome = run("compare", "only-one.flac")

    assert outcome.code == 2
    assert outcome.out == ""


def test_compare_reports_inputs_it_cannot_compare(run: Run, make_set: MakeSet) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "a.flac", signal(1000, 2, 16), 16, "FLAC")
        write_audio(source / "modified.flac", signal(1000, 2, 16), 16, "FLAC")
        (source / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" * 50)

    evidence_set = make_set(fill)
    album = evidence_set / "data/Album"
    with (album / "modified.flac").open("r+b") as file:
        file.seek(-1, 2)
        file.write(b"\x00" if file.read(1) != b"\x00" else b"\x01")
    write_audio(album / "unlisted.flac", signal(1000, 2, 16), 16, "FLAC")

    expected = {
        "modified.flac": (
            inspector.NOT_INSPECTED,
            "its digest differs from the manifest's",
        ),
        "unlisted.flac": (
            inspector.NOT_INSPECTED,
            "manifest-sha256.txt does not list it",
        ),
        "cover.jpg": (
            inspector.NOT_INTERPRETED,
            "no supported audio format was recognized",
        ),
    }
    for name, (outcome_expected, reason) in expected.items():
        outcome, report = compare(run, album / "a.flac", album / name)
        assert outcome.code == 1, name
        entry = report["inputs"]["b"]
        assert (entry["outcome"], entry["reason"]) == (outcome_expected, reason)
        assert "measurements" not in report
        assert "common_sample_rate" not in report["method"]

        human = run("compare", album / "a.flac", album / name)
        assert human.code == 1
        lines = human.out.splitlines()
        outcome_text = outcome_expected.replace("_", " ")
        assert lines[1].endswith(f"({outcome_text}: {reason})")
        assert lines[2:] == ["Not compared: an input was not interpreted"]


@requires_permissions
def test_compare_finds_a_set_whose_root_cannot_be_searched(
    run: Run, make_set: MakeSet
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "a.flac", signal(1000, 2, 16), 16, "FLAC")

    evidence_set = make_set(fill)
    track = evidence_set / "data/Album/a.flac"
    evidence_set.chmod(0)
    try:
        outcome, report = compare(run, track, track)
    finally:
        evidence_set.chmod(0o755)

    # As inspect does: the set's records cannot be read, so it is not inspected.
    assert outcome.code == 1
    for entry in report["inputs"].values():
        assert entry["evidence_set"] == str(evidence_set)
        assert entry["reason"] == "the Integrity Baseline is unusable"


def test_compare_inspects_nothing_with_an_unusable_baseline(
    run: Run, make_set: MakeSet
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "a.flac", signal(1000, 2, 16), 16, "FLAC")

    evidence_set = make_set(fill)
    (evidence_set / "tagmanifest-sha256.txt").unlink()
    track = evidence_set / "data/Album/a.flac"

    outcome, report = compare(run, track, track)

    assert outcome.code == 1
    for entry in report["inputs"].values():
        assert entry["outcome"] == inspector.NOT_INSPECTED
        assert entry["reason"] == "the Integrity Baseline is unusable"
        assert entry["integrity_baseline"]["usable"] is False


def test_compare_report_content(run: Run, make_set: MakeSet) -> None:
    samples = signal(RATE, 2, 16)
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", samples >> 1, 16, "FLAC"),
    )
    before = datetime.now(UTC).replace(microsecond=0)

    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    after = datetime.now(UTC)
    assert outcome.code == 0, outcome.err
    assert outcome.err.splitlines() == [
        "Inspected data/Album/a.flac: interpreted",
        "Inspected data/Album/b.flac: interpreted",
    ]
    assert report["report_kind"] == "copyofa.comparison"
    assert report["format_version"] == 2
    assert report["omitted"] == []
    assert report["copyofa_version"] == copyofa.__version__
    compared_at = datetime.strptime(
        report["compared_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=UTC)
    assert before <= compared_at <= after + timedelta(seconds=1)
    for name, album in (("a", a), ("b", b)):
        entry = report["inputs"][name]
        root = album.parent.parent
        manifest = (root / "manifest-sha256.txt").read_bytes()
        file_digest = hashlib.sha256((album / f"{name}.flac").read_bytes()).hexdigest()
        assert entry["evidence_set"] == str(root)
        assert entry["integrity_baseline"] == {
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "usable": True,
            "problems": [],
        }
        assert entry["path"] == f"data/Album/{name}.flac"
        assert entry["outcome"] == inspector.INTERPRETED
        assert entry["observed_digest"] == file_digest
        assert entry["audio_digest"].startswith("pcm1:44100:2:16:")
        assert (entry["format"], entry["sample_rate"], entry["channels"]) == (
            "flac",
            RATE,
            2,
        )
        assert (entry["bits_per_sample"], entry["frames"]) == (16, RATE)
    assert report["method"] == {
        "decoder": "libsndfile",
        "decoder_version": soundfile.__libsndfile_version__,
        "resampler": "libsoxr",
        "resampler_version": soxr.__libsoxr_version__,
        "resampler_quality": "VHQ",
        "common_sample_rate": RATE,
        "alignment": "downmix_cross_correlation",
    }
    assert report["limitations"] == list(comparator.LIMITATIONS)


def test_compare_omit_locations_leaves_out_where_each_set_is(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> None:
    samples = signal(RATE, 2, 16)
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", samples >> 1, 16, "FLAC"),
    )

    outcome, report = compare(run, a / "a.flac", b / "b.flac", "--omit-locations")

    assert outcome.code == 0, outcome.err
    assert report["format_version"] == 2
    assert report["omitted"] == ["/inputs/a/evidence_set", "/inputs/b/evidence_set"]
    for name in "ab":
        entry = report["inputs"][name]
        assert "evidence_set" not in entry
        assert entry["path"] == f"data/Album/{name}.flac"
        assert entry["integrity_baseline"]["usable"] is True
    # tmp_path holds both sets, so this also covers each set's parent directories.
    assert str(tmp_path) not in outcome.out
    assert outcome.err.splitlines() == [
        "Inspected data/Album/a.flac: interpreted",
        "Inspected data/Album/b.flac: interpreted",
    ]


def test_compare_omit_locations_shows_each_path_in_its_set(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> None:
    samples = signal(RATE, 2, 16)
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.wav", samples >> 1, 16, "WAV"),
    )

    outcome = run("compare", a / "a.flac", b / "b.wav", "--omit-locations")

    assert outcome.code == 0, outcome.err
    lines = outcome.out.splitlines()
    assert lines[0] == (
        "Track A: data/Album/a.flac (flac, 44100 Hz, 16-bit, 2 channels, 0:01.000)"
    )
    assert lines[1] == (
        "Track B: data/Album/b.wav (wav, 44100 Hz, 16-bit, 2 channels, 0:01.000)"
    )
    assert lines[2].startswith("Offset: ")
    assert str(tmp_path) not in outcome.out


def test_compare_omit_locations_with_an_input_that_is_not_inspected(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> None:
    root = make_set(
        lambda source: write_audio(source / "a.flac", signal(100, 1, 16), 16, "FLAC")
    )
    (root / "tagmanifest-sha256.txt").unlink()
    track = root / "data/Album/a.flac"

    json_outcome, report = compare(run, track, track, "--omit-locations")
    human_outcome = run("compare", track, track, "--omit-locations")

    assert json_outcome.code == human_outcome.code == 1
    assert report["omitted"] == ["/inputs/a/evidence_set", "/inputs/b/evidence_set"]
    assert all("evidence_set" not in entry for entry in report["inputs"].values())
    assert str(tmp_path) not in json_outcome.out
    assert str(tmp_path) not in human_outcome.out
    assert human_outcome.out.splitlines()[0].startswith("Track A: data/Album/a.flac ")


def test_compare_human_result(run: Run, make_set: MakeSet) -> None:
    samples = signal(2 * RATE, 2, 16)
    delayed = np.vstack([np.zeros((12345, 2), np.int32), samples >> 1])
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.wav", delayed, 16, "WAV"),
    )

    outcome = run("compare", a / "a.flac", b / "b.wav")

    assert outcome.code == 0, outcome.err
    lines = outcome.out.splitlines()
    assert lines[0] == (
        f"Track A: {a / 'a.flac'} (flac, 44100 Hz, 16-bit, 2 channels, 0:02.000)"
    )
    assert lines[1] == (
        f"Track B: {b / 'b.wav'} (wav, 44100 Hz, 16-bit, 2 channels, 0:02.279)"
    )
    assert lines[2:5] == [
        "Offset: +12345 frames (+0.280 s) at 44100 Hz",
        "Overlap: 100.0% of track A, 87.7% of track B",
        "Correlation: 1.000",
    ]
    assert lines[5] == "Gain: +6.02 dB"
    assert lines[6].startswith("Residual: -")
    assert len(lines) == 7


def test_compare_human_result_names_identical_and_absent_values(
    run: Run, make_set: MakeSet
) -> None:
    track = make_set(
        lambda source: write_audio(
            source / "a.flac", np.zeros((RATE, 1), np.int32), 16, "FLAC"
        )
    )
    a = track / "data/Album/a.flac"

    outcome = run("compare", a, a)

    assert outcome.code == 0, outcome.err
    assert outcome.out.splitlines()[2:] == [
        "Identical audio: the Audio Digests are equal",
        "Offset: +0 frames (+0.000 s) at 44100 Hz",
        "Overlap: 100.0% of track A, 100.0% of track B",
        "Correlation: absent (track A is constant over the overlap)",
        "Gain: absent (track B is zero throughout the overlap)",
        "Residual: absent (the audio is identical)",
    ]


def test_compare_writes_nothing(run: Run, make_set: MakeSet) -> None:
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", signal(RATE, 2, 16), 16, "FLAC"),
        lambda source: write_audio(source / "b.wav", signal(RATE, 2, 16), 16, "WAV"),
    )
    sets = [a.parent.parent, b.parent.parent]
    before = [snapshot(root) for root in sets]

    outcome = run("compare", a / "a.flac", b / "b.wav", "--json")

    assert outcome.code == 0, outcome.err
    assert [snapshot(root) for root in sets] == before


def test_compare_canceled_prints_nothing(
    run: Run, make_set: MakeSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    track = make_set(
        lambda source: write_audio(source / "a.flac", signal(100, 1, 16), 16, "FLAC")
    )
    a = track / "data/Album/a.flac"

    def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(inspector, "_interpret", interrupted)
    outcome = run("compare", a, a, "--json")

    assert outcome.code == 130
    assert outcome.out == ""
    assert "canceled" in outcome.err
