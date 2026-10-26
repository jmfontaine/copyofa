"""Read a plain audio CD with redumper and preserve it as a new Evidence Set."""

from __future__ import annotations

import hashlib
import lzma
import mmap
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile

import copyofa
from copyofa import evidence_set, inspector, staging
from copyofa.errors import CopyOfAError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

READER = "redumper"
MINIMUM_BUILD = 768
"""The oldest redumper build acquire accepts: the one whose output it was tested on."""

IMAGE_NAME = "disc"
"""The `--image-name` acquire gives redumper, and so the stem of every file it keeps."""

DEFAULT_RETRIES = 20
"""How many times redumper re-reads a sector with a SCSI or C2 error, unless told.

The Redump project's guidance for audio CDs; redumper's own default is 0.
"""

FRAME_BYTES = evidence_set.CD_CHANNELS * evidence_set.CD_BITS_PER_SAMPLE // 8

FLAC = "flac"
XZ = "xz"
AS_WRITTEN = "as_written"

# redumper's State values, one byte per frame of the image: ERROR_SKIP (0) and
# ERROR_C2 (1) mark a frame that was not read successfully.
_FIRST_SUCCESS_STATE = 2

_CHUNK_SIZE = 1024 * 1024
_IMAGE_BLOCK_FRAMES = 1 << 16
_WINDOW_BYTES = 4096
_STOP_TIMEOUT = 10


class AcquisitionError(CopyOfAError):
    """An acquisition that was refused or failed; no Evidence Set was created."""


@dataclass(frozen=True)
class AcquisitionResult:
    evidence_set: Path
    acquisition_record: dict[str, Any]
    files: int
    bytes: int
    # Problems that did not fail the acquisition, reported on stderr.
    warnings: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "evidence_set": str(self.evidence_set),
            "acquisition_record": self.acquisition_record,
        }


def has_read_errors(record: dict[str, Any]) -> bool:
    """Tell whether an Acquisition Record shows audio that was not read cleanly.

    SCSI and C2 errors count, and so does a track frame not read successfully.
    Subchannel errors do not: the audio is read from the main channel.
    """
    errors = record["read_errors"]
    return bool(
        errors["scsi_samples"]
        or errors["c2_samples"]
        or any(track["error_frames"] for track in record["tracks"])
    )


def acquire(
    destination: str,
    *,
    drive: str | None = None,
    retries: int = DEFAULT_RETRIES,
    note: str | None = None,
    references: Sequence[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> AcquisitionResult:
    """Read the disc in a drive with redumper into a new Evidence Set at destination.

    Every refusal that does not depend on the disc happens before redumper reads it.
    redumper re-reads each sector it read with a SCSI or C2 error up to retries times.
    redumper writes into a staging directory beside the destination, where its files
    are stored and checked; the staging directory is renamed to the destination only
    once every check passes. Raises CopyOfAError, after removing the staging
    directory, when the acquisition is refused or fails. A disc read with errors is
    accepted: has_read_errors tells.
    """
    acquired_at = datetime.now(UTC)
    if note is not None:
        staging.require_utf8(note, "the --note text", "the Acquisition Record requires")
    for reference in references or ():
        staging.require_utf8(
            reference, "a --ref value", "the Acquisition Record requires"
        )
    if drive is not None:
        staging.require_utf8(
            drive, "the --drive value", "the Acquisition Record requires"
        )
    checked = staging.check_destination(destination)
    found = shutil.which(READER)
    if found is None:
        raise AcquisitionError(
            f"Refused: {READER} is not on PATH; acquire needs build "
            f"b{MINIMUM_BUILD} or later."
        )
    # Absolute, since redumper runs in the staging directory: a relative PATH entry
    # would otherwise be resolved there.
    executable = str(Path(found).absolute())
    build = _reader_build(executable)
    arguments = ["disc", f"--image-name={IMAGE_NAME}"]
    if drive is not None:
        arguments.append(f"--drive={drive}")
    arguments.append(f"--retries={retries}")

    record: dict[str, Any] = {
        "record_kind": evidence_set.ACQUISITION_RECORD_KIND,
        "format_version": evidence_set.ACQUISITION_RECORD_FORMAT_VERSION,
        "copyofa_version": copyofa.__version__,
        "acquired_at": acquired_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if note is not None:
        record["note"] = note
    if references is not None:
        record["external_references"] = list(references)
    record["reader"] = {"name": READER, "build": build, "arguments": arguments}

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    def build_set(root: Path) -> tuple[int, int]:
        work = root / READER
        work.mkdir()
        report(f"Reading the disc with {READER} {build}")
        _run_reader(executable, arguments, work, report)
        log = _read_log(work / f"{IMAGE_NAME}.log")
        if log.sessions > 1:
            raise AcquisitionError(
                f"Refused: the disc has {log.sessions} sessions; acquire accepts "
                "plain audio CDs only."
            )
        if log.data_tracks:
            raise AcquisitionError(
                f"Refused: track {log.data_tracks[0]} is a data track; acquire "
                "accepts plain audio CDs only."
            )
        cue = _read_cue(
            work / f"{IMAGE_NAME}.cue", _cd_text_codec(work / f"{IMAGE_NAME}.cdtext")
        )
        if [track.number for track in cue.tracks] != log.tracks:
            raise AcquisitionError(
                f"Failed: {READER}'s cue sheet and log list different tracks."
            )
        report("Locating each track in the image")
        image = _locate_tracks(work, cue.tracks)
        payload, stored_files = _store_files(
            work, root / evidence_set.PAYLOAD_DIR, cue, report
        )
        shutil.rmtree(work)
        record["drive"] = log.drive
        disc: dict[str, Any] = {}
        if log.write_offset is not None:
            disc["write_offset"] = log.write_offset
        disc.update(cue.disc)
        disc["image"] = {
            "path": evidence_set.DISC_IMAGE,
            "frames": image.frames,
            "sample_rate": evidence_set.CD_SAMPLE_RATE,
            "channels": evidence_set.CD_CHANNELS,
            "bits_per_sample": evidence_set.CD_BITS_PER_SAMPLE,
        }
        record["disc"] = disc
        record["read_errors"] = log.read_errors
        record["tracks"] = [track.to_json() for track in cue.tracks]
        record["stored_files"] = stored_files
        total = staging.build_bag(
            root, payload, evidence_set.ACQUISITION_RECORD, record, acquired_at
        )
        return len(payload), total

    (files, total), warnings = staging.accept(checked, "acquire", build_set)
    return AcquisitionResult(checked.target, record, files, total, warnings)


_BUILD = re.compile(r"\(build: b(\d+)\)")


def _reader_build(executable: str) -> str:
    """Return redumper's build, such as `b768`; refuse one too old or unreadable."""
    try:
        completed = subprocess.run(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AcquisitionError(
            f"Refused: cannot run `{READER} --version`: {error}."
        ) from None
    match = _BUILD.search(completed.stdout.decode(errors="replace"))
    if completed.returncode or match is None:
        raise AcquisitionError(
            f"Refused: `{READER} --version` does not give its build; acquire needs "
            f"build b{MINIMUM_BUILD} or later."
        )
    number = int(match.group(1))
    if number < MINIMUM_BUILD:
        raise AcquisitionError(
            f"Refused: {READER} build b{number} is older than b{MINIMUM_BUILD}, the "
            "oldest build acquire accepts."
        )
    return f"b{number}"


_STAGE = re.compile(r"\*\*\* (\S+)")


def _run_reader(
    executable: str,
    arguments: Sequence[str],
    work: Path,
    report: Callable[[str], None],
) -> None:
    """Run redumper in work; report each stage it starts, relay nothing else."""
    process = subprocess.Popen(
        [executable, *arguments],
        cwd=work,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    last = ""
    try:
        assert process.stdout is not None
        for line in _lines(process.stdout.fileno()):
            match = _STAGE.match(line)
            if match is not None:
                report(f"{READER} stage: {match.group(1).lower()}")
            if line.strip():
                last = line.strip()
        status = process.wait()
    except BaseException:
        _stop(process)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
    if status:
        detail = f" Its last message: {last}" if last else ""
        raise AcquisitionError(f"Failed: {READER} exited with status {status}.{detail}")


def _lines(fd: int) -> Iterator[str]:
    """Yield the lines of a console output, which ends them with \\n or \\r."""
    pending = b""
    while chunk := os.read(fd, 65536):
        *lines, pending = re.split(rb"[\r\n]", pending + chunk)
        for line in lines:
            yield line.decode(errors="replace")
        # A progress line rewritten without end could grow without bound.
        pending = pending[-4096:]
    if pending:
        yield pending.decode(errors="replace")


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Make redumper exit before its files are removed."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@dataclass
class _Log:
    """What acquire reads from redumper's log."""

    drive: dict[str, Any]
    tracks: list[int]
    """The numbers of the disc's tracks, from its table of contents."""
    data_tracks: list[int]
    sessions: int
    read_errors: dict[str, int]
    write_offset: int | None


_INQUIRY = re.compile(
    r"^ +inquiry: (.*?) - (.*) \(revision level: (.*?), vendor specific: .*\)$",
    re.MULTILINE,
)
_READ_OFFSET = re.compile(
    r"^ +configuration: .*\(read offset: ([+-]?\d+),", re.MULTILINE
)
_WRITE_OFFSET = re.compile(r"^disc write offset: ([+-]?\d+)$", re.MULTILINE)
_TOC = re.compile(r"^disc TOC:\n((?:.+\n)+)", re.MULTILINE)
_SESSION = re.compile(r"^ +session (\d+)$")
_TRACK = re.compile(r"^ +track (\w+) \{ *([^,}]*?) *(?:,[^}]*)?\}$")
_ERRORS = re.compile(
    r"^media errors: *\n +SCSI: (\d+) samples\n +C2: (\d+) samples\n +Q: (\d+)$",
    re.MULTILINE,
)


def _read_log(path: Path) -> _Log:
    """Read the drive, the table of contents, the errors and the write offset."""
    try:
        text = path.read_bytes().decode(errors="replace").replace("\r\n", "\n")
    except FileNotFoundError:
        raise AcquisitionError(f"Failed: {READER} wrote no log.") from None
    inquiry = _INQUIRY.search(text)
    if inquiry is None:
        raise _unreadable_log("it does not identify the drive")
    vendor, product, revision = (part.strip() for part in inquiry.groups())
    drive: dict[str, Any] = {"vendor": vendor, "product": product}
    if revision and revision != "<empty>":
        drive["firmware_revision"] = revision
    read_offset = _READ_OFFSET.search(text)
    if read_offset is not None:
        drive["read_offset"] = int(read_offset.group(1))

    toc = _TOC.search(text)
    if toc is None:
        raise _unreadable_log("it has no table of contents")
    tracks: list[int] = []
    data_tracks: list[int] = []
    sessions = 0
    for line in toc.group(1).splitlines():
        if _SESSION.match(line):
            sessions += 1
        elif track := _TRACK.match(line):
            number, kind = track.groups()
            # The lead-out is `A`, repeated to the width of the track numbers.
            if number == "A" * len(number):
                continue
            if not number.isdigit() or kind not in {"audio", "data"}:
                raise _unreadable_log(f"its table of contents has {line.strip()!r}")
            tracks.append(int(number))
            if kind == "data":
                data_tracks.append(int(number))
    if not tracks:
        raise _unreadable_log("its table of contents lists no track")

    errors = _ERRORS.search(text)
    if errors is None:
        raise _unreadable_log("it gives no media error counts")
    scsi, c2, q = (int(count) for count in errors.groups())
    write_offset = _WRITE_OFFSET.search(text)
    return _Log(
        drive=drive,
        tracks=tracks,
        data_tracks=data_tracks,
        sessions=max(sessions, 1),
        read_errors={
            "scsi_samples": scsi,
            "c2_samples": c2,
            "subchannel_q_sectors": q,
        },
        write_offset=None if write_offset is None else int(write_offset.group(1)),
    )


def _unreadable_log(reason: str) -> AcquisitionError:
    return AcquisitionError(f"Failed: {READER}'s log cannot be read: {reason}.")


@dataclass
class _Track:
    number: int
    file: str
    """The name of redumper's track file."""
    cue: dict[str, str] = field(default_factory=dict)
    """The ISRC and CD-Text title and performer the cue sheet gives."""
    first_frame: int = 0
    frame_count: int = 0
    sha256: str = ""
    error_frames: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "first_frame": self.first_frame,
            "frame_count": self.frame_count,
            "audio_digest": (
                f"{inspector.DIGEST_SCHEME}:{evidence_set.CD_SAMPLE_RATE}:{evidence_set.CD_CHANNELS}:"
                f"{evidence_set.CD_BITS_PER_SAMPLE}:{self.sha256}"
            ),
            **self.cue,
            "error_frames": self.error_frames,
        }


@dataclass
class _Cue:
    disc: dict[str, str]
    """The catalog number and CD-Text album title and performer, when given."""
    tracks: list[_Track]


_CUE_LINE = re.compile(r'^\s*([A-Z]+)\s+(?:"(.*)"|(\S+))(?:\s+(\S+))?\s*$')
_CUE_FIELDS = {"TITLE": "title", "PERFORMER": "performer"}

# CD-Text character codes, as its block size information gives them, and the codec
# of each that redumper supports.
_CD_TEXT_CODECS = {0x00: "latin-1", 0x01: "ascii", 0x80: "cp932"}
_CD_TEXT_PACK = 18
_CD_TEXT_SIZE_INFO = 0x8F


def _cd_text_codec(path: Path) -> str | None:
    """Return the codec of the CD-Text's first block, as redumper decides it.

    redumper copies CD-Text bytes verbatim into the cue sheet. Without block size
    information, it assumes ISO 8859-1. Returns None for a character code it does
    not support.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return _CD_TEXT_CODECS[0x00]
    # A 4-byte header, then 18-byte packs: type, track, sequence, block and
    # character position, 12 bytes of content, and a CRC.
    for start in range(4, len(data) - _CD_TEXT_PACK + 1, _CD_TEXT_PACK):
        pack = data[start : start + _CD_TEXT_PACK]
        if pack[0] == _CD_TEXT_SIZE_INFO and pack[1] == 0 and (pack[3] >> 4) & 7 == 0:
            return _CD_TEXT_CODECS.get(pack[4])
    return _CD_TEXT_CODECS[0x00]


def _read_cue(path: Path, codec: str | None) -> _Cue:
    """Read the tracks' files, the catalog number, ISRCs and CD-Text titles.

    CD-Text is decoded with codec, and left out when it is None or the text does not
    decode with it.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise AcquisitionError(f"Failed: {READER} wrote no cue sheet.") from None
    # Byte for byte, so CD-Text can be decoded with its own codec.
    text = data.decode("latin-1")
    disc: dict[str, str] = {}
    tracks: list[_Track] = []
    file: str | None = None
    # Only line feeds end a line: splitlines() would also split at bytes, such as
    # 0x85, that occur inside MS-JIS characters.
    for line in text.split("\n"):
        match = _CUE_LINE.match(line.removesuffix("\r"))
        if match is None:
            continue
        keyword, quoted, word, extra = match.groups()
        value = quoted if quoted is not None else word
        if keyword == "FILE":
            file = value
        elif keyword == "TRACK":
            if file is None or extra != "AUDIO" or not value.isdigit():
                raise _unreadable_cue(line)
            if tracks and tracks[-1].file == file:
                raise _unreadable_cue(line)
            tracks.append(_Track(int(value), file))
        elif keyword == "CATALOG" and not tracks:
            disc["catalog"] = value
        elif keyword == "ISRC" and tracks:
            tracks[-1].cue["isrc"] = value
        elif keyword in _CUE_FIELDS and value and codec is not None:
            try:
                decoded = value.encode("latin-1").decode(codec)
            except UnicodeDecodeError:
                continue
            target = tracks[-1].cue if tracks else disc
            target[_CUE_FIELDS[keyword]] = decoded
    for track in tracks:
        if "/" in track.file or track.file in {"", ".", ".."}:
            raise _unreadable_cue(f'FILE "{track.file}"')
    return _Cue(disc, tracks)


def _unreadable_cue(line: str) -> AcquisitionError:
    return AcquisitionError(
        f"Failed: {READER}'s cue sheet cannot be read: {line.strip()!r}."
    )


@dataclass(frozen=True)
class _Image:
    frames: int


def _locate_tracks(work: Path, tracks: Sequence[_Track]) -> _Image:
    """Find each track's range in the image and count its frames not read well."""
    image_path = work / f"{IMAGE_NAME}.scram"
    state_path = work / f"{IMAGE_NAME}.state"
    size = _size(image_path, "image")
    if not size or size % FRAME_BYTES:
        raise AcquisitionError(
            f"Failed: {READER}'s image is not a whole number of stereo frames."
        )
    frames = size // FRAME_BYTES
    if _size(state_path, "state") != frames:
        raise AcquisitionError(
            f"Failed: {READER}'s state does not hold one byte per frame of its image."
        )
    sizes = [_track_size(work, track) for track in tracks]
    starts: list[int | None] = [None] * len(tracks)
    with (
        image_path.open("rb") as file,
        mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as image,
    ):
        # Where the previous track ends, else wherever a part of the track that is
        # not a single repeated byte occurs.
        for index, track in enumerate(tracks):
            previous = starts[index - 1] if index else None
            hint = None if previous is None else previous + sizes[index - 1]
            starts[index] = _find(image, work / track.file, hint)
        # A track of a single repeated byte, such as digital silence, that starts
        # the disc: where the next track begins.
        for index in reversed(range(len(tracks) - 1)):
            following = starts[index + 1]
            if starts[index] is None and following is not None:
                hint = following - sizes[index]
                if hint >= 0:
                    starts[index] = _find(image, work / tracks[index].file, hint)
    for index, (track, start, length) in enumerate(
        zip(tracks, starts, sizes, strict=True)
    ):
        if start is None:
            message = (
                f"Failed: the bytes of {track.file}, track {track.number}, are found "
                "nowhere in the image, or are a single repeated byte that no other "
                "track places in it."
            )
            unread = _unread_where(state_path, frames, starts, sizes, index)
            if unread:
                message += (
                    f" The state marks {unread} frames where it would lie as not "
                    f"read, and {READER} replaces unread sectors with generated ones "
                    "when it splits the disc into track files."
                )
            raise AcquisitionError(message)
        track.first_frame = start // FRAME_BYTES
        track.frame_count = length // FRAME_BYTES
        with (work / track.file).open("rb") as data:
            track.sha256 = hashlib.file_digest(data, "sha256").hexdigest()
        state = np.fromfile(
            state_path,
            dtype=np.uint8,
            count=track.frame_count,
            offset=track.first_frame,
        )
        track.error_frames = int(np.count_nonzero(state < _FIRST_SUCCESS_STATE))
    return _Image(frames)


def _unread_where(
    state_path: Path,
    frames: int,
    starts: Sequence[int | None],
    sizes: Sequence[int],
    index: int,
) -> int:
    """Count the frames not read well where a track that was not found would lie.

    That is right after the previous track, else right before the next one; with
    neither found, nothing tells where it would lie.
    """
    length = sizes[index] // FRAME_BYTES
    previous = starts[index - 1] if index else None
    following = starts[index + 1] if index + 1 < len(starts) else None
    if previous is not None:
        first = (previous + sizes[index - 1]) // FRAME_BYTES
    elif following is not None:
        first = following // FRAME_BYTES - length
    else:
        return 0
    first, end = max(first, 0), min(first + length, frames)
    if first >= end:
        return 0
    state = np.fromfile(state_path, dtype=np.uint8, count=end - first, offset=first)
    return int(np.count_nonzero(state < _FIRST_SUCCESS_STATE))


def _size(path: Path, what: str) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        raise AcquisitionError(f"Failed: {READER} wrote no {what}.") from None


def _track_size(work: Path, track: _Track) -> int:
    try:
        size = (work / track.file).stat().st_size
    except FileNotFoundError:
        raise AcquisitionError(
            f"Failed: {READER} did not write {track.file}, the file of track "
            f"{track.number}."
        ) from None
    if not size or size % FRAME_BYTES:
        raise AcquisitionError(
            f"Failed: {track.file} is not a whole number of stereo frames."
        )
    return size


def _find(image: mmap.mmap, path: Path, hint: int | None) -> int | None:
    """Return where the image holds exactly a track file's bytes, at a frame start.

    Tries hint first. Without it, or when the image does not hold the track there,
    searches for a part of the track that is not a single repeated byte; a track
    with no such part could be anywhere a run of that byte is, so it is not searched.
    """
    with (
        path.open("rb") as file,
        mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as track,
    ):
        if hint is not None and _holds(image, hint, track):
            return hint
        offset = 0
        while offset < len(track):
            window = track[offset : offset + _WINDOW_BYTES]
            if window != window[:1] * len(window):
                break
            offset += _WINDOW_BYTES
        else:
            return None
        position = image.find(window)
        while position != -1:
            start = position - offset
            if start >= 0 and start % FRAME_BYTES == 0 and _holds(image, start, track):
                return start
            position = image.find(window, position + 1)
    return None


def _holds(image: mmap.mmap, start: int, track: mmap.mmap) -> bool:
    size = len(track)
    if start + size > len(image):
        return False
    return all(
        image[start + index : start + min(index + _CHUNK_SIZE, size)]
        == track[index : index + _CHUNK_SIZE]
        for index in range(0, size, _CHUNK_SIZE)
    )


# disc.<extension>, or disc_<language code>.cue, a cue sheet for each further
# CD-Text language.
_KEPT_NAME = re.compile(rf"{IMAGE_NAME}\.[A-Za-z0-9]+|{IMAGE_NAME}_[0-9A-F]{{2}}\.cue")
# The lead-in and lead-out, which redumper writes as tracks 0 and A when they hold
# audio, and leaves out of the cue sheet; the image holds them.
_LEAD_TRACK_NAME = re.compile(rf"{IMAGE_NAME} \(Track (0+|A+)\)\.bin")


def _store_files(
    work: Path, data: Path, cue: _Cue, report: Callable[[str], None]
) -> tuple[list[tuple[str, str, int]], list[dict[str, Any]]]:
    """Store every file redumper wrote but the track files, and check each.

    Returns the payload entries and the record's `stored_files`, sorted by path.
    """
    track_files = {track.file for track in cue.tracks}
    track_files.update(
        entry.name for entry in work.iterdir() if _LEAD_TRACK_NAME.fullmatch(entry.name)
    )
    names = sorted(entry.name for entry in work.iterdir())
    for name in names:
        if name not in track_files and not (
            _KEPT_NAME.fullmatch(name) and (work / name).is_file()
        ):
            raise AcquisitionError(f"Failed: {READER} wrote an unexpected {name!r}.")
    data.mkdir()
    entries = []
    for name in names:
        if name in track_files:
            continue
        source = work / name
        size = source.stat().st_size
        original = staging.digest_file(source)
        if name == f"{IMAGE_NAME}.scram":
            storage, target = FLAC, data / f"{name}.flac"
            report(f"Compressing {name} as FLAC")
            try:
                _compress_image(source, target)
                decoded = _decoded_image_digest(target)
            except soundfile.LibsndfileError as error:
                raise AcquisitionError(
                    f"Failed: cannot store {name} as FLAC: {error.error_string}."
                ) from None
        elif name in {f"{IMAGE_NAME}.state", f"{IMAGE_NAME}.subcode"}:
            storage, target = XZ, data / f"{name}.xz"
            report(f"Compressing {name} as xz")
            _compress_xz(source, target)
            try:
                decoded = _decoded_xz_digest(target)
            except lzma.LZMAError as error:
                raise AcquisitionError(
                    f"Failed: cannot decode {target.name}: {error}."
                ) from None
        else:
            storage, target = AS_WRITTEN, data / name
            source.rename(target)
            staging.sync_file(target)
            decoded = staging.digest_file(target)
        if decoded != original:
            raise AcquisitionError(
                f"Failed: {target.name} does not decode to {READER}'s {name}."
            )
        source.unlink(missing_ok=True)
        path = f"{evidence_set.PAYLOAD_DIR}/{target.name}"
        stored_size = target.stat().st_size
        report(f"Stored {path} ({stored_size} bytes)")
        entries.append(
            (
                (path, staging.digest_file(target), stored_size),
                {
                    "path": path,
                    "storage": storage,
                    "original_name": name,
                    "original_size": size,
                    "original_sha256": original,
                },
            )
        )
    entries.sort(key=lambda entry: entry[0][0])
    return [payload for payload, _ in entries], [stored for _, stored in entries]


def _compress_image(source: Path, target: Path) -> None:
    """Write the image as 16-bit stereo FLAC at libsndfile's highest level."""
    with (
        source.open("rb") as file,
        soundfile.SoundFile(
            target,
            "x",
            evidence_set.CD_SAMPLE_RATE,
            evidence_set.CD_CHANNELS,
            f"PCM_{evidence_set.CD_BITS_PER_SAMPLE}",
            format="FLAC",
            compression_level=1.0,
        ) as sound,
    ):
        while chunk := file.read(_IMAGE_BLOCK_FRAMES * FRAME_BYTES):
            samples = np.frombuffer(chunk, dtype="<i2").astype(np.int16, copy=False)
            sound.write(samples.reshape(-1, evidence_set.CD_CHANNELS))
    staging.sync_file(target)


def _decoded_image_digest(path: Path) -> str:
    """Decode the stored image; return the SHA-256 of its little-endian PCM."""
    digest = hashlib.sha256()
    shift = 32 - evidence_set.CD_BITS_PER_SAMPLE
    with soundfile.SoundFile(path) as sound:
        for block in inspector.read_blocks(sound, "int32"):
            digest.update(np.right_shift(block, shift).astype("<i2").tobytes())
    return digest.hexdigest()


def _compress_xz(source: Path, target: Path) -> None:
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_XZ)
    with source.open("rb") as file, target.open("xb") as out:
        while chunk := file.read(_CHUNK_SIZE):
            out.write(compressor.compress(chunk))
        out.write(compressor.flush())
        out.flush()
        os.fsync(out.fileno())


def _decoded_xz_digest(path: Path) -> str:
    digest = hashlib.sha256()
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK_SIZE):
            digest.update(decompressor.decompress(chunk))
    if not decompressor.eof:
        raise AcquisitionError(f"Failed: {path.name} is not a complete xz stream.")
    return digest.hexdigest()
