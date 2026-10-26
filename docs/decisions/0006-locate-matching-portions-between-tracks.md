# Locate matching portions between tracks

- **Date:** 2026-10-25
- **Status:** Accepted
- **Supersedes:** decisions 2 (Alignment) and 3 (Overlap) of
  [ADR 0003](0003-measure-track-comparisons-on-aligned-decoded-audio.md); its other
  decisions stand
- **Related artifacts:**
  [Brief 0005: Locate Matching Portions Between Tracks](../briefs/0005-locate-matching-portions.md);
  Product Map capability
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
  and scenario [S3](../product-map.md#s3-compare-two-tracks)

## Context

ADR 0003 aligns two tracks with one global offset and measures them over their
overlap. That handles leading silence and encoder delay, but not edits: a cut, an
inserted or repeated section, or a different intro moves part of the audio, so one
offset lines up only part of it and the measurements mix the aligned part with the
rest. Collectors and discography researchers need to know which portions of one track
appear in the other, where, and how alike they are, and which audio appears in only
one.

A spike tested a windowed method on content known to be identical, so that every
expected answer was known:

- **Edits made to a CD track with an answer key** (cut, insertion from another track,
  repetition, added silence, fades, a crossfade, a shift, a 0.3 s replacement, a
  dropout, inverted polarity), each also resampled to 48 and 96 kHz, at 24 bits, with a
  gain change, and as 128 and 320 kbps MP3: 240 runs, none of 426 expected portions
  missed, every offset exact, boundaries within 0 to 20 frames on lossless inputs.
- **The same audio cut differently** (each CD track inside its disc image, tracks
  joined into one stream, a 48 kHz download against its own tracks): 56 runs, all
  exact.
- **Format siblings:** *The Downward Spiral* (2017) as FLAC and WAV have equal Audio
  Digests on all 14 tracks; FLAC against MP3, and *Broken* WAV against MP3, gave one
  portion at offset 0 for each of 22 pairs, with no false edit.
- **Unrelated tracks:** 35 pairs gave no portion.

On the same edited files, ADR 0003's global offset gave correlations of 0.67 to 0.93
for every edit that moves audio, and hid a 0.3 s replacement in a −26 dB overall
residual. A pair of 3½-minute tracks took about 1 s.

The spike also showed the method's limits: a portion shorter than about half a window
is not found, a speed or drift difference of even 0.1 % gives no portion, and in music
that repeats a section, one range of a track matches several places in the other.

## Decision

Compare keeps ADR 0003's decoding, common rate and resampler, downmix, measurements,
identical-audio shortcut and undefined values. It replaces the global offset with
portions, found on the mono downmixes at the common rate. The `alignment` of the
Report becomes `windowed_portions`.

1. **Coarse search.** Both downmixes are decimated by 16 with libsoxr at its `HQ`
   quality and filtered with a first difference of coefficient 0.5. A is cut into
   5-second windows, without overlap. For each window that is not silent (energy at
   least 10⁻⁴ of the mean window energy), the magnitude of its normalized
   cross-correlation with every position of B that holds the whole window gives up to
   three candidates of at least 0.4, 0.5 s apart. Candidates of neighboring windows,
   one window may be skipped, whose offsets differ by at most 32 frames are chained.
2. **Refinement at the common rate.** For each chain, strongest first, the offset is
   the integer within 32 frames of the coarse one that maximizes |Σ*ab*| / ‖*b*‖ over
   the chain's core (its strongest window and the neighbors at 0.85 of its score or
   more, up to 20 s). The portion grows outward in blocks of 2048 frames while each
   block matches: after its own least-squares gain, the residual is at most 0.2 of A's
   energy in the block (−7 dB). A block where A is digitally silent or below −80 dBFS
   neither confirms nor refutes the match; a block where A is silent and B is above
   −60 dBFS refutes it. Each end is then placed to the frame by the maximum-scoring
   prefix or suffix of the frames around it. Windows of the chain left outside the
   portion are refined again, so a portion after a hole is kept. Short gaps are never
   bridged.
3. **Acceptance.** A portion is kept when it is at least 1 s long and its residual
   after the per-block gains, weighted by energy, is at most −10 dB.
4. **Ranking.** Portions at the same offset that overlap or touch are merged. A
   portion is an alternate, ranked after the others covering its range of A, when
   portions at least 3 dB better cover 90 % or more of its range of A; residuals below
   −60 dB count as equal. Every portion is reported, primaries first.
5. **Measurements.** Each portion is measured as ADR 0003 measures an overlap
   (correlation, gain and residual on the downmix and for each channel, and the
   residual of each one-second window), with its ranges in A and in B, its offset, and
   its residual after the per-block gains.
6. **Unmatched audio.** The ranges of A and of B that no primary portion covers are
   reported, each with its level in dBFS and whether it is digitally silent. When no
   portion is found, the Report says so instead of giving an offset.
7. **Parameters in the Report.** Every value above is a fixed method parameter, stated
   in the Report's `method`, since the result moves with them.

## Rationale and alternatives

- **Portions, not one offset,** because an edit moves only part of the audio, and the
  collector needs to see which part. When the tracks differ only by a shift, there is
  one portion, with the offset ADR 0003 would give.
- **Normalized cross-correlation per window** finds a window wherever it is in B,
  whatever B's level. On unrelated tracks the highest window score was 0.24, against
  0.9 or more for every matching window, so the 0.4 threshold separates them.
- **Decimation by 16 with a gentle first difference:** at a decimation of 8 with a
  strong pre-emphasis, an exactly matching window scored as low as 0.59 when its true
  offset fell between two coarse samples. Decimating by 16 keeps the matching windows
  at 0.9 or more and halves the cost.
- **A gain per block,** because fades and gain changes otherwise end a portion where
  the audio is still the same: one global gain left −17 dB of residual on a fade that
  the per-block gain measured at −52 dB.
- **An evidence floor of −80 dBFS,** because MP3 does not reproduce a CD's dither-level
  noise: without it, every MP3 portion started 0.47 s late for that reason alone.
- **No bridging,** so a 0.3 s replacement or dropout shows as the gap it is. Bridging
  0.25 s would have merged ten portions of one track into three and hidden seven gaps.
- **5-second windows:** they found every edit the spike made, at half the
  coarse-search cost of 2-second windows; 10-second windows miss portions shorter than
  about 5 s.
- **All matches reported, ranked,** because a repeated section really does match
  several places. Keeping only the best one would hide that, and two exact repeats tie.
- **Fixed parameters,** because thresholds decide what a portion is: on one track of
  two editions, the unmatched time was 11 s, 36 s or 62 s for three threshold sets.
  One fixed method keeps Reports comparable; the Report states it.

Alternatives considered:

- **Keeping the global offset next to the portions.** Rejected: its measurements mix
  aligned and unaligned audio, and the longest portion gives the same offset when one
  exists.
- **Audio fingerprints, such as Chromaprint.** Rejected for the reason ADR 0003 gives:
  a match score is an interpretation, not a measurement.
- **Dynamic time warping, or an offset that drifts.** Not adopted now: it is what speed
  and drift differences need, and it is a later `alignment` value if a release needs
  them.
- **User-chosen thresholds.** Rejected: Reports made with different thresholds could
  not be compared.

## Consequences

- Comparison Reports get a new format version, with portions and unmatched ranges in
  place of the offset and overlap. Reports of earlier versions keep their meaning and
  their schemas.
- A portion shorter than about 2.5 s may be missed, and a speed or drift difference
  gives no portion; the Report states both limits.
- A boundary inside audio below −80 dBFS is placed at the nearest frame with evidence,
  and the rest is reported as unmatched; lossy encoding moves boundaries only there.
- The coarse search costs two FFTs of B's length per window of A, so its time grows
  with the product of the two lengths: about 1 s for two 3½-minute tracks, 28 s and
  2.7 GB for two 27-minute releases. Memory and speed are not optimized yet.
- Revisit this decision when a release needs speed or drift differences, compares
  whole editions, or needs the coarse search to scale to long recordings.
