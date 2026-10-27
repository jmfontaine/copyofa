"""Describe the audio in an Evidence Set."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO

import numpy as np
import soundfile

import copyofa
from copyofa import evidence_set, verifier

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from io import FileIO
    from pathlib import Path

    import numpy.typing as npt

    Sink = Callable[[npt.NDArray[np.float32]], None]

REPORT_KIND = "copyofa.inspection"
REPORT_FORMAT_VERSION = 2

INTERPRETED = "interpreted"
NOT_INTERPRETED = "not_interpreted"
FAILED = "failed"
NOT_INSPECTED = "not_inspected"
OUTCOMES = (INTERPRETED, NOT_INTERPRETED, FAILED, NOT_INSPECTED)

MD5_MATCHING = "matching"
MD5_DIFFERS = "differs"
MD5_ABSENT = "absent"

DIGEST_SCHEME = "pcm1"
"""The Audio Digest definition of ADR 0002."""

LIMITATIONS = (
    (
        "Only the files manifest-sha256.txt lists are inspected; verify reports "
        "unexpected files."
    ),
    (
        "An Audio Digest recognizes identical decoded audio. It does not say what "
        "the audio is, and it establishes neither its source nor the accuracy of its "
        "acquisition."
    ),
    (
        "A file that is not interpreted may still hold audio, in a format CopyOfA "
        "does not decode. Archives are not opened, and tags and embedded artwork are "
        "not read."
    ),
)

MP3_LIMITATION = (
    "MP3 is lossy: its decoded samples, and so its frame count, depend on the "
    "decoder, so it has no Audio Digest."
)

_UNUSABLE = "the Integrity Baseline is unusable"
_RECORD = "the Acquisition Record"
_CD_FORMAT = (
    evidence_set.CD_SAMPLE_RATE,
    evidence_set.CD_CHANNELS,
    evidence_set.CD_BITS_PER_SAMPLE,
)
_CD_DIGEST_PREFIX = f"{DIGEST_SCHEME}:{':'.join(map(str, _CD_FORMAT))}:"
_CD_DIGEST = re.compile(rf"{_CD_DIGEST_PREFIX}[0-9a-f]{{64}}")
_EXPECTED_SUFFIXES = frozenset({".flac", ".wav", ".mp3"})
_BLOCK_FRAMES = 1 << 16

# The libsndfile subtypes CopyOfA decodes exactly, with their bits per sample.
_PCM_BITS = {"PCM_S8": 8, "PCM_U8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32}
_FLAC_BITS = frozenset({8, 16, 24})
_FORMATS = {"FLAC": "flac", "WAV": "wav", "WAVEX": "wav", "MP3": "mp3"}
_MP3_SUBTYPE = "MPEG_LAYER_III"


@dataclass(frozen=True)
class _StreamInfo:
    """The fields of a FLAC STREAMINFO block that inspect uses."""

    bits_per_sample: int
    total_samples: int
    """Sample frames per channel; 0 when the encoder did not know the length."""
    md5: bytes
    """The MD5 signature of the canonical PCM byte stream; all zeros when absent."""


class _UnreadableError(Exception):
    """A FLAC stream whose STREAMINFO block cannot be read."""


class UnusableRecordError(Exception):
    """An Acquisition Record that cannot be used; the message says why."""


@dataclass(frozen=True)
class RecordedTrack:
    """A track as the Acquisition Record gives it."""

    number: int
    first_frame: int
    """Where the track starts in the image, in frames."""
    frame_count: int
    audio_digest: str
    """The Audio Digest recorded at acquisition."""


@dataclass(frozen=True)
class AcquiredDisc:
    """What a usable Acquisition Record says about the disc image and its tracks."""

    image: str
    """The image's path in the Evidence Set."""
    image_digest: str
    """The image's SHA-256, as the payload manifest records it."""
    tracks: tuple[RecordedTrack, ...]

    def track(self, number: int) -> RecordedTrack | None:
        """Return the track with this number, or None when the record lists none."""
        return next((track for track in self.tracks if track.number == number), None)


def inspect(
    target: str, progress: Callable[[dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    """Inspect the Evidence Set at target and return its inspection Report.

    Calls progress with each file's Report entry as it is inspected. Writes nothing.
    Raises verifier.NotAnEvidenceSetError when target is not an Evidence Set.
    """
    root = verifier.locate(target)
    inspected_at = datetime.now(UTC)
    baseline = verifier.read_baseline(root)
    disc: dict[str, Any] | None = None
    try:
        acquired = read_acquired_disc(root, baseline)
    except UnusableRecordError as error:
        acquired = None
        disc = {"reason": str(error)}
    with ExitStack() as stack:
        # Read and checked once, for its own entry and for every track.
        image = (
            None
            if acquired is None
            else stack.enter_context(
                open_accepted(root, acquired.image, acquired.image_digest)
            )
        )
        files = []
        for digest, path in baseline.entries:
            if not baseline.usable:
                entry = _entry(path, digest, NOT_INSPECTED, reason=_UNUSABLE)
            elif image is not None and path == image.path:
                entry = inspect_accepted(image)
            else:
                entry = inspect_file(root, path, digest)
            if progress is not None:
                progress(entry)
            files.append(entry)
        if acquired is not None and image is not None:
            disc = _inspect_disc(acquired, image, progress)
    counts = Counter(entry["outcome"] for entry in files)
    return {
        "report_kind": REPORT_KIND,
        "format_version": REPORT_FORMAT_VERSION,
        "copyofa_version": copyofa.__version__,
        "inspected_at": inspected_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_set": str(root),
        "integrity_baseline": baseline.to_json(),
        "method": {
            "decoder": "libsndfile",
            "decoder_version": soundfile.__libsndfile_version__,
        },
        "files": files,
        **({} if disc is None else {"disc": disc}),
        "counts": {outcome: counts[outcome] for outcome in OUTCOMES},
        "limitations": list(LIMITATIONS),
    }


def found_problems(report: dict[str, Any]) -> bool:
    """Tell whether an inspection Report found anything that makes inspect exit 1."""
    disc = report.get("disc", {})
    return (
        not report["integrity_baseline"]["usable"]
        or any(
            entry["outcome"] in {FAILED, NOT_INSPECTED}
            or entry.get("flac_md5_signature") == MD5_DIFFERS
            for entry in report["files"]
        )
        or "reason" in disc
        or any(
            track["outcome"] != INTERPRETED
            or track["audio_digest"] != track["recorded_audio_digest"]
            for track in disc.get("tracks", [])
        )
    )


def _inspect_disc(
    disc: AcquiredDisc,
    image: AcceptedFile,
    progress: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    """Describe each track of an acquired set, decoded from its opened image."""
    tracks = []
    for track in disc.tracks:
        findings = decode_track(image, track)
        entry: dict[str, Any] = {
            "number": track.number,
            "first_frame": track.first_frame,
            "frame_count": track.frame_count,
            "outcome": findings["outcome"],
        }
        if "reason" in findings:
            entry["reason"] = findings["reason"]
        if "audio_digest" in findings:
            entry["audio_digest"] = findings["audio_digest"]
        entry["recorded_audio_digest"] = track.audio_digest
        if findings["outcome"] == INTERPRETED:
            for key in (
                "frames",
                "peak",
                "leading_silence_frames",
                "trailing_silence_frames",
            ):
                entry[key] = findings[key]
        if progress is not None:
            progress(entry)
        tracks.append(entry)
    return {"tracks": tracks}


def read_acquired_disc(root: Path, baseline: verifier.Baseline) -> AcquiredDisc | None:
    """Read the Acquisition Record of the Evidence Set at root, if it may be used.

    Returns None when the tag manifest does not list the record: the set is not an
    acquired set. Raises UnusableRecordError when the baseline is unusable, or the
    record is not the bytes the tag manifest records or cannot be read or parsed.
    """
    listed = next(
        (
            item
            for item in baseline.tag_files
            if item["path"] == evidence_set.ACQUISITION_RECORD
        ),
        None,
    )
    if listed is None:
        return None
    if not baseline.usable:
        raise UnusableRecordError(_UNUSABLE)
    problem = verifier.find_file(root, evidence_set.ACQUISITION_RECORD)
    if problem is not None:
        if problem[0] == verifier.MISSING:
            raise UnusableRecordError(f"{_RECORD} is missing")
        raise UnusableRecordError(f"{_RECORD} cannot be read: {problem[1]}")
    # Read once: the bytes checked against the tag manifest are the bytes parsed.
    read = verifier.read_record(root, evidence_set.ACQUISITION_RECORD)
    if read.data is None:
        raise UnusableRecordError(f"{_RECORD} {read.problem}")
    if hashlib.sha256(read.data).hexdigest() != listed["expected_digest"]:
        raise UnusableRecordError(f"{_RECORD}'s digest differs from the tag manifest's")
    try:
        record = json.loads(read.data)
    except ValueError as error:
        raise UnusableRecordError(f"{_RECORD} cannot be parsed: {error}") from None
    except RecursionError:
        raise UnusableRecordError(
            f"{_RECORD} cannot be parsed: it is nested too deeply"
        ) from None
    return _acquired_disc(record, {path: digest for digest, path in baseline.entries})


def _acquired_disc(record: Any, manifest: dict[str, str]) -> AcquiredDisc:
    """Take the image and the track ranges from a parsed Acquisition Record."""
    if not isinstance(record, dict):
        raise _unusable("it is not a JSON object")
    kind = evidence_set.ACQUISITION_RECORD_KIND
    version = evidence_set.ACQUISITION_RECORD_FORMAT_VERSION
    if (
        record.get("record_kind") != kind
        or record.get("format_version") != version
        # Not 1.0, nor true, which compare equal to 1.
        or type(record.get("format_version")) is not int
    ):
        raise UnusableRecordError(
            f"{_RECORD} is not format version {version} of {kind}"
        )
    disc = record.get("disc")
    image = disc.get("image") if isinstance(disc, dict) else None
    if not isinstance(image, dict) or not isinstance(image.get("path"), str):
        raise _unusable("it names no disc image")
    if image["path"] not in manifest:
        raise _unusable(
            f"its disc image {image['path']} is not listed in {evidence_set.MANIFEST}"
        )
    if (
        image.get("sample_rate"),
        image.get("channels"),
        image.get("bits_per_sample"),
    ) != _CD_FORMAT:
        raise _unusable("its disc image is not 16-bit stereo at 44.1 kHz")
    entries = record.get("tracks")
    if not isinstance(entries, list) or not entries:
        raise _unusable("it lists no track")
    tracks: list[RecordedTrack] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or not _is_count(entry.get("number"), 1):
            raise _unusable(f"its track entry {index} has no valid number")
        number = entry["number"]
        if any(track.number == number for track in tracks):
            raise _unusable(f"it lists track {number} twice")
        for field, minimum in (("first_frame", 0), ("frame_count", 1)):
            if not _is_count(entry.get(field), minimum):
                raise _unusable(f"track {number} has no valid {field}")
        digest = entry.get("audio_digest")
        if not isinstance(digest, str) or not _CD_DIGEST.fullmatch(digest):
            raise _unusable(f"track {number} has no valid audio_digest")
        tracks.append(
            RecordedTrack(number, entry["first_frame"], entry["frame_count"], digest)
        )
    return AcquiredDisc(image["path"], manifest[image["path"]], tuple(tracks))


def _unusable(reason: str) -> UnusableRecordError:
    return UnusableRecordError(f"{_RECORD} cannot be used: {reason}")


def _is_count(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _read_streaminfo(file: BinaryIO) -> _StreamInfo | None:
    """Read the STREAMINFO block of a FLAC stream, from the file's start.

    Returns None when the content is not FLAC, after an optional ID3v2 tag, which
    libsndfile and `flac` also skip. Raises _UnreadableError when it is FLAC but its
    STREAMINFO block cannot be read.
    """
    file.seek(0)
    head = file.read(10)
    offset = 0
    if len(head) == 10 and head[:3] == b"ID3":
        size = 0
        for byte in head[6:10]:
            size = (size << 7) | (byte & 0x7F)
        footer = 10 if head[5] & 0x10 else 0
        offset = 10 + size + footer
    file.seek(offset)
    if file.read(4) != b"fLaC":
        return None
    block = file.read(4 + 34)
    # The first metadata block must be STREAMINFO: type 0, 34 bytes long.
    if len(block) < 38 or block[0] & 0x7F != 0 or block[1:4] != b"\x00\x00\x22":
        raise _UnreadableError
    # After the block and frame sizes (10 bytes): sample rate (20 bits), channels
    # minus one (3), bits per sample minus one (5), total samples (36), then MD5.
    fields = int.from_bytes(block[14:22], "big")
    return _StreamInfo(
        bits_per_sample=((fields >> 36) & 0x1F) + 1,
        total_samples=fields & 0xF_FFFF_FFFF,
        md5=block[22:38],
    )


def _entry(
    path: str,
    expected: str | None,
    outcome: str,
    *,
    observed: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path, "outcome": outcome}
    if expected is not None:
        entry["expected_digest"] = expected
    if observed is not None:
        entry["observed_digest"] = observed
    if reason is not None:
        entry["reason"] = reason
    return entry


@dataclass(frozen=True)
class AcceptedFile:
    """A listed file, opened once by open_accepted, and what checking it found."""

    path: str
    """The file's path, relative to the directory it was opened in."""
    expected: str | None
    """The SHA-256 the manifest records; None when it is not checked."""
    problem: dict[str, Any] | None = None
    """Why the file is not inspected, as findings; None when it is open."""
    file: BinaryIO | None = None
    """The open file, when there is no problem."""
    before: os.stat_result | None = None
    """The file's status when it was opened, before it was read."""
    observed: str | None = None
    """The SHA-256 of the file's content, when it was read completely."""

    def read(self, interpret: Callable[[BinaryIO], dict[str, Any]]) -> dict[str, Any]:
        """Interpret the file, which holds the checked bytes while it is unchanged.

        Returns interpret's findings, with `outcome` `interpreted` unless they give
        another, or `not_inspected` with a reason: the file's problem, or a change
        to its size or modification time since it was opened, before interpret
        ended. Adds `observed_digest` once the file was read completely.
        """
        if self.problem is not None:
            return dict(self.problem)
        file, before = self.file, self.before
        assert file is not None
        assert before is not None
        try:
            findings = {
                "outcome": INTERPRETED,
                **({} if self.observed is None else {"observed_digest": self.observed}),
                **interpret(file),
            }
            after = os.fstat(file.fileno())
        except OSError as error:
            return _not_inspected(f"cannot be read: {error.strerror}")
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return _not_inspected(
                "the file changed while it was inspected", self.observed
            )
        return findings


@contextmanager
def open_accepted(
    root: Path, path: str, expected: str | None
) -> Generator[AcceptedFile]:
    """Open a listed file, read it completely and check its SHA-256 against expected.

    Yields the file, open until the block ends, or, when it cannot be opened, is not
    a regular file, cannot be read or does not match expected, its problem. With
    expected None, the file is opened but not hashed: its SHA-256 is not checked.
    """
    problem = verifier.find_file(root, path)
    if problem is not None:
        yield AcceptedFile(path, expected, _not_inspected(problem[1]))
        return
    try:
        # Non-blocking, so a named pipe swapped in cannot hang inspect.
        fd = os.open(root / path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        reason = f"cannot be read: {error.strerror}"
        yield AcceptedFile(path, expected, _not_inspected(reason))
        return
    # Unbuffered: libsndfile moves the offset of the descriptor it shares, which a
    # buffer kept between two reads would not see.
    with os.fdopen(fd, "rb", buffering=0) as file:
        yield _check(file, path, expected)


def _check(file: FileIO, path: str, expected: str | None) -> AcceptedFile:
    """Check an open file is regular and, when expected is given, its SHA-256."""
    try:
        before = os.fstat(file.fileno())
        if not stat.S_ISREG(before.st_mode):
            problem = _not_inspected("a special file, not a regular file")
            return AcceptedFile(path, expected, problem)
        if expected is None:
            return AcceptedFile(path, expected, file=file, before=before)
        observed = hashlib.file_digest(file, "sha256").hexdigest()
    except OSError as error:
        problem = _not_inspected(f"cannot be read: {error.strerror}")
        return AcceptedFile(path, expected, problem)
    if observed != expected:
        problem = _not_inspected("its digest differs from the manifest's", observed)
        return AcceptedFile(path, expected, problem)
    return AcceptedFile(path, expected, None, file, before, observed)


def inspect_file(
    root: Path,
    path: str,
    expected: str | None,
    sink: Callable[[npt.NDArray[np.float32]], None] | None = None,
) -> dict[str, Any]:
    """Check one listed file against the baseline, then interpret it.

    Returns the file's Report entry. When sink is given, it receives the decoded
    frames block by block, shaped (frames, channels), as float32 where 1.0 is full
    scale; 32-bit PCM is rounded to float32's 24-bit precision. They are the file's
    audio only when the entry's outcome is `interpreted`. With expected None, the
    file's SHA-256 is neither computed nor checked, and the entry has no digest.
    """
    with open_accepted(root, path, expected) as accepted:
        return inspect_accepted(accepted, sink)


def inspect_accepted(
    accepted: AcceptedFile,
    sink: Callable[[npt.NDArray[np.float32]], None] | None = None,
) -> dict[str, Any]:
    """Interpret a file open_accepted opened; return its entry, as inspect_file."""
    suffix = PurePosixPath(accepted.path).suffix.lower()
    findings = accepted.read(lambda file: _interpret(file, suffix, sink))
    entry = _entry(
        accepted.path,
        accepted.expected,
        findings.pop("outcome"),
        observed=findings.pop("observed_digest", None),
    )
    entry.update(findings)
    return entry


def decode_track(
    image: AcceptedFile,
    track: RecordedTrack,
    sink: Callable[[npt.NDArray[np.float32]], None] | None = None,
) -> dict[str, Any]:
    """Decode one track's range of the disc image open_accepted opened.

    Returns the track's outcome, with a reason when it is not `interpreted`, the
    image's File Digest when the image was read completely, and, when interpreted,
    the track's audio properties, frames, Audio Digest, peak and silences. sink
    receives the track's frames as inspect_file's does.
    """
    findings = image.read(lambda file: _decode_range(file, track, sink))
    if findings["outcome"] == NOT_INSPECTED:
        findings["reason"] = (
            f"the disc image {image.path} was not inspected: {findings['reason']}"
        )
    return findings


def _not_inspected(reason: str, observed: str | None = None) -> dict[str, Any]:
    findings = {"outcome": NOT_INSPECTED, "reason": reason}
    if observed is not None:
        findings["observed_digest"] = observed
    return findings


def _decode_range(
    file: BinaryIO, track: RecordedTrack, sink: Sink | None
) -> dict[str, Any]:
    """Decode a track's range of the disc image exactly and measure it."""
    os.lseek(file.fileno(), 0, os.SEEK_SET)
    # A duplicate, which libsndfile owns and closes, as in _interpret.
    duplicate = os.dup(file.fileno())
    try:
        sound = soundfile.SoundFile(duplicate, closefd=True)
    except soundfile.LibsndfileError as error:
        return _failed(f"libsndfile cannot open the disc image: {error.error_string}")
    with sound:
        bits = evidence_set.CD_BITS_PER_SAMPLE
        if (
            sound.format != "FLAC"
            or (sound.samplerate, sound.channels, _PCM_BITS.get(sound.subtype))
            != _CD_FORMAT
        ):
            return _failed("the disc image is not 16-bit stereo FLAC at 44.1 kHz")
        end = track.first_frame + track.frame_count
        if end > sound.frames:
            return _failed(
                f"the range ends after the image's {sound.frames} frames, at {end}"
            )
        digest = hashlib.sha256()
        measures = _Measures(sound.channels, integer=True)
        frames = 0
        try:
            sound.seek(track.first_frame)
            # Only the range, so no error outside it makes the track fail.
            for block in read_blocks(sound, "int32", track.frame_count):
                # libsndfile scales integer samples to the full 32-bit range.
                samples = np.right_shift(block, 32 - bits)
                digest.update(_canonical_bytes(samples, bits))
                measures.add(samples)
                if sink is not None:
                    sink(samples.astype(np.float32) * np.float32(1 / (1 << (bits - 1))))
                frames += len(samples)
        except soundfile.LibsndfileError as error:
            return _failed(
                f"decoding stopped after {frames} frames of the range: "
                f"{error.error_string}"
            )
        if frames != track.frame_count:
            return _failed(
                f"decoding stopped after {frames} of the range's "
                f"{track.frame_count} frames"
            )
        return {
            **_properties(sound, "flac", frames, bits),
            "audio_digest": f"{_CD_DIGEST_PREFIX}{digest.hexdigest()}",
            **measures.to_json(),
        }


def _interpret(file: BinaryIO, suffix: str, sink: Sink | None) -> dict[str, Any]:
    """Decode a file; return its outcome, with a reason or its findings."""
    try:
        streaminfo = _read_streaminfo(file)
    except _UnreadableError:
        return _failed("its FLAC STREAMINFO block cannot be read")
    if streaminfo is not None:
        if streaminfo.bits_per_sample not in _FLAC_BITS:
            return _not_interpreted(
                f"{streaminfo.bits_per_sample}-bit FLAC is not supported by the decoder"
            )
        if streaminfo.total_samples == 0:
            return _not_interpreted(
                "FLAC whose STREAMINFO gives no length is not supported by the decoder"
            )
    # A descriptor, not the file object: libsndfile then reads in C, where a
    # Ctrl-C or an I/O error is not lost inside a cffi callback. Rewind the
    # descriptor itself; the file object's buffer may have kept it elsewhere.
    os.lseek(file.fileno(), 0, os.SEEK_SET)
    # A duplicate, which libsndfile owns and closes, also when it cannot open the
    # file: libsndfile 1.2.0 does so even when told not to close it.
    duplicate = os.dup(file.fileno())
    try:
        sound = soundfile.SoundFile(duplicate, closefd=True)
    except soundfile.LibsndfileError as error:
        if streaminfo is not None or suffix in _EXPECTED_SUFFIXES:
            return _failed(f"libsndfile cannot open it: {error.error_string}")
        return _not_interpreted("no supported audio format was recognized")
    with sound:
        kind = _FORMATS.get(sound.format)
        if kind is None:
            return _not_interpreted(f"{sound.format} audio is not supported")
        if kind == "mp3":
            if sound.subtype != _MP3_SUBTYPE:
                return _not_interpreted(
                    f"MP3 audio with {sound.subtype} encoding is not supported"
                )
            return _decode_mp3(sound, sink)
        bits = _PCM_BITS.get(sound.subtype)
        if bits is None or (kind == "flac" and bits not in _FLAC_BITS):
            return _not_interpreted(
                f"{sound.format} audio with {sound.subtype} encoding is not supported"
            )
        return _decode_pcm(sound, kind, bits, streaminfo, sink)


def _decode_pcm(
    sound: soundfile.SoundFile,
    kind: str,
    bits: int,
    streaminfo: _StreamInfo | None,
    sink: Sink | None,
) -> dict[str, Any]:
    """Decode integer PCM exactly, measure it, and compute its Audio Digest."""
    digest = hashlib.sha256()
    signature = hashlib.md5(usedforsecurity=False)
    measures = _Measures(sound.channels, integer=True)
    frames = 0
    shift = 32 - bits
    try:
        for block in read_blocks(sound, "int32"):
            # libsndfile scales integer samples to the full 32-bit range.
            samples = np.right_shift(block, shift)
            data = _canonical_bytes(samples, bits)
            digest.update(data)
            signature.update(data)
            measures.add(samples)
            if sink is not None:
                sink(samples.astype(np.float32) * np.float32(1 / (1 << (bits - 1))))
            frames += len(block)
    except soundfile.LibsndfileError as error:
        return _failed(f"decoding stopped after {frames} frames: {error.error_string}")
    if frames != sound.frames:
        return _failed(f"decoding stopped after {frames} of {sound.frames} frames")
    findings = {
        **_properties(sound, kind, frames, bits),
        "audio_digest": (
            f"{DIGEST_SCHEME}:{sound.samplerate}:{sound.channels}:{bits}:"
            f"{digest.hexdigest()}"
        ),
        **measures.to_json(),
    }
    if streaminfo is not None:
        if streaminfo.md5 == bytes(16):
            findings["flac_md5_signature"] = MD5_ABSENT
        elif streaminfo.md5 == signature.digest():
            findings["flac_md5_signature"] = MD5_MATCHING
        else:
            findings["flac_md5_signature"] = MD5_DIFFERS
    return findings


class _Measures:
    """Per-channel peak and digital silence, accumulated block by block."""

    def __init__(self, channels: int, *, integer: bool) -> None:
        self._integer = integer
        self._peak = np.zeros(channels, dtype=np.int64 if integer else np.float64)
        self._leading = 0
        self._trailing = 0
        self._sound_seen = False

    def add(self, block: np.ndarray) -> None:
        """Measure the next block of frames, shaped (frames, channels)."""
        if not len(block):
            return
        magnitude = np.abs(block.astype(self._peak.dtype))
        self._peak = np.maximum(self._peak, magnitude.max(axis=0))
        sounding = np.flatnonzero(np.any(block != 0, axis=1))
        if not sounding.size:
            if self._sound_seen:
                self._trailing += len(block)
            else:
                self._leading += len(block)
            return
        if not self._sound_seen:
            self._leading += int(sounding[0])
            self._sound_seen = True
        self._trailing = len(block) - 1 - int(sounding[-1])

    def to_json(self) -> dict[str, Any]:
        convert = int if self._integer else float
        return {
            "peak": [convert(value) for value in self._peak],
            "leading_silence_frames": self._leading,
            "trailing_silence_frames": self._trailing,
        }


def _canonical_bytes(samples: np.ndarray, bits: int) -> bytes:
    """Pack interleaved samples as signed little-endian integers of bits size."""
    if bits == 8:
        return samples.astype(np.int8).tobytes()
    if bits == 16:
        return samples.astype("<i2").tobytes()
    if bits == 24:
        packed = samples.astype("<i4").view(np.uint8).reshape(-1, 4)
        return packed[:, :3].tobytes()
    return samples.astype("<i4").tobytes()


def _decode_mp3(sound: soundfile.SoundFile, sink: Sink | None) -> dict[str, Any]:
    """Decode MP3 completely and measure it; both depend on the decoder."""
    measures = _Measures(sound.channels, integer=False)
    frames = 0
    try:
        for block in read_blocks(sound, "float32"):
            measures.add(block)
            if sink is not None:
                sink(block)
            frames += len(block)
    except soundfile.LibsndfileError as error:
        return _failed(f"decoding stopped after {frames} frames: {error.error_string}")
    return {
        **_properties(sound, "mp3", frames),
        **measures.to_json(),
        "limitations": [MP3_LIMITATION],
    }


_CTYPES = {"int32": "int", "float32": "float"}


def read_blocks(
    sound: soundfile.SoundFile, dtype: str, limit: int | None = None
) -> Iterator[np.ndarray]:
    """Yield the decoded frames in order, until libsndfile has no more.

    Each block is shaped (frames, channels). With limit, asks libsndfile for no more
    than limit frames in all. Raises soundfile.LibsndfileError when libsndfile
    reports an error.
    """
    # KLUDGE: soundfile's read() and blocks() cap reading at the header's frame
    # count, which an MP3 may overstate or understate, blocks() yields stale data
    # after a short read, and both seek after every read, which makes mpg123 decode
    # slightly different samples. This calls libsndfile's sequential sf_readf_*
    # through soundfile's private _snd, _ffi and SoundFile._file. Remove it when
    # soundfile offers a sequential read that reports the frames it decoded.
    ctype = _CTYPES[dtype]
    read = getattr(soundfile._snd, f"sf_readf_{ctype}")
    handle = sound._file
    remaining = limit
    while remaining is None or remaining > 0:
        size = _BLOCK_FRAMES if remaining is None else min(_BLOCK_FRAMES, remaining)
        block = np.empty((size, sound.channels), dtype=dtype)
        pointer = soundfile._ffi.cast(f"{ctype} *", soundfile._ffi.from_buffer(block))
        count = read(handle, pointer, size)
        code = soundfile._snd.sf_error(handle)
        if code:
            raise soundfile.LibsndfileError(code)
        if not count:
            return
        if remaining is not None:
            remaining -= count
        yield block[:count]


def _properties(
    sound: soundfile.SoundFile, kind: str, frames: int, bits: int | None = None
) -> dict[str, Any]:
    return {
        "format": kind,
        "encoding": sound.subtype.lower(),
        "sample_rate": sound.samplerate,
        "channels": sound.channels,
        **({} if bits is None else {"bits_per_sample": bits}),
        "frames": frames,
    }


def _failed(reason: str) -> dict[str, Any]:
    return {"outcome": FAILED, "reason": reason}


def _not_interpreted(reason: str) -> dict[str, Any]:
    return {"outcome": NOT_INTERPRETED, "reason": reason}
