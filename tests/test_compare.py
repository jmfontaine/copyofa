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
from conftest import (
    RATE,
    as_version_1,
    edit_record,
    requires_permissions,
    signal,
    snapshot,
    synthetic_disc,
    write_audio,
)

import copyofa
from copyofa import comparator, inspector, locator

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Outcome, Run, StandIn

    MakeSet = Callable[[Callable[[Path], None]], Path]


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


def only_portion(report: dict[str, Any]) -> dict[str, Any]:
    [portion] = report["measurements"]["portions"]
    return portion


@pytest.mark.parametrize("delay", [12345, -12345])
def test_compare_finds_the_exact_offset(
    run: Run, make_set: MakeSet, delay: int
) -> None:
    # Eleven seconds: a window of A is searched only where B holds all of it, so
    # with the leading silence in A, the first window of A gives no candidate.
    samples = signal(11 * RATE, 2, 16)
    delayed = np.vstack([np.zeros((abs(delay), 2), np.int32), samples])
    later, earlier = (delayed, samples) if delay > 0 else (samples, delayed)

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", earlier, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", later, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    portion = only_portion(report)
    assert portion["rank"] == "primary"
    assert portion["offset"] == {"frames": delay, "seconds": delay / RATE}
    assert portion["a"] == {"start_frame": max(0, -delay), "frames": 11 * RATE}
    assert portion["b"] == {"start_frame": max(0, delay), "frames": 11 * RATE}
    assert portion["downmix"]["correlation"] == pytest.approx(1)
    # The leading silence is all that the portion leaves out.
    unmatched = report["measurements"]["unmatched"]
    silence = [{"start_frame": 0, "frames": abs(delay), "digitally_silent": True}]
    assert unmatched == {
        "a": [] if delay > 0 else silence,
        "b": silence if delay > 0 else [],
    }


def test_compare_measures_gain_and_residual(run: Run, make_set: MakeSet) -> None:
    # Five and a half seconds, so the last residual window is half a second.
    samples = signal(11 * RATE // 2, 2, 16)

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", samples >> 1, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    portion = only_portion(report)
    assert portion["block_gain_residual_db"] < -60
    for values in [portion["downmix"], *portion["channels"]]:
        # B is A at half amplitude, so A is twice B: +6.02 dB.
        assert values["gain_db"] == pytest.approx(20 * math.log10(2), abs=0.01)
        assert values["residual_db"] < -60
        windows = values["residual_windows"]
        assert [(window["start_frame"], window["frames"]) for window in windows] == [
            *((second * RATE, RATE) for second in range(5)),
            (5 * RATE, RATE // 2),
        ]
        assert all(window["residual_db"] < -60 for window in windows)
    assert len(portion["channels"]) == 2
    assert "identical_audio" not in report["measurements"]


def test_compare_resamples_to_the_lower_rate(run: Run, make_set: MakeSet) -> None:
    def fill_a(source: Path) -> None:
        soundfile.write(source / "a.flac", tones(48000, 6), 48000, subtype="PCM_24")

    def fill_b(source: Path) -> None:
        soundfile.write(source / "b.flac", tones(44100, 6), 44100, subtype="PCM_24")

    a, b = two_sets(make_set, fill_a, fill_b)
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    assert report["method"]["common_sample_rate"] == 44100
    [portion] = [
        portion
        for portion in report["measurements"]["portions"]
        if portion["rank"] == "primary"
    ]
    assert abs(portion["offset"]["frames"]) <= 1
    assert portion["downmix"]["correlation"] > 0.99


def test_compare_measures_lossy_audio(run: Run, make_set: MakeSet) -> None:
    samples = tones(RATE, 6)

    def fill_a(source: Path) -> None:
        soundfile.write(source / "a.flac", samples, RATE, subtype="PCM_16")

    def fill_b(source: Path) -> None:
        soundfile.write(
            source / "b.mp3", samples, RATE, format="MP3", subtype="MPEG_LAYER_III"
        )

    a, b = two_sets(make_set, fill_a, fill_b)
    outcome, report = compare(run, a / "a.flac", b / "b.mp3")

    assert outcome.code == 0, outcome.err
    primaries = [
        portion
        for portion in report["measurements"]["portions"]
        if portion["rank"] == "primary"
    ]
    assert primaries
    assert all(portion["downmix"]["correlation"] > 0.9 for portion in primaries)
    assert "audio_digest" not in report["inputs"]["b"]


def test_compare_aligns_a_polarity_inversion(run: Run, make_set: MakeSet) -> None:
    # Halved, so that negating the 16-bit minimum stays in range.
    samples = signal(6 * RATE, 2, 16) >> 1

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", -samples, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    portion = only_portion(report)
    assert portion["offset"]["frames"] == 0
    assert portion["downmix"]["correlation"] == pytest.approx(-1)
    assert portion["downmix"]["gain_db"] == pytest.approx(0, abs=1e-9)


def _reject_constant(name: str) -> Any:
    pytest.fail(f"the JSON holds {name}")


def test_compare_finds_no_portion_in_a_silent_track(
    run: Run, make_set: MakeSet
) -> None:
    a, b = two_sets(
        make_set,
        lambda source: write_audio(
            source / "a.flac", signal(6 * RATE, 2, 16), 16, "FLAC"
        ),
        lambda source: write_audio(
            source / "b.flac", np.zeros((6 * RATE, 2), np.int32), 16, "FLAC"
        ),
    )
    outcome = run("compare", a / "a.flac", b / "b.flac", "--json")

    assert outcome.code == 0, outcome.err
    report = json.loads(outcome.out, parse_constant=_reject_constant)
    measurements = report["measurements"]
    assert measurements["portions"] == []
    assert measurements["absent"] == {
        "portions": "the downmix of track B is zero throughout"
    }
    assert measurements["unmatched"]["b"] == [
        {"start_frame": 0, "frames": 6 * RATE, "digitally_silent": True}
    ]


def test_compare_gives_values_undefined_over_a_portion_as_absent(
    run: Run, make_set: MakeSet
) -> None:
    # Both channels of A are the same, so A's downmix is B's, at twice the level;
    # B's right channel is silent.
    left = signal(6 * RATE, 1, 16)
    samples = np.hstack([left, left])
    silent_right = np.hstack([left, np.zeros_like(left)])

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", silent_right, 16, "FLAC"),
    )
    outcome = run("compare", a / "a.flac", b / "b.flac", "--json")

    assert outcome.code == 0, outcome.err
    report = json.loads(outcome.out, parse_constant=_reject_constant)
    left_values, right_values = only_portion(report)["channels"]
    assert left_values["correlation"] == 1
    assert right_values["absent"] == {
        "correlation": "track B is constant over the portion",
        "gain_db": "track B is zero throughout the portion",
        "residual_db": (
            "the gain is undefined: track B is zero throughout the portion"
        ),
        "residual_windows": (
            "the gain is undefined: track B is zero throughout the portion"
        ),
    }


def test_compare_finds_no_portion_in_identical_tracks_without_frames(
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
    assert report["measurements"] == {
        "identical_audio": True,
        "portions": [],
        "unmatched": {"a": [], "b": []},
        "absent": {"portions": "track A has no frames"},
    }


def test_compare_downmix_only_for_different_channel_counts(
    run: Run, make_set: MakeSet
) -> None:
    stereo = signal(6 * RATE, 2, 16) >> 1
    mono = stereo.sum(axis=1, keepdims=True, dtype=np.int32) >> 1

    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", stereo, 16, "FLAC"),
        lambda source: write_audio(source / "b.flac", mono, 16, "FLAC"),
    )
    outcome, report = compare(run, a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    portion = only_portion(report)
    assert "channels" not in portion
    assert portion["absent"] == {
        "channels": "the tracks have different channel counts: 2 and 1"
    }
    assert portion["downmix"]["correlation"] > 0.99


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
    assert report["format_version"] == 6
    assert report["scope"] == "tracks"
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
    # The schema pins each parameter to the value ADR 0006 decides.
    assert set(report["method"].pop("parameters")) == set(locator.PARAMETERS)
    assert report["method"] == {
        "decoder": "libsndfile",
        "decoder_version": soundfile.__libsndfile_version__,
        "resampler": "libsoxr",
        "resampler_version": soxr.__libsoxr_version__,
        "resampler_quality": "VHQ",
        "common_sample_rate": RATE,
        "alignment": "windowed_portions",
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
    assert report["format_version"] == 6
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
    assert lines[2] == "Common sample rate: 44100 Hz"
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
    samples = signal(11 * RATE, 2, 16)
    tail = signal(2 * RATE, 2, 16, seed=5) >> 3
    delayed = np.vstack([np.zeros((12345, 2), np.int32), samples >> 1, tail])
    a, b = two_sets(
        make_set,
        lambda source: write_audio(source / "a.flac", samples, 16, "FLAC"),
        lambda source: write_audio(source / "b.wav", delayed, 16, "WAV"),
    )

    outcome = run("compare", a / "a.flac", b / "b.wav")

    assert outcome.code == 0, outcome.err
    lines = outcome.out.splitlines()
    assert lines[0] == (
        f"Track A: {a / 'a.flac'} (flac, 44100 Hz, 16-bit, 2 channels, 0:11.000)"
    )
    assert lines[1] == (
        f"Track B: {b / 'b.wav'} (wav, 44100 Hz, 16-bit, 2 channels, 0:13.279)"
    )
    assert lines[2] == "Common sample rate: 44100 Hz"
    assert lines[3].startswith(
        "Portion 1, primary: A 0.000-11.000 s, B 0.280-11.280 s, "
        "offset +12345 frames (+0.280 s), correlation 1.000, residual (one gain) -"
    )
    assert lines[3].endswith(" dB")
    level = 10 * math.log10(np.mean(np.square(tail / 32768)))
    assert lines[4:] == [
        "Unmatched in B: 0.000-0.280 s, digital silence",
        f"Unmatched in B: 11.280-13.280 s, {level:.1f} dBFS",
    ]


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
        "Common sample rate: 44100 Hz",
        "Identical audio: the Audio Digests are equal",
        (
            "Portion 1, primary: A 0.000-1.000 s, B 0.000-1.000 s, "
            "offset +0 frames (+0.000 s), "
            "correlation absent (track A is constant over the portion), "
            "residual (one gain) absent (the audio is identical)"
        ),
    ]


def test_compare_human_result_names_why_no_portion_was_found(
    run: Run, make_set: MakeSet
) -> None:
    a, b = two_sets(
        make_set,
        lambda source: write_audio(
            source / "a.flac", signal(RATE, 2, 16, seed=1), 16, "FLAC"
        ),
        lambda source: write_audio(
            source / "b.flac", signal(RATE, 2, 16, seed=2), 16, "FLAC"
        ),
    )

    outcome = run("compare", a / "a.flac", b / "b.flac")

    assert outcome.code == 0, outcome.err
    assert outcome.out.splitlines()[2:] == [
        "Common sample rate: 44100 Hz",
        "No portion found: track A is shorter than one window of 5 s",
        "Unmatched in A: 0.000-1.000 s, -4.8 dBFS",
        "Unmatched in B: 0.000-1.000 s, -4.8 dBFS",
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


def track_samples(redumper: StandIn, number: int) -> np.ndarray:
    """The samples of a track of the synthetic disc, as write_audio takes them."""
    data = synthetic_disc(redumper.config).tracks[number - 1]
    return np.frombuffer(data, dtype="<i2").reshape(-1, 2).astype(np.int32)


def test_compare_measures_a_track_of_an_acquired_set(
    run: Run,
    make_set: MakeSet,
    redumper: StandIn,
    acquired_set: Path,
) -> None:
    samples = track_samples(redumper, 2)
    album = make_set(
        lambda source: write_audio(source / "02.flac", samples, 16, "FLAC", 44100)
    )

    outcome, report = compare(
        run, acquired_set, album / "data/Album/02.flac", "--track-a", "2"
    )

    assert outcome.code == 0, outcome.err
    assert report["format_version"] == 6
    record = json.loads((acquired_set / "copyofa/acquisition-record.json").read_bytes())
    recorded = record["tracks"][1]
    a = report["inputs"]["a"]
    image_digest = next(
        line.split("  ")[0]
        for line in (acquired_set / "manifest-sha256.txt").read_text().splitlines()
        if line.endswith("  data/disc.scram.flac")
    )
    assert {key: a[key] for key in ("path", "track", "outcome", "expected_digest")} == {
        "path": "data/disc.scram.flac",
        "track": {
            "number": 2,
            "first_frame": recorded["first_frame"],
            "frame_count": recorded["frame_count"],
            "error_ranges": [],
        },
        "outcome": "interpreted",
        "expected_digest": image_digest,
    }
    assert a["observed_digest"] == a["expected_digest"]
    assert a["audio_digest"] == recorded["audio_digest"]
    assert a["frames"] == len(samples)
    assert "flac_md5_signature" not in a
    assert "track" not in report["inputs"]["b"]
    assert report["measurements"]["identical_audio"] is True
    text = run("compare", acquired_set, album / "data/Album/02.flac", "--track-a", "2")
    assert f"Track A: track 2 of {acquired_set} (flac, 44100 Hz" in text.out


def test_compare_measures_two_tracks_of_acquired_sets(
    run: Run, acquired_set: Path
) -> None:
    outcome, report = compare(
        run, acquired_set, acquired_set, "--track-a", "1", "--track-b", "3"
    )

    assert outcome.code == 0, outcome.err
    assert [report["inputs"][name]["track"]["number"] for name in "ab"] == [1, 3]
    assert "identical_audio" not in report["measurements"]


def test_compare_records_the_error_ranges_of_each_track(
    run: Run, acquired_set: Path, damaged_set: Path
) -> None:
    outcome, report = compare(
        run, damaged_set, acquired_set, "--track-a", "2", "--track-b", "2"
    )
    unaffected, _ = compare(
        run, acquired_set, acquired_set, "--track-a", "2", "--track-b", "2"
    )

    assert outcome.code == unaffected.code == 0, outcome.err
    assert report["format_version"] == 6
    record = json.loads((damaged_set / "copyofa/acquisition-record.json").read_bytes())
    assert report["inputs"]["a"]["track"]["error_ranges"] == [
        {"offset_frames": 100, "frame_count": 37, "state": "not_read"},
        {"offset_frames": 300, "frame_count": 1, "state": "c2_error"},
        {"offset_frames": 301, "frame_count": 1, "state": "not_read"},
        {"offset_frames": 500, "frame_count": 24, "state": "c2_error"},
    ]
    assert (
        report["inputs"]["a"]["track"]["error_ranges"]
        == (record["tracks"][1]["error_ranges"])
    )
    assert report["inputs"]["b"]["track"]["error_ranges"] == []


def test_compare_records_no_error_ranges_from_a_version_1_record(
    run: Run, damaged_set: Path
) -> None:
    as_version_1(damaged_set)

    outcome, report = compare(
        run, damaged_set, damaged_set, "--track-a", "1", "--track-b", "2"
    )

    assert outcome.code == 0, outcome.err
    assert report["format_version"] == 6
    for name in "ab":
        assert report["inputs"][name]["outcome"] == "interpreted"
        assert "error_ranges" not in report["inputs"][name]["track"]


def test_compare_does_not_inspect_a_track_it_cannot_find(
    run: Run, make_set: MakeSet, acquired_set: Path
) -> None:
    imported = make_set(
        lambda source: write_audio(source / "a.flac", signal(1000, 2, 16), 16, "FLAC")
    )

    outcome, report = compare(
        run, acquired_set, imported, "--track-a", "9", "--track-b", "1"
    )

    assert outcome.code == 1
    a, b = report["inputs"]["a"], report["inputs"]["b"]
    assert (a["path"], a["track"], a["outcome"], a["reason"]) == (
        "data/disc.scram.flac",
        {"number": 9},
        "not_inspected",
        "the Acquisition Record lists no track 9",
    )
    assert "observed_digest" not in a
    assert (b["track"], b["outcome"], b["reason"]) == (
        {"number": 1},
        "not_inspected",
        (
            "the Evidence Set is not an acquired set: tagmanifest-sha256.txt does "
            "not list copyofa/acquisition-record.json"
        ),
    )
    assert "path" not in b
    assert "measurements" not in report


def test_compare_does_not_inspect_a_track_of_an_unusable_record_or_image(
    run: Run, make_acquired_set: Callable[..., Path]
) -> None:
    edited = make_acquired_set()
    edit_record(edited, lambda record: record.update(note="edited"), reseal=False)
    changed = make_acquired_set()
    image = changed / "data/disc.scram.flac"
    data = bytearray(image.read_bytes())
    data[-1] ^= 0xFF
    image.write_bytes(bytes(data))

    outcome, report = compare(run, edited, changed, "--track-a", "1", "--track-b", "1")

    assert outcome.code == 1
    a, b = report["inputs"]["a"], report["inputs"]["b"]
    assert (a["outcome"], a["reason"]) == (
        "not_inspected",
        "the Acquisition Record's digest differs from the tag manifest's",
    )
    assert "path" not in a
    assert (b["path"], b["outcome"], b["reason"]) == (
        "data/disc.scram.flac",
        "not_inspected",
        (
            "the disc image data/disc.scram.flac was not inspected: its digest "
            "differs from the manifest's"
        ),
    )
    assert b["observed_digest"] != b["expected_digest"]


@pytest.mark.parametrize(
    "arguments",
    [
        ("{set}", "{set}", "--track-a", "0"),
        ("{set}", "{set}", "--track-a", "one"),
        ("{set}/data/disc.scram.flac", "{set}", "--track-a", "1", "--track-b", "1"),
    ],
    ids=["track 0", "not a number", "file as a set"],
)
def test_compare_exits_2_for_a_track_input_it_cannot_take(
    run: Run, acquired_set: Path, arguments: tuple[str, ...]
) -> None:
    outcome = run(
        "compare", *(argument.format(set=acquired_set) for argument in arguments)
    )

    assert outcome.code == 2
    assert outcome.out == ""


def test_compare_omit_locations_with_a_track_input(
    run: Run, acquired_set: Path
) -> None:
    outcome, report = compare(
        run,
        acquired_set,
        acquired_set,
        "--track-a",
        "1",
        "--track-b",
        "2",
        "--omit-locations",
    )

    assert outcome.code == 0, outcome.err
    assert str(acquired_set) not in outcome.out
    assert all("evidence_set" not in entry for entry in report["inputs"].values())
    text = run(
        "compare",
        acquired_set,
        acquired_set,
        "--track-a",
        "1",
        "--track-b",
        "2",
        "--omit-locations",
    )
    assert "Track A: track 1 of data/disc.scram.flac (flac" in text.out
    assert str(acquired_set) not in text.out


def test_compare_help_names_the_inputs(run: Run) -> None:
    outcome = run("compare", "--help")

    assert outcome.code == 0
    assert "input-a" in outcome.out
    assert "input-b" in outcome.out
    assert "--track-a" in outcome.out
