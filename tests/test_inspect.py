from __future__ import annotations

import hashlib
import inspect as pyinspect
import json
import os
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soundfile
from conftest import (
    RATE,
    as_version_1,
    edit_record,
    requires_permissions,
    reseal_file,
    signal,
    snapshot,
    synthetic_disc,
    write_audio,
)

import copyofa
from copyofa import inspector, verifier

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Outcome, Run, StandIn


def canonical_digest(samples: np.ndarray, bits: int) -> str:
    """ADR 0002's hash, built one sample at a time, independently of inspect."""
    width = (bits + 7) // 8
    data = b"".join(
        int(value).to_bytes(width, "little", signed=True) for value in samples.ravel()
    )
    return hashlib.sha256(data).hexdigest()


def patch_streaminfo(
    path: Path,
    *,
    bits: int | None = None,
    total: int | None = None,
    md5: bytes | None = None,
) -> None:
    """Rewrite fields of a FLAC file's STREAMINFO block, which starts at byte 8."""
    data = bytearray(path.read_bytes())
    assert data[:4] == b"fLaC"
    fields = int.from_bytes(data[18:26], "big")
    if bits is not None:
        fields = (fields & ~(0x1F << 36)) | ((bits - 1) << 36)
    if total is not None:
        fields = (fields & ~0xF_FFFF_FFFF) | total
    data[18:26] = fields.to_bytes(8, "big")
    if md5 is not None:
        data[26:42] = md5
    path.write_bytes(bytes(data))


def inspect(run: Run, evidence_set: Path) -> tuple[Outcome, dict]:
    outcome = run("inspect", evidence_set, "--json")
    return outcome, json.loads(outcome.out)


def entries(report: dict) -> dict[str, dict]:
    """Map each file name under data/Album/ to its Report entry."""
    return {
        entry["path"].removeprefix("data/Album/"): entry for entry in report["files"]
    }


def outcomes(report: dict) -> dict[str, tuple[str, str | None]]:
    return {
        name: (entry["outcome"], entry.get("reason"))
        for name, entry in entries(report).items()
    }


def test_inspect_gives_the_documented_audio_digest(run: Run, make_set) -> None:
    # Known answer: two stereo frames, (0, 1) and (-1, the 16-bit minimum), as
    # signed little-endian 16-bit integers.
    tiny = np.array([[0, 1], [-1, -32768]], dtype=np.int32)
    expected_tiny = hashlib.sha256(bytes.fromhex("0000 0100 ffff 0080")).hexdigest()

    def fill(source: Path) -> None:
        write_audio(source / "tiny.flac", tiny, 16, "FLAC")

    _, report = inspect(run, make_set(fill))

    assert entries(report)["tiny.flac"]["audio_digest"] == (
        f"pcm1:{RATE}:2:16:{expected_tiny}"
    )


@pytest.mark.parametrize("bits", [16, 24])
def test_inspect_gives_one_audio_digest_to_the_same_samples(
    run: Run, make_set, bits: int
) -> None:
    # A smooth signal, so FLAC compression levels produce different files.
    phase = np.arange(3000)[:, None] / 40 + np.array([0.0, 1.0])
    samples = (np.sin(phase) * ((1 << (bits - 1)) - 1) * 0.9).astype(np.int32)
    supports_level = (
        "compression_level" in pyinspect.signature(soundfile.SoundFile).parameters
    )

    def fill(source: Path) -> None:
        write_audio(source / "plain.flac", samples, bits, "FLAC")
        write_audio(source / "tagged.flac", samples, bits, "FLAC", title="Tagged")
        write_audio(source / "plain.wav", samples, bits, "WAV")
        write_audio(source / "extensible.wav", samples, bits, "WAVEX")
        if supports_level:
            write_audio(
                source / "fastest.flac", samples, bits, "FLAC", compression_level=0.0
            )

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0, outcome.err
    found = entries(report)
    expected = f"pcm1:{RATE}:2:{bits}:{canonical_digest(samples, bits)}"
    assert {
        name: entry["audio_digest"] for name, entry in found.items()
    } == dict.fromkeys(found, expected)
    file_digests = {entry["observed_digest"] for entry in found.values()}
    assert len(file_digests) == len(found)
    if not supports_level:
        pytest.skip("this soundfile cannot choose a FLAC compression level")


def test_inspect_reports_properties(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "a.flac", signal(1500, 1, 24), 24, "FLAC", rate=96000)
        write_audio(source / "b.flac", signal(1200, 2, 8), 8, "FLAC", rate=22050)
        write_audio(source / "c.wav", signal(1000, 2, 16), 16, "WAV")
        write_audio(source / "d.wav", signal(900, 6, 24), 24, "WAVEX", rate=48000)
        write_audio(source / "e.wav", signal(800, 2, 32), 32, "WAV")
        write_audio(source / "f.wav", signal(700, 1, 8), 8, "WAV")
        soundfile.write(
            source / "g.mp3",
            signal(4410, 2, 16).astype(np.int16),
            RATE,
            format="MP3",
            subtype="MPEG_LAYER_III",
        )

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0, outcome.err
    keys = (
        "format",
        "encoding",
        "sample_rate",
        "channels",
        "bits_per_sample",
        "frames",
    )
    found = {
        name: tuple(entry.get(key) for key in keys)
        for name, entry in entries(report).items()
    }
    assert found == {
        "a.flac": ("flac", "pcm_24", 96000, 1, 24, 1500),
        "b.flac": ("flac", "pcm_s8", 22050, 2, 8, 1200),
        "c.wav": ("wav", "pcm_16", RATE, 2, 16, 1000),
        "d.wav": ("wav", "pcm_24", 48000, 6, 24, 900),
        "e.wav": ("wav", "pcm_32", RATE, 2, 32, 800),
        "f.wav": ("wav", "pcm_u8", RATE, 1, 8, 700),
        "g.mp3": ("mp3", "mpeg_layer_iii", RATE, 2, None, 4410),
    }


def test_inspect_gives_8_bit_wav_samples_as_signed(run: Run, make_set) -> None:
    samples = signal(500, 2, 8)

    def fill(source: Path) -> None:
        write_audio(source / "unsigned.wav", samples, 8, "WAV")
        write_audio(source / "signed.flac", samples, 8, "FLAC")

    _, report = inspect(run, make_set(fill))

    expected = f"pcm1:{RATE}:2:8:{canonical_digest(samples, 8)}"
    assert {entry["audio_digest"] for entry in report["files"]} == {expected}


def test_inspect_describes_mp3_without_an_audio_digest(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        soundfile.write(
            source / "track.mp3",
            signal(4410, 2, 16).astype(np.int16),
            RATE,
            format="MP3",
            subtype="MPEG_LAYER_III",
        )

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0, outcome.err
    entry = entries(report)["track.mp3"]
    assert entry["outcome"] == "interpreted"
    assert "audio_digest" not in entry
    assert entry["limitations"] == [inspector.MP3_LIMITATION]
    assert report["method"] == {
        "decoder": "libsndfile",
        "decoder_version": soundfile.__libsndfile_version__,
    }


def test_inspect_does_not_interpret_unsupported_material(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        (source / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" * 50)
        (source / "notes.txt").write_text("Recorded live.\n")
        with zipfile.ZipFile(source / "scans.zip", "w") as archive:
            archive.writestr("scan.txt", "scan")
        soundfile.write(
            source / "track.aiff",
            signal(500, 2, 16).astype(np.int16),
            RATE,
            format="AIFF",
            subtype="PCM_16",
        )
        soundfile.write(
            source / "float.wav", np.zeros((500, 2), dtype=np.float32), RATE, "FLOAT"
        )
        write_audio(source / "20-bit.flac", signal(500, 2, 24), 24, "FLAC")
        patch_streaminfo(source / "20-bit.flac", bits=20)
        write_audio(source / "no-length.flac", signal(500, 2, 16), 16, "FLAC")
        patch_streaminfo(source / "no-length.flac", total=0)

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0, outcome.err
    assert outcomes(report) == {
        "cover.jpg": ("not_interpreted", "no supported audio format was recognized"),
        "notes.txt": ("not_interpreted", "no supported audio format was recognized"),
        "scans.zip": ("not_interpreted", "no supported audio format was recognized"),
        "track.aiff": ("not_interpreted", "AIFF audio is not supported"),
        "float.wav": (
            "not_interpreted",
            "WAV audio with FLOAT encoding is not supported",
        ),
        "20-bit.flac": (
            "not_interpreted",
            "20-bit FLAC is not supported by the decoder",
        ),
        "no-length.flac": (
            "not_interpreted",
            "FLAC whose STREAMINFO gives no length is not supported by the decoder",
        ),
    }
    assert report["counts"] == {
        "interpreted": 0,
        "not_interpreted": 7,
        "failed": 0,
        "not_inspected": 0,
    }


def test_inspect_reports_audio_it_cannot_decode_as_failed(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "whole.flac", signal(20000, 2, 16), 16, "FLAC")
        data = (source / "whole.flac").read_bytes()
        (source / "truncated.flac").write_bytes(data[: len(data) * 2 // 3])
        (source / "short.flac").write_bytes(data[:20])
        (source / "fake.MP3").write_text("not an MP3 at all\n" * 20)

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 1
    found = outcomes(report)
    assert found.pop("whole.flac") == ("interpreted", None)
    assert found["short.flac"] == (
        "failed",
        "its FLAC STREAMINFO block cannot be read",
    )
    assert {name: outcome for name, (outcome, _) in found.items()} == {
        "truncated.flac": "failed",
        "short.flac": "failed",
        "fake.MP3": "failed",
    }
    assert str(found["truncated.flac"][1]).startswith("decoding stopped after ")
    assert str(found["fake.MP3"][1]).startswith("libsndfile cannot open it: ")


def test_inspect_counts_the_frames_a_truncated_mp3_decodes_to(
    run: Run, make_set
) -> None:
    def fill(source: Path) -> None:
        samples = signal(5 * RATE, 2, 16).astype(np.int16) // 4
        soundfile.write(
            source / "whole.mp3", samples, RATE, format="MP3", subtype="MPEG_LAYER_III"
        )
        data = (source / "whole.mp3").read_bytes()
        (source / "half.mp3").write_bytes(data[: len(data) // 2])

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0, outcome.err
    found = entries(report)
    assert found["whole.mp3"]["frames"] == 5 * RATE
    # The header still announces five seconds; the decoder finds about half.
    assert 2 * RATE < found["half.mp3"]["frames"] < 3 * RATE


@requires_permissions
def test_inspect_inspects_only_the_accepted_bytes(
    run: Run, make_set, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = [
        "modified",
        "deleted",
        "unreadable",
        "directory",
        "symlink",
        "pipe",
        "locked/inside",
        "linked/inside",
        "intact",
    ]

    def fill(source: Path) -> None:
        for name in names:
            (source / name).parent.mkdir(exist_ok=True)
            write_audio(source / f"{name}.flac", signal(100, 1, 16), 16, "FLAC")

    evidence_set = make_set(fill)
    album = evidence_set / "data" / "Album"
    (album / "modified.flac").write_bytes(b"fLaC changed")
    (album / "deleted.flac").unlink()
    (album / "unreadable.flac").chmod(0)
    (album / "directory.flac").unlink()
    (album / "directory.flac").mkdir()
    (album / "symlink.flac").unlink()
    (album / "symlink.flac").symlink_to(album / "intact.flac")
    (album / "pipe.flac").unlink()
    os.mkfifo(album / "pipe.flac")
    (album / "locked").chmod(0o600)
    elsewhere = evidence_set.parent / "elsewhere"
    (album / "linked").rename(elsewhere)
    (album / "linked").symlink_to(elsewhere)
    decoded = []
    original = inspector._interpret

    def spy(file, suffix, sink):
        decoded.append(file.name)
        return original(file, suffix, sink)

    monkeypatch.setattr(inspector, "_interpret", spy)
    try:
        outcome, report = inspect(run, evidence_set)
    finally:
        (album / "unreadable.flac").chmod(0o644)
        (album / "locked").chmod(0o755)

    assert outcome.code == 1
    assert outcomes(report) == {
        "modified.flac": ("not_inspected", "its digest differs from the manifest's"),
        "deleted.flac": ("not_inspected", "the file does not exist"),
        "unreadable.flac": (
            "not_inspected",
            "cannot be read: Permission denied",
        ),
        "directory.flac": ("not_inspected", "a directory, not a regular file"),
        "symlink.flac": ("not_inspected", "a symbolic link, which is not followed"),
        "pipe.flac": ("not_inspected", "a special file, not a regular file"),
        "locked/inside.flac": (
            "not_inspected",
            "cannot be examined: Permission denied",
        ),
        "linked/inside.flac": (
            "not_inspected",
            "a symbolic link, which is not followed",
        ),
        "intact.flac": ("interpreted", None),
    }
    assert (
        entries(report)["modified.flac"]["observed_digest"]
        == hashlib.sha256(b"fLaC changed").hexdigest()
    )
    assert len(decoded) == 1


def test_inspect_decodes_nothing_with_an_unusable_baseline(
    run: Run, make_set, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track.flac", signal(100, 1, 16), 16, "FLAC")

    evidence_set = make_set(fill)
    manifest = evidence_set / "manifest-sha256.txt"
    text = manifest.read_text()
    manifest.write_text(("1" if text[0] == "0" else "0") + text[1:])

    def fail(*_: object) -> None:
        pytest.fail("decoded a file despite an unusable baseline")

    monkeypatch.setattr(inspector, "_interpret", fail)
    outcome, report = inspect(run, evidence_set)

    assert outcome.code == 1
    assert report["integrity_baseline"]["usable"] is False
    assert outcomes(report) == {
        "track.flac": ("not_inspected", "the Integrity Baseline is unusable")
    }


def test_inspect_reports_a_file_that_changes_while_inspected(
    run: Run, make_set, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track.flac", signal(100, 1, 16), 16, "FLAC")

    evidence_set = make_set(fill)
    original = inspector._interpret

    def change_during(file, suffix, sink):
        result = original(file, suffix, sink)
        with (evidence_set / "data/Album/track.flac").open("ab") as writer:
            writer.write(b"appended")
        return result

    monkeypatch.setattr(inspector, "_interpret", change_during)
    outcome, report = inspect(run, evidence_set)

    assert outcome.code == 1
    assert outcomes(report) == {
        "track.flac": ("not_inspected", "the file changed while it was inspected")
    }


def test_inspect_report_content(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track.flac", signal(100, 1, 16), 16, "FLAC")

    evidence_set = make_set(fill)
    before = datetime.now(UTC).replace(microsecond=0)
    outcome, report = inspect(run, evidence_set)
    after = datetime.now(UTC)

    assert outcome.code == 0
    inspected_at = datetime.strptime(
        report["inspected_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=UTC)
    assert before <= inspected_at <= after + timedelta(seconds=1)
    manifest = (evidence_set / "manifest-sha256.txt").read_bytes()
    data = (evidence_set / "data/Album/track.flac").read_bytes()
    entry = entries(report)["track.flac"]
    assert {key: value for key, value in report.items() if key != "files"} == {
        "report_kind": "copyofa.inspection",
        "format_version": 3,
        "copyofa_version": copyofa.__version__,
        "inspected_at": report["inspected_at"],
        "evidence_set": str(evidence_set),
        "integrity_baseline": {
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "usable": True,
            "problems": [],
        },
        "method": {
            "decoder": "libsndfile",
            "decoder_version": soundfile.__libsndfile_version__,
        },
        "counts": {
            "interpreted": 1,
            "not_interpreted": 0,
            "failed": 0,
            "not_inspected": 0,
        },
        "limitations": list(inspector.LIMITATIONS),
    }
    assert entry["path"] == "data/Album/track.flac"
    assert entry["expected_digest"] == entry["observed_digest"]
    assert entry["observed_digest"] == hashlib.sha256(data).hexdigest()


def test_inspect_human_result_names_each_file_not_interpreted(
    run: Run, make_set
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track.flac", signal(RATE * 61, 2, 16), 16, "FLAC")
        (source / "cover.jpg").write_bytes(b"\xff\xd8 cover")
        (source / "gone.flac").write_bytes(b"soon gone")

    evidence_set = make_set(fill)
    (evidence_set / "data/Album/gone.flac").unlink()
    before = snapshot(evidence_set)

    outcome = run("inspect", evidence_set)

    assert outcome.code == 1
    assert outcome.out.splitlines() == [
        f"Evidence Set {evidence_set}",
        "Integrity Baseline: usable",
        "Files: 1 interpreted, 1 not interpreted, 1 not inspected",
        "  data/Album/track.flac: flac, 44100 Hz, 16-bit, 2 channels, 1:01.000",
        (
            "  not interpreted: data/Album/cover.jpg "
            "(no supported audio format was recognized)"
        ),
        "  not inspected: data/Album/gone.flac (the file does not exist)",
        "Result: problems found",
    ]
    assert "Inspected data/Album/track.flac: interpreted" in outcome.err
    assert snapshot(evidence_set) == before


def test_inspect_exits_2_when_target_is_not_an_evidence_set(
    run: Run, tmp_path: Path
) -> None:
    outcome = run("inspect", tmp_path)

    assert outcome.code == 2
    assert outcome.out == ""
    assert "is not an Evidence Set" in outcome.err


def test_inspect_canceled_prints_nothing(
    run: Run, make_set, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track.flac", signal(100, 1, 16), 16, "FLAC")

    evidence_set = make_set(fill)

    def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(inspector, "_interpret", interrupted)
    outcome = run("inspect", evidence_set, "--json")

    assert outcome.code == 130
    assert outcome.out == ""


def test_inspect_skips_an_id3v2_tag_before_flac(run: Run, make_set) -> None:
    samples = signal(300, 2, 16)

    def fill(source: Path) -> None:
        write_audio(source / "plain.flac", samples, 16, "FLAC")
        # An ID3v2.4 tag of 20 bytes (syncsafe size), then the FLAC stream.
        tag = b"ID3\x04\x00\x00\x00\x00\x00\x14" + b"\x00" * 20
        data = (source / "plain.flac").read_bytes()
        (source / "tagged.flac").write_bytes(tag + data)
        shutil.copy(source / "plain.flac", source / "copy.flac")

    _, report = inspect(run, make_set(fill))

    digests = {entry["outcome"]: entry.get("audio_digest") for entry in report["files"]}
    assert digests == {
        "interpreted": f"pcm1:{RATE}:2:16:{canonical_digest(samples, 16)}"
    }


def bracketed_by_silence(bits: int) -> np.ndarray:
    """Return stereo samples: 70000 zero frames, 1000 sounding, 70000 zero frames.

    The silences span more than one decoding block, and the peaks are known: the
    lowest sample value on the left channel, a positive one on the right.
    """
    low = -(1 << (bits - 1))
    middle = np.zeros((1000, 2), dtype=np.int32)
    middle[0] = [3, 0]
    middle[400] = [low, 1]
    middle[999] = [0, 1234]
    silence = np.zeros((70000, 2), dtype=np.int32)
    return np.concatenate([silence, middle, silence])


@pytest.mark.parametrize(("bits", "container"), [(16, "FLAC"), (24, "WAVEX")])
def test_inspect_measures_peak_and_digital_silence(
    run: Run, make_set, bits: int, container: str
) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track", bracketed_by_silence(bits), bits, container)
        write_audio(source / "silent", np.zeros((5000, 2), np.int32), bits, container)

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0, outcome.err
    keys = ("peak", "leading_silence_frames", "trailing_silence_frames")
    found = {
        name: tuple(entry[key] for key in keys)
        for name, entry in entries(report).items()
    }
    assert found == {
        "track": ([1 << (bits - 1), 1234], 70000, 70000),
        "silent": ([0, 0], 5000, 0),
    }


def test_inspect_measures_mp3_as_decoded(run: Run, make_set) -> None:
    # One second of silence, one of a 440 Hz tone at half and quarter scale, one of
    # silence. MP3 encoding blurs the edges and the peaks a little.
    tone = np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE)
    samples = np.zeros((3 * RATE, 2), dtype=np.float32)
    samples[RATE : 2 * RATE] = np.column_stack([0.5 * tone, 0.25 * tone])

    def fill(source: Path) -> None:
        soundfile.write(
            source / "track.mp3", samples, RATE, format="MP3", subtype="MPEG_LAYER_III"
        )

    _, report = inspect(run, make_set(fill))

    entry = entries(report)["track.mp3"]
    assert entry["peak"] == [
        pytest.approx(0.5, abs=0.02),
        pytest.approx(0.25, abs=0.02),
    ]
    assert RATE * 0.9 < entry["leading_silence_frames"] <= RATE
    assert RATE * 0.9 < entry["trailing_silence_frames"] <= RATE


def test_inspect_checks_the_flac_md5_signature(run: Run, make_set) -> None:
    samples = signal(2000, 2, 16)

    def fill(source: Path) -> None:
        for name in ("intact", "altered", "zeroed"):
            write_audio(source / f"{name}.flac", samples, 16, "FLAC")
        patch_streaminfo(source / "altered.flac", md5=b"\x01" * 16)
        patch_streaminfo(source / "zeroed.flac", md5=bytes(16))
        write_audio(source / "track.wav", samples, 16, "WAV")

    evidence_set = make_set(fill)
    outcome, report = inspect(run, evidence_set)

    assert outcome.code == 1
    found = {
        name: entry.get("flac_md5_signature") for name, entry in entries(report).items()
    }
    assert found == {
        "intact.flac": "matching",
        "altered.flac": "differs",
        "zeroed.flac": "absent",
        "track.wav": None,
    }
    human = run("inspect", evidence_set)
    assert human.code == 1
    assert [line for line in human.out.splitlines() if "MD5" in line] == [
        (
            "  data/Album/altered.flac: flac, 44100 Hz, 16-bit, 2 channels, "
            "0:00.045, decoded audio differs from its FLAC MD5 signature"
        )
    ]


def test_inspect_accepts_an_absent_flac_md5_signature(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "zeroed.flac", signal(2000, 2, 16), 16, "FLAC")
        patch_streaminfo(source / "zeroed.flac", md5=bytes(16))

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0
    assert report["files"][0]["flac_md5_signature"] == "absent"


def test_inspect_describes_each_track_of_an_acquired_set(
    run: Run, redumper: StandIn, acquired_set: Path
) -> None:
    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 0, outcome.err
    assert report["format_version"] == 3
    disc = synthetic_disc(redumper.config)
    record = json.loads((acquired_set / "copyofa/acquisition-record.json").read_bytes())
    tracks = report["disc"]["tracks"]
    assert [
        (track["number"], track["first_frame"], track["frame_count"])
        for track in tracks
    ] == [
        (track["number"], track["first_frame"], track["frame_count"])
        for track in record["tracks"]
    ]
    for track, data in zip(tracks, disc.tracks, strict=True):
        samples = np.frombuffer(data, dtype="<i2").reshape(-1, 2)
        assert track["outcome"] == "interpreted"
        assert track["audio_digest"] == track["recorded_audio_digest"]
        assert track["audio_digest"] == (
            f"pcm1:44100:2:16:{hashlib.sha256(data).hexdigest()}"
        )
        assert track["frames"] == len(samples)
        assert track["peak"] == np.abs(samples.astype(np.int32)).max(axis=0).tolist()
    # The first track starts with silence in the synthetic disc.
    leading = redumper.config["tracks"][0].get("leading_zero_frames", 0)
    assert tracks[0]["leading_silence_frames"] == leading
    assert [track["error_ranges"] for track in tracks] == [[], [], []]
    image = next(
        entry for entry in report["files"] if entry["path"] == "data/disc.scram.flac"
    )
    assert image["outcome"] == "interpreted"
    assert image["frames"] == len(disc.image) // 4


def test_inspect_exits_1_when_a_track_differs_from_its_recorded_digest(
    run: Run, acquired_set: Path
) -> None:
    def change(record: dict) -> None:
        record["tracks"][1]["audio_digest"] = "pcm1:44100:2:16:" + "0" * 64

    edit_record(acquired_set, change, reseal=True)

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    tracks = report["disc"]["tracks"]
    assert [track["outcome"] for track in tracks] == ["interpreted"] * len(tracks)
    assert tracks[1]["recorded_audio_digest"] == "pcm1:44100:2:16:" + "0" * 64
    assert tracks[1]["audio_digest"] != tracks[1]["recorded_audio_digest"]
    text = run("inspect", acquired_set)
    assert text.code == 1
    assert "  track 2: " in text.out
    assert "differs from the recorded one" in text.out


OTHER_VERSION = (
    "the Acquisition Record is not format version 1 or 2 of copyofa.acquisition"
)


def nest_record(evidence_set: Path, depth: int) -> None:
    """Replace the Acquisition Record with nested arrays, and reseal it."""
    path = evidence_set / "copyofa/acquisition-record.json"
    path.write_text("[" * depth + "]" * depth)
    reseal_file(evidence_set, "copyofa/acquisition-record.json")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda bag: edit_record(
                bag, lambda record: record.update(note="edited"), reseal=False
            ),
            "the Acquisition Record's digest differs from the tag manifest's",
        ),
        (
            lambda bag: (bag / "copyofa/acquisition-record.json").unlink(),
            "the Acquisition Record is missing",
        ),
        (
            lambda bag: edit_record(
                bag, lambda record: record.update(format_version=3), reseal=True
            ),
            OTHER_VERSION,
        ),
        (
            lambda bag: edit_record(
                bag, lambda record: record.update(format_version=1.0), reseal=True
            ),
            OTHER_VERSION,
        ),
        (
            lambda bag: edit_record(
                bag, lambda record: record["tracks"][0].pop("frame_count"), reseal=True
            ),
            "the Acquisition Record cannot be used: track 1 has no valid frame_count",
        ),
        (
            lambda bag: (bag / "manifest-sha256.txt").unlink(),
            "the Integrity Baseline is unusable",
        ),
    ],
    ids=[
        "edited",
        "missing",
        "other version",
        "version as a float",
        "no range",
        "unusable baseline",
    ],
)
def test_inspect_decodes_no_track_when_the_record_cannot_be_used(
    run: Run, acquired_set: Path, change: Callable[[Path], None], reason: str
) -> None:
    change(acquired_set)

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    assert report["disc"] == {"reason": reason}
    text = run("inspect", acquired_set)
    assert text.code == 1
    assert f"Disc: not inspected ({reason})" in text.out


def test_inspect_decodes_no_track_of_a_record_nested_100_000_deep(
    run: Run, acquired_set: Path
) -> None:
    nest_record(acquired_set, 100_000)

    outcome, report = inspect(run, acquired_set)

    # How deep the parser nests depends on the platform: Python 3.14 on Linux parses
    # the record, then finds no object; elsewhere the parser gives up.
    assert outcome.code == 1
    assert report["disc"]["reason"] in {
        "the Acquisition Record cannot be parsed: it is nested too deeply",
        "the Acquisition Record cannot be used: it is not a JSON object",
    }


def test_the_record_reader_reads_format_versions_1_and_2(
    make_acquired_set: Callable[..., Path],
) -> None:
    bag = make_acquired_set(code=1, errors={"2": [[100, 37, 0], [300, 1, 1]]})

    disc = inspector.read_acquired_disc(bag, verifier.read_baseline(bag))

    assert disc is not None
    assert [track.error_ranges for track in disc.tracks] == [
        (),
        (
            inspector.ErrorRange(100, 37, "not_read"),
            inspector.ErrorRange(300, 1, "c2_error"),
        ),
        (),
    ]
    as_version_1(bag)
    old = inspector.read_acquired_disc(bag, verifier.read_baseline(bag))
    assert old is not None
    assert [track.error_ranges for track in old.tracks] == [None] * 3
    assert [
        (track.number, track.first_frame, track.frame_count, track.audio_digest)
        for track in old.tracks
    ] == [
        (track.number, track.first_frame, track.frame_count, track.audio_digest)
        for track in disc.tracks
    ]


def test_inspect_reads_a_version_1_record_without_error_ranges(
    run: Run, damaged_set: Path
) -> None:
    as_version_1(damaged_set)

    outcome, report = inspect(run, damaged_set)

    assert outcome.code == 0, outcome.err
    assert report["format_version"] == 3
    tracks = report["disc"]["tracks"]
    assert [track["outcome"] for track in tracks] == ["interpreted"] * 3
    assert all("error_ranges" not in track for track in tracks)
    text = run("inspect", damaged_set)
    assert text.code == 0
    assert "not read successfully" not in text.out


def test_inspect_reports_each_track_s_error_ranges(run: Run, damaged_set: Path) -> None:
    outcome, report = inspect(run, damaged_set)

    assert outcome.code == 0, outcome.err
    assert report["format_version"] == 3
    record = json.loads((damaged_set / "copyofa/acquisition-record.json").read_bytes())
    tracks = report["disc"]["tracks"]
    assert [track["error_ranges"] for track in tracks] == [
        track["error_ranges"] for track in record["tracks"]
    ]
    assert tracks[1]["error_ranges"] == [
        {"offset_frames": 100, "frame_count": 37, "state": "not_read"},
        {"offset_frames": 300, "frame_count": 1, "state": "c2_error"},
        {"offset_frames": 301, "frame_count": 1, "state": "not_read"},
        {"offset_frames": 500, "frame_count": 24, "state": "c2_error"},
    ]
    assert all(track["outcome"] == "interpreted" for track in tracks)
    text = run("inspect", damaged_set)
    assert text.code == 0
    lines = [line for line in text.out.splitlines() if line.startswith("  track ")]
    assert lines[0].endswith(
        ", Audio Digest matches the recorded one, 12 frames not read successfully: "
        + ", ".join(["0:00.027+1 (C2 errors)"] * 10)
        + ", and 2 more"
    )
    assert lines[1].endswith(
        ", Audio Digest matches the recorded one, 63 frames not read successfully: "
        "0:00.002+37 (not read), 0:00.006+1 (C2 errors), 0:00.006+1 (not read), "
        "0:00.011+24 (C2 errors)"
    )
    assert lines[2].endswith(
        ", Audio Digest matches the recorded one, 1 frame not read successfully: "
        "0:00.000+1 (C2 errors)"
    )


def set_ranges(track: int, ranges: Any) -> Callable[[dict[str, Any]], None]:
    """Return a change giving a track of the record these error_ranges."""

    def change(record: dict[str, Any]) -> None:
        record["tracks"][track - 1]["error_ranges"] = ranges

    return change


def no_ranges(record: dict[str, Any]) -> None:
    del record["tracks"][1]["error_ranges"]


# Track 2 of the synthetic disc has 2940 frames.
INVALID_RANGES = {
    "absent": (no_ranges, "track 2 has no valid error_ranges"),
    "not a list": (set_ranges(2, {}), "track 2 has no valid error_ranges"),
    "not an object": (set_ranges(2, [5]), "track 2 has no valid error range 1"),
    "no state": (
        set_ranges(2, [{"offset_frames": 0, "frame_count": 1}]),
        "track 2 has no valid error range 1",
    ),
    "unknown state": (
        set_ranges(2, [{"offset_frames": 0, "frame_count": 1, "state": "skipped"}]),
        "track 2 has no valid error range 1",
    ),
    "empty": (
        set_ranges(2, [{"offset_frames": 0, "frame_count": 0, "state": "not_read"}]),
        "track 2 has no valid error range 1",
    ),
    "negative offset": (
        set_ranges(2, [{"offset_frames": -1, "frame_count": 1, "state": "not_read"}]),
        "track 2 has no valid error range 1",
    ),
    "offset as a float": (
        set_ranges(2, [{"offset_frames": 1.0, "frame_count": 1, "state": "not_read"}]),
        "track 2 has no valid error range 1",
    ),
    "past the track's end": (
        set_ranges(
            2, [{"offset_frames": 2900, "frame_count": 41, "state": "c2_error"}]
        ),
        "track 2 has no valid error range 1",
    ),
    "overlapping": (
        set_ranges(
            2,
            [
                {"offset_frames": 10, "frame_count": 5, "state": "c2_error"},
                {"offset_frames": 14, "frame_count": 5, "state": "not_read"},
            ],
        ),
        "track 2 has no valid error range 2",
    ),
    "out of order": (
        set_ranges(
            2,
            [
                {"offset_frames": 20, "frame_count": 5, "state": "c2_error"},
                {"offset_frames": 10, "frame_count": 5, "state": "not_read"},
            ],
        ),
        "track 2 has no valid error range 2",
    ),
}


@pytest.mark.parametrize("case", INVALID_RANGES)
def test_inspect_decodes_no_track_of_a_record_with_invalid_error_ranges(
    run: Run, acquired_set: Path, case: str
) -> None:
    change, reason = INVALID_RANGES[case]
    edit_record(acquired_set, change, reseal=True)

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    assert report["disc"] == {
        "reason": f"the Acquisition Record cannot be used: {reason}"
    }


def test_the_record_reader_accepts_ranges_that_touch_and_end_the_track(
    acquired_set: Path,
) -> None:
    ranges = [
        {"offset_frames": 0, "frame_count": 5, "state": "c2_error"},
        {"offset_frames": 5, "frame_count": 2935, "state": "not_read"},
    ]
    edit_record(acquired_set, set_ranges(2, ranges), reseal=True)

    disc = inspector.read_acquired_disc(
        acquired_set, verifier.read_baseline(acquired_set)
    )

    assert disc is not None
    assert disc.tracks[1].error_ranges == (
        inspector.ErrorRange(0, 5, "c2_error"),
        inspector.ErrorRange(5, 2935, "not_read"),
    )


def test_inspect_does_not_inspect_tracks_of_an_image_that_is_not_accepted(
    run: Run, acquired_set: Path
) -> None:
    image = acquired_set / "data/disc.scram.flac"
    data = bytearray(image.read_bytes())
    data[-1] ^= 0xFF
    image.write_bytes(bytes(data))

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    reason = (
        "the disc image data/disc.scram.flac was not inspected: its digest differs "
        "from the manifest's"
    )
    assert [
        (track["outcome"], track["reason"]) for track in report["disc"]["tracks"]
    ] == [("not_inspected", reason)] * 3
    assert all("audio_digest" not in track for track in report["disc"]["tracks"])


def test_inspect_does_not_inspect_tracks_after_the_image_changes(
    run: Run, acquired_set: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = acquired_set / "data/disc.scram.flac"
    decode_track = inspector.decode_track
    calls = []

    def touch_after_first(*args, **kwargs):
        findings = decode_track(*args, **kwargs)
        calls.append(args)
        if len(calls) == 1:
            info = image.stat()
            os.utime(image, ns=(info.st_atime_ns, info.st_mtime_ns + 10**9))
        return findings

    monkeypatch.setattr(inspector, "decode_track", touch_after_first)

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    assert outcomes(report)["data/disc.scram.flac"] == ("interpreted", None)
    reason = (
        "the disc image data/disc.scram.flac was not inspected: the file changed "
        "while it was inspected"
    )
    assert [
        (track["outcome"], track.get("reason")) for track in report["disc"]["tracks"]
    ] == [("interpreted", None), ("not_inspected", reason), ("not_inspected", reason)]


def test_inspect_hashes_the_disc_image_once(
    run: Run, acquired_set: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = acquired_set / "data/disc.scram.flac"
    file_digest = hashlib.file_digest
    hashed = []

    def counting(file, digest):
        if os.path.samestat(os.fstat(file.fileno()), image.stat()):
            hashed.append(digest)
        return file_digest(file, digest)

    monkeypatch.setattr(hashlib, "file_digest", counting)

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 0, outcome.err
    assert len(report["disc"]["tracks"]) == 3
    assert hashed == ["sha256"]


def test_inspect_reports_a_track_the_image_cannot_be_decoded_over_as_failed(
    run: Run, acquired_set: Path
) -> None:
    def change(record: dict) -> None:
        record["tracks"][2]["frame_count"] = record["disc"]["image"]["frames"]

    edit_record(acquired_set, change, reseal=True)

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    tracks = report["disc"]["tracks"]
    assert [track["outcome"] for track in tracks] == [
        "interpreted",
        "interpreted",
        "failed",
    ]
    assert tracks[2]["reason"].startswith("the range ends after the image's ")
    text = run("inspect", acquired_set)
    assert text.code == 1
    assert f"  failed: track 3 ({tracks[2]['reason']})\n" in text.out


def test_inspect_prints_no_disc_for_an_imported_set(run: Run, make_set) -> None:
    def fill(source: Path) -> None:
        write_audio(source / "track.flac", signal(100, 1, 16), 16, "FLAC")

    outcome, report = inspect(run, make_set(fill))

    assert outcome.code == 0
    assert report["format_version"] == 3
    assert "disc" not in report


def test_inspect_decodes_a_track_without_decoding_past_its_range(
    run: Run, make_acquired_set: Callable[..., Path]
) -> None:
    # Tracks longer than a FLAC frame, and a damaged last FLAC frame, which holds
    # the lead-out and the end of track 3. Decoding past track 2 would reach it.
    acquired_set = make_acquired_set(tracks=[{"frames": 20 * 588}] * 3)
    image = acquired_set / "data/disc.scram.flac"
    data = bytearray(image.read_bytes())
    data[-2:] = bytes(byte ^ 0xFF for byte in data[-2:])
    image.write_bytes(bytes(data))
    reseal_file(acquired_set, "data/disc.scram.flac")

    outcome, report = inspect(run, acquired_set)

    assert outcome.code == 1
    assert [track["outcome"] for track in report["disc"]["tracks"]] == [
        "interpreted",
        "interpreted",
        "failed",
    ]
