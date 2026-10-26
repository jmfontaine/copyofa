"""Locate the portions of one track that appear in another (see ADR 0006).

Both tracks are mono downmixes at one common rate, as float64 samples where 1.0 is
full scale. Frame n of track A lines up with frame n + offset of track B in a
portion, as in ADR 0003.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import soxr

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import numpy.typing as npt

    Samples = npt.NDArray[np.float64]

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
# Not a parameter of the method: a position of B is searched only when its energy
# under the window exceeds this share of B's whole energy, which keeps the energy,
# a difference of two running sums, well above their rounding error.
_ROUNDING_GUARD = 1e-10

PARAMETERS: dict[str, Any] = {
    "decimation_factor": DECIMATION,
    "decimation_quality": DECIMATION_QUALITY,
    "first_difference_coefficient": FIRST_DIFFERENCE,
    "window_seconds": WINDOW_SECONDS,
    "hop_seconds": HOP_SECONDS,
    "silent_window_energy_ratio": SILENT_WINDOW_RATIO,
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
}
"""The parameters as the comparison Report states them, each name ending in its unit
when it has one."""

_CONFIRMS, _NEUTRAL, _REFUTES = 1, 0, -1
_GROWTH_BLOCKS = 64
"""Blocks classified at a time while a portion grows: enough to be fast, few enough
not to classify a whole track past an edge."""
_CHUNK_FRAMES = BLOCK_FRAMES << 9
"""Frames summed at a time over a long range, a whole number of blocks."""


@dataclass(frozen=True)
class Portion:
    """A range of track A found in track B, at the common rate."""

    start_a: int
    frames: int
    offset: int
    """Frame n of A lines up with frame n + offset of B."""
    residual_db: float | None
    """The residual after the per-block gains; None when it is zero throughout."""
    alternate: bool = False

    @property
    def end_a(self) -> int:
        return self.start_a + self.frames

    @property
    def start_b(self) -> int:
        return self.start_a + self.offset


@dataclass(frozen=True)
class _Candidate:
    """A place in B of one window of A, from the coarse search."""

    window: int
    """The window's index in A."""
    start: int
    """The window's first frame in A, at the common rate."""
    offset: int
    """In frames at the common rate, a multiple of DECIMATION."""
    score: float


def locate(a: Samples, b: Samples, rate: int) -> list[Portion]:
    """Return the portions of downmix a found in downmix b, at rate.

    Primary portions come first, in A's order, then alternates. An input shorter
    than one window gives none.
    """
    if min(len(a), len(b)) < WINDOW_SECONDS * rate:
        return []
    candidates = _candidates(_coarse(a, rate), _coarse(b, rate), rate / DECIMATION)
    pair = _Pair(a, b, rate)
    found: list[Portion] = []
    for chain in sorted(
        _chains(candidates), key=lambda chain: -max(node.score for node in chain)
    ):
        strongest = max(chain, key=lambda node: node.score)
        if any(
            abs(portion.offset - strongest.offset) <= CHAINING_TOLERANCE_FRAMES
            and portion.start_a <= min(node.start for node in chain)
            and max(node.start for node in chain) + pair.window <= portion.end_a
            for portion in found
        ):
            continue  # Already inside a portion found at this offset.
        remaining = chain
        while remaining:
            portion = _refine(pair, remaining)
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


def _coarse(x: Samples, rate: int) -> npt.NDArray[np.float64]:
    """Decimate a downmix for the coarse search, then take its first difference."""
    y = np.asarray(
        soxr.resample(x, rate, rate / DECIMATION, quality=DECIMATION_QUALITY),
        dtype=np.float64,
    )
    y[1:] -= FIRST_DIFFERENCE * y[:-1]
    return y


def _candidates(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], coarse_rate: float
) -> list[_Candidate]:
    """Find where each window of A may be in B, by normalized cross-correlation."""
    length = round(WINDOW_SECONDS * coarse_rate)
    hop = round(HOP_SECONDS * coarse_rate)
    positions = len(b) - length + 1
    # At a sample rate under 2 Hz, a window holds no frame of the decimated audio.
    if length < 1 or len(a) < length or positions < 1:
        return []
    starts = range(0, len(a) - length + 1, hop)
    energies = np.array([a[s : s + length] @ a[s : s + length] for s in starts])
    silent = SILENT_WINDOW_RATIO * energies.mean()
    # The energy of B under the window at each position, from a running sum. Where
    # B holds next to nothing, rounding errors in that sum could pass for a match.
    running = np.concatenate(([0.0], np.cumsum(np.square(b))))
    under = running[length:] - running[:-length]
    searched = under > _ROUNDING_GUARD * running[-1]
    scale = np.zeros(positions)
    scale[searched] = 1 / np.sqrt(under[searched])
    size = _fast_length(len(b))
    spectrum_b = np.fft.rfft(b, size)
    # At 16 Hz and below, 0.5 s rounds to no decimated frame: the chosen position is
    # still cleared, so that the next candidate lies elsewhere.
    separation = max(1, round(CANDIDATE_SEPARATION_SECONDS * coarse_rate))
    found = []
    for index, (start, energy) in enumerate(zip(starts, energies, strict=True)):
        if energy <= silent:
            continue  # A silent window gives no evidence.
        spectrum = np.fft.rfft(a[start : start + length], size)
        np.conjugate(spectrum, out=spectrum)
        spectrum *= spectrum_b
        scores = np.abs(np.fft.irfft(spectrum, size)[:positions])
        scores *= scale
        scores /= math.sqrt(energy)
        for _ in range(CANDIDATES_PER_WINDOW):
            position = int(np.argmax(scores))
            score = float(scores[position])
            if score < CANDIDATE_THRESHOLD:
                break
            found.append(
                _Candidate(
                    index,
                    start * DECIMATION,
                    (position - start) * DECIMATION,
                    score,
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
                    abs(candidates[other].offset - candidate.offset)
                    <= CHAINING_TOLERANCE_FRAMES
                ):
                    parent[root(index)] = root(other)
    chains: dict[int, list[_Candidate]] = {}
    for index, candidate in enumerate(candidates):
        chains.setdefault(root(index), []).append(candidate)
    return list(chains.values())


class _Pair:
    """Both downmixes at the common rate, and what refinement computes on them."""

    def __init__(self, a: Samples, b: Samples, rate: int) -> None:
        self.a = a
        self.b = b
        self.rate = rate
        self.window = round(WINDOW_SECONDS * rate / DECIMATION) * DECIMATION
        self.quiet = 10 ** (EVIDENCE_FLOOR_DBFS / 10)
        self.silent = 10 ** (SILENCE_AGAINST_SIGNAL_DBFS / 10)

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
        error = energy = 0.0
        for chunk in range(start, stop, _CHUNK_FRAMES):
            end = min(stop, chunk + _CHUNK_FRAMES)
            a = self.a[chunk:end]
            b = self.b[chunk + offset : end + offset]
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


def _refine(pair: _Pair, chain: list[_Candidate]) -> Portion | None:
    """Refine a chain into a portion at the common rate, if it holds one."""
    best: dict[int, _Candidate] = {}
    for node in chain:
        if node.window not in best or node.score > best[node.window].score:
            best[node.window] = node
    windows = [best[index] for index in sorted(best)]
    strongest = max(range(len(windows)), key=lambda index: windows[index].score)
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
    best, chosen = -1.0, None
    for offset in range(lowest, highest + 1):
        b = pair.b[start + offset : stop + offset]
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
    """Merge portions at nearly the same offset whose ranges of A overlap or touch.

    A merged portion takes the offset of the longer one.
    """
    merged = list(portions)
    changed = True
    while changed:
        changed = False
        for first in range(len(merged)):
            for second in range(first + 1, len(merged)):
                one, other = merged[first], merged[second]
                if (
                    abs(one.offset - other.offset) <= MERGE_TOLERANCE_FRAMES
                    and one.start_a <= other.end_a
                    and other.start_a <= one.end_a
                ):
                    longer = max(one, other, key=lambda portion: portion.frames)
                    low, high = pair.valid(longer.offset)
                    start = max(low, min(one.start_a, other.start_a))
                    end = min(high, max(one.end_a, other.end_a))
                    merged[first] = Portion(
                        start,
                        end - start,
                        longer.offset,
                        pair.residual_db(start, end, longer.offset),
                    )
                    del merged[second]
                    changed = True
                    break
            if changed:
                break
    return merged


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
