"""Compare the audio of two tracks or two editions preserved in Evidence Sets (see ADRs
0003, 0006, 0009)."""

from __future__ import annotations

import bisect
import itertools
import math
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile
import soxr

import copyofa
from copyofa import evidence_set, inspector, locator, verifier
from copyofa.errors import CopyOfAError

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy.typing as npt

REPORT_KIND = "copyofa.comparison"
REPORT_FORMAT_VERSION = 6

TRACKS = "tracks"
"""The `scope` of a comparison of two tracks."""
EDITIONS = "editions"
"""The `scope` of a comparison of two editions, each its tracks in order."""

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

EDITION_LIMITATIONS = (
    (
        "Each edition is compared as its tracks joined in order without gap: an "
        "acquired set's in the order of its Acquisition Record, an imported set's "
        "audio files in the order of their paths."
    ),
    (
        "Where the speeds of two editions differ, even by a few parts per million, "
        "portions are short and the coverage stays partial."
    ),
    (
        "Tracks that match, even with identical audio, do not establish that the "
        "editions are equivalent."
    ),
)
"""What an edition comparison adds to LIMITATIONS (see ADR 0009)."""

_UNUSABLE = "the Integrity Baseline is unusable"
_NOT_LISTED = f"{evidence_set.MANIFEST} does not list it"
_NOT_ACQUIRED = (
    f"the Evidence Set is not an acquired set: {evidence_set.TAG_MANIFEST} does not "
    f"list {evidence_set.ACQUISITION_RECORD}"
)
_IDENTICAL = "the audio is identical"


class InputsError(CopyOfAError):
    """Inputs that are neither two tracks nor two editions."""


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
    progress: Callable[[str | None, dict[str, Any]], None] | None = None,
    *,
    track_a: int | None = None,
    track_b: int | None = None,
    omit_locations: bool = False,
) -> dict[str, Any]:
    """Compare two tracks or two editions and return the comparison Report.

    Each input is the path of a file under the `data/` directory of an Evidence Set,
    or, with a track number (track_a for input_a, track_b for input_b), the root of
    an acquired set, whose track it names: the Report's scope is `tracks`. Two roots
    of Evidence Sets without track numbers are two editions, each the tracks of its
    set in order: the scope is `editions` (see ADR 0009). Calls progress with None
    and each input's Report entry once it is inspected, or, for editions, with the
    edition's name, `a` or `b`, and the entry of each of its tracks and excluded
    files. With omit_locations, the Report holds no location of an Evidence Set,
    and its `omitted` lists what it leaves out. Writes nothing. Raises InputsError
    when an input is the root of an Evidence Set without a track number and the
    other is not, and verifier.NotAnEvidenceSetError when a file is not under the
    `data/` directory of an Evidence Set, or a set root given with a track number is
    not an Evidence Set.
    """
    givens = ((input_a, track_a), (input_b, track_b))
    roots = [_set_root(given) if track is None else None for given, track in givens]
    if roots[0] is not None and roots[1] is not None:
        return _compare_editions((roots[0], roots[1]), progress, omit_locations)
    for (given, _), root in zip(givens, roots, strict=True):
        if root is not None:
            raise InputsError(
                f"compare takes two tracks or two editions: {given} is the root of "
                "an Evidence Set given without a track number, but the other input "
                "is not a set root given without one. Give two set roots without "
                "track numbers to compare editions, or a track number with each set "
                "root to compare tracks."
            )
    locations = [
        (verifier.locate(given), track) if track is not None else _locate(given)
        for given, track in givens
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
            progress(None, entry)
        inputs[name] = entry
        if audio is not None:
            decoded.append(audio)
    method = _method()
    report = _report(TRACKS, compared_at, omitted, inputs, method)
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
    if report.get("scope") == EDITIONS:
        return "measurements" not in report
    return any(
        entry["outcome"] != inspector.INTERPRETED for entry in report["inputs"].values()
    )


def input_name(entry: dict[str, Any]) -> str:
    """Name an input of a comparison Report, or a track of an edition, by its path in
    its set and its track."""
    if "track" not in entry:
        return entry["path"]
    track = f"track {entry['track']['number']}"
    return f"{track} of {entry['path']}" if "path" in entry else track


def _method() -> dict[str, Any]:
    """Return how the audio is decoded and resampled; the caller adds the rest."""
    return {
        "decoder": "libsndfile",
        "decoder_version": soundfile.__libsndfile_version__,
        "resampler": "libsoxr",
        "resampler_version": soxr.__libsoxr_version__,
        "resampler_quality": RESAMPLER_QUALITY,
    }


def _report(
    scope: str,
    compared_at: datetime,
    omitted: list[str],
    inputs: dict[str, dict[str, Any]],
    method: dict[str, Any],
) -> dict[str, Any]:
    """Return the start of a Report: what it is, when, and what it compares."""
    return {
        "report_kind": REPORT_KIND,
        "format_version": REPORT_FORMAT_VERSION,
        "scope": scope,
        "copyofa_version": copyofa.__version__,
        "compared_at": compared_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "omitted": omitted,
        "inputs": inputs,
        "method": method,
    }


def _set_root(given: str) -> Path | None:
    """Return the Evidence Set whose root given is, or None when given is not the
    root of a set.

    A directory that cannot be searched, such as a set root without search
    permission, may be a set: as verifier.locate does, it is taken as one, whose
    records then cannot be read.
    """
    try:
        (Path(given) / evidence_set.BAGIT_TXT).lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        try:
            if not stat.S_ISDIR(Path(given).stat().st_mode):
                return None
        except OSError:
            # Itself unreachable, such as a file under a set root without search
            # permission: not a root, which _locate then finds.
            return None
    return verifier.locate(given)


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
    return entry, _audio_of(entry, blocks)


def _audio_of(
    entry: dict[str, Any], blocks: list[npt.NDArray[np.float32]]
) -> _Audio | None:
    """Return the audio of an inspected file or track when it is interpreted."""
    if entry["outcome"] != inspector.INTERPRETED:
        return None
    samples = (
        np.concatenate(blocks)
        if blocks
        else np.zeros((0, entry["channels"]), dtype=np.float32)
    )
    return _Audio(samples, entry["sample_rate"], entry.get("audio_digest"))


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
    with inspector.open_accepted(root, disc.image, disc.image_digest) as image:
        found, audio = _decode_recorded(image, disc, track)
    entry.update(found)
    return entry, audio


def _decode_recorded(
    image: inspector.AcceptedFile,
    disc: inspector.AcquiredDisc,
    track: inspector.RecordedTrack,
) -> tuple[dict[str, Any], _Audio | None]:
    """Check one track of an acquired set from its opened image as inspect does, and
    decode it when it can; return its entry from `path` on."""
    recorded: dict[str, Any] = {
        "number": track.number,
        "first_frame": track.first_frame,
        "frame_count": track.frame_count,
    }
    if track.error_ranges is not None:
        recorded["error_ranges"] = [
            error_range.to_json() for error_range in track.error_ranges
        ]
    entry: dict[str, Any] = {"path": disc.image, "track": recorded}
    blocks: list[npt.NDArray[np.float32]] = []
    findings = inspector.decode_track(image, track, blocks.append)
    entry["outcome"] = findings.pop("outcome")
    entry["expected_digest"] = disc.image_digest
    if "observed_digest" in findings:
        entry["observed_digest"] = findings.pop("observed_digest")
    entry.update(findings)
    return entry, _audio_of(entry, blocks)


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
        missing = _no_frames(downmix_a, "track A")
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


@dataclass(frozen=True)
class _Listing:
    """The tracks an Evidence Set gives as an edition, before any is inspected."""

    baseline: verifier.Baseline
    disc: inspector.AcquiredDisc | None
    """The disc of an acquired set; None for any other set."""
    files: list[tuple[str, str]]
    """An imported set's listed files, (path, SHA-256), in the order of their paths."""
    reason: str | None
    """Why the set gives no track; None when it gives its tracks."""


@dataclass(frozen=True)
class _Edition:
    """The tracks of an edition at the common rate, joined in order without gap."""

    tracks: list[_Audio]
    starts: list[int]
    """Each track's first frame in the sequence, then the sequence's frame count."""
    downmix: npt.NDArray[np.float64]
    """The downmix of the sequence: each track's downmix, in order."""

    def track_at(self, frame: int) -> int:
        """Return the index of the track holding a frame of the sequence."""
        return bisect.bisect_right(self.starts, frame) - 1

    def frames(self, index: int) -> int:
        return self.starts[index + 1] - self.starts[index]

    def downmix_of(self, index: int) -> npt.NDArray[np.float64]:
        return self.downmix[self.starts[index] : self.starts[index + 1]]


@dataclass(frozen=True)
class _Segment:
    """The part of a portion within one track of each edition."""

    start: int
    """The segment's first frame in the sequence of edition A."""
    frames: int
    index_a: int
    index_b: int
    start_a: int
    """The segment's first frame in its track of edition A."""
    start_b: int
    """The segment's first frame in its track of edition B."""


def _compare_editions(
    roots: tuple[Path, Path],
    progress: Callable[[str | None, dict[str, Any]], None] | None,
    omit_locations: bool,
) -> dict[str, Any]:
    """Compare two editions, each the tracks of an Evidence Set (see ADR 0009)."""
    compared_at = datetime.now(UTC)
    listings = [_list_edition(root) for root in roots]
    # The common rate comes from the headers, so each track is resampled to it as it
    # is decoded and only the resampled tracks are held.
    rate = min(
        (
            found
            for root, listing in zip(roots, listings, strict=True)
            for found in _rates(root, listing)
        ),
        default=evidence_set.CD_SAMPLE_RATE,
    )
    inputs: dict[str, dict[str, Any]] = {}
    omitted: list[str] = []
    editions: list[list[_Audio]] = []
    reasons: list[str] = []
    for name, root, listing in zip("ab", roots, listings, strict=True):
        entry, tracks = _inspect_edition(
            name, root, listing, rate, omit_locations, progress
        )
        if omit_locations:
            omitted.append(f"/inputs/{name}/evidence_set")
        inputs[name] = entry
        if (reason := _unmeasured(name, entry)) is not None:
            reasons.append(reason)
        editions.append([audio for audio in tracks if audio is not None])
    method = _method()
    report = _report(EDITIONS, compared_at, omitted, inputs, method)
    if reasons:
        report["absent"] = {"measurements": "; ".join(reasons)}
    else:
        method["common_sample_rate"] = rate
        report["measurements"] = _measure_editions(
            _join(editions[0]), _join(editions[1]), rate
        )
    method["alignment"] = ALIGNMENT
    method["parameters"] = dict(locator.PARAMETERS)
    report["limitations"] = [*LIMITATIONS, *EDITION_LIMITATIONS]
    return report


def _list_edition(root: Path) -> _Listing:
    """Read which tracks an Evidence Set gives as an edition, and in which order."""
    baseline = verifier.read_baseline(root)
    if not baseline.usable:
        return _Listing(baseline, None, [], _UNUSABLE)
    try:
        disc = inspector.read_acquired_disc(root, baseline)
    except inspector.UnusableRecordError as error:
        return _Listing(baseline, None, [], str(error))
    if disc is not None:
        return _Listing(baseline, disc, [], None)
    files = sorted((path, digest) for digest, path in baseline.entries)
    return _Listing(baseline, None, files, None)


def _rates(root: Path, listing: _Listing) -> list[int]:
    """Return the sample rate each track of an edition's headers give, without
    decoding it; a file inspect would not interpret gives none."""
    if listing.disc is not None:
        return [evidence_set.CD_SAMPLE_RATE] if listing.disc.tracks else []
    rates = (inspector.sample_rate_of(root, path) for path, _ in listing.files)
    return [found for found in rates if found is not None]


def _inspect_edition(
    name: str,
    root: Path,
    listing: _Listing,
    rate: int,
    omit_location: bool,
    progress: Callable[[str | None, dict[str, Any]], None] | None,
) -> tuple[dict[str, Any], list[_Audio | None]]:
    """Check each track of an edition as inspect does and decode it when it can;
    return the edition's entry and each track's audio at the common rate."""
    entry: dict[str, Any] = {}
    if not omit_location:
        entry["evidence_set"] = str(root)
    entry["integrity_baseline"] = listing.baseline.to_json()
    tracks: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    decoded: list[_Audio | None] = []

    def add(found: dict[str, Any], audio: _Audio | None) -> None:
        track = {"position": len(tracks) + 1, **found}
        tracks.append(track)
        if progress is not None:
            progress(name, track)
        decoded.append(
            None
            if audio is None
            else _Audio(_resample(audio, rate), rate, audio.digest)
        )

    disc = listing.disc
    if disc is not None:
        with inspector.open_accepted(root, disc.image, disc.image_digest) as image:
            for recorded in disc.tracks:
                add(*_decode_recorded(image, disc, recorded))
    for path, digest in listing.files:
        blocks: list[npt.NDArray[np.float32]] = []
        found = inspector.inspect_file(root, path, digest, blocks.append)
        if found["outcome"] == inspector.NOT_INTERPRETED:
            item = {
                "path": path,
                "outcome": found["outcome"],
                "reason": found["reason"],
            }
            excluded.append(item)
            if progress is not None:
                progress(name, item)
            continue
        audio = _audio_of(found, blocks)
        blocks.clear()
        add(found, audio)
        # The samples at the file's own rate go before the next file is decoded.
        del audio
    entry["tracks"] = tracks
    entry["excluded"] = excluded
    if listing.reason is not None:
        entry["reason"] = listing.reason
    return entry, decoded


def _unmeasured(name: str, entry: dict[str, Any]) -> str | None:
    """Say why an edition leaves the comparison unmeasured, if it does."""
    edition = f"edition {name.upper()}"
    if not entry["tracks"]:
        reason = entry.get("reason")
        return f"{edition} has no track" + ("" if reason is None else f": {reason}")
    positions = [
        str(track["position"])
        for track in entry["tracks"]
        if track["outcome"] != inspector.INTERPRETED
    ]
    if not positions:
        return None
    if len(positions) == 1:
        return f"the track at position {positions[0]} of {edition} is not interpreted"
    listed = ", ".join(positions[:-1]) + f" and {positions[-1]}"
    return f"the tracks at positions {listed} of {edition} are not interpreted"


def _join(tracks: list[_Audio]) -> _Edition:
    """Join an edition's tracks, at the common rate, in order without gap."""
    starts = [0]
    for audio in tracks:
        starts.append(starts[-1] + len(audio.samples))
    downmix = np.empty(starts[-1], dtype=np.float64)
    for index, audio in enumerate(tracks):
        audio.samples.mean(
            axis=1, dtype=np.float64, out=downmix[starts[index] : starts[index + 1]]
        )
    return _Edition(tracks, starts, downmix)


def _measure_editions(a: _Edition, b: _Edition, rate: int) -> dict[str, Any]:
    """Measure how edition B relates to edition A, at the common rate.

    Locates portions between the two sequences as between two tracks, splits each
    at the boundaries of both editions' tracks into segments, and measures each
    segment. Primary portions, each frame counted once, give the correspondences
    between tracks, the ranges no portion covers and each edition's coverage.
    """
    editions = (a, b)
    portions: list[locator.Portion] = []
    missing = _unsearchable(a.downmix, b.downmix, rate, "edition")
    if missing is None:
        portions = locator.locate(a.downmix, b.downmix, rate)
        if not portions:
            missing = "no portion was found"
    entries = []
    primary_segments: list[_Segment] = []
    for portion in portions:
        segments = _split(portion, a, b)
        entry, absent = _portion_head(portion, rate, identical=False)
        entry["segments"] = [_segment(segment, a, b, rate) for segment in segments]
        if absent:
            entry["absent"] = absent
        entries.append(entry)
        if not portion.alternate:
            primary_segments.extend(segments)
    primaries = [portion for portion in portions if not portion.alternate]
    covered = {
        "a": [(portion.start_a, portion.end_a) for portion in primaries],
        "b": [
            (portion.start_b, portion.start_b + portion.frames) for portion in primaries
        ],
    }
    measurements: dict[str, Any] = {
        "sequences": {
            name: [
                {
                    "position": index + 1,
                    "start_frame": edition.starts[index],
                    "frames": edition.frames(index),
                }
                for index in range(len(edition.tracks))
            ]
            for name, edition in zip("ab", editions, strict=True)
        },
        "portions": entries,
        "correspondences": _correspondences(primary_segments, a, b),
        "unmatched": {
            name: _edition_unmatched(edition, covered[name])
            for name, edition in zip("ab", editions, strict=True)
        },
        "coverage": {
            name: {
                "matched_frames": _matched_frames(covered[name]),
                "frames": edition.starts[-1],
            }
            for name, edition in zip("ab", editions, strict=True)
        },
    }
    if missing is not None:
        measurements["absent"] = {"portions": missing}
    return measurements


def _split(portion: locator.Portion, a: _Edition, b: _Edition) -> list[_Segment]:
    """Split a portion at the boundaries of the tracks of both editions."""
    start, end = portion.start_a, portion.end_a
    cuts = {start, end}
    cuts.update(first for first in a.starts if start < first < end)
    cuts.update(
        first - portion.offset
        for first in b.starts
        if start < first - portion.offset < end
    )
    segments = []
    for first, stop in itertools.pairwise(sorted(cuts)):
        index_a = a.track_at(first)
        index_b = b.track_at(first + portion.offset)
        segments.append(
            _Segment(
                first,
                stop - first,
                index_a,
                index_b,
                first - a.starts[index_a],
                first + portion.offset - b.starts[index_b],
            )
        )
    return segments


def _segment(segment: _Segment, a: _Edition, b: _Edition, rate: int) -> dict[str, Any]:
    """Describe and measure one segment, within its two tracks."""
    entry: dict[str, Any] = {
        "a": {
            "position": segment.index_a + 1,
            "start_frame": segment.start_a,
            "frames": segment.frames,
        },
        "b": {
            "position": segment.index_b + 1,
            "start_frame": segment.start_b,
            "frames": segment.frames,
        },
    }
    span = locator.Portion(
        segment.start_a, segment.frames, segment.start_b - segment.start_a, None
    )
    values, absent = _measure_series(
        (a.tracks[segment.index_a].samples, b.tracks[segment.index_b].samples),
        (a.downmix_of(segment.index_a), b.downmix_of(segment.index_b)),
        span,
        rate,
        identical=False,
        extent="segment",
    )
    entry.update(values)
    if absent:
        entry["absent"] = absent
    return entry


def _correspondences(
    segments: list[_Segment], a: _Edition, b: _Edition
) -> list[dict[str, Any]]:
    """Pair the tracks the primary segments join, with the frames of each found in
    the other, counted once."""
    pairs: dict[tuple[int, int], tuple[list[tuple[int, int]], list[tuple[int, int]]]]
    pairs = {}
    for segment in segments:
        ranges_a, ranges_b = pairs.setdefault(
            (segment.index_a, segment.index_b), ([], [])
        )
        ranges_a.append((segment.start_a, segment.start_a + segment.frames))
        ranges_b.append((segment.start_b, segment.start_b + segment.frames))
    correspondences = []
    for (index_a, index_b), (ranges_a, ranges_b) in sorted(pairs.items()):
        entry: dict[str, Any] = {}
        for name, edition, index, ranges in (
            ("a", a, index_a, ranges_a),
            ("b", b, index_b, ranges_b),
        ):
            matched = _matched_frames(ranges)
            entry[name] = {
                "position": index + 1,
                "matched_frames": matched,
                "fraction": matched / edition.frames(index),
            }
        digest = a.tracks[index_a].digest
        if digest is not None and digest == b.tracks[index_b].digest:
            entry["identical_audio"] = True
        correspondences.append(entry)
    return correspondences


def _edition_unmatched(
    edition: _Edition, covered: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    """Describe each range of an edition's tracks that no primary portion covers."""
    ranges = []
    for start, stop in locator.uncovered(covered, edition.starts[-1]):
        for index in range(edition.track_at(start), len(edition.tracks)):
            first = edition.starts[index]
            if first >= stop:
                break
            low, high = max(start, first), min(stop, edition.starts[index + 1])
            if high > low:
                samples = edition.tracks[index].samples
                ranges.append(
                    {
                        "position": index + 1,
                        **_described(samples, low - first, high - first),
                    }
                )
    return ranges


def _matched_frames(ranges: list[tuple[int, int]]) -> int:
    """Count the frames ranges cover, each frame once."""
    matched, reach = 0, 0
    for start, stop in sorted(ranges):
        if stop > reach:
            matched += stop - max(start, reach)
            reach = stop
    return matched


def _portion(
    portion: locator.Portion,
    samples: tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]],
    downmixes: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]],
    rate: int,
    identical: bool,
) -> dict[str, Any]:
    """Describe and measure one portion."""
    entry, absent = _portion_head(portion, rate, identical)
    values, missing = _measure_series(
        samples, downmixes, portion, rate, identical=identical
    )
    entry.update(values)
    absent.update(missing)
    if absent:
        entry["absent"] = absent
    return entry


def _portion_head(
    portion: locator.Portion, rate: int, identical: bool
) -> tuple[dict[str, Any], dict[str, str]]:
    """Describe a portion: its rank, ranges, offset and block-gain residual; return
    the entry and the reasons of its absent values."""
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
    return entry, absent


def _measure_series(
    samples: tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]],
    downmixes: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]],
    span: locator.Portion,
    rate: int,
    *,
    identical: bool,
    extent: str = "portion",
) -> tuple[dict[str, Any], dict[str, str]]:
    """Measure B against A over a span, a portion or a segment, on the downmix and,
    when both tracks have as many, on each channel; return the values and the reasons
    of absent ones."""
    values: dict[str, Any] = {
        "downmix": _measure_pair(
            *downmixes, span, rate, identical=identical, extent=extent
        )
    }
    absent: dict[str, str] = {}
    samples_a, samples_b = samples
    channels = samples_a.shape[1]
    if channels == samples_b.shape[1]:
        values["channels"] = [
            _measure_pair(
                samples_a[:, index],
                samples_b[:, index],
                span,
                rate,
                identical=identical,
                extent=extent,
            )
            for index in range(channels)
        ]
    else:
        absent["channels"] = (
            f"the tracks have different channel counts: {channels} and "
            f"{samples_b.shape[1]}"
        )
    return values, absent


def _unmatched(
    samples: npt.NDArray[np.float32], covered: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    """Describe each range of a track that no primary portion covers."""
    return [
        _described(samples, start, stop)
        for start, stop in locator.uncovered(covered, len(samples))
    ]


def _described(
    samples: npt.NDArray[np.float32], start: int, stop: int
) -> dict[str, Any]:
    """Describe a range of a track: whether it is digitally silent, else its level."""
    entry: dict[str, Any] = {"start_frame": start, "frames": stop - start}
    part = samples[start:stop]
    entry["digitally_silent"] = not part.any()
    if part.any():
        power = float(np.mean(np.square(part, dtype=np.float64)))
        entry["level_dbfs"] = 10 * math.log10(power)
    return entry


def _resample(audio: _Audio, rate: int) -> npt.NDArray[np.float32]:
    if audio.rate == rate or not len(audio.samples):
        return audio.samples
    return soxr.resample(audio.samples, audio.rate, rate, quality=RESAMPLER_QUALITY)


def _unsearchable(
    a: npt.NDArray[np.float64],
    b: npt.NDArray[np.float64],
    rate: int,
    noun: str = "track",
) -> str | None:
    """Say why the downmixes leave the search without a candidate, if they do; noun
    names what each downmix is of, a track or an edition."""
    downmixes = (("A", a), ("B", b))
    for name, downmix in downmixes:
        if (missing := _no_frames(downmix, f"{noun} {name}")) is not None:
            return missing
    for name, downmix in downmixes:
        if len(downmix) < locator.WINDOW_SECONDS * rate:
            return (
                f"{noun} {name} is shorter than one window of "
                f"{locator.WINDOW_SECONDS} s"
            )
    for name, downmix in downmixes:
        if not downmix.any():
            return f"the downmix of {noun} {name} is zero throughout"
    return None


def _no_frames(downmix: npt.NDArray[np.float64], name: str) -> str | None:
    return None if len(downmix) else f"{name} has no frames"


def _measure_pair(
    a: npt.NDArray[Any],
    b: npt.NDArray[Any],
    span: locator.Portion,
    rate: int,
    *,
    identical: bool,
    extent: str = "portion",
) -> dict[str, Any]:
    """Measure B against A over a span, a portion or a segment as extent names it:
    correlation, gain and residual."""
    end_b = span.start_b + span.frames
    # Views when the samples are already float64, as a downmix is.
    x = a[span.start_a : span.end_a].astype(np.float64, copy=False)
    y = b[span.start_b : end_b].astype(np.float64, copy=False)
    values: dict[str, Any] = {}
    absent: dict[str, str] = {}

    if np.min(x) == np.max(x):
        absent["correlation"] = f"track A is constant over the {extent}"
    elif np.min(y) == np.max(y):
        absent["correlation"] = f"track B is constant over the {extent}"
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
        absent["gain_db"] = f"track B is zero throughout the {extent}"
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
            else f"the gain is undefined: track B is zero throughout the {extent}"
        )
    else:
        error = y * -gain
        error += x
        np.square(error, out=error)
        energy = np.square(x)
        level = _residual(float(error.sum()), float(energy.sum()), extent)
        if isinstance(level, str):
            absent["residual_db"] = level
        else:
            values["residual_db"] = level
        starts = np.arange(0, span.frames, rate)
        values["residual_windows"] = [
            {
                "start_frame": int(start),
                "frames": min(rate, span.frames - int(start)),
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
