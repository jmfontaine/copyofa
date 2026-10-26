"""Compare the audio of two tracks preserved in Evidence Sets (see ADRs 0003, 0006)."""

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
from copyofa import evidence_set, inspector, locator, verifier

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy.typing as npt

REPORT_KIND = "copyofa.comparison"
REPORT_FORMAT_VERSION = 4

RESAMPLER_QUALITY = "VHQ"
"""The soxr quality preset: libsoxr's very high quality."""
ALIGNMENT = "windowed_portions"
PRIMARY = "primary"
ALTERNATE = "alternate"

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
        "Portions shorter than about 2.5 s may be missed, and the search finds no "
        "portion in a track shorter than 5 s; identical audio still gets its "
        "portion."
    ),
    "Speed, pitch and drift differences give no portion.",
    (
        "A boundary inside audio below -80 dBFS is placed at the nearest frame "
        "with evidence, and the rest is reported as unmatched."
    ),
    (
        "A boundary at a fade falls about three blocks of 2048 frames inside it, "
        "where the gain fitted over the eight blocks inside the edge stops fitting "
        "the faded audio, not where the fade gets quiet; a boundary at a crossfade "
        "falls where the other audio refutes the match."
    ),
    (
        "In music that repeats a section, one range of a track can match several "
        "places in the other; each is reported as a portion."
    ),
    "Channels are paired in the order each file stores them.",
)

_UNUSABLE = "the Integrity Baseline is unusable"
_NOT_LISTED = f"{evidence_set.MANIFEST} does not list it"
_NOT_ACQUIRED = (
    f"the Evidence Set is not an acquired set: {evidence_set.TAG_MANIFEST} does not "
    f"list {evidence_set.ACQUISITION_RECORD}"
)
_IDENTICAL = "the audio is identical"


@dataclass(frozen=True)
class _Audio:
    """The decoded frames of an interpreted track."""

    samples: npt.NDArray[np.float32]
    """Shaped (frames, channels), where 1.0 is full scale."""
    rate: int
    digest: str | None


def compare(
    input_a: str,
    input_b: str,
    progress: Callable[[dict[str, Any]], None] | None = None,
    *,
    track_a: int | None = None,
    track_b: int | None = None,
    omit_locations: bool = False,
) -> dict[str, Any]:
    """Compare two tracks preserved in Evidence Sets and return the comparison Report.

    Each input is the path of a file under the `data/` directory of an Evidence Set,
    or, with a track number (track_a for input_a, track_b for input_b), the root of
    an acquired set, whose track it names. Calls progress with each input's Report
    entry once it is inspected. With omit_locations, neither the Report nor an entry
    holds where an Evidence Set is stored, and the Report's `omitted` lists what it
    leaves out. Writes nothing. Raises verifier.NotAnEvidenceSetError when a file is
    not under the `data/` directory of an Evidence Set, or a set root given with a
    track number is not an Evidence Set.
    """
    locations = [
        (verifier.locate(given), track) if track is not None else _locate(given)
        for given, track in ((input_a, track_a), (input_b, track_b))
    ]
    compared_at = datetime.now(UTC)
    inputs: dict[str, dict[str, Any]] = {}
    omitted: list[str] = []
    decoded: list[_Audio] = []
    for name, (root, path) in zip("ab", locations, strict=True):
        if isinstance(path, int):
            entry, audio = _inspect_track(root, path, omit_locations)
        else:
            entry, audio = _inspect(root, path, omit_locations)
        if omit_locations:
            omitted.append(f"/inputs/{name}/evidence_set")
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
        "omitted": omitted,
        "inputs": inputs,
        "method": method,
    }
    if len(decoded) == 2:
        rate = min(audio.rate for audio in decoded)
        method["common_sample_rate"] = rate
        report["measurements"] = _measure(decoded[0], decoded[1], rate)
    method["alignment"] = ALIGNMENT
    method["parameters"] = dict(locator.PARAMETERS)
    report["limitations"] = list(LIMITATIONS)
    return report


def found_problems(report: dict[str, Any]) -> bool:
    """Tell whether a comparison Report found anything that makes compare exit 1."""
    return any(
        entry["outcome"] != inspector.INTERPRETED for entry in report["inputs"].values()
    )


def input_name(entry: dict[str, Any]) -> str:
    """Name an input of a comparison Report by its path in its set and its track."""
    if "track" not in entry:
        return entry["path"]
    track = f"track {entry['track']['number']}"
    return f"{track} of {entry['path']}" if "path" in entry else track


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


def _inspect(
    root: Path, path: str, omit_location: bool
) -> tuple[dict[str, Any], _Audio | None]:
    """Check one input as inspect checks a file; decode it when it is audio."""
    baseline = verifier.read_baseline(root)
    expected = {listed: digest for digest, listed in baseline.entries}.get(path)
    entry: dict[str, Any] = {}
    if not omit_location:
        entry["evidence_set"] = str(root)
    entry["integrity_baseline"] = baseline.to_json()
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


def _inspect_track(
    root: Path, number: int, omit_location: bool
) -> tuple[dict[str, Any], _Audio | None]:
    """Check one track of an acquired set as inspect does; decode it when it can."""
    baseline = verifier.read_baseline(root)
    entry: dict[str, Any] = {}
    if not omit_location:
        entry["evidence_set"] = str(root)
    entry["integrity_baseline"] = baseline.to_json()
    disc = None
    reason = _UNUSABLE
    if baseline.usable:
        try:
            disc = inspector.read_acquired_disc(root, baseline)
        except inspector.UnusableRecordError as error:
            reason = str(error)
        else:
            reason = _NOT_ACQUIRED
    if disc is None:
        entry.update(
            {
                "track": {"number": number},
                "outcome": inspector.NOT_INSPECTED,
                "reason": reason,
            }
        )
        return entry, None
    track = disc.track(number)
    entry["path"] = disc.image
    if track is None:
        entry.update(
            {
                "track": {"number": number},
                "outcome": inspector.NOT_INSPECTED,
                "expected_digest": disc.image_digest,
                "reason": f"the Acquisition Record lists no track {number}",
            }
        )
        return entry, None
    entry["track"] = {
        "number": track.number,
        "first_frame": track.first_frame,
        "frame_count": track.frame_count,
    }
    blocks: list[npt.NDArray[np.float32]] = []
    findings = inspector.decode_track(root, disc, track, blocks.append)
    entry["outcome"] = findings.pop("outcome")
    entry["expected_digest"] = disc.image_digest
    if "observed_digest" in findings:
        entry["observed_digest"] = findings.pop("observed_digest")
    entry.update(findings)
    if entry["outcome"] != inspector.INTERPRETED:
        return entry, None
    return entry, _Audio(
        np.concatenate(blocks), entry["sample_rate"], entry["audio_digest"]
    )


def _measure(a: _Audio, b: _Audio, rate: int) -> dict[str, Any]:
    """Measure how track B relates to track A, at the common rate."""
    identical = a.digest is not None and a.digest == b.digest
    samples_a = _resample(a, rate)
    samples_b = _resample(b, rate)
    downmix_a = samples_a.mean(axis=1, dtype=np.float64)
    downmix_b = samples_b.mean(axis=1, dtype=np.float64)

    measurements: dict[str, Any] = {}
    portions: list[locator.Portion] = []
    if identical:
        measurements["identical_audio"] = True
        # Identical tracks match at 0 without a search, unless there is no frame.
        missing = _no_frames(downmix_a, "A")
        if missing is None:
            portions.append(locator.Portion(0, len(downmix_a), 0, None))
    else:
        missing = _unsearchable(downmix_a, downmix_b, rate)
        if missing is None:
            portions = locator.locate(downmix_a, downmix_b, rate)
            if not portions:
                missing = "no portion was found"
    measurements["portions"] = [
        _portion(
            portion, (samples_a, samples_b), (downmix_a, downmix_b), rate, identical
        )
        for portion in portions
    ]
    primaries = [portion for portion in portions if not portion.alternate]
    measurements["unmatched"] = {
        "a": _unmatched(
            samples_a, [(portion.start_a, portion.end_a) for portion in primaries]
        ),
        "b": _unmatched(
            samples_b,
            [
                (portion.start_b, portion.start_b + portion.frames)
                for portion in primaries
            ],
        ),
    }
    if missing is not None:
        measurements["absent"] = {"portions": missing}
    return measurements


def _portion(
    portion: locator.Portion,
    samples: tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]],
    downmixes: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]],
    rate: int,
    identical: bool,
) -> dict[str, Any]:
    """Describe and measure one portion."""
    entry: dict[str, Any] = {
        "rank": ALTERNATE if portion.alternate else PRIMARY,
        "a": {"start_frame": portion.start_a, "frames": portion.frames},
        "b": {"start_frame": portion.start_b, "frames": portion.frames},
        "offset": {"frames": portion.offset, "seconds": portion.offset / rate},
    }
    absent: dict[str, str] = {}
    if identical:
        absent["block_gain_residual_db"] = _IDENTICAL
    elif portion.residual_db is None:
        absent["block_gain_residual_db"] = (
            "A minus B after the per-block gains is zero throughout the portion"
        )
    else:
        entry["block_gain_residual_db"] = portion.residual_db
    entry["downmix"] = _measure_pair(*downmixes, portion, rate, identical=identical)
    samples_a, samples_b = samples
    channels = samples_a.shape[1]
    if channels == samples_b.shape[1]:
        entry["channels"] = [
            _measure_pair(
                samples_a[:, index],
                samples_b[:, index],
                portion,
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
        entry["absent"] = absent
    return entry


def _unmatched(
    samples: npt.NDArray[np.float32], covered: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    """Describe each range of a track that no primary portion covers."""
    ranges = []
    for start, stop in locator.uncovered(covered, len(samples)):
        entry: dict[str, Any] = {"start_frame": start, "frames": stop - start}
        part = samples[start:stop]
        entry["digitally_silent"] = not part.any()
        if part.any():
            power = float(np.mean(np.square(part, dtype=np.float64)))
            entry["level_dbfs"] = 10 * math.log10(power)
        ranges.append(entry)
    return ranges


def _resample(audio: _Audio, rate: int) -> npt.NDArray[np.float32]:
    if audio.rate == rate or not len(audio.samples):
        return audio.samples
    return soxr.resample(audio.samples, audio.rate, rate, quality=RESAMPLER_QUALITY)


def _unsearchable(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], rate: int
) -> str | None:
    """Say why the downmixes leave the search without a candidate, if they do."""
    downmixes = (("A", a), ("B", b))
    for name, downmix in downmixes:
        if (missing := _no_frames(downmix, name)) is not None:
            return missing
    for name, downmix in downmixes:
        if len(downmix) < locator.WINDOW_SECONDS * rate:
            return (
                f"track {name} is shorter than one window of {locator.WINDOW_SECONDS} s"
            )
    for name, downmix in downmixes:
        if not downmix.any():
            return f"the downmix of track {name} is zero throughout"
    return None


def _no_frames(downmix: npt.NDArray[np.float64], name: str) -> str | None:
    return None if len(downmix) else f"track {name} has no frames"


def _measure_pair(
    a: npt.NDArray[Any],
    b: npt.NDArray[Any],
    portion: locator.Portion,
    rate: int,
    *,
    identical: bool,
) -> dict[str, Any]:
    """Measure B against A over a portion: correlation, gain and residual."""
    end_b = portion.start_b + portion.frames
    # Views when the samples are already float64, as a downmix is.
    x = a[portion.start_a : portion.end_a].astype(np.float64, copy=False)
    y = b[portion.start_b : end_b].astype(np.float64, copy=False)
    values: dict[str, Any] = {}
    absent: dict[str, str] = {}

    if np.min(x) == np.max(x):
        absent["correlation"] = "track A is constant over the portion"
    elif np.min(y) == np.max(y):
        absent["correlation"] = "track B is constant over the portion"
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
        absent["gain_db"] = "track B is zero throughout the portion"
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
            else "the gain is undefined: track B is zero throughout the portion"
        )
    else:
        error = y * -gain
        error += x
        np.square(error, out=error)
        energy = np.square(x)
        level = _residual(float(error.sum()), float(energy.sum()), "portion")
        if isinstance(level, str):
            absent["residual_db"] = level
        else:
            values["residual_db"] = level
        starts = np.arange(0, portion.frames, rate)
        values["residual_windows"] = [
            {
                "start_frame": int(start),
                "frames": min(rate, portion.frames - int(start)),
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
