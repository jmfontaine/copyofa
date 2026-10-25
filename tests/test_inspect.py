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
from conftest import requires_permissions, snapshot

import copyofa
from copyofa import inspector

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Outcome, Run

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

    def spy(file, suffix):
        decoded.append(file.name)
        return original(file, suffix)

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

    def change_during(file, suffix):
        result = original(file, suffix)
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
        "format_version": 1,
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
