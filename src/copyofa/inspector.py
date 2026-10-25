"""Describe the audio in an Evidence Set."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO

import numpy as np
import soundfile

import copyofa
from copyofa import verifier

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

REPORT_KIND = "copyofa.inspection"
REPORT_FORMAT_VERSION = 1

INTERPRETED = "interpreted"
NOT_INTERPRETED = "not_interpreted"
FAILED = "failed"
NOT_INSPECTED = "not_inspected"
OUTCOMES = (INTERPRETED, NOT_INTERPRETED, FAILED, NOT_INSPECTED)

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
    files = []
    for digest, path in baseline.entries:
        if baseline.usable:
            entry = _inspect_file(root, path, digest)
        else:
            entry = _entry(path, digest, NOT_INSPECTED, reason=_UNUSABLE)
        if progress is not None:
            progress(entry)
        files.append(entry)
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
        "counts": {outcome: counts[outcome] for outcome in OUTCOMES},
        "limitations": list(LIMITATIONS),
    }


def found_problems(report: dict[str, Any]) -> bool:
    """Tell whether an inspection Report found anything that makes inspect exit 1."""
    return not report["integrity_baseline"]["usable"] or any(
        entry["outcome"] in {FAILED, NOT_INSPECTED} for entry in report["files"]
    )


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
    expected: str,
    outcome: str,
    *,
    observed: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": path,
        "outcome": outcome,
        "expected_digest": expected,
    }
    if observed is not None:
        entry["observed_digest"] = observed
    if reason is not None:
        entry["reason"] = reason
    return entry


def _inspect_file(root: Path, path: str, expected: str) -> dict[str, Any]:
    """Check one listed file against the baseline, then interpret it."""
    problem = verifier.find_file(root, path)
    if problem is not None:
        return _entry(path, expected, NOT_INSPECTED, reason=problem[1])
    try:
        # Non-blocking, so a named pipe swapped in cannot hang inspect.
        fd = os.open(root / path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        return _entry(
            path, expected, NOT_INSPECTED, reason=f"cannot be read: {error.strerror}"
        )
    try:
        with os.fdopen(fd, "rb") as file:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                return _entry(
                    path,
                    expected,
                    NOT_INSPECTED,
                    reason="a special file, not a regular file",
                )
            observed = hashlib.file_digest(file, "sha256").hexdigest()
            if observed != expected:
                return _entry(
                    path,
                    expected,
                    NOT_INSPECTED,
                    observed=observed,
                    reason="its digest differs from the manifest's",
                )
            entry = _entry(path, expected, INTERPRETED, observed=observed)
            entry.update(_interpret(file, PurePosixPath(path).suffix.lower()))
            after = os.fstat(fd)
    except OSError as error:
        return _entry(
            path, expected, NOT_INSPECTED, reason=f"cannot be read: {error.strerror}"
        )
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return _entry(
            path,
            expected,
            NOT_INSPECTED,
            observed=observed,
            reason="the file changed while it was inspected",
        )
    return entry


def _interpret(file: BinaryIO, suffix: str) -> dict[str, Any]:
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
    # A duplicate, which libsndfile owns: libsndfile 1.2.0 closes the descriptor it
    # was given when it cannot open the file, even when told not to.
    duplicate = os.dup(file.fileno())
    try:
        sound = soundfile.SoundFile(duplicate, closefd=True)
    except soundfile.LibsndfileError as error:
        with contextlib.suppress(OSError):
            os.close(duplicate)
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
            return _decode_mp3(sound)
        bits = _PCM_BITS.get(sound.subtype)
        if bits is None or (kind == "flac" and bits not in _FLAC_BITS):
            return _not_interpreted(
                f"{sound.format} audio with {sound.subtype} encoding is not supported"
            )
        return _decode_pcm(sound, kind, bits)


def _decode_pcm(sound: soundfile.SoundFile, kind: str, bits: int) -> dict[str, Any]:
    """Decode integer PCM exactly and compute its Audio Digest (ADR 0002)."""
    digest = hashlib.sha256()
    frames = 0
    shift = 32 - bits
    try:
        for block in _read_blocks(sound, "int32"):
            # libsndfile scales integer samples to the full 32-bit range.
            digest.update(_canonical_bytes(np.right_shift(block, shift), bits))
            frames += len(block)
    except soundfile.LibsndfileError as error:
        return _failed(f"decoding stopped after {frames} frames: {error.error_string}")
    if frames != sound.frames:
        return _failed(f"decoding stopped after {frames} of {sound.frames} frames")
    return {
        **_properties(sound, kind, frames, bits),
        "audio_digest": (
            f"{DIGEST_SCHEME}:{sound.samplerate}:{sound.channels}:{bits}:"
            f"{digest.hexdigest()}"
        ),
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


def _decode_mp3(sound: soundfile.SoundFile) -> dict[str, Any]:
    """Decode MP3 completely; its frame count is the decoder's."""
    frames = 0
    try:
        for block in _read_blocks(sound, "float32"):
            frames += len(block)
    except soundfile.LibsndfileError as error:
        return _failed(f"decoding stopped after {frames} frames: {error.error_string}")
    return {**_properties(sound, "mp3", frames), "limitations": [MP3_LIMITATION]}


_CTYPES = {"int32": "int", "float32": "float"}


def _read_blocks(sound: soundfile.SoundFile, dtype: str) -> Iterator[np.ndarray]:
    """Yield the decoded frames in order, until libsndfile has no more.

    Each block is shaped (frames, channels). Raises soundfile.LibsndfileError when
    libsndfile reports an error.
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
    while True:
        block = np.empty((_BLOCK_FRAMES, sound.channels), dtype=dtype)
        pointer = soundfile._ffi.cast(f"{ctype} *", soundfile._ffi.from_buffer(block))
        count = read(handle, pointer, _BLOCK_FRAMES)
        code = soundfile._snd.sf_error(handle)
        if code:
            raise soundfile.LibsndfileError(code)
        if not count:
            return
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
