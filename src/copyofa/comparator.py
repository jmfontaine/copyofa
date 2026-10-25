"""Compare the audio of two tracks preserved in Evidence Sets (see ADR 0003)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile
import soxr

import copyofa
from copyofa import evidence_set, inspector, verifier

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy.typing as npt

REPORT_KIND = "copyofa.comparison"
REPORT_FORMAT_VERSION = 1

RESAMPLER_QUALITY = "VHQ"
"""The soxr quality preset: libsoxr's very high quality."""
ALIGNMENT = "downmix_cross_correlation"

LIMITATIONS = (
    (
        "No measurement says whether the tracks share a master, a mix or a source; "
        "the Report draws no such conclusion."
    ),
    "MP3 is lossy: the measurements of an MP3 depend on its decoder.",
    (
        "Tracks at different sample rates are compared at the lower rate, after "
        "resampling, so differences above that rate's band are not measured."
    ),
    (
        "One global offset aligns the tracks: inserted or removed sections, drift "
        "and speed changes are not located; they lower the correlation and raise the "
        "residual."
    ),
    "Channels are paired in the order each file stores them.",
)

_UNUSABLE = "the Integrity Baseline is unusable"
_NOT_LISTED = f"{evidence_set.MANIFEST} does not list it"
_IDENTICAL = "the audio is identical"
_MEASURED = ("correlation", "gain_db", "residual_db", "residual_windows")


@dataclass(frozen=True)
class _Audio:
    """The decoded frames of an interpreted track."""

    samples: npt.NDArray[np.float32]
    """Shaped (frames, channels), where 1.0 is full scale."""
    rate: int
    digest: str | None


@dataclass(frozen=True)
class _Overlap:
    """The aligned frames, at the common rate: start in each track and length."""

    start_a: int
    start_b: int
    frames: int


def compare(
    track_a: str,
    track_b: str,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Compare two tracks preserved in Evidence Sets and return the comparison Report.

    Each track is the path of a file under the `data/` directory of an Evidence Set.
    Calls progress with each input's Report entry once it is inspected. Writes
    nothing. Raises verifier.NotAnEvidenceSetError when a track is not inside an
    Evidence Set.
    """
    locations = [_locate(track_a), _locate(track_b)]
    compared_at = datetime.now(UTC)
    inputs: dict[str, dict[str, Any]] = {}
    decoded: list[_Audio] = []
    for name, (root, path) in zip("ab", locations, strict=True):
        entry, audio = _inspect(root, path)
        if progress is not None:
            progress(entry)
        inputs[name] = entry
        if audio is not None:
            decoded.append(audio)
    method: dict[str, Any] = {
        "decoder": "libsndfile",
        "decoder_version": soundfile.__libsndfile_version__,
        "resampler": "libsoxr",
        "resampler_version": soxr.__libsoxr_version__,
        "resampler_quality": RESAMPLER_QUALITY,
    }
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "format_version": REPORT_FORMAT_VERSION,
        "copyofa_version": copyofa.__version__,
        "compared_at": compared_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": inputs,
        "method": method,
    }
    if len(decoded) == 2:
        rate = min(audio.rate for audio in decoded)
        method["common_sample_rate"] = rate
        report["measurements"] = _measure(decoded[0], decoded[1], rate)
    method["alignment"] = ALIGNMENT
    report["limitations"] = list(LIMITATIONS)
    return report


def found_problems(report: dict[str, Any]) -> bool:
    """Tell whether a comparison Report found anything that makes compare exit 1."""
    return any(
        entry["outcome"] != inspector.INTERPRETED for entry in report["inputs"].values()
    )


def _locate(track: str) -> tuple[Path, str]:
    """Return the Evidence Set holding track, and track's path in it.

    The set is the nearest directory above track that holds `bagit.txt`; the path
    must be under its `data/`. Raises verifier.NotAnEvidenceSetError otherwise.
    """
    # Absolute but not normalized, as verifier.locate does: removing `..` lexically
    # could name another directory than the one a symbolic link leads to.
    location = Path(track).absolute()
    for root in location.parents:
        path = PurePosixPath(*location.parts[len(root.parts) :]).as_posix()
        try:
            (root / evidence_set.BAGIT_TXT).lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            # Unreachable, such as behind a set root without search permission: as
            # in verifier.locate, it may be the set, whose records then cannot be
            # read. Every directory below such a root is unreachable too, so only
            # the one whose data/ holds the track is taken.
            if evidence_set.is_payload_path(path):
                return root, path
            continue
        if not evidence_set.is_payload_path(path):
            raise verifier.NotAnEvidenceSetError(
                f"{track} is not under the {evidence_set.PAYLOAD_DIR}/ directory of "
                f"the Evidence Set {root}."
            )
        return root, path
    raise verifier.NotAnEvidenceSetError(
        f"{track} is not inside an Evidence Set: no directory above it holds "
        f"{evidence_set.BAGIT_TXT}."
    )


def _inspect(root: Path, path: str) -> tuple[dict[str, Any], _Audio | None]:
    """Check one input as inspect checks a file; decode it when it is audio."""
    baseline = verifier.read_baseline(root)
    expected = {listed: digest for digest, listed in baseline.entries}.get(path)
    entry: dict[str, Any] = {
        "evidence_set": str(root),
        "integrity_baseline": baseline.to_json(),
    }
    if not baseline.usable or expected is None:
        entry.update({"path": path, "outcome": inspector.NOT_INSPECTED})
        if expected is not None:
            entry["expected_digest"] = expected
        entry["reason"] = _NOT_LISTED if baseline.usable else _UNUSABLE
        return entry, None
    blocks: list[npt.NDArray[np.float32]] = []
    entry.update(inspector.inspect_file(root, path, expected, blocks.append))
    if entry["outcome"] != inspector.INTERPRETED:
        return entry, None
    samples = (
        np.concatenate(blocks)
        if blocks
        else np.zeros((0, entry["channels"]), dtype=np.float32)
    )
    return entry, _Audio(samples, entry["sample_rate"], entry.get("audio_digest"))


def _measure(a: _Audio, b: _Audio, rate: int) -> dict[str, Any]:
    """Measure how track B relates to track A, at the common rate."""
    identical = a.digest is not None and a.digest == b.digest
    samples_a = _resample(a, rate)
    samples_b = _resample(b, rate)
    downmix_a = samples_a.mean(axis=1, dtype=np.float64)
    downmix_b = samples_b.mean(axis=1, dtype=np.float64)

    measurements: dict[str, Any] = {}
    absent: dict[str, str] = {}
    if identical:
        measurements["identical_audio"] = True
        # Identical tracks align at 0 without a search, unless there is no frame.
        missing = _no_frames(downmix_a, "A")
    else:
        missing = _no_alignment(downmix_a, "A") or _no_alignment(downmix_b, "B")
    overlap: _Overlap | str
    if missing is not None:
        overlap = f"no offset was found: {missing}"
        absent["offset"] = absent["overlap"] = overlap
    else:
        offset = 0 if identical else _align(downmix_a, downmix_b)
        start_a, start_b = max(0, -offset), max(0, offset)
        frames = min(len(downmix_a) - start_a, len(downmix_b) - start_b)
        overlap = _Overlap(start_a, start_b, frames)
        measurements["offset"] = {"frames": offset, "seconds": offset / rate}
        measurements["overlap"] = {
            "a": _extent(start_a, frames, len(downmix_a)),
            "b": _extent(start_b, frames, len(downmix_b)),
        }
    measurements["downmix"] = _measure_pair(
        downmix_a, downmix_b, overlap, rate, identical=identical
    )
    channels = samples_a.shape[1]
    if channels == samples_b.shape[1]:
        measurements["channels"] = [
            _measure_pair(
                samples_a[:, index],
                samples_b[:, index],
                overlap,
                rate,
                identical=identical,
            )
            for index in range(channels)
        ]
    else:
        absent["channels"] = (
            f"the tracks have different channel counts: {channels} and "
            f"{samples_b.shape[1]}"
        )
    if absent:
        measurements["absent"] = absent
    return measurements


def _resample(audio: _Audio, rate: int) -> npt.NDArray[np.float32]:
    if audio.rate == rate or not len(audio.samples):
        return audio.samples
    return soxr.resample(audio.samples, audio.rate, rate, quality=RESAMPLER_QUALITY)


def _no_alignment(downmix: npt.NDArray[np.float64], name: str) -> str | None:
    """Say why a downmix leaves the cross-correlation without a maximum, if it does."""
    if not downmix.any():
        return _no_frames(downmix, name) or (
            f"the downmix of track {name} is zero throughout"
        )
    return None


def _no_frames(downmix: npt.NDArray[np.float64], name: str) -> str | None:
    return None if len(downmix) else f"track {name} has no frames"


def _align(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> int:
    """Return the offset of b from a that maximizes the cross-correlation's magnitude.

    A positive offset means b starts that many frames later than a: frame n of a
    lines up with frame n + offset of b. The magnitude, so that a copy with its
    polarity inverted still aligns, and shows as a negative correlation.
    """
    size = _fast_length(len(a) + len(b) - 1)
    spectrum = np.fft.rfft(b, size)
    conjugate = np.fft.rfft(a, size)
    np.conjugate(conjugate, out=conjugate)
    spectrum *= conjugate
    del conjugate
    correlation = np.fft.irfft(spectrum, size)
    del spectrum
    np.abs(correlation, out=correlation)
    # Circular, but the padding keeps every lag apart: index k holds the lag k for
    # 0 <= k < len(b), and the lag k - size for size - len(a) < k < size.
    best = int(np.argmax(correlation[: len(b)]))
    if len(a) > 1:
        start = size - len(a) + 1
        earlier = start + int(np.argmax(correlation[start:]))
        if correlation[earlier] > correlation[best]:
            best = earlier - size
    return best


def _fast_length(minimum: int) -> int:
    """Return the smallest product of powers of 2, 3 and 5 that is at least minimum.

    NumPy's FFT is fast on such lengths and can be much slower on others.
    """
    best = 1 << (minimum - 1).bit_length()
    odd = 1
    while odd < best:
        factor = odd
        while factor < best:
            quotient = -(-minimum // factor)
            best = min(best, factor << (quotient - 1).bit_length())
            factor *= 3
        odd *= 5
    return best


def _extent(start: int, frames: int, total: int) -> dict[str, Any]:
    return {"start_frame": start, "frames": frames, "fraction": frames / total}


def _measure_pair(
    a: npt.NDArray[Any],
    b: npt.NDArray[Any],
    overlap: _Overlap | str,
    rate: int,
    *,
    identical: bool,
) -> dict[str, Any]:
    """Measure B against A over the overlap: correlation, gain and residual.

    When overlap is a string, it is why there is none, and every value is absent.
    """
    if isinstance(overlap, str):
        return {"absent": dict.fromkeys(_MEASURED, overlap)}
    end_a = overlap.start_a + overlap.frames
    end_b = overlap.start_b + overlap.frames
    # Views when the samples are already float64, as a downmix is.
    x = a[overlap.start_a : end_a].astype(np.float64, copy=False)
    y = b[overlap.start_b : end_b].astype(np.float64, copy=False)
    values: dict[str, Any] = {}
    absent: dict[str, str] = {}

    if np.min(x) == np.max(x):
        absent["correlation"] = "track A is constant over the overlap"
    elif np.min(y) == np.max(y):
        absent["correlation"] = "track B is constant over the overlap"
    else:
        dx = x - x.mean()
        dy = y - y.mean()
        pearson = float(dx @ dy) / math.sqrt(float(dx @ dx) * float(dy @ dy))
        values["correlation"] = max(-1.0, min(1.0, pearson))
        del dx, dy

    # The least-squares gain g that maps B onto A: A ≈ g·B.
    energy_b = float(y @ y)
    gain = None
    if energy_b == 0:
        absent["gain_db"] = "track B is zero throughout the overlap"
    else:
        gain = float(x @ y) / energy_b
        if gain == 0:
            absent["gain_db"] = "the least-squares gain is zero"
        else:
            values["gain_db"] = 20 * math.log10(abs(gain))

    if identical or gain is None:
        absent["residual_db"] = absent["residual_windows"] = (
            _IDENTICAL
            if identical
            else "the gain is undefined: track B is zero throughout the overlap"
        )
    else:
        error = y * -gain
        error += x
        np.square(error, out=error)
        energy = np.square(x)
        level = _residual(float(error.sum()), float(energy.sum()), "overlap")
        if isinstance(level, str):
            absent["residual_db"] = level
        else:
            values["residual_db"] = level
        starts = np.arange(0, overlap.frames, rate)
        values["residual_windows"] = [
            {
                "start_frame": int(start),
                "frames": min(rate, overlap.frames - int(start)),
                **_window_residual(float(window_error), float(window_energy)),
            }
            for start, window_error, window_energy in zip(
                starts,
                np.add.reduceat(error, starts),
                np.add.reduceat(energy, starts),
                strict=True,
            )
        ]
    if absent:
        values["absent"] = absent
    return values


def _window_residual(error: float, energy: float) -> dict[str, Any]:
    level = _residual(error, energy, "window")
    if isinstance(level, str):
        return {"absent": {"residual_db": level}}
    return {"residual_db": level}


def _residual(error: float, energy: float, scope: str) -> float | str:
    """The level of A minus B after the gain, in dB relative to A, or why it is absent.

    error and energy are the sums of squares of A minus B after the gain, and of A,
    over the scope.
    """
    if energy == 0:
        return f"track A is zero throughout the {scope}"
    if error == 0:
        return f"A minus B after the gain is zero throughout the {scope}"
    return 10 * math.log10(error / energy)
