from __future__ import annotations

import contextlib
import copy
import errno
import functools
import hashlib
import io
import json
import os
import random
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import soundfile

from copyofa import comparator, inspector, validator, verifier
from copyofa.cli import main

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    Run = Callable[..., "Outcome"]


@dataclass(frozen=True)
class Outcome:
    code: int | str | None
    out: str
    err: str


@pytest.fixture(autouse=True)
def _reports_match_their_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every Report the suite produces validate against its schema.

    The Report must also be valid JSON as printed, so it holds no NaN or infinity.
    """

    def checked(produce: Callable[..., dict[str, Any]]) -> Callable[..., Any]:
        @functools.wraps(produce)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            report = produce(*args, **kwargs)
            document = json.loads(json.dumps(report, allow_nan=False))
            outcome, problems = validator.check(document)
            assert (outcome, problems) == (validator.VALID, [])
            return report

        return wrapper

    for module, name in (
        (verifier, "verify"),
        (inspector, "inspect"),
        (comparator, "compare"),
    ):
        monkeypatch.setattr(module, name, checked(getattr(module, name)))


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


class _ClosedPipe(io.RawIOBase):
    """The write end of a pipe whose reader has exited, as `| true` leaves stdout."""

    def __init__(self) -> None:
        super().__init__()
        self.reader_gone = True

    def writable(self) -> bool:
        return True

    def write(self, data: Any, /) -> int:
        if self.reader_gone:
            raise BrokenPipeError(errno.EPIPE, os.strerror(errno.EPIPE))
        return len(data)


@contextlib.contextmanager
def closed_stdout() -> Generator[None]:
    """Make stdout, while the block runs, a pipe whose reader has exited."""
    pipe = _ClosedPipe()
    stdout = io.TextIOWrapper(io.BufferedWriter(pipe), encoding="utf-8")
    try:
        with contextlib.redirect_stdout(stdout):
            yield
    finally:
        # Let the wrapper flush what it still holds, so it closes without an error.
        pipe.reader_gone = False
        stdout.close()


def run_without_stdout(
    *args: str | os.PathLike[str],
) -> subprocess.CompletedProcess[bytes]:
    """Run the command line in a process whose stdout is closed, as `>&-` leaves it."""
    main = "import sys; from copyofa.cli import main; sys.exit(main(sys.argv[1:]))"
    return subprocess.run(
        ["sh", "-c", 'exec "$0" "$@" >&-', sys.executable, "-c", main, *args],
        stderr=subprocess.PIPE,
        check=False,
    )


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


# A stand-in for redumper: `redumper --version` and `redumper disc` as build b768
# answers them, writing small synthetic files and a log in b768's format into the
# working directory. The REDUMPER_STAND_IN environment variable names its JSON
# configuration, a disc as DISC describes it with changes; it appends each call's
# arguments to `calls.jsonl` beside it.

SECTOR_FRAMES = 588
"""Stereo frames in a CD sector."""

DISC: dict[str, Any] = {
    "build": "b768",
    "drive": {
        "vendor": "PLEXTOR",
        "product": "CD-R PX-W5224A",
        "revision": "1.04",
        "read_offset": 30,
    },
    "write_offset": -12,
    "catalog": "0602557897975",
    "title": "SYNTHETIC ALBUM",
    "performer": "THE TESTERS",
    "tracks": [
        {
            "frames": 4 * SECTOR_FRAMES,
            # More than a 4096-byte window of zeros, as a track may start.
            "leading_zero_frames": 1100,
            "title": "FIRST",
            "isrc": "USAAA2600001",
        },
        {
            "frames": 5 * SECTOR_FRAMES,
            "title": "SECOND",
            "performer": "A GUEST",
            "isrc": "USAAA2600002",
        },
        {"frames": 3 * SECTOR_FRAMES, "isrc": "USAAA2600003"},
    ],
    "media_errors": {"scsi": 0, "c2": 0, "q": 3},
    # Other keys, all optional: version_output, exit_status, sessions, data_track,
    # omit_track_file, corrupt_track_file, unreadable_log, errors (track number to
    # a list of [first frame in the track, count, state]: state 0, not read, leaves
    # zeros in the image and the track file; state 1, read with a C2 error, keeps the
    # audio), lead_in_c2 (frames at the lead-in's end read with a C2 error),
    # unread_tail (frames at the disc's end never read, which the image does not
    # hold: the lead-out's, then the last track's, whose file redumper pads with
    # zeros), corrected (the errors a refine stage corrected, as media_errors gives
    # them), lead_track_files (write the lead-in and lead-out as tracks 0 and A),
    # cd_text_languages (language codes after the first, each with a further cue
    # sheet), cd_text_charset (the CD-Text character code) and hang. A track may
    # also be silent.
}

_CD_TEXT_CODECS = {0x00: "latin-1", 0x01: "ascii", 0x80: "cp932"}

_LEAD_IN_SECTORS = 3
_PREGAP_SECTORS = 2
_LEAD_OUT_SECTORS = 2


@dataclass(frozen=True)
class SyntheticDisc:
    """What the stand-in reads from a disc configuration."""

    image: bytes
    state: bytes
    subcode: bytes
    tracks: list[bytes]
    """Each track file's bytes."""
    first_frames: list[int]
    """Where each track starts in the image."""
    track_files: list[str]


def synthetic_disc(config: dict[str, Any]) -> SyntheticDisc:
    """Build the image, state and tracks of a disc configuration, reproducibly."""
    tracks = []
    errors = config.get("errors", {})
    for number, track in enumerate(config["tracks"], start=1):
        zeros = (
            track["frames"]
            if track.get("silent")
            else track.get("leading_zero_frames", 0)
        )
        noise = random.Random(number).randbytes((track["frames"] - zeros) * 4)
        data = bytearray(bytes(zeros * 4) + noise)
        # A sector the drive never read is never written to the image: zeros.
        for first, count, value in errors.get(str(number), []):
            if value == 0:
                data[first * 4 : (first + count) * 4] = bytes(count * 4)
        tracks.append(bytes(data))
    # The disc's write offset moves the tracks off sector boundaries in the image.
    lead_in = bytes((_LEAD_IN_SECTORS * SECTOR_FRAMES - config["write_offset"]) * 4)
    pregap = random.Random(0).randbytes(_PREGAP_SECTORS * SECTOR_FRAMES * 4)
    lead_out = bytes(_LEAD_OUT_SECTORS * SECTOR_FRAMES * 4)
    first_frames = []
    position = (len(lead_in) + len(pregap)) // 4
    for track in tracks:
        first_frames.append(position)
        position += len(track) // 4
    image = lead_in + pregap + b"".join(tracks) + lead_out
    state = bytearray(b"\x04" * (len(image) // 4))
    lead_in_frames = len(lead_in) // 4
    state[:lead_in_frames] = bytes(lead_in_frames)
    c2 = config.get("lead_in_c2", 0)
    state[lead_in_frames - c2 : lead_in_frames] = b"\x01" * c2
    for number, ranges in errors.items():
        for first, count, value in ranges:
            start = first_frames[int(number) - 1] + first
            state[start : start + count] = bytes([value]) * count
    unread = config.get("unread_tail", 0)
    if unread:
        image, state = image[: -unread * 4], state[:-unread]
        # redumper pads a track file with zeros past the image's end.
        missing = first_frames[-1] + len(tracks[-1]) // 4 - len(image) // 4
        if missing > 0:
            tracks[-1] = tracks[-1][: -missing * 4] + bytes(missing * 4)
    sectors = len(image) // (SECTOR_FRAMES * 4) + 1
    subcode = random.Random(-1).randbytes(sectors * 96)
    width = len(str(len(tracks)))
    names = (
        [f"disc (Track {n:0{width}}).bin" for n in range(1, len(tracks) + 1)]
        if len(tracks) > 1
        else ["disc.bin"]
    )
    return SyntheticDisc(image, bytes(state), subcode, tracks, first_frames, names)


def _has_errors(disc: SyntheticDisc) -> bool:
    """Tell whether b768 refuses to split a pressed CD read as the disc was.

    That is a frame of a track not read successfully, which includes a track
    extending past the image's end, or a C2 error anywhere.
    """
    return b"\x01" in disc.state or any(
        first + len(track) // 4 > len(disc.state)
        or min(disc.state[first : first + len(track) // 4]) < 2
        for first, track in zip(disc.first_frames, disc.tracks, strict=True)
    )


def _msf(lba: int) -> str:
    minutes, rest = divmod(lba + 150, 60 * 75)
    seconds, frames = divmod(rest, 75)
    return f"{minutes:02}:{seconds:02}:{frames:02}"


def _toc_lines(config: dict[str, Any], disc: SyntheticDisc) -> list[str]:
    sessions = config.get("sessions", 1)
    lines = []
    lba = 0
    count = len(disc.tracks)
    width = len(str(count))
    for index, track in enumerate(disc.tracks):
        number = f"{index + 1:0{width}}"
        session = 1 + index * sessions // count
        indent = "  " if sessions == 1 else "    "
        if sessions > 1 and (
            index == 0 or session != 1 + (index - 1) * sessions // count
        ):
            lines.append(f"  session {session}")
        data = config.get("data_track") and index + 1 == count
        lines.append(f"{indent}track {number} {{ {' data' if data else 'audio'} }}")
        lines.append(f"{indent}  index 01 {{ LBA: {lba:6}, MSF: {_msf(lba)} }}")
        lba += len(track) // (4 * SECTOR_FRAMES)
    indent = "  " if sessions == 1 else "    "
    lines.append(f"{indent}track {'A' * width} {{ audio }}")
    lines.append(f"{indent}  index 01 {{ LBA: {lba:6}, MSF: {_msf(lba)} }}")
    return lines


def _cue(config: dict[str, Any], disc: SyntheticDisc) -> str:
    """Return the cue sheet, whose CD-Text redumper writes in its own encoding."""
    lines = [f"CATALOG {config['catalog']}"] if "catalog" in config else []
    lines.extend(
        f'{key.upper()} "{config[key]}"'
        for key in ("title", "performer")
        if key in config
    )
    for number, (track, name) in enumerate(
        zip(config["tracks"], disc.track_files, strict=True), start=1
    ):
        lines.append(f'FILE "{name}" BINARY')
        lines.append(f"  TRACK {number:02} AUDIO")
        lines.extend(
            f'    {key.upper()} "{track[key]}"'
            for key in ("title", "performer")
            if key in track
        )
        if "isrc" in track:
            lines.append(f"    ISRC {track['isrc']}")
        lines.append("    INDEX 01 00:00:00")
    return "".join(f"{line}\n" for line in lines)


def _split_errors(disc: SyntheticDisc) -> list[str]:
    """Return the line b768's split stage logs for each track with errors.

    As `check_tracks` in cd/cd_split.ixx counts them: the sectors holding a frame not
    read (SKIP, state 0, which past the image's end every frame is) or read with a
    C2 error (state 1), and those frames. The stand-in's tracks start on sectors.
    """
    width = len(str(len(disc.tracks)))
    lines = []
    for number, (first, track) in enumerate(
        zip(disc.first_frames, disc.tracks, strict=True), start=1
    ):
        frames = len(track) // 4
        state = disc.state[first : first + frames]
        state += bytes(frames - len(state))
        sectors = [
            state[start : start + SECTOR_FRAMES]
            for start in range(0, frames, SECTOR_FRAMES)
        ]
        counts = [
            (sum(sector.count(value) > 0 for sector in sectors), state.count(value))
            for value in (0, 1)
        ]
        (skip_sectors, skip), (c2_sectors, c2) = counts
        if skip_sectors or c2_sectors:
            lines.append(
                f"errors detected, track: {number:0{width}}, sectors: "
                f"{{SKIP: {skip_sectors}, C2: {c2_sectors}}}, "
                f"samples: {{SKIP: {skip}, C2: {c2}}}"
            )
    return lines


def _log(config: dict[str, Any], disc: SyntheticDisc, arguments: list[str]) -> str:
    drive = config["drive"]
    errors = config["media_errors"]
    drive_path = next(
        (arg.split("=", 1)[1] for arg in arguments if arg.startswith("--drive=")),
        "disk6",
    )
    cue = _cue(config, disc)
    lines = [
        "=== 2026-10-25 16:36:26 " + "=" * 56,
        f"redumper (build: {config['build']})",
        "",
        f"arguments: {' '.join(arguments)}",
        "",
        "drive information",
        f"  path: {drive_path}",
        (
            f"  inquiry: {drive['vendor']} - {drive['product']} (revision level: "
            f"{drive['revision']}, vendor specific: 04/10/06 17:00)"
        ),
        (
            f"  configuration: PLEXTOR (read offset: {drive['read_offset']:+}, C2 "
            "shift: 294, pre-gap start: -75, read method: D8, sector order: "
            "DATA_C2_SUB)"
        ),
        "  profile: CD-ROM",
        "  read speed: <optimal>",
        "",
        "image path: .",
        "image name: disc",
        "",
        "*** DUMP (time check: 0s)",
        "",
        "disc TOC:",
        *_toc_lines(config, disc),
        "",
        "media errors: ",
        f"  SCSI: {errors['scsi']} samples",
        f"  C2: {errors['c2']} samples",
        f"  Q: {errors['q']}",
        "",
        "*** PROTECTION (time check: 0s)",
        "",
        "protection: none",
        "",
        *_refine_lines(config),
        "*** SPLIT (time check: 0s)",
        "",
        f"disc write offset: {config['write_offset']:+}",
        "",
        "checking tracks",
        *_split_errors(disc),
        "done",
        "",
        "writing tracks",
        "done",
        "",
        "CUE [disc.cue]:",
        # As redumper copies it: CD-Text may hold a carriage return.
        *cue.removesuffix("\n").split("\n"),
        "",
        "*** END (time check: 0s)",
    ]
    return "".join(f"{line}\n" for line in lines)


def _refine_lines(config: dict[str, Any]) -> list[str]:
    """Return the refine stage, with its statistics only when it re-read sectors."""
    lines = ["*** REFINE (time check: 0s)", ""]
    if "corrected" in config:
        corrected = config["corrected"]
        lines += [
            "correction statistics: ",
            f"  SCSI: {corrected['scsi']} samples",
            f"  C2: {corrected['c2']} samples",
            f"  Q: {corrected['q']} sectors",
            "",
        ]
    return lines


def _write_log(config_path: Path, log: bytes) -> None:
    """Write redumper's log, and a copy beside the configuration for the tests."""
    Path("disc.log").write_bytes(log)
    (config_path.parent / "last.log").write_bytes(log)


def stand_in_redumper(arguments: list[str]) -> int:
    """Answer a redumper command line as the configuration says."""
    config_path = Path(os.environ["REDUMPER_STAND_IN"])
    config = json.loads(config_path.read_text())
    with (config_path.parent / "calls.jsonl").open("a") as calls:
        calls.write(json.dumps(arguments) + "\n")
    if arguments == ["--version"]:
        print(config.get("version_output", f"redumper (build: {config['build']})"))
        return 0
    if arguments[:1] != ["disc"]:
        return 2
    disc = synthetic_disc(config)
    log = _log(config, disc, arguments)
    if config.get("hang"):
        (config_path.parent / "pid").write_text(str(os.getpid()))
        print("*** DUMP (time check: 0s)", flush=True)
        time.sleep(300)
        return 1
    if config.get("exit_status"):
        _write_log(config_path, log.split("*** DUMP")[0].encode())
        print("error: drive not ready")
        return config["exit_status"]
    # b768 refuses to split such a disc unless forced; forced alone, it would
    # generate sectors, which acquire never asks for.
    if _has_errors(disc) and not {"--force-split", "--leave-unchanged"} <= set(
        arguments
    ):
        refused = "error: data errors detected, unable to continue"
        checked = log.split("done\n\nwriting tracks")[0]
        _write_log(config_path, f"{checked}{refused}\n".encode())
        print(refused)
        return 1
    for line in log.splitlines():
        print(line)
        if line.startswith("*** DUMP"):
            print("/ [ 50%] LBA:   1000/2000, errors: { SCSIs: 0, C2s: 0, Q: 0 }\r")
    Path("disc.scram").write_bytes(disc.image)
    Path("disc.state").write_bytes(disc.state)
    Path("disc.subcode").write_bytes(disc.subcode)
    Path("disc.toc").write_bytes(b"\x00\x32\x01\x03" + bytes(range(24)))
    Path("disc.fulltoc").write_bytes(b"\x00\x5a\x01\x01" + bytes(range(40)))
    charset = config.get("cd_text_charset", 0x00)
    codec = _CD_TEXT_CODECS.get(charset, "utf-8")
    # The block size information: a pack of type 0x8F for block 0, its first byte
    # of content the character code.
    size_info = bytes([0x8F, 0, 0, 0, charset, 1, len(disc.tracks)]) + bytes(11)
    Path("disc.cdtext").write_bytes(b"\x00\x14\x00\x00" + size_info)
    cue = _cue(config, disc).encode(codec)
    Path("disc.cue").write_bytes(cue)
    for language in config.get("cd_text_languages", []):
        Path(f"disc_{language}.cue").write_bytes(cue)
    _write_log(
        config_path,
        b"garbage\n" if config.get("unreadable_log") else log.encode(codec),
    )
    if config.get("lead_track_files"):
        width = len(str(len(disc.tracks)))
        Path(f"disc (Track {'0' * width}).bin").write_bytes(disc.image[:2352])
        Path(f"disc (Track {'A' * width}).bin").write_bytes(disc.image[-2352:])
    for number, (name, data) in enumerate(
        zip(disc.track_files, disc.tracks, strict=True), start=1
    ):
        if config.get("omit_track_file") == number:
            continue
        written = bytearray(data)
        if config.get("corrupt_track_file") == number:
            written[len(written) // 2] ^= 0xFF
        Path(name).write_bytes(written)
    return 0


@dataclass(frozen=True)
class StandIn:
    """The stand-in redumper on PATH, and its configuration."""

    directory: Path

    def configure(self, **changes: Any) -> dict[str, Any]:
        """Make the stand-in answer for DISC with changes; return that config.

        A change to None removes the key.
        """
        config = copy.deepcopy(DISC)
        config.update(changes)
        config = {key: value for key, value in config.items() if value is not None}
        (self.directory / "config.json").write_text(json.dumps(config))
        return config

    @property
    def config(self) -> dict[str, Any]:
        return json.loads((self.directory / "config.json").read_text())

    def calls(self) -> list[list[str]]:
        """Return the arguments of each call made so far."""
        path = self.directory / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def last_log(self) -> str:
        """Return the log the last call wrote, as acquire decodes it."""
        return (self.directory / "last.log").read_bytes().decode(errors="replace")


@pytest.fixture
def redumper(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> StandIn:
    """Put the stand-in redumper first on PATH, answering for DISC."""
    directory = tmp_path_factory.mktemp("redumper")
    script = directory / "redumper"
    code = (
        f"import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); "
        "from conftest import stand_in_redumper; "
        "sys.exit(stand_in_redumper(sys.argv[1:]))"
    )
    script.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(code)} "$@"\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("REDUMPER_STAND_IN", str(directory / "config.json"))
    stand_in = StandIn(directory)
    stand_in.configure()
    return stand_in


@pytest.fixture
def make_acquired_set(
    run: Run, redumper: StandIn, tmp_path: Path
) -> Callable[..., Path]:
    """Acquire a synthetic disc, DISC with changes, into a new Evidence Set.

    The acquisition must exit with code: 1 for a disc read with errors.
    """
    count = 0

    def _make(*, code: int = 0, **changes: Any) -> Path:
        nonlocal count
        count += 1
        redumper.configure(**changes)
        destination = tmp_path / f"acquired-{count}"
        outcome = run("acquire", "--to", destination)
        assert outcome.code == code, outcome.err
        return destination

    return _make


@pytest.fixture
def acquired_set(make_acquired_set: Callable[..., Path]) -> Path:
    """An Evidence Set acquired from the synthetic disc DISC."""
    return make_acquired_set()


DAMAGED_ERRORS = {
    "1": [[1200 + 2 * index, 1, 1] for index in range(12)],
    "2": [[100, 37, 0], [300, 1, 1], [301, 1, 0], [500, 24, 1]],
    "3": [[0, 1, 1]],
}
"""The errors of a disc read with errors, as the stand-in's `errors` gives them.

Track 1 has 12 ranges of one frame read with C2 errors; track 2, frames not read and
frames read with C2 errors, two of them adjacent; track 3, a single frame.
"""


@pytest.fixture
def damaged_set(make_acquired_set: Callable[..., Path]) -> Path:
    """An Evidence Set acquired from DISC read with DAMAGED_ERRORS."""
    return make_acquired_set(code=1, errors=DAMAGED_ERRORS)


def edit_record(
    evidence_set: Path, change: Callable[[dict[str, Any]], None], *, reseal: bool
) -> None:
    """Change the Acquisition Record, and the tag manifest to match when reseal."""
    path = evidence_set / "copyofa/acquisition-record.json"
    record = json.loads(path.read_bytes())
    change(record)
    path.write_text(json.dumps(record, indent=2) + "\n")
    if reseal:
        reseal_file(evidence_set, "copyofa/acquisition-record.json")


def as_version_1(evidence_set: Path) -> None:
    """Rewrite an acquired set's record as format version 1, as v0.7.0 wrote it."""

    def change(record: dict[str, Any]) -> None:
        record["format_version"] = 1
        for track in record["tracks"]:
            ranges = track.pop("error_ranges")
            track["error_frames"] = sum(error["frame_count"] for error in ranges)

    edit_record(evidence_set, change, reseal=True)


def reseal_file(evidence_set: Path, name: str) -> None:
    """Record a changed file's digest in the manifest that lists it."""
    manifest = evidence_set / (
        "manifest-sha256.txt" if name.startswith("data/") else "tagmanifest-sha256.txt"
    )
    digest = hashlib.sha256((evidence_set / name).read_bytes()).hexdigest()
    manifest.write_text(
        "".join(
            f"{digest}  {name}\n" if line.endswith(f"  {name}") else f"{line}\n"
            for line in manifest.read_text().splitlines()
        )
    )
    if manifest.name == "manifest-sha256.txt":
        reseal_file(evidence_set, manifest.name)
