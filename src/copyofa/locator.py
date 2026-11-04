"""Locate the portions of one track that appear in another (see ADRs 0006 and 0010).

Both tracks are mono downmixes at one common rate, as float64 samples where 1.0 is
full scale: each an array, or a Lazy downmix read a block at a time, for a sequence
too long to hold. In a portion, frame n of track A lines up with frame
n + offset + ratio·(n - start) of track B, where start is the portion's first frame
of A: at a ratio of 0, frame n + offset, as in ADR 0003.
"""

from __future__ import annotations

import copy
import functools
import math
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, TypeAlias

import numpy as np
import soxr
from numpy.lib.stride_tricks import sliding_window_view

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    import numpy.typing as npt

    Samples = npt.NDArray[np.float64]

Downmix: TypeAlias = "Samples | Lazy"
"""A downmix the search reads: an array, or a Lazy downmix."""

# The fixed parameters of ADR 0006, decision 7. A change to any of them changes what
# a portion is, so it is a new comparison Report format version.
DECIMATION = 16
DECIMATION_QUALITY = "HQ"
FIRST_DIFFERENCE = 0.5
WINDOW_SECONDS = 5
HOP_SECONDS = 5
SILENT_WINDOW_RATIO = 1e-4
CANDIDATE_THRESHOLD = 0.4
CANDIDATES_PER_WINDOW = 3
CANDIDATE_SEPARATION_SECONDS = 0.5
SKIPPED_WINDOWS = 1
CHAINING_TOLERANCE_FRAMES = 32
CORE_RATIO = 0.85
CORE_SECONDS = 20
REFINEMENT_RADIUS_FRAMES = 32
BLOCK_FRAMES = 2048
MATCHED_BLOCK_RESIDUAL = 0.2
CORE_CONFIRMING_RATIO = 0.5
EVIDENCE_FLOOR_DBFS = -80
SILENCE_AGAINST_SIGNAL_DBFS = -60
END_RANGE_INSIDE_BLOCKS = 8
END_RANGE_OUTSIDE_BLOCKS = 1
ACCEPTANCE_RESIDUAL_DB = -10
MINIMUM_PORTION_SECONDS = 1
MERGE_TOLERANCE_FRAMES = 2
ALTERNATE_MARGIN_DB = 3
ALTERNATE_COVERAGE = 0.9
EQUAL_RESIDUAL_FLOOR_DB = -60
B_POSITION_ENERGY_FLOOR = 1e-10
"""A position of B whose energy under the window is at most this share of B's whole
energy gives no candidate, so that rounding errors in that energy, a difference of two
running sums, cannot pass for a match where B is next to silent."""

# The fixed parameters of ADR 0010, decision 8, and the details it leaves to the
# implementation: the first line's outlier distance.
ESTIMATE_DECIMATION_FACTORS = (128, 16)
"""The decimation factor of each level of the speed estimate."""
ESTIMATE_WINDOWS = (8, 12)
"""The windows of A each level of the speed estimate stretches."""
ESTIMATE_RANGE_PPM = 45_000
"""The first level tries every ratio within this many ppm of 0."""
ESTIMATE_STEPS_PPM = (1_500, 200)
"""The step between the ratios of each level."""
ESTIMATE_SPAN_PPM = 1_000
"""The second level tries every ratio within this many ppm of the first level's."""
ESTIMATE_ADOPTION_SCORE = 0.25
"""The mean of the windows' best scores at the second level's ratio that adopts it."""
FIRST_LINE_OUTLIER_FRAMES = 32
"""A coarse offset farther than this from the first line is left out of it."""
FIRST_RATIO_STRETCH_PPM = 20
"""B is stretched by the first ratio before the windows' offsets are taken when the
first ratio is at least this far from 0."""
RATIO_WINDOWS = 12
RATIO_MINIMUM_WINDOWS = 4
RATIO_RADIUS_FRAMES = 40
RATIO_WINDOW_SCORE_RATIO = 0.5
RATIO_OUTLIER_FRAMES = 4
RATIO_OUTLIER_DEVIATIONS = 3
RATIO_SNAP_PPM = 0.05
STRETCH_TAPS = 32
STRETCH_KAISER_BETA = 9
STRETCH_CUTOFF = 0.96
STRETCH_PHASES = 1024
STRETCH_MARGIN_SECONDS = 40
REFIT_WINDOW_SCORE = 0.3
REFIT_MINIMUM_WINDOWS = 3
REFIT_RADIUS_FRAMES = 12
REFIT_OUTLIER_FRAMES = 3
CONVERGENCE_FRAMES = 0.3
MAXIMUM_PASSES = 10

PARAMETERS: dict[str, Any] = {
    "decimation_factor": DECIMATION,
    "decimation_quality": DECIMATION_QUALITY,
    "first_difference_coefficient": FIRST_DIFFERENCE,
    "window_seconds": WINDOW_SECONDS,
    "hop_seconds": HOP_SECONDS,
    "silent_window_energy_ratio": SILENT_WINDOW_RATIO,
    "b_position_energy_floor": B_POSITION_ENERGY_FLOOR,
    "candidate_threshold": CANDIDATE_THRESHOLD,
    "candidates_per_window": CANDIDATES_PER_WINDOW,
    "candidate_separation_seconds": CANDIDATE_SEPARATION_SECONDS,
    "skipped_windows": SKIPPED_WINDOWS,
    "chaining_tolerance_frames": CHAINING_TOLERANCE_FRAMES,
    "core_ratio": CORE_RATIO,
    "core_seconds": CORE_SECONDS,
    "refinement_radius_frames": REFINEMENT_RADIUS_FRAMES,
    "block_frames": BLOCK_FRAMES,
    "matched_block_residual_ratio": MATCHED_BLOCK_RESIDUAL,
    "core_confirming_ratio": CORE_CONFIRMING_RATIO,
    "evidence_floor_dbfs": EVIDENCE_FLOOR_DBFS,
    "silence_against_signal_dbfs": SILENCE_AGAINST_SIGNAL_DBFS,
    "end_range_inside_blocks": END_RANGE_INSIDE_BLOCKS,
    "end_range_outside_blocks": END_RANGE_OUTSIDE_BLOCKS,
    "acceptance_residual_db": ACCEPTANCE_RESIDUAL_DB,
    "minimum_portion_seconds": MINIMUM_PORTION_SECONDS,
    "merge_tolerance_frames": MERGE_TOLERANCE_FRAMES,
    "alternate_margin_db": ALTERNATE_MARGIN_DB,
    "alternate_coverage_ratio": ALTERNATE_COVERAGE,
    "equal_residual_floor_db": EQUAL_RESIDUAL_FLOOR_DB,
    "estimate_decimation_factors": list(ESTIMATE_DECIMATION_FACTORS),
    "estimate_windows": list(ESTIMATE_WINDOWS),
    "estimate_range_ppm": ESTIMATE_RANGE_PPM,
    "estimate_steps_ppm": list(ESTIMATE_STEPS_PPM),
    "estimate_span_ppm": ESTIMATE_SPAN_PPM,
    "estimate_adoption_score": ESTIMATE_ADOPTION_SCORE,
    "first_line_outlier_frames": FIRST_LINE_OUTLIER_FRAMES,
    "first_ratio_stretch_ppm": FIRST_RATIO_STRETCH_PPM,
    "ratio_windows": RATIO_WINDOWS,
    "ratio_minimum_windows": RATIO_MINIMUM_WINDOWS,
    "ratio_radius_frames": RATIO_RADIUS_FRAMES,
    "ratio_window_score_ratio": RATIO_WINDOW_SCORE_RATIO,
    "ratio_outlier_frames": RATIO_OUTLIER_FRAMES,
    "ratio_outlier_deviations": RATIO_OUTLIER_DEVIATIONS,
    "ratio_snap_ppm": RATIO_SNAP_PPM,
    "stretch_taps": STRETCH_TAPS,
    "stretch_kaiser_beta": STRETCH_KAISER_BETA,
    "stretch_cutoff_ratio": STRETCH_CUTOFF,
    "stretch_phases": STRETCH_PHASES,
    "stretch_margin_seconds": STRETCH_MARGIN_SECONDS,
    "refit_window_score": REFIT_WINDOW_SCORE,
    "refit_minimum_windows": REFIT_MINIMUM_WINDOWS,
    "refit_radius_frames": REFIT_RADIUS_FRAMES,
    "refit_outlier_frames": REFIT_OUTLIER_FRAMES,
    "convergence_frames": CONVERGENCE_FRAMES,
    "maximum_passes": MAXIMUM_PASSES,
}
"""The parameters as the comparison Report states them, each name ending in its unit
when it has one."""

_CONFIRMS, _NEUTRAL, _REFUTES = 1, 0, -1
_GROWTH_BLOCKS = 64
"""Blocks classified at a time while a portion grows: enough to be fast, few enough
not to classify a whole track past an edge."""
_CHUNK_FRAMES = BLOCK_FRAMES << 9
"""Frames summed or stretched at a time over a long range, a whole number of blocks."""
_LAZY_BLOCK_FRAMES = 1 << 16
"""Frames a Lazy downmix reads or computes at a time."""
_KEPT_BLOCKS = 16
"""The blocks a Lazy downmix keeps, the last read: enough for the ranges refinement
reads again, such as a chain's core, few enough to hold little whatever the length."""
_PIECE_FRAMES = 1 << 20
"""Frames of a Lazy downmix decimated at a time."""
_ALIGNMENT_BYTES = 4096
"""Each array a Lazy downmix gives lies where it would in an array of the whole
downmix, modulo this many bytes (see empty_at)."""
_PPM = 1e-6
_EDGE_FRAMES = 2 * BLOCK_FRAMES
"""A portion refined on stretched B that ends this close to the stretched range,
where A and B go on, is refined again on a longer range."""

SAME_SPEED = "same_speed"
"""A portion's ratio is 0, however it came to be 0: snapped to it, or never fitted."""
CONFIRMED = "confirmed"
"""A portion's ratio is not 0, and a refit of its line on B stretched along it held
within CONVERGENCE_FRAMES."""
NOT_CONVERGED = "not_converged"
"""A portion's ratio is not 0, and a refit of its line succeeded but none held: the
passes ran out, or a later pass ended early, and the portion keeps the line of the
last pass that gave one."""
FIRST_RATIO = "first_ratio"
"""A portion's ratio is not 0, and no refit succeeded: the portion on its chain's line
has too few windows to refit, so it keeps that line."""


@dataclass(frozen=True)
class Portion:
    """A range of track A found in track B, at the common rate."""

    start_a: int
    frames: int
    offset: float
    """B's frame minus A's at the portion's first frame of A: an integer at a ratio of
    0, else to 0.01 frame."""
    residual_db: float | None
    """The residual after the per-block gains; None when it is zero throughout."""
    alternate: bool = False
    ratio_ppm: float = 0.0
    """B's frames per frame of A, minus one, in parts per million, to 0.01; 0 when
    the speeds agree."""
    ratio_fit: str = SAME_SPEED
    """How the ratio was set: SAME_SPEED exactly when the ratio is 0, else CONFIRMED,
    NOT_CONVERGED or FIRST_RATIO."""

    @property
    def end_a(self) -> int:
        return self.start_a + self.frames

    @property
    def start_b(self) -> int:
        """The first frame of B the portion holds, the nearest to its line."""
        return _nearest(self.start_a + self.offset)

    @property
    def end_b(self) -> int:
        return _nearest(self.position_b(self.end_a))

    @property
    def frames_b(self) -> int:
        return self.end_b - self.start_b

    def position_b(self, frame_a: float) -> float:
        """Return the position of B, to a fraction of a frame, at a frame of A."""
        return self._line().at(frame_a)

    def frame_a(self, position_b: float) -> float:
        """Return the position of A, to a fraction of a frame, at a frame of B."""
        return self._line().frame_of(position_b)

    def _line(self) -> _Line:
        return _Line(self.start_a, self.offset, self.ratio_ppm * _PPM)


@dataclass(frozen=True)
class _Line:
    """Where B lines up with A: frame n of A with n + offset + ratio·(n - start)."""

    start: float
    offset: float
    ratio: float

    def at(self, frame: float) -> float:
        return frame + self.offset + self.ratio * (frame - self.start)

    def frame_of(self, position: float) -> float:
        """Return the position of A that lines up with a position of B."""
        return self.start + (position - self.start - self.offset) / (1 + self.ratio)

    def moved(self, start: float) -> _Line:
        """Return the same line with its offset given at another frame of A."""
        return _Line(start, self.offset + self.ratio * (start - self.start), self.ratio)

    def corrected(self, fit: _Fit) -> _Line:
        """Return the line a fit of offsets measured against B along this line gives.

        A frame n of A found d(n) frames after B along this line lies at
        self.at(n) + (1 + ratio)·d(n) of B.
        """
        moved = self.moved(fit.anchor)
        scale = 1 + self.ratio
        return _Line(
            fit.anchor,
            moved.offset + scale * fit.offset,
            self.ratio + scale * fit.slope,
        )

    def shifted(self, frames: int) -> _Line:
        """Return the line of B along this line read a whole number of frames later."""
        return _Line(self.start, self.offset + (1 + self.ratio) * frames, self.ratio)

    def valid(self, frames_a: int, frames_b: int) -> tuple[int, int]:
        """Return the frames of A that have a frame of B on the line."""
        first = max(0, math.ceil(self.frame_of(0)))
        last = min(frames_a, math.floor(self.frame_of(frames_b - 1)) + 1)
        return first, max(first, last)


@dataclass(frozen=True)
class _Fit:
    """A line through offsets: offset + slope·(n - anchor) at frame n of A."""

    anchor: float
    offset: float
    slope: float


@dataclass(frozen=True)
class _Candidate:
    """A place in B of one window of A, from the coarse search."""

    window: int
    """The window's index in A."""
    start: int
    """The window's first frame in A, at the common rate."""
    offset: int
    """B's frame minus A's at the window's first frame, at the common rate."""
    score: float
    key: int
    """The offset in the coarse search, of A stretched by the speed estimate, in
    frames at the common rate: a multiple of DECIMATION, which chaining compares."""


class Lazy:
    """A downmix read or computed a block at a time as the search needs it, so that
    it is never held whole (brief 0009).

    Slicing it, with a step of 1, gives its frames as an array, as slicing an array
    would. The last _KEPT_BLOCKS blocks are kept, so that a range read again is not
    read or computed again.
    """

    def __init__(self, frames: int, read: Callable[[int, Samples], object]) -> None:
        """Make a downmix of frames frames that read(start, out) fills out with,
        from its frame start on."""
        self._blocks = _Blocks(frames, read)
        self._first = 0
        self._frames = frames

    def __len__(self) -> int:
        return self._frames

    def __getitem__(self, key: slice) -> Samples:
        start, stop, step = key.indices(self._frames)
        if step != 1:
            raise ValueError("a Lazy downmix is sliced with a step of 1")
        return self._blocks.read(self._first + start, self._first + max(start, stop))

    def part(self, start: int, stop: int) -> Lazy:
        """Return the frames [start, stop) as a downmix of their own, read through
        the same blocks, as slicing an array gives a view of it."""
        start, stop, _ = slice(start, stop).indices(self._frames)
        part = copy.copy(self)
        part._first += start
        part._frames = max(0, stop - start)
        return part

    def pieces(self) -> Iterator[Samples]:
        """Yield the frames in order, _PIECE_FRAMES at a time, without keeping them."""
        last = self._first + self._frames
        for start in range(self._first, last, _PIECE_FRAMES):
            yield self._blocks.fresh(start, min(last, start + _PIECE_FRAMES))


class _Blocks:
    """The frames of a Lazy downmix, read a block of _LAZY_BLOCK_FRAMES at a time,
    the last _KEPT_BLOCKS kept."""

    def __init__(self, frames: int, read: Callable[[int, Samples], object]) -> None:
        self._frames = frames
        self._read = read
        self._kept: OrderedDict[int, Samples] = OrderedDict()

    def read(self, start: int, stop: int) -> Samples:
        """Return the frames [start, stop), a view of a block when one holds them."""
        if stop <= start:
            return np.zeros(0)
        first, last = start // _LAZY_BLOCK_FRAMES, (stop - 1) // _LAZY_BLOCK_FRAMES
        if first == last:
            base = first * _LAZY_BLOCK_FRAMES
            return self._block(first)[start - base : stop - base]
        out = empty_at(start, stop - start)
        for index in range(first, last + 1):
            base = index * _LAZY_BLOCK_FRAMES
            low = max(start, base)
            high = min(stop, base + _LAZY_BLOCK_FRAMES)
            out[low - start : high - start] = self._block(index)[
                low - base : high - base
            ]
        return out

    def fresh(self, start: int, stop: int) -> Samples:
        """Return the frames [start, stop), read without keeping them."""
        out = empty_at(start, stop - start)
        self._read(start, out)
        return out

    def _block(self, index: int) -> Samples:
        block = self._kept.get(index)
        if block is not None:
            self._kept.move_to_end(index)
            return block
        start = index * _LAZY_BLOCK_FRAMES
        block = self.fresh(start, min(self._frames, start + _LAZY_BLOCK_FRAMES))
        block.flags.writeable = False
        self._kept[index] = block
        if len(self._kept) > _KEPT_BLOCKS:
            self._kept.popitem(last=False)
        return block


def empty_at(first: int, length: int) -> Samples:
    """Return an uninitialized array for frames [first, first + length) of a downmix,
    each frame lying where it would in an array of the whole downmix, modulo
    _ALIGNMENT_BYTES.

    The dot product of the BLAS NumPy uses can round differently at another alignment
    of the same values, so a downmix held in pieces, each made with this, gives each
    score, fit and sum that the whole downmix, as one array, gives.
    """
    slack = _ALIGNMENT_BYTES // 8
    buffer = np.empty(length + slack)
    shift = (first * 8 - buffer.ctypes.data) % _ALIGNMENT_BYTES // 8
    return buffer[shift : shift + length]


def _part(x: Downmix, start: int, stop: int) -> Downmix:
    """Return the frames [start, stop) of a downmix, without copying them."""
    return x[start:stop] if isinstance(x, np.ndarray) else x.part(start, stop)


def locate(a: Downmix, b: Downmix, rate: int) -> list[Portion]:
    """Return the portions of downmix a found in downmix b, at rate.

    Primary portions come first, in A's order, then alternates. An input shorter
    than one window gives none.
    """
    if min(len(a), len(b)) < WINDOW_SECONDS * rate:
        return []
    # Each downmix is read once to decimate it for both the speed estimate and the
    # coarse search, and once more for A stretched by the estimate.
    factors = sorted({DECIMATION, *ESTIMATE_DECIMATION_FACTORS})
    targets = [(factor, 0.0) for factor in factors]
    levels_a = dict(zip(factors, _coarse(a, rate, targets), strict=True))
    levels_b = dict(zip(factors, _coarse(b, rate, targets), strict=True))
    estimate = _estimate(levels_a, levels_b, rate)
    coarse_a, coarse_b = levels_a[DECIMATION], levels_b[DECIMATION]
    del levels_a, levels_b
    if estimate:
        (coarse_a,) = _coarse(a, rate, [(DECIMATION, estimate)])
    candidates = _candidates(coarse_a, coarse_b, rate / DECIMATION, estimate)
    del coarse_a, coarse_b
    pair = _Pair(a, b, rate)
    found: list[Portion] = []
    for chain in sorted(
        _chains(candidates), key=lambda chain: -max(node.score for node in chain)
    ):
        strongest = max(chain, key=lambda node: node.score)
        if any(
            abs(
                portion.position_b(strongest.start)
                - (strongest.start + strongest.offset)
            )
            <= CHAINING_TOLERANCE_FRAMES
            and portion.start_a <= min(node.start for node in chain)
            and max(node.start for node in chain) + pair.window <= portion.end_a
            for portion in found
        ):
            continue  # Already inside a portion found at this offset.
        remaining = chain
        while remaining:
            portion = _portion(pair, remaining, estimate)
            kept = remaining
            if portion is not None:
                found.append(portion)
                # Windows of the chain left outside the portion are refined again.
                kept = [
                    node
                    for node in remaining
                    if not (
                        portion.start_a <= node.start
                        and node.start + pair.window <= portion.end_a
                    )
                ]
            if len(kept) == len(remaining):
                strongest = max(remaining, key=lambda node: node.score)
                kept = [node for node in remaining if node is not strongest]
            remaining = kept
    accepted = [
        portion
        for portion in found
        if portion.residual_db is None or portion.residual_db <= ACCEPTANCE_RESIDUAL_DB
    ]
    return _rank(_merge(pair, accepted))


def aligned(b: npt.NDArray[Any], portion: Portion) -> Samples:
    """Return B lined up with a portion's range of A, one value per frame of A.

    At a ratio of 0, the portion's range of B, as float64; else B stretched along the
    portion's line by the interpolator of ADR 0010, frames outside B being zero.
    """
    if portion.ratio_ppm == 0:
        start = portion.start_b
        return b[start : start + portion.frames].astype(np.float64, copy=False)
    return _stretch(b, portion._line(), portion.start_a, portion.end_a)


def uncovered(ranges: Sequence[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    """Return the ranges of [0, total) that no range of ranges covers, in order."""
    gaps = []
    position = 0
    for start, end in sorted(ranges):
        if start > position:
            gaps.append((position, start))
        position = max(position, end)
    if position < total:
        gaps.append((position, total))
    return gaps


def _nearest(position: float) -> int:
    """Return the frame nearest a position, halves rounding up."""
    return math.floor(position + 0.5)


def _coarse(
    x: Downmix, rate: int, targets: Sequence[tuple[int, float]]
) -> list[npt.NDArray[np.float64]]:
    """Decimate a downmix for a search by each (decimation, ratio) of targets,
    stretched by the ratio, then take each one's first difference.

    The downmix is read once, a piece at a time, through one streaming resampler per
    target, which carries its state from piece to piece: each result is the one a
    single call on the whole downmix gives.
    """
    streams = []
    for decimation, ratio in targets:
        target = rate / decimation
        if ratio:
            target *= 1 + ratio
        streams.append(
            soxr.ResampleStream(
                rate, target, 1, dtype="float64", quality=DECIMATION_QUALITY
            )
        )
    outputs: list[list[npt.NDArray[np.float64]]] = [[] for _ in streams]
    pieces = (
        [np.ascontiguousarray(x, dtype=np.float64)]
        if isinstance(x, np.ndarray)
        else x.pieces()
    )
    for piece in pieces:
        for stream, output in zip(streams, outputs, strict=True):
            output.append(stream.resample_chunk(piece))
    decimated = []
    for stream, output in zip(streams, outputs, strict=True):
        output.append(stream.resample_chunk(np.zeros(0), last=True))
        y = empty_at(0, sum(len(part) for part in output))
        np.concatenate(output, out=y)
        output.clear()
        y[1:] -= FIRST_DIFFERENCE * y[:-1]
        decimated.append(y)
    return decimated


class _Searched:
    """Decimated B, ready to be correlated with windows of decimated A."""

    def __init__(self, b: npt.NDArray[np.float64]) -> None:
        self.b = b
        # The energy of B under the window at each position, from a running sum.
        # Where B holds next to nothing, rounding errors in that sum could pass for
        # a match.
        self.running = np.concatenate(([0.0], np.cumsum(np.square(b))))
        self.size = _fast_length(len(b))
        self.spectrum = np.fft.rfft(b, self.size)
        self._length = 0
        self._scale = np.zeros(0)

    def positions(self, length: int) -> int:
        return len(self.b) - length + 1

    def scale(self, length: int) -> npt.NDArray[np.float64]:
        """Return 1 / √(B's energy) under a window of length at each position, or 0
        where B is next to silent."""
        if length != self._length:
            under = self.running[length:] - self.running[:-length]
            searched = under > B_POSITION_ENERGY_FLOOR * self.running[-1]
            self._scale = np.zeros(self.positions(length))
            self._scale[searched] = 1 / np.sqrt(under[searched])
            self._length = length
        return self._scale

    def scores(
        self, window: npt.NDArray[np.float64], energy: float
    ) -> npt.NDArray[np.float64]:
        """Score each position of B for a window of A, by normalized
        cross-correlation."""
        length = len(window)
        positions = self.positions(length)
        spectrum = np.fft.rfft(window, self.size)
        np.conjugate(spectrum, out=spectrum)
        spectrum *= self.spectrum
        scores = np.abs(np.fft.irfft(spectrum, self.size)[:positions])
        scores *= self.scale(length)
        scores /= math.sqrt(energy)
        return scores


def _windows(
    a: npt.NDArray[np.float64], length: int, hop: int
) -> tuple[range, npt.NDArray[np.float64]]:
    """Return the starts of the windows of A and their energies."""
    starts = range(0, len(a) - length + 1, hop)
    energies = np.array([a[s : s + length] @ a[s : s + length] for s in starts])
    return starts, energies


def _estimate(
    levels_a: dict[int, npt.NDArray[np.float64]],
    levels_b: dict[int, npt.NDArray[np.float64]],
    rate: int,
) -> float:
    """Estimate the speed of B against A, as a ratio (ADR 0010, decision 1).

    levels_a and levels_b map each decimation factor of the estimate to the downmix
    of A and of B decimated by it, as _coarse gives it. Returns 0 when the estimate
    is not adopted.
    """
    center, span = 0, ESTIMATE_RANGE_PPM
    mean = 0.0
    for decimation, count, step in zip(
        ESTIMATE_DECIMATION_FACTORS, ESTIMATE_WINDOWS, ESTIMATE_STEPS_PPM, strict=True
    ):
        x, y = levels_a[decimation], levels_b[decimation]
        coarse_rate = rate / decimation
        length = round(WINDOW_SECONDS * coarse_rate)
        if length < 1 or len(x) < length or len(y) < length:
            return 0.0
        starts, energies = _windows(x, length, round(HOP_SECONDS * coarse_rate))
        audible = [
            start
            for start, energy in zip(starts, energies, strict=True)
            if energy > SILENT_WINDOW_RATIO * energies.mean()
        ]
        if not audible:
            return 0.0
        if len(audible) > count:
            audible = [
                audible[round(index)]
                for index in np.linspace(0, len(audible) - 1, count)
            ]
        searched = _Searched(y)
        ratios = range(center - span, center + span + 1, step)
        best: list[list[float]] = []
        for ppm in ratios:
            scores = []
            for start in audible:
                window = _stretched_window(x, start, length, ppm * _PPM, coarse_rate)
                energy = float(window @ window)
                if energy == 0 or len(window) > len(y):
                    scores.append(0.0)
                    continue
                scores.append(float(np.max(searched.scores(window, energy))))
            best.append(scores)
        del searched
        chosen = max(range(len(ratios)), key=lambda index: sum(best[index]))
        center, span = ratios[chosen], ESTIMATE_SPAN_PPM
        mean = sum(best[chosen]) / len(best[chosen])
    return center * _PPM if mean >= ESTIMATE_ADOPTION_SCORE else 0.0


def _stretched_window(
    x: npt.NDArray[np.float64], start: int, length: int, ratio: float, rate: float
) -> npt.NDArray[np.float64]:
    """Return a window of decimated A stretched by a ratio with libsoxr.

    The window is cut from a stretched excerpt a quarter of a window longer on
    each side, so that the resampler's edges fall outside it.
    """
    margin = max(1, length // 4)
    first = max(0, start - margin)
    excerpt = x[first : min(len(x), start + length + margin)]
    stretched = np.asarray(
        soxr.resample(excerpt, rate, rate * (1 + ratio), quality=DECIMATION_QUALITY),
        dtype=np.float64,
    )
    cut = round((start - first) * (1 + ratio))
    wanted = max(1, round(length * (1 + ratio)))
    window = stretched[cut : cut + wanted]
    if len(window) < wanted:
        window = np.concatenate((window, np.zeros(wanted - len(window))))
    return window


def _candidates(
    a: npt.NDArray[np.float64],
    b: npt.NDArray[np.float64],
    coarse_rate: float,
    ratio: float = 0,
) -> list[_Candidate]:
    """Find where each window of A may be in B, by normalized cross-correlation.

    A is stretched by ratio; each candidate's start and offset are mapped back to
    A's frames.
    """
    length = round(WINDOW_SECONDS * coarse_rate)
    hop = round(HOP_SECONDS * coarse_rate)
    positions = len(b) - length + 1
    # At a sample rate under 2 Hz, a window holds no frame of the decimated audio.
    if length < 1 or len(a) < length or positions < 1:
        return []
    starts, energies = _windows(a, length, hop)
    silent = SILENT_WINDOW_RATIO * energies.mean()
    searched = _Searched(b)
    # At 16 Hz and below, 0.5 s rounds to no decimated frame: the chosen position is
    # still cleared, so that the next candidate lies elsewhere.
    separation = max(1, round(CANDIDATE_SEPARATION_SECONDS * coarse_rate))
    found = []
    for index, (start, energy) in enumerate(zip(starts, energies, strict=True)):
        if energy <= silent:
            continue  # A silent window gives no evidence.
        scores = searched.scores(a[start : start + length], float(energy))
        first = start * DECIMATION
        if ratio:
            first = _nearest(first / (1 + ratio))
        for _ in range(CANDIDATES_PER_WINDOW):
            position = int(np.argmax(scores))
            score = float(scores[position])
            if score < CANDIDATE_THRESHOLD:
                break
            found.append(
                _Candidate(
                    index,
                    first,
                    position * DECIMATION - first,
                    score,
                    (position - start) * DECIMATION,
                )
            )
            scores[max(0, position - separation + 1) : position + separation] = 0
    return found


def _chains(candidates: list[_Candidate]) -> list[list[_Candidate]]:
    """Chain the candidates of neighboring windows that agree on the offset."""
    parent = list(range(len(candidates)))

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    by_window: dict[int, list[int]] = {}
    for index, candidate in enumerate(candidates):
        by_window.setdefault(candidate.window, []).append(index)
    for index, candidate in enumerate(candidates):
        for step in range(1, SKIPPED_WINDOWS + 2):
            for other in by_window.get(candidate.window + step, []):
                if (
                    abs(candidates[other].key - candidate.key)
                    <= CHAINING_TOLERANCE_FRAMES
                ):
                    parent[root(index)] = root(other)
    chains: dict[int, list[_Candidate]] = {}
    for index, candidate in enumerate(candidates):
        chains.setdefault(root(index), []).append(candidate)
    return list(chains.values())


class _Pair:
    """Both downmixes at the common rate, and what refinement computes on them."""

    def __init__(self, a: Downmix, b: Downmix, rate: int) -> None:
        self.a = a
        self.b = b
        self.rate = rate
        self.window = round(WINDOW_SECONDS * rate / DECIMATION) * DECIMATION
        self.quiet = 10 ** (EVIDENCE_FLOOR_DBFS / 10)
        self.silent = 10 ** (SILENCE_AGAINST_SIGNAL_DBFS / 10)
        self.offsets: dict[tuple[int, int], tuple[float, float, float] | None] = {}
        """Each window's offset against B itself, by its start and center."""

    def valid(self, offset: int) -> tuple[int, int]:
        """Return the frames of A that have a frame of B at offset."""
        return max(0, -offset), min(len(self.a), len(self.b) - offset)

    def sums(
        self, bounds: npt.NDArray[np.int64], offset: int
    ) -> tuple[npt.NDArray[np.float64], ...]:
        """Return Σa², Σab, Σb² and the length of each block between bounds."""
        start, stop = int(bounds[0]), int(bounds[-1])
        a = self.a[start:stop]
        b = self.b[start + offset : stop + offset]
        at = bounds[:-1] - start
        return (
            np.add.reduceat(a * a, at),
            np.add.reduceat(a * b, at),
            np.add.reduceat(b * b, at),
            np.diff(bounds).astype(np.float64),
        )

    def states(
        self, bounds: npt.NDArray[np.int64], offset: int
    ) -> npt.NDArray[np.int8]:
        """Classify each block between bounds as confirming, neutral or refuting."""
        aa, ab, bb, frames = self.sums(bounds, offset)
        explained = np.divide(ab * ab, bb, out=np.zeros_like(ab), where=bb > 0)
        confirms = (aa > 0) & (aa - explained <= MATCHED_BLOCK_RESIDUAL * aa)
        quiet = aa < self.quiet * frames
        states = np.full(len(aa), _REFUTES, dtype=np.int8)
        states[(aa > 0) & quiet] = _NEUTRAL
        states[(aa == 0) & (bb <= self.silent * frames)] = _NEUTRAL
        states[confirms] = _CONFIRMS
        return states

    def residual_db(self, start: int, stop: int, offset: int) -> float | None:
        """The residual after the per-block gains over [start, stop) of A, in dB.

        None when A minus the gained B is zero throughout.
        """
        return self._residual_db(
            start, stop, lambda chunk, end: self.b[chunk + offset : end + offset]
        )

    def residual_along(self, portion: Portion) -> float | None:
        """The residual after the per-block gains of a portion, B along its line."""
        line = portion._line()
        return self._residual_db(
            portion.start_a,
            portion.end_a,
            lambda chunk, end: _stretch(self.b, line, chunk, end),
        )

    def _residual_db(
        self, start: int, stop: int, b_of: Callable[[int, int], Samples]
    ) -> float | None:
        error = energy = 0.0
        for chunk in range(start, stop, _CHUNK_FRAMES):
            end = min(stop, chunk + _CHUNK_FRAMES)
            a = self.a[chunk:end]
            b = b_of(chunk, end)
            at = np.arange(0, end - chunk, BLOCK_FRAMES)
            bb = np.add.reduceat(b * b, at)
            gains = np.divide(
                np.add.reduceat(a * b, at), bb, out=np.zeros_like(bb), where=bb > 0
            )
            difference = a - np.repeat(gains, np.diff(np.append(at, end - chunk))) * b
            error += float(difference @ difference)
            energy += float(a @ a)
        if error == 0:
            return None
        return 10 * math.log10(error / energy)

    def gain(self, start: int, stop: int, offset: int) -> float:
        a = self.a[start:stop]
        b = self.b[start + offset : stop + offset]
        energy = float(b @ b)
        return float(a @ b) / energy if energy > 0 else 0.0

    def scores(
        self, start: int, stop: int, offset: int, gain: float
    ) -> npt.NDArray[np.float64]:
        """Score each frame: positive where B explains A, negative where it does not."""
        a = self.a[start:stop]
        error = a - gain * self.b[start + offset : stop + offset]
        return MATCHED_BLOCK_RESIDUAL * a * a - error * error


def _portion(pair: _Pair, chain: list[_Candidate], estimate: float) -> Portion | None:
    """Refine a chain into a portion at its own ratio, if it holds one."""
    line = _chain_line(pair, chain, estimate)
    if line is None:
        return _refine(pair, chain)
    found = _refine_along(pair, chain, line)
    if found is not None and found.ratio_ppm == 0:
        # At a ratio that snaps to 0, the chain is refined as ADR 0006 refines it.
        return _refine(pair, chain)
    return found


def _best_windows(chain: list[_Candidate]) -> tuple[list[_Candidate], int]:
    """Return the best candidate of each window of a chain, in A's order, and the
    index of the strongest."""
    best: dict[int, _Candidate] = {}
    for node in chain:
        if node.window not in best or node.score > best[node.window].score:
            best[node.window] = node
    windows = [best[index] for index in sorted(best)]
    strongest = max(range(len(windows)), key=lambda index: windows[index].score)
    return windows, strongest


def _chain_line(pair: _Pair, chain: list[_Candidate], estimate: float) -> _Line | None:
    """Fit the line of a chain near its strongest window (ADR 0010, decision 3).

    None when its ratio is 0.
    """
    windows, strongest = _best_windows(chain)
    peak = windows[strongest]
    fit = _fit(
        [(node.start, float(node.offset)) for node in windows],
        FIRST_LINE_OUTLIER_FRAMES,
        None,
        2,
    )
    if fit is None:
        first = _Line(peak.start, peak.offset, estimate)
    else:
        first = _Line(fit.anchor, fit.offset, fit.slope).moved(peak.start)
    stretched = abs(first.ratio) >= FIRST_RATIO_STRETCH_PPM * _PPM
    near = [node for node in windows if abs(node.window - peak.window) <= RATIO_WINDOWS]
    base = first if stretched else _Line(0, 0, 0)
    reach = RATIO_RADIUS_FRAMES + 1
    low = min(node.start for node in near) - reach
    high = max(node.start for node in near) + pair.window + reach
    along = _Along(pair.b, base, low, high, stretch=stretched)
    if stretched:
        centers = [
            round(base.frame_of(node.start + node.offset) - node.start) for node in near
        ]
        offsets = _offsets(
            pair.a,
            along,
            [node.start for node in near],
            pair.window,
            centers,
            RATIO_RADIUS_FRAMES,
        )
    else:
        # On B itself a window's offset depends only on the window and its center,
        # so a chain refined again, after a portion took some of its windows, reuses
        # them.
        offsets = []
        for node in near:
            key = (node.start, node.offset)
            if key not in pair.offsets:
                pair.offsets[key] = _offset(
                    pair.a,
                    along,
                    node.start,
                    pair.window,
                    node.offset,
                    RATIO_RADIUS_FRAMES,
                )
            offset = pair.offsets[key]
            if offset is not None:
                offsets.append(offset)
    line = base if stretched else None
    if offsets:
        top = max(score for _, _, score in offsets)
        corrected = _fit(
            [
                (start, offset)
                for start, offset, score in offsets
                if score >= RATIO_WINDOW_SCORE_RATIO * top
            ],
            RATIO_OUTLIER_FRAMES,
            RATIO_OUTLIER_DEVIATIONS,
            RATIO_MINIMUM_WINDOWS,
        )
        if corrected is not None:
            line = base.corrected(corrected)
    if line is None or abs(line.ratio) <= RATIO_SNAP_PPM * _PPM:
        return None
    return line


def _refine_along(pair: _Pair, chain: list[_Candidate], line: _Line) -> Portion | None:
    """Refine a chain into a portion on B stretched along its line, refitting the
    line until it holds (ADR 0010, decision 4).

    The portion's ratio is CONFIRMED when a refit holds, FIRST_RATIO when no refit
    succeeds, the portion on the chain's line having too few windows, and
    NOT_CONVERGED when a refit succeeded and none held after it.
    """
    windows, strongest = _best_windows(chain)
    low, high = _core(pair, windows, strongest)
    core_start = windows[low].start
    core_stop = min(windows[high].start + pair.window, len(pair.a))
    if not _core_holds(pair, chain, line, core_start, core_stop):
        return None
    margin = STRETCH_MARGIN_SECONDS * pair.rate
    span = (core_start, core_stop)
    result: tuple[_Line, int, int] | None = None
    ratio_fit = FIRST_RATIO
    for _ in range(MAXIMUM_PASSES):
        first, last = line.valid(len(pair.a), len(pair.b))
        lo, hi = max(first, span[0] - margin), min(last, span[1] + margin)
        while True:
            if hi - lo < pair.window:
                return None if result is None else _quantized(pair, *result, ratio_fit)
            along, found = _refined_on(pair, chain, line, lo, hi)
            if found is None:
                return None if result is None else _quantized(pair, *result, ratio_fit)
            extend = max(margin, hi - lo)
            if found.start_a < _EDGE_FRAMES and lo > first:
                lo = max(first, lo - extend)
                continue
            if found.end_a > hi - lo - _EDGE_FRAMES and hi < last:
                hi = min(last, hi + extend)
                continue
            break
        shift = int(found.offset)
        start, end = lo + found.start_a, lo + found.end_a
        current = line.shifted(shift)
        result = (current, start, end)
        starts = list(range(start, end - pair.window + 1, pair.window))
        offsets = [
            (frame, offset)
            for frame, offset, score in _offsets(
                pair.a,
                along,
                starts,
                pair.window,
                [shift] * len(starts),
                REFIT_RADIUS_FRAMES,
            )
            if score >= REFIT_WINDOW_SCORE
        ]
        fit = _fit(offsets, REFIT_OUTLIER_FRAMES, None, REFIT_MINIMUM_WINDOWS)
        if fit is None:
            break
        refitted = line.corrected(fit)
        if all(
            abs(refitted.at(frame) - current.at(frame)) <= CONVERGENCE_FRAMES
            for frame in (start, end)
        ):
            # The portion holds on the refitted line, the closer of the two.
            result = (refitted, start, end)
            ratio_fit = CONFIRMED
            break
        # A refit succeeded but did not hold: whichever line the portion keeps, it is
        # not confirmed.
        ratio_fit = NOT_CONVERGED
        line = refitted
        span = (min(start, core_start), max(end, core_stop))
    return None if result is None else _quantized(pair, *result, ratio_fit)


def _refined_on(
    pair: _Pair, chain: list[_Candidate], line: _Line, lo: int, hi: int
) -> tuple[_Along, Portion | None]:
    """Refine a chain as ADR 0006 does, on B stretched along a line over frames
    [lo, hi) of A; the portion's frames are counted from lo."""
    along, local, nodes = _local(pair, chain, line, lo, hi)
    return along, (_refine(local, nodes) if nodes else None)


def _local(
    pair: _Pair, chain: list[_Candidate], line: _Line, lo: int, hi: int
) -> tuple[_Along, _Pair, list[_Candidate]]:
    """Return B stretched along a line over frames [lo, hi) of A, the pair it makes
    with that range of A, and the windows of the chain inside it, counted from lo."""
    along = _Along(pair.b, line, lo, hi)
    local = _Pair(_part(pair.a, lo, hi), along.samples, pair.rate)
    nodes = [
        _Candidate(
            node.window,
            node.start - lo,
            round(line.frame_of(node.start + node.offset) - node.start),
            node.score,
            node.key,
        )
        for node in chain
        if lo <= node.start and node.start + pair.window <= hi
    ]
    return along, local, nodes


def _core_holds(
    pair: _Pair, chain: list[_Candidate], line: _Line, core_start: int, core_stop: int
) -> bool:
    """Whether a chain's core holds a match on its line, from B stretched over the
    core and the frames around it that the offsets searched reach.

    Whether the core holds depends on nothing outside that range, so a chain whose
    core does not hold gives no portion on any range: the chains that fail, many of
    those tried, are spared stretching the margins around their core. Where A or B
    ends within that range, refinement could choose its core again from other
    windows, so the whole range decides.
    """
    windows, strongest = _best_windows(chain)
    peak = windows[strongest]
    coarse = round(line.frame_of(peak.start + peak.offset) - peak.start)
    reach = abs(coarse) + REFINEMENT_RADIUS_FRAMES
    first, last = line.valid(len(pair.a), len(pair.b))
    lo, hi = core_start - reach, core_stop + reach
    if lo < first or hi > last:
        return True
    _, local, nodes = _local(pair, chain, line, lo, hi)
    return not nodes or _held_core(local, nodes) is not None


def _quantized(
    pair: _Pair, line: _Line, start: int, end: int, ratio_fit: str
) -> Portion | None:
    """Return a portion on a line given to 0.01 frame and 0.01 ppm, its residual
    taken on that line, its ratio set as ratio_fit says, unless it rounds to 0.

    The rounding can move the line by a fraction of a frame, so the range keeps only
    the frames of A that have a frame of B on the line as given; None when less than
    the shortest portion is left.
    """
    ratio_ppm = round(line.ratio / _PPM, 2) + 0.0
    if abs(ratio_ppm) <= RATIO_SNAP_PPM:
        return Portion(start, end - start, 0, None)
    offset = round(line.at(start) - start, 2)
    given = Portion(start, end - start, offset, None, ratio_ppm=ratio_ppm)
    first, last = given._line().valid(len(pair.a), len(pair.b))
    start, end = max(start, first), min(end, last)
    if end - start < MINIMUM_PORTION_SECONDS * pair.rate:
        return None
    offset = round(line.at(start) - start, 2) + 0.0
    portion = Portion(
        start, end - start, offset, None, ratio_ppm=ratio_ppm, ratio_fit=ratio_fit
    )
    return replace(portion, residual_db=pair.residual_along(portion))


class _Along:
    """B along a line, over a range of A's frames; on the line of ratio and offset 0,
    B itself, not stretched."""

    def __init__(
        self, b: Downmix, line: _Line, low: int, high: int, *, stretch: bool = True
    ) -> None:
        self.samples: Downmix
        if stretch:
            first = self.low = max(0, low)
            # Stretched a block at a time as refinement reads it, never over the
            # whole range at once (brief 0009).
            self.samples = Lazy(
                max(first, high) - first,
                lambda start, out: _stretch(
                    b, line, first + start, first + start + len(out), out
                ),
            )
        else:
            self.low = 0
            self.samples = b

    def window(self, start: int, stop: int) -> Samples:
        """Return the samples over [start, stop) of A, zero outside the range."""
        first, last = start - self.low, stop - self.low
        if first >= 0 and last <= len(self.samples):
            return self.samples[first:last]
        window = np.zeros(stop - start)
        low, high = max(first, 0), min(last, len(self.samples))
        if high > low:
            window[low - first : high - first] = self.samples[low:high]
        return window


def _offsets(
    a: Downmix,
    along: _Along,
    starts: Sequence[int],
    length: int,
    centers: Sequence[int],
    radius: int,
) -> list[tuple[float, float, float]]:
    """Find each window of A in B along a line, within radius of its center.

    Returns each window's middle frame, its offset against B along the line, to a
    fraction of a frame, and its score, |Σab| / √(Σa²·Σb²). The offset is the mean
    over the window, so it belongs to the window's middle: where the line drifts
    across the window, at its start it would be off by half the drift. The whole
    frames are those of the best score; the fraction is the slope of the phase of
    the cross-spectrum there, each frequency weighted by its magnitude times the
    frequency. A window whose best offset is at the edge of the search, that holds no
    energy or whose cross-spectrum holds none above 0 Hz, or whose fraction is a whole
    frame or more, gives none.
    """
    found = []
    for start, center in zip(starts, centers, strict=True):
        offset = _offset(a, along, start, length, center, radius)
        if offset is not None:
            found.append(offset)
    return found


def _offset(
    a: Downmix, along: _Along, start: int, length: int, center: int, radius: int
) -> tuple[float, float, float] | None:
    """Find one window of A in B along a line, as _offsets does."""
    x = a[start : start + length]
    energy = float(x @ x)
    if energy == 0:
        return None
    first = start + center - radius
    y = along.window(first, first + len(x) + 2 * radius)
    products = np.correlate(y, x, "valid")
    running = np.concatenate(([0.0], np.cumsum(y * y)))
    under = running[len(x) :] - running[: -len(x)]
    scores = np.zeros(len(products))
    positive = under > 0
    scores[positive] = np.abs(products[positive]) / np.sqrt(energy * under[positive])
    peak = int(np.argmax(scores))
    if peak in (0, len(scores) - 1) or scores[peak] == 0:
        return None
    size = _fast_length(len(x))
    x_spectrum = np.fft.rfft(x, size)
    cross = np.fft.rfft(y[peak : peak + len(x)], size) * np.conjugate(x_spectrum)
    if products[peak] < 0:
        cross = -cross  # Inverted polarity.
    angles = 2 * np.pi * np.arange(len(cross)) / size
    weights = np.abs(cross) * angles
    spread = float(weights @ angles)
    if spread == 0:
        return None  # Nothing above 0 Hz places the window in time.
    fraction = -float(weights @ np.angle(cross)) / spread
    if abs(fraction) >= 1:
        return None
    return start + len(x) / 2, center - radius + peak + fraction, float(scores[peak])


def _fit(
    points: Sequence[tuple[float, float]],
    outlier_frames: float,
    deviations: float | None,
    minimum: int,
) -> _Fit | None:
    """Fit a line through (frame, offset) points by least squares, leaving out the
    farthest point while it lies farther than outlier_frames, or than deviations
    times the residuals' standard deviation; None with fewer than minimum points
    left, or no two at different frames."""
    kept = list(points)
    while len(kept) >= minimum:
        frames = np.array([frame for frame, _ in kept], dtype=np.float64)
        offsets = np.array([offset for _, offset in kept], dtype=np.float64)
        anchor = float(frames.mean())
        spread = frames - anchor
        weight = float(spread @ spread)
        if weight == 0:
            return None
        slope = float(spread @ (offsets - offsets.mean())) / weight
        level = float(offsets.mean())
        distances = np.abs(offsets - (level + slope * spread))
        worst = int(np.argmax(distances))
        limit = outlier_frames
        if deviations is not None:
            limit = min(limit, deviations * math.sqrt(float(np.mean(distances**2))))
        if distances[worst] <= limit:
            return _Fit(anchor, level, slope)
        del kept[worst]
    return None


@functools.cache
def _kernel() -> npt.NDArray[np.float64]:
    """Return the interpolator's taps at each phase, one row per phase from 0 to 1.

    A windowed sinc of STRETCH_TAPS taps, Kaiser window, cut off at STRETCH_CUTOFF of
    the Nyquist frequency, each row scaled to a gain of 1 at 0 Hz.
    """
    half = STRETCH_TAPS // 2
    phases = np.arange(STRETCH_PHASES + 1) / STRETCH_PHASES
    distance = np.arange(STRETCH_TAPS)[None, :] - (half - 1) - phases[:, None]
    window = np.i0(
        STRETCH_KAISER_BETA * np.sqrt(np.clip(1 - (distance / half) ** 2, 0, None))
    ) / np.i0(STRETCH_KAISER_BETA)
    taps = STRETCH_CUTOFF * np.sinc(STRETCH_CUTOFF * distance) * window
    taps /= taps.sum(axis=1, keepdims=True)
    return taps


def _stretch(
    b: Downmix | npt.NDArray[Any],
    line: _Line,
    start: int,
    stop: int,
    out: Samples | None = None,
) -> Samples:
    """Return B along a line over frames [start, stop) of A, by the interpolator.

    Each value is B at the line's position, from the STRETCH_TAPS frames around it,
    at the nearest of STRETCH_PHASES phases; frames outside B count as zero. A frame's
    position is taken from the line's own start, so its value is the same whatever
    range it is stretched in.
    """
    taps = _kernel()
    half = STRETCH_TAPS // 2
    if out is None:
        out = np.empty(max(0, stop - start))
    origin = line.at(line.start)
    scale = 1 + line.ratio
    chunk = _CHUNK_FRAMES >> 4
    for first in range(start, stop, chunk):
        last = min(stop, first + chunk)
        positions = origin + (np.arange(first, last) - line.start) * scale
        whole = np.floor(positions)
        phases = np.rint((positions - whole) * STRETCH_PHASES).astype(np.int64)
        indices = whole.astype(np.int64)
        low = int(indices[0]) - (half - 1)
        high = int(indices[-1]) + half + 1
        local = np.zeros(high - low)
        inside_low, inside_high = max(low, 0), min(high, len(b))
        if inside_high > inside_low:
            local[inside_low - low : inside_high - low] = b[inside_low:inside_high]
        rows = sliding_window_view(local, STRETCH_TAPS)[indices - (half - 1) - low]
        out[first - start : last - start] = np.einsum("ij,ij->i", rows, taps[phases])
    return out


def _core(pair: _Pair, windows: list[_Candidate], strongest: int) -> tuple[int, int]:
    """Return the first and last of the windows of a chain's core."""
    low = high = strongest
    core_limit = CORE_SECONDS * pair.rate
    grew = True
    while grew:
        grew = False
        for neighbor in (low - 1, high + 1):
            if not 0 <= neighbor < len(windows):
                continue
            node = windows[neighbor]
            first, last = min(neighbor, low), max(neighbor, high)
            if (
                node.score >= CORE_RATIO * windows[strongest].score
                and abs(node.window - windows[low if neighbor < low else high].window)
                == 1
                and windows[last].start - windows[first].start + pair.window
                <= core_limit
            ):
                low, high = first, last
                grew = True
    return low, high


def _refine(pair: _Pair, chain: list[_Candidate]) -> Portion | None:
    """Refine a chain into a portion at one offset, if it holds one (ADR 0006)."""
    held = _held_core(pair, chain)
    if held is None:
        return None
    offset, bounds, states = held
    first_valid, last_valid = pair.valid(offset)
    run_start, run_stop = _best_run(states)
    confirmed = run_start + np.flatnonzero(states[run_start:run_stop] == _CONFIRMS)
    left = _grow_left(pair, int(bounds[confirmed[0]]), first_valid, offset)
    right = _grow_right(pair, int(bounds[confirmed[-1] + 1]), last_valid, offset)
    # Each end is placed to the frame, inside the frames that hold both tracks.
    inside = max(left, right - END_RANGE_INSIDE_BLOCKS * BLOCK_FRAMES)
    outside = min(last_valid, right + END_RANGE_OUTSIDE_BLOCKS * BLOCK_FRAMES)
    gain = pair.gain(inside, right, offset)
    prefix = np.cumsum(pair.scores(inside, outside, offset, gain))
    # The maximum-scoring prefix; an empty one scores 0.
    end = inside + _first_maximum(prefix)
    inside = min(right, left + END_RANGE_INSIDE_BLOCKS * BLOCK_FRAMES)
    outside = max(first_valid, left - END_RANGE_OUTSIDE_BLOCKS * BLOCK_FRAMES)
    gain = pair.gain(left, inside, offset)
    suffix = np.cumsum(pair.scores(outside, inside, offset, gain)[::-1])
    start = inside - _first_maximum(suffix)
    if end - start < MINIMUM_PORTION_SECONDS * pair.rate:
        return None
    return Portion(start, end - start, offset, pair.residual_db(start, end, offset))


def _held_core(
    pair: _Pair, chain: list[_Candidate]
) -> tuple[int, npt.NDArray[np.int64], npt.NDArray[np.int8]] | None:
    """Return a chain's offset and the bounds and states of its core's blocks, or
    None when its core holds no match: no best offset, or too few confirming blocks.

    Only the core and the refinement radius around it decide.
    """
    windows, strongest = _best_windows(chain)
    low, high = _core(pair, windows, strongest)
    core_start = windows[low].start
    core_stop = min(windows[high].start + pair.window, len(pair.a))
    offset = _best_offset(pair, core_start, core_stop, windows[strongest].offset)
    if offset is None:
        return None
    first_valid, last_valid = pair.valid(offset)
    core_start, core_stop = max(core_start, first_valid), min(core_stop, last_valid)
    if core_stop <= core_start:
        return None
    bounds = _bounds(core_start, core_stop)
    states = pair.states(bounds, offset)
    confirming = int((states == _CONFIRMS).sum())
    if confirming == 0 or confirming < CORE_CONFIRMING_RATIO * int(
        (states != _NEUTRAL).sum()
    ):
        return None
    return offset, bounds, states


def _best_offset(pair: _Pair, start: int, stop: int, coarse: int) -> int | None:
    """Return the offset near coarse that maximizes |Σab| / √Σb² over the core.

    Every offset is scored over the same frames of A: those that have a frame of B
    at each offset searched. None when there are none.
    """
    lowest = coarse - REFINEMENT_RADIUS_FRAMES
    highest = coarse + REFINEMENT_RADIUS_FRAMES
    start = max(start, -lowest)
    stop = min(stop, len(pair.b) - highest)
    if stop <= start:
        return None
    a = pair.a[start:stop]
    # B over every offset searched, read once; each offset's frames are a view of it.
    reach = pair.b[start + lowest : stop + highest]
    best, chosen = -1.0, None
    for offset in range(lowest, highest + 1):
        b = reach[offset - lowest : offset - lowest + stop - start]
        energy = float(b @ b)
        if energy == 0:
            continue
        score = abs(float(a @ b)) / math.sqrt(energy)
        if score > best:
            best, chosen = score, offset
    return chosen


def _bounds(start: int, stop: int) -> npt.NDArray[np.int64]:
    """Return the bounds of the blocks from start to stop; the last may be short."""
    return np.append(np.arange(start, stop, BLOCK_FRAMES), stop).astype(np.int64)


def _best_run(states: npt.NDArray[np.int8]) -> tuple[int, int]:
    """Return the run of blocks without a refuting one that most blocks confirm."""
    best, chosen = 0, (0, 0)
    for run_start, run_stop in _runs(states != _REFUTES):
        confirming = int((states[run_start:run_stop] == _CONFIRMS).sum())
        if confirming > best:
            best, chosen = confirming, (run_start, run_stop)
    return chosen


def _runs(flags: npt.NDArray[np.bool_]) -> Iterator[tuple[int, int]]:
    """Yield the start and stop of each run of true flags."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], flags.view(np.int8), [0]))))
    yield from zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True)


def _grow_right(pair: _Pair, edge: int, limit: int, offset: int) -> int:
    """Grow a portion's end block by block until a block refutes the match."""
    position = edge
    while position < limit:
        stop = min(limit, position + _GROWTH_BLOCKS * BLOCK_FRAMES)
        bounds = _bounds(position, stop)
        for index, state in enumerate(pair.states(bounds, offset).tolist()):
            if state == _REFUTES:
                return edge
            if state == _CONFIRMS:
                edge = int(bounds[index + 1])
        position = stop
    return edge


def _grow_left(pair: _Pair, edge: int, limit: int, offset: int) -> int:
    """Grow a portion's start block by block until a block refutes the match."""
    position = edge
    while position > limit:
        start = max(limit, position - _GROWTH_BLOCKS * BLOCK_FRAMES)
        bounds = np.concatenate(
            (
                [start],
                np.arange(position - BLOCK_FRAMES, start, -BLOCK_FRAMES)[::-1],
                [position],
            )
        ).astype(np.int64)
        states = pair.states(bounds, offset).tolist()
        for index in range(len(states) - 1, -1, -1):
            if states[index] == _REFUTES:
                return edge
            if states[index] == _CONFIRMS:
                edge = int(bounds[index])
        position = start
    return edge


def _first_maximum(cumulative: npt.NDArray[np.float64]) -> int:
    """Return the length of the first maximum-scoring prefix, from running sums."""
    index = int(np.argmax(cumulative)) if len(cumulative) else 0
    return index + 1 if len(cumulative) and cumulative[index] > 0 else 0


def _merge(pair: _Pair, portions: list[Portion]) -> list[Portion]:
    """Merge portions whose lines lie within MERGE_TOLERANCE_FRAMES of each other
    where their ranges of A overlap or touch.

    A merged portion takes the line of the longer one, given at its own first frame.
    """
    merged = list(portions)
    changed = True
    while changed:
        changed = False
        for first in range(len(merged)):
            for second in range(first + 1, len(merged)):
                one, other = merged[first], merged[second]
                if _mergeable(one, other):
                    merged[first] = _merged(pair, one, other)
                    del merged[second]
                    changed = True
                    break
            if changed:
                break
    return merged


def _mergeable(one: Portion, other: Portion) -> bool:
    low, high = max(one.start_a, other.start_a), min(one.end_a, other.end_a)
    return low <= high and all(
        abs(one.position_b(frame) - other.position_b(frame)) <= MERGE_TOLERANCE_FRAMES
        for frame in (low, high)
    )


def _merged(pair: _Pair, one: Portion, other: Portion) -> Portion:
    longer = max(one, other, key=lambda portion: portion.frames)
    if longer.ratio_ppm == 0:
        offset = int(longer.offset)
        low, high = pair.valid(offset)
        start = max(low, min(one.start_a, other.start_a))
        end = min(high, max(one.end_a, other.end_a))
        return Portion(start, end - start, offset, pair.residual_db(start, end, offset))
    line = longer._line()
    low, high = line.valid(len(pair.a), len(pair.b))
    start = max(low, min(one.start_a, other.start_a))
    end = min(high, max(one.end_a, other.end_a))
    offset = round(line.at(start) - start, 2) + 0.0
    # The merged portion takes the longer one's line, and with it how its ratio was set.
    portion = Portion(
        start,
        end - start,
        offset,
        None,
        ratio_ppm=longer.ratio_ppm,
        ratio_fit=longer.ratio_fit,
    )
    return replace(portion, residual_db=pair.residual_along(portion))


def _rank(portions: list[Portion]) -> list[Portion]:
    """Mark the alternates, then order primaries, then alternates, each in A's order."""

    def level(portion: Portion) -> float:
        if portion.residual_db is None:
            return EQUAL_RESIDUAL_FLOOR_DB
        return max(portion.residual_db, EQUAL_RESIDUAL_FLOOR_DB)

    ranked = []
    for portion in portions:
        # The ranges of better portions inside this one, counted from its start.
        better = [
            (
                max(other.start_a, portion.start_a) - portion.start_a,
                min(other.end_a, portion.end_a) - portion.start_a,
            )
            for other in portions
            if other is not portion
            and level(other) <= level(portion) - ALTERNATE_MARGIN_DB
        ]
        gaps = uncovered(
            [(start, end) for start, end in better if start < end], portion.frames
        )
        covered = portion.frames - sum(end - start for start, end in gaps)
        ranked.append(
            replace(portion, alternate=covered >= ALTERNATE_COVERAGE * portion.frames)
        )
    return sorted(
        ranked, key=lambda portion: (portion.alternate, portion.start_a, portion.offset)
    )


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
