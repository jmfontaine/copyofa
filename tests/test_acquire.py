from __future__ import annotations

import hashlib
import json
import lzma
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import soundfile
from conftest import DISC, closed_stdout, snapshot, synthetic_disc

import copyofa
from copyofa import acquirer, staging

if TYPE_CHECKING:
    from conftest import Run, StandIn

STORED = [
    "data/disc.cdtext",
    "data/disc.cue",
    "data/disc.fulltoc",
    "data/disc.log",
    "data/disc.scram.flac",
    "data/disc.state.xz",
    "data/disc.subcode.xz",
    "data/disc.toc",
]

AS_READ = ["--force-split", "--leave-unchanged"]
"""The options that make redumper split a disc with errors as read (ADR 0008)."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_of(track: bytes) -> str:
    return f"pcm1:44100:2:16:{sha256(track)}"


def record_of(bag: Path) -> dict[str, Any]:
    return json.loads((bag / "copyofa" / "acquisition-record.json").read_text())


def decode(bag: Path, path: str) -> bytes:
    """Decode a stored file as `flac -d --force-raw-format` or `xz -d` would."""
    if path.endswith(".flac"):
        samples, _ = soundfile.read(bag / path, dtype="int16")
        return samples.astype("<i2").tobytes()
    if path.endswith(".xz"):
        return lzma.decompress((bag / path).read_bytes())
    return (bag / path).read_bytes()


def manifest(bag: Path, name: str = "manifest-sha256.txt") -> dict[str, str]:
    lines = (bag / name).read_text().splitlines()
    return {line[66:]: line[:64] for line in lines}


def left_behind(destination: Path) -> list[Path]:
    staging_dir = destination.with_name(destination.name + staging.STAGING_SUFFIX)
    return [path for path in (destination, staging_dir) if os.path.lexists(path)]


def disc_runs(redumper: StandIn) -> list[list[str]]:
    return [call for call in redumper.calls() if call[:1] == ["disc"]]


def test_acquire_preserves_the_disc_without_track_files(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    destination = tmp_path / "Album"

    outcome = run(
        "acquire",
        "--to",
        destination,
        "--drive",
        "disk7",
        "--note",
        "Bought new",
        "--ref",
        "discogs=r1",
        "--ref",
        "musicbrainz=x",
    )

    assert outcome.code == 0, outcome.err
    assert disc_runs(redumper) == [
        ["disc", "--image-name=disc", "--drive=disk7", "--retries=20", *AS_READ]
    ]
    assert sorted(path.name for path in destination.iterdir()) == [
        "bag-info.txt",
        "bagit.txt",
        "copyofa",
        "data",
        "manifest-sha256.txt",
        "tagmanifest-sha256.txt",
    ]
    assert sorted(f"data/{p.name}" for p in (destination / "data").iterdir()) == STORED
    assert list(manifest(destination)) == STORED
    assert list(manifest(destination, "tagmanifest-sha256.txt")) == [
        "bagit.txt",
        "bag-info.txt",
        "manifest-sha256.txt",
        "copyofa/acquisition-record.json",
    ]
    for path, digest in manifest(destination).items():
        assert sha256((destination / path).read_bytes()) == digest

    disc = synthetic_disc(DISC)
    record = record_of(destination)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["acquired_at"])
    originals = {
        "disc.scram": disc.image,
        "disc.state": disc.state,
        "disc.subcode": disc.subcode,
    }
    stored_files = record.pop("stored_files")
    assert [entry["path"] for entry in stored_files] == STORED
    for entry in stored_files:
        decoded = decode(destination, entry["path"])
        assert entry["original_name"] == entry["path"].removeprefix("data/").replace(
            ".flac", ""
        ).replace(".xz", "")
        assert entry["original_size"] == len(decoded)
        assert entry["original_sha256"] == sha256(decoded)
        if entry["original_name"] in originals:
            assert decoded == originals[entry["original_name"]]
        expected = {"flac": "flac", "xz": "xz"}.get(
            entry["path"].rsplit(".", 1)[1], "as_written"
        )
        assert entry["storage"] == expected
    image_frames = len(disc.image) // 4
    assert record == {
        "record_kind": "copyofa.acquisition",
        "format_version": 2,
        "copyofa_version": copyofa.__version__,
        "acquired_at": record["acquired_at"],
        "note": "Bought new",
        "external_references": ["discogs=r1", "musicbrainz=x"],
        "reader": {
            "name": "redumper",
            "build": "b768",
            "arguments": [
                "disc",
                "--image-name=disc",
                "--drive=disk7",
                "--retries=20",
                "--force-split",
                "--leave-unchanged",
            ],
        },
        "drive": {
            "vendor": "PLEXTOR",
            "product": "CD-R PX-W5224A",
            "firmware_revision": "1.04",
            "read_offset": 30,
        },
        "disc": {
            "write_offset": -12,
            "catalog": "0602557897975",
            "title": "SYNTHETIC ALBUM",
            "performer": "THE TESTERS",
            "image": {
                "path": "data/disc.scram.flac",
                "frames": image_frames,
                "sample_rate": 44100,
                "channels": 2,
                "bits_per_sample": 16,
            },
        },
        "read_errors": {"scsi_samples": 0, "c2_samples": 0, "subchannel_q_sectors": 3},
        "tracks": [
            {
                "number": 1,
                "first_frame": disc.first_frames[0],
                "frame_count": len(disc.tracks[0]) // 4,
                "audio_digest": digest_of(disc.tracks[0]),
                "title": "FIRST",
                "isrc": "USAAA2600001",
                "error_ranges": [],
            },
            {
                "number": 2,
                "first_frame": disc.first_frames[1],
                "frame_count": len(disc.tracks[1]) // 4,
                "audio_digest": digest_of(disc.tracks[1]),
                "title": "SECOND",
                "performer": "A GUEST",
                "isrc": "USAAA2600002",
                "error_ranges": [],
            },
            {
                "number": 3,
                "first_frame": disc.first_frames[2],
                "frame_count": len(disc.tracks[2]) // 4,
                "audio_digest": digest_of(disc.tracks[2]),
                "isrc": "USAAA2600003",
                "error_ranges": [],
            },
        ],
    }
    image = decode(destination, "data/disc.scram.flac")
    for track, data in zip(record["tracks"], disc.tracks, strict=True):
        start = track["first_frame"] * 4
        assert image[start : start + track["frame_count"] * 4] == data
    with soundfile.SoundFile(destination / "data/disc.scram.flac") as sound:
        assert (sound.format, sound.subtype) == ("FLAC", "PCM_16")
        assert (sound.samplerate, sound.channels, sound.frames) == (
            44100,
            2,
            image_frames,
        )

    payload_size = sum(p.stat().st_size for p in (destination / "data").iterdir())
    assert outcome.out.splitlines() == [
        f"Accepted Evidence Set {destination}",
        "Drive: PLEXTOR CD-R PX-W5224A (firmware 1.04, read offset +30)",
        "Reader: redumper b768",
        "Disc write offset: -12",
        "Read errors: none (SCSI 0 samples, C2 0 samples; subchannel Q 3 sectors)",
        "Tracks: 3",
        f"  1: 0:00.053, {digest_of(disc.tracks[0])}",
        f"  2: 0:00.066, {digest_of(disc.tracks[1])}",
        f"  3: 0:00.040, {digest_of(disc.tracks[2])}",
        f"Preserved 8 files, {payload_size} bytes",
    ]
    for stage in ("dump", "protection", "split", "end"):
        assert f"redumper stage: {stage}\n" in outcome.err
    assert "LBA:" not in outcome.err


def test_acquire_prints_the_acquisition_result_as_json(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination, "--json")

    assert outcome.code == 0, outcome.err
    assert json.loads(outcome.out) == {
        "evidence_set": str(destination),
        "acquisition_record": record_of(destination),
    }
    assert disc_runs(redumper) == [
        ["disc", "--image-name=disc", "--retries=20", *AS_READ]
    ]


def test_acquire_gives_redumper_the_retry_count_and_records_it(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination, "--retries", "0")

    assert outcome.code == 0, outcome.err
    arguments = ["disc", "--image-name=disc", "--retries=0", *AS_READ]
    assert disc_runs(redumper) == [arguments]
    assert record_of(destination)["reader"]["arguments"] == arguments


@pytest.mark.parametrize(
    "retries",
    [
        ["--retries", "-1"],
        ["--retries", "x"],
        ["--retries", str(2**31)],
        ["--retries", "1", "--retries", "2"],
    ],
    ids=["negative", "not a number", "too large", "repeated"],
)
def test_acquire_exits_2_on_an_invalid_retry_count(
    run: Run, redumper: StandIn, tmp_path: Path, retries: list[str]
) -> None:
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination, *retries)

    assert outcome.code == 2
    assert outcome.out == ""
    assert "--retries" in outcome.err
    assert disc_runs(redumper) == []
    assert left_behind(destination) == []


def test_acquire_refuses_a_repeated_destination(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    outcome = run("acquire", "--to", tmp_path / "A", "--to", tmp_path / "B")

    assert outcome.code == 2
    assert outcome.out == ""
    assert "--to may be given only once" in outcome.err
    assert disc_runs(redumper) == []
    assert left_behind(tmp_path / "A") == []
    assert left_behind(tmp_path / "B") == []


@pytest.mark.parametrize("options", [(), ("--json",)])
def test_acquire_keeps_the_set_when_stdout_is_closed(
    run: Run, redumper: StandIn, tmp_path: Path, options: tuple[str, ...]
) -> None:
    destination = tmp_path / "Album"

    with closed_stdout():
        outcome = run("acquire", "--to", destination, *options)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.endswith(
        f"\ncopyofa: stdout closed; {destination} was created\n"
    )
    assert "Traceback" not in outcome.err
    assert left_behind(destination) == [destination]
    assert run("verify", destination).code == 0


def test_acquire_reads_a_single_track_disc_and_absent_values(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    redumper.configure(
        tracks=[{"frames": 6 * 588}],
        catalog=None,
        title=None,
        performer=None,
        drive={**DISC["drive"], "revision": "<empty>"},
    )
    destination = tmp_path / "Single"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == 0, outcome.err
    record = record_of(destination)
    disc = synthetic_disc(redumper.config)
    assert "firmware_revision" not in record["drive"]
    assert set(record["disc"]) == {"write_offset", "image"}
    assert record["tracks"] == [
        {
            "number": 1,
            "first_frame": disc.first_frames[0],
            "frame_count": 6 * 588,
            "audio_digest": digest_of(disc.tracks[0]),
            "error_ranges": [],
        }
    ]


def make_refusal(
    case: str, tmp_path: Path, redumper: StandIn, monkeypatch: pytest.MonkeyPatch
) -> list[Any]:
    destination = tmp_path / "Album"
    if case == "missing redumper":
        empty = tmp_path / "empty-path"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
    elif case == "older build":
        redumper.configure(build="b767")
    elif case == "unreadable version":
        redumper.configure(version_output="redumper, unknown build")
    elif case == "existing destination":
        destination.mkdir()
    elif case == "missing parent":
        destination = tmp_path / "Missing" / "Album"
    elif case == "leftover staging directory":
        destination.with_name("Album" + staging.STAGING_SUFFIX).mkdir()
    elif case == "note not UTF-8":
        return ["--to", destination, "--note", "caf\udce9"]
    return ["--to", destination]


REFUSALS = {
    "missing redumper": "redumper is not on PATH",
    "older build": "build b767 is older than b768",
    "unreadable version": "does not give its build",
    "existing destination": "already exists",
    "missing parent": "does not exist",
    "leftover staging directory": "Album.copyofa-staging",
    "note not UTF-8": "the --note text is not valid UTF-8",
}


@pytest.mark.parametrize("output", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize("case", REFUSALS)
def test_acquire_refuses_before_reading(
    run: Run,
    redumper: StandIn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    output: list[str],
) -> None:
    args = make_refusal(case, tmp_path, redumper, monkeypatch)
    before = snapshot(tmp_path)

    outcome = run("acquire", *args, *output)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.startswith("copyofa: Refused: ")
    assert REFUSALS[case] in outcome.err
    assert snapshot(tmp_path) == before
    assert disc_runs(redumper) == []


FAILURES: dict[str, tuple[dict[str, Any], str]] = {
    "data track": ({"data_track": True}, "Refused: track 3 is a data track"),
    "two sessions": ({"sessions": 2}, "Refused: the disc has 2 sessions"),
    "redumper fails": (
        {"exit_status": 3},
        (
            "Failed: redumper exited with status 3. Its last message: error: drive "
            "not ready"
        ),
    ),
    "missing track file": (
        {"omit_track_file": 2},
        "Failed: redumper did not write disc (Track 2).bin, the file of track 2.",
    ),
    "track found nowhere": (
        {"corrupt_track_file": 3},
        (
            "Failed: the bytes of disc (Track 3).bin, track 3, are found nowhere in "
            "the image, or are a single repeated byte that no other track places in "
            "it.\n"
        ),
    ),
    "last track past the end of the image": (
        # The drive never read the lead-out nor the last track's last 10 frames.
        {"unread_tail": 2 * 588 + 10},
        (
            "Failed: the bytes of disc (Track 3).bin, track 3, are found nowhere in "
            "the image, or are a single repeated byte that no other track places in "
            "it.\n"
        ),
    ),
    "every track silent": (
        {"tracks": [{"frames": 2 * 588, "silent": True}] * 2},
        (
            "Failed: the bytes of disc (Track 1).bin, track 1, are found nowhere in "
            "the image, or are a single repeated byte that no other track places in "
            "it."
        ),
    ),
    "unreadable log": (
        {"unreadable_log": True},
        "Failed: redumper's log cannot be read: it does not identify the drive.",
    ),
}


@pytest.mark.parametrize("output", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize("case", FAILURES)
def test_acquire_refuses_or_fails_after_reading_and_leaves_nothing(
    run: Run, redumper: StandIn, tmp_path: Path, case: str, output: list[str]
) -> None:
    changes, reason = FAILURES[case]
    redumper.configure(**changes)
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination, *output)

    assert outcome.code == 1
    assert outcome.out == ""
    assert f"copyofa: {reason}" in outcome.err
    assert len(disc_runs(redumper)) == 1
    assert left_behind(destination) == []
    if reason.startswith("Refused:"):
        assert "redumper's log:" not in outcome.err
    else:
        assert_log_precedes_failure(outcome.err, redumper.last_log(), reason)


def assert_log_precedes_failure(err: str, log: str, reason: str) -> None:
    """Check that stderr ends with redumper's log, then the failure."""
    shown = "".join(f"{line}\n" for line in log.removesuffix("\n").split("\n"))
    assert f"copyofa: redumper's log:\n{shown}copyofa: {reason}" in err
    assert err.splitlines()[-1].startswith("copyofa: Failed: ")


def test_acquire_escapes_line_breaks_inside_a_shown_log_line(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    redumper.configure(title="A\rB\x1bC", corrupt_track_file=3)

    outcome = run("acquire", "--to", tmp_path / "Album")

    assert outcome.code == 1
    assert 'TITLE "A\\rB\\x1bC"\n' in outcome.err
    assert "\r" not in outcome.err
    assert "\x1b" not in outcome.err


@pytest.mark.parametrize("output", [[], ["--json"]], ids=["text", "json"])
def test_acquire_accepts_a_disc_read_with_errors_as_read_and_exits_1(
    run: Run, redumper: StandIn, tmp_path: Path, output: list[str]
) -> None:
    # Frames not read, read with C2 errors, two adjacent frames of different states,
    # and two adjacent runs of one state, which make one range.
    redumper.configure(
        errors={
            "2": [[100, 37, 0], [300, 1, 1], [301, 1, 0], [500, 20, 1], [520, 4, 1]]
        }
    )
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination, *output)

    assert outcome.code == 1
    assert "the disc was read with errors" in outcome.err
    assert disc_runs(redumper)[0][-2:] == AS_READ
    record = record_of(destination)
    assert record["format_version"] == 2
    assert [track["error_ranges"] for track in record["tracks"]] == [
        [],
        [
            {"offset_frames": 100, "frame_count": 37, "state": "not_read"},
            {"offset_frames": 300, "frame_count": 1, "state": "c2_error"},
            {"offset_frames": 301, "frame_count": 1, "state": "not_read"},
            {"offset_frames": 500, "frame_count": 24, "state": "c2_error"},
        ],
        [],
    ]
    # The track holds what the drive returned: zeros where it read nothing.
    disc = synthetic_disc(redumper.config)
    assert record["tracks"][1]["audio_digest"] == digest_of(disc.tracks[1])
    assert disc.tracks[1][100 * 4 : 137 * 4] == bytes(37 * 4)
    assert acquirer.has_read_errors(record)
    if output:
        assert json.loads(outcome.out)["acquisition_record"] == record
    else:
        assert "Read errors: found (" in outcome.out
        assert ", 63 frames not read successfully\n" in outcome.out


def test_acquire_records_every_range_and_a_wholly_unread_track(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    redumper.configure(
        errors={
            "1": [[1200 + 2 * index, 1, 1] for index in range(12)],
            "3": [[0, 3 * 588, 0]],
        }
    )
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == 1, outcome.err
    tracks = record_of(destination)["tracks"]
    assert tracks[0]["error_ranges"] == [
        {"offset_frames": 1200 + 2 * index, "frame_count": 1, "state": "c2_error"}
        for index in range(12)
    ]
    assert tracks[2]["error_ranges"] == [
        {"offset_frames": 0, "frame_count": 3 * 588, "state": "not_read"}
    ]
    assert tracks[2]["audio_digest"] == digest_of(bytes(3 * 588 * 4))
    assert "  1: 0:00.053, " in outcome.out
    assert ", 12 frames not read successfully\n" in outcome.out
    assert ", 1764 frames not read successfully\n" in outcome.out


@pytest.mark.parametrize(
    ("changes", "code", "found"),
    [
        ({"lead_in_c2": 10, "media_errors": {"scsi": 0, "c2": 10, "q": 3}}, 1, True),
        # The image ends before the lead-out's last 588 frames, which no track holds.
        ({"unread_tail": 588}, 0, False),
    ],
    ids=["lead-in C2 errors", "unread lead-out"],
)
def test_acquire_records_no_range_for_errors_outside_the_tracks(
    run: Run,
    redumper: StandIn,
    tmp_path: Path,
    changes: dict[str, Any],
    code: int,
    found: bool,
) -> None:
    redumper.configure(**changes)
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == code, outcome.err
    record = record_of(destination)
    assert [track["error_ranges"] for track in record["tracks"]] == [[], [], []]
    assert f"Read errors: {'found' if found else 'none'} (" in outcome.out
    assert "not read successfully" not in outcome.out


def test_acquire_counts_scsi_and_c2_errors_as_read_errors(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    redumper.configure(media_errors={"scsi": 0, "c2": 12, "q": 0})

    outcome = run("acquire", "--to", tmp_path / "Album")

    assert outcome.code == 1
    assert "Read errors: found (SCSI 0 samples, C2 12 samples;" in outcome.out


@pytest.mark.parametrize(
    ("corrected", "left", "code"),
    [
        ({"scsi": 2352, "c2": 1176, "q": 3}, {"scsi": 0, "c2": 0}, 0),
        ({"scsi": 2352, "c2": 588, "q": 3}, {"scsi": 0, "c2": 588}, 1),
        # A re-read turned skipped sectors into 10 more C2 samples than the dump had:
        # redumper logs the corrected C2 count wrapped as a 32-bit unsigned integer.
        ({"scsi": 2352, "c2": 2**32 - 10, "q": 3}, {"scsi": 0, "c2": 1186}, 1),
    ],
    ids=["all corrected", "some left", "more c2 than read"],
)
def test_acquire_counts_only_the_errors_left_after_re_reading(
    run: Run,
    redumper: StandIn,
    tmp_path: Path,
    corrected: dict[str, int],
    left: dict[str, int],
    code: int,
) -> None:
    # Q stays as the dump gives it: the re-reads also count sectors it did not.
    redumper.configure(
        media_errors={"scsi": 2352, "c2": 1176, "q": 5}, corrected=corrected
    )
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == code, outcome.err
    assert record_of(destination)["read_errors"] == {
        "scsi_samples": left["scsi"],
        "c2_samples": left["c2"],
        "subchannel_q_sectors": 5,
    }


def test_acquire_stops_redumper_and_cleans_up_when_canceled_while_reading(
    run: Run,
    redumper: StandIn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redumper.configure(hang=True)
    original = acquirer.acquire

    def canceled_at_first_stage(*args: Any, **kwargs: Any) -> Any:
        progress = kwargs.pop("progress")

        def interrupting(message: str) -> None:
            progress(message)
            if message.startswith("redumper stage"):
                raise KeyboardInterrupt

        return original(*args, progress=interrupting, **kwargs)

    monkeypatch.setattr(acquirer, "acquire", canceled_at_first_stage)
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination, "--json")

    assert outcome.code == 130
    assert outcome.out == ""
    assert left_behind(destination) == []
    pid = int((redumper.directory / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_acquire_cleans_up_when_canceled_while_storing(
    run: Run, redumper: StandIn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(source: Path, target: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(acquirer, "_compress_xz", interrupted)
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == 130
    assert outcome.out == ""
    assert left_behind(destination) == []


def test_acquire_fails_when_a_stored_file_does_not_decode_to_the_original(
    run: Run, redumper: StandIn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compress = acquirer._compress_xz

    def lossy(source: Path, target: Path) -> None:
        compress(source, target)
        data = lzma.decompress(target.read_bytes())
        target.unlink()
        target.write_bytes(lzma.compress(data[:-1]))

    monkeypatch.setattr(acquirer, "_compress_xz", lossy)
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == 1
    reason = "Failed: disc.state.xz does not decode to redumper's disc.state."
    assert_log_precedes_failure(outcome.err, redumper.last_log(), reason)
    assert left_behind(destination) == []


def test_a_left_staging_directory_is_refused_naming_every_command(
    run: Run, acquired_set: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "Album"
    left = destination.with_name("Album" + staging.STAGING_SUFFIX)
    left.mkdir()
    (tmp_path / "left").write_bytes(b"x")

    for args in (
        ["acquire"],
        ["import", tmp_path / "left"],
        ["export", acquired_set],
    ):
        outcome = run(*args, "--to", destination)
        assert outcome.code == 1
        assert (
            "a staging directory left by an earlier import, acquire or export exists "
            f"at {left}." in outcome.err
        )
        assert not destination.exists()


def test_acquire_reads_ten_tracks_a_silent_first_track_and_lead_track_files(
    run: Run, redumper: StandIn, tmp_path: Path
) -> None:
    # b768 pads track numbers and the lead-out marker to two characters, writes
    # the lead-in and lead-out as tracks when they hold audio, and writes a cue
    # sheet per further CD-Text language.
    tracks = [{"frames": 2 * 588, "silent": True}] + [
        {"frames": (2 + n % 3) * 588} for n in range(9)
    ]
    redumper.configure(tracks=tracks, lead_track_files=True, cd_text_languages=["09"])
    destination = tmp_path / "Ten"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == 0, outcome.err
    disc = synthetic_disc(redumper.config)
    record = record_of(destination)
    assert [
        (track["number"], track["first_frame"], track["audio_digest"])
        for track in record["tracks"]
    ] == [
        (number, first, digest_of(data))
        for number, (first, data) in enumerate(
            zip(disc.first_frames, disc.tracks, strict=True), start=1
        )
    ]
    stored = {entry["original_name"] for entry in record["stored_files"]}
    assert "disc_09.cue" in stored
    assert not any(name.endswith(".bin") for name in stored)


@pytest.mark.parametrize(
    ("charset", "expected"),
    [(0x80, {"title": "日本のミュージック"}), (0x81, {})],
    ids=["ms-jis", "unsupported"],
)
def test_acquire_decodes_cd_text_in_its_character_set(
    run: Run,
    redumper: StandIn,
    tmp_path: Path,
    charset: int,
    expected: dict[str, str],
) -> None:
    redumper.configure(
        # ュ is 0x83 0x85 in MS-JIS, and 0x85 a line break in ISO 8859-1.
        cd_text_charset=charset,
        title="日本のミュージック",
        performer=None,
    )
    destination = tmp_path / "Album"

    outcome = run("acquire", "--to", destination)

    assert outcome.code == 0, outcome.err
    disc = record_of(destination)["disc"]
    assert {key: disc[key] for key in ("title", "performer") if key in disc} == (
        expected
    )


def test_acquire_runs_redumper_found_through_a_relative_path_entry(
    run: Run, redumper: StandIn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(redumper.directory.parent)
    monkeypatch.setenv(
        "PATH", f"{redumper.directory.name}{os.pathsep}{os.environ['PATH']}"
    )

    outcome = run("acquire", "--to", tmp_path / "Album")

    assert outcome.code == 0, outcome.err
