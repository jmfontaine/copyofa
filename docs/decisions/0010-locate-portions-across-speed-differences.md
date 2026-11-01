# Locate portions across speed differences

- **Date:** 2026-11-01
- **Status:** Accepted
- **Supersedes:** in [ADR 0006](0006-locate-matching-portions-between-tracks.md), the
  single offset of a portion where decisions 1, 2, 4, 5 and 8 assume one, and its fixed
  parameters (decision 7), which gain those below; its other decisions stand, as do
  [ADR 0003](0003-measure-track-comparisons-on-aligned-decoded-audio.md)'s, and
  [ADR 0009](0009-compare-editions-as-sequences-of-their-tracks.md)'s, whose decision 2
  now applies ADR 0006 as amended here
- **Related artifacts:**
  [Brief 0008: Compare Masters That Differ in Speed](../briefs/0008-compare-masters-that-differ-in-speed.md);
  Product Map capability
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
  and scenarios [S3](../product-map.md#s3-compare-two-tracks) and
  [S4](../product-map.md#s4-compare-two-editions)

## Context

A portion of ADR 0006 holds one offset: frame *n* of A lines up with frame *n* +
offset of B throughout. Audio played back or transferred at a slightly different speed
drifts against that offset, so the block test refutes the match after a few seconds and
the portion ends. ADR 0006 measured that a speed difference of 0.1 % gives no portion,
and ADR 0009's spike that the 2017 download of *The Downward Spiral* matches its CD
only in short portions in its drifting tracks. Both decisions name drift as a later
`alignment`.

A spike on the maintainer's Mac measured the drift and tried three designs, on the
acquired sets of ADR 0009's spike, the 2017 download, and an unrelated 70-minute
release:

- **The drift is a speed ratio per stretch of audio.** Seven of the download's 14
  tracks drift against the CD at 9.0 to 11.4 parts per million (ppm), the other seven
  within ±0.9 ppm. Within a track the offset follows a straight line to 0.4 to 1.5
  frames rms, at most 5.8 frames. The ratio is not one per edition: about 9.1 ppm in
  tracks 1 and 2, 9.8 in 5 and 6, 11.2 in 12 to 14, and the offset jumps between
  tracks, by more than 32 frames at 11 of 13 boundaries. ADR 0009 counted five drifting
  tracks; two more, 5 and 12, drift too but hold audio that differs.
- **Coverage of the CD by the download:**

  | Method | Five drifting tracks that match | Whole edition | Primary portions |
  | --- | --- | --- | --- |
  | ADR 0006 | 52.7 % | 59.8 % | 133 |
  | B stretched by a ratio fitted per portion | 65.3 % | 66.2 % | 93 |
  | An offset free to move one frame per block | 64.9 % | 66.0 % | 99 |
  | Any method keeping ADR 0006's block test, on each track's own line | 78.3 % | 70.7 % | — |

  The rest is audio that differs between the two masters: on its own line, a drifting
  track still holds blocks the block test refutes, scattered, which ADR 0006 does not
  bridge.
- **Larger speed differences:** one CD track stretched by soxr. ADR 0006 gave 24 short
  portions at 10 ppm and almost nothing from 100 ppm. A ratio fitted per portion found
  ±10, ±100 and +150 ppm whole, one portion over 99.8 % of the track at the ratio set,
  but not +200 ppm: ADR 0006's chaining tolerates 32 frames per 5 s window, 145 ppm.
  With a first estimate of the speed, it found every ratio tried, to the ppm: ±1,000
  ppm, ±1 % and ±41,667 ppm (the 4.2 % of PAL video), each one portion over 99.8 %. An
  offset free to move one frame per block was erratic from 100 ppm.
- **Nothing changed where speeds agree:** the other pressings, the 15-track edition and
  the disc read with errors gave, at a ratio of 0, ADR 0006's primary portions exactly.
  Alternates, on repeated sections, differed by one or two per comparison, some at
  fitted ratios of −3 to +3 ppm. The unrelated release gave no portion against the CD,
  nor did eight unrelated pairs of tracks.
- **Cost:** for two editions of about 65 min, the estimate took 41 s, the search as
  before, and the stretched refinement 113 s; 323 s in all, against 212 s without
  either, at a peak of 7.1 GB against 4.1 GB, in the spike's harness, which holds the
  downmixes but not the samples compare keeps for its measurements.

## Decision

Compare finds portions whose speed differs, each at its own constant ratio. The
`alignment` of the Report becomes `speed_tolerant_portions`.

1. **Speed estimate.** Before the coarse search, the speed of B against A is estimated
   in two levels. At each level, both downmixes are decimated with libsoxr at its `HQ`
   quality and filtered as ADR 0006's coarse search filters them, A is cut into
   5-second windows, and windows of A evenly spread among the non-silent ones (as ADR
   0006 defines them), or all of them when A has fewer, are each stretched by every
   ratio of the level with libsoxr at its `HQ` quality and correlated with all of B, as
   ADR 0006 correlates a window; the ratio with the highest sum of the windows' best
   scores is kept. The first level decimates by 128 and takes 8 windows and the ratios
   from −45,000 to +45,000 ppm in steps of 1,500 ppm; the second decimates by 16 and
   takes 12 windows and the ratios within 1,000 ppm of the first level's, in steps of
   200 ppm. The estimate is the second level's ratio when the mean, over its windows,
   of each window's best score at that ratio is at least 0.25, and 0 otherwise.
2. **Coarse search and chaining.** ADR 0006's, with A's decimated downmix stretched by
   the estimate with libsoxr at its `HQ` quality, and the candidates' offsets mapped
   back to A's frames. The chaining
   tolerance stays 32 frames, so a chain holds a ratio within about ±145 ppm of the
   estimate.
3. **Ratio per chain.** A line through the coarse offsets of the chain's candidates
   gives a first ratio; when it is at least 20 ppm from 0, B is first stretched by it.
   Then, for the windows within 12 windows of the chain's strongest one, each window's
   offset at the common rate, to a fraction of a frame, within 40 frames of its coarse
   offset, against B or the stretched B; from those scoring at least 0.5 of the best, a
   line that rejects any whose distance exceeds 4 frames or three standard deviations,
   from at least 4 windows, corrects the first ratio. With fewer windows the ratio is
   the first one, or 0 below 20 ppm. A ratio of 0.05 ppm or less from 0 is 0, and the
   chain is refined exactly as ADR 0006 refines it.
4. **Stretched refinement.** Otherwise B is stretched along the line by a windowed-sinc
   interpolator of 32 taps (Kaiser, β 9, cutoff 0.96 of the Nyquist frequency, 1,024
   phases), over the core and 40 s on either side, extended as growth needs it, and
   ADR 0006's refinement, growth, ends and acceptance run against the stretched B. The
   line is fitted again on the 5-second windows of the grown portion (score at least
   0.3, at least 3 windows, within 12 frames, rejecting any farther than 3 frames), and
   the refinement repeats until the stretched B lies within 0.3 frame of the line at
   both ends of the portion, at most 10 times.
5. **What a portion is.** A range of A, its range of B, its offset at its first frame of
   A, to 0.01 frame, and its speed ratio, to 0.01 ppm, B's frames per frame of A minus
   one: frame *n* of A lines up with frame *n* + offset + ratio·(*n* − start) of B. The
   two ranges differ in length when the ratio is not 0. A portion at a ratio of 0 is an
   ADR 0006 portion, with an integer offset.
6. **Merging and ranking.** Portions whose lines lie within 2 frames of each other
   where their ranges of A overlap or touch are merged, and the merged portion's
   residual is taken again over its range. Ranking is ADR 0006's.
7. **Measurements.** A portion at a ratio other than 0 is measured, as ADR 0003 and
   ADR 0006 measure a portion, against B stretched along its line by the same
   interpolator, per channel as on the downmix. An edition's segments (ADR 0009) take
   the portion's ratio and their own offset at their first frame.
8. **Parameters in the Report.** ADR 0006's, and: estimate decimation factors 128 and
   16, windows 8 and 12, range ±45,000 ppm, steps 1,500 and 200 ppm, second-level span
   1,000 ppm, adoption score 0.25; first-ratio stretch at 20 ppm; ratio windows 12 on
   each side, at least 4, search radius 40 frames, window score ratio 0.5, outlier
   distance 4 frames or 3 standard deviations, ratio snapped to 0 at 0.05 ppm;
   interpolator 32 taps, Kaiser β 9, cutoff 0.96, 1,024 phases; stretch margin 40 s;
   refit window score 0.3, at least 3 windows, radius 12 frames, outlier distance 3
   frames, convergence 0.3 frame, at most 10 passes. Details the implementation
   settles, such as how the stretch extends and the outlier distance of the first
   line, are recorded with it, as ADR 0006's decision 8 records its own.

## Rationale and alternatives

- **A constant ratio per portion,** because the measured drift is a straight line within
  a track, and a ratio is what a clock or a turntable changes: one number the collector
  can read, "B runs 9.8 ppm fast here". It recovers the ratio set on every synthetic
  case to the ppm.
- **Per portion, not per edition,** because the download's tracks drift at different
  ratios and its offset jumps between them: one ratio for the edition would fit none.
- **A first estimate of the speed,** because chaining fails beyond about 145 ppm, and
  widening it broke edition comparisons: with a tolerance for 500 ppm and the ratio
  fitted on the whole chain, coverage of the download fell to 49.9 %, and three tracks
  that matched whole fell to 60 %, 0 % and 16 %. The estimate lets chaining stay as it
  is. ±4.5 % holds the speed errors of turntables, tape transfers and the PAL speed-up.
- **An adoption score of 0.25,** between the mean window scores the spike measured:
  0.05 to 0.11 at the estimate on unrelated tracks, 0.41 when one 60-second excerpt at
  +1,000 ppm sat inside unrelated audio, and 0.80 or more on matching audio. It was not
  tuned further.
- **The ratio fitted near the strongest window,** because a line through a whole chain
  crosses track boundaries where the offset jumps, and gave a false ratio: 64.7 %
  coverage instead of 66.2 %.
- **Snapping to 0 at 0.05 ppm,** so that audio at the same speed gives ADR 0006's
  portions, offsets and residuals.
- **Measurements on stretched B,** because they are taken on aligned audio, as ADR 0003
  decides; stretching is the alignment a ratio needs, as resampling to the common rate
  already is.

Alternatives considered:

- **An offset that follows the audio, one frame per block.** It covered as much of the
  download (66.0 %) in a tenth of the time, but its core must hold one offset for up to
  20 s, so it was erratic from 100 ppm, its residuals were higher (−20.6 dB against
  −41.3 dB at 10 ppm), and it gives a path of offsets instead of a ratio.
- **A grid of ratios, each searched in full.** It found ±1 %, but costs one coarse
  search per ratio: 50 s per pair of 4-minute tracks, too slow for editions.
- **Bridging the refuting blocks a drifting track leaves.** It would raise coverage
  past the 78.3 % bound, but ADR 0006 rejects bridging because it hides real gaps, and
  the gaps are not about speed.
- **One ratio per edition.** Rejected by the measurements above.

## Consequences

- Comparison Reports get a new format version: a portion's ratio, its fractional
  offset, ranges of A and B that may differ in length, the new `alignment` and the
  added parameters. Reports of earlier versions keep their meaning and their schemas.
- Audio at the same speed gives ADR 0006's primary portions, at a ratio of 0;
  alternates on repeated sections may change in number and carry small ratios.
- A speed difference up to ±4.5 % is found when the estimate's windows match. The
  estimate is one per comparison, so a portion more than about 145 ppm from it is
  missed whatever its length, such as a track of an edition whose speed differs from
  that of most of the others by more. A portion shorter than 20 s has fewer than 4
  windows and keeps the first ratio, so it lasts only as far as its remaining drift
  passes the block test. A short excerpt at a different speed inside unrelated audio
  may not raise the estimate.
- Pitch is not corrected: stretching changes speed and pitch together, as a clock or a
  turntable does. A tempo change that keeps the pitch (a time-stretch) gives no
  portion, nor does a speed that varies within a portion beyond what the block test
  absorbs; a step in offset, such as an edit, is a portion of its own.
- Coverage stays bounded by the audio: different masters still leave unmatched audio
  the block test refutes.
- The estimate adds about 40 s to an edition comparison, and the stretched refinement
  about 2 minutes when many portions drift. Memory must not grow past what an edition
  comparison needs today; the brief bounds it.
- Revisit this decision when a release needs tempo or varying-speed changes, or a
  different bound on the ratio.
