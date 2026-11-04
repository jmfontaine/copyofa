# Brief: Bound Compare's Memory and Time

## Goal and context

A collector who compares two editions longer than a CD, such as two two-disc editions,
on a Mac with 16 GB of memory gets the comparison instead of a Mac that runs out of
memory, and two CDs compare in a fraction of today's memory, no slower and with the
same Report.

- **Milestone:** [v0.11.0](https://github.com/jmfontaine/copyofa/milestone/11)
- **Product Map capability:**
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
- **Decisions kept:**
  [ADR 0006](../decisions/0006-locate-matching-portions-between-tracks.md),
  [ADR 0009](../decisions/0009-compare-editions-as-sequences-of-their-tracks.md) and
  [ADR 0010](../decisions/0010-locate-portions-across-speed-differences.md)
- **Parking Lot:**
  [#76](https://github.com/jmfontaine/copyofa/discussions/76)

An edition comparison holds both editions at the common rate twice for its whole run:
the decoded samples as float32, for the measurements, and the joined downmix as
float64, for the locator, 16 bytes per stereo frame per edition: 2.75 GB per CD of
65 min, held before the search starts. In v0.10.0's AC10, comparisons of two CDs peaked
at 8.4 to 10.8 GB. Measured again with v0.10.0 on the maintainer's Mac, with macOS's
peak memory footprint:

| Pair | Length of each edition | Peak |
| --- | --- | --- |
| Two CDs (the pressings of ADR 0009's spike) | 65 min, 44.1 kHz | 8.27 GB |
| *Tron: Ares; Divergence* against itself | 145 min, 48 kHz, two discs | 16.24 GB |
| *Deviations*, the 96 kHz WAV download against the MP3 download | 154 min, compared at 48 kHz | not finished: stopped after the system's swap grew by 6.3 GB |

The search itself needs much less. The locator takes both joined downmixes at the
common rate, decimates them by 128 and 16 for the speed estimate and by 16 for the
coarse search, and reads the full-rate downmixes again only around each portion, to
refine and measure it; at a ratio other than 0, it stretches B over the whole region a
portion needs, as one float64 array. Each segment is measured within one track of each
edition. Time grows with the product of the editions' lengths: the two-disc edition
against itself took 26 min on battery, in Low Power Mode, where the two CDs took
7.8 min.

## Primary scenario

Refines [S4](../product-map.md#s4-compare-two-editions):

1. A collector has imported the WAV and the MP3 downloads of a two-disc edition into
   `~/Archive/deviations-wav` and `~/Archive/deviations-mp3`, on a Mac with 16 GB of
   memory.
2. `copyofa compare ~/Archive/deviations-wav ~/Archive/deviations-mp3` compares them,
   at a peak of 8 GB or less.
3. The text result and `--json`'s comparison Report of format version 7 are those a
   machine with enough memory would get from v0.10.0, within the tolerance below.

The same holds for two CDs, at 4 GB or less.

## In scope

- Edition comparisons that hold only the audio a step needs, not both editions at full
  rate for the whole run: the locator reads the full-rate downmix track by track, to
  decimate it and around each portion, and stretches B in pieces rather than over a
  portion's whole region, the debt brief 0008's delivery notes handed to this release.
- The same Reports: format version 7, its schema, compare's text result and view,
  unchanged.
- A timed spike on searching each window of A only near where its neighbors were found,
  measured and reported, not shipped.
- The format document's known limit, the README and AGENTS.md's Architecture section,
  updated to the new figures and to how compare reads audio.

## Out of scope

- Changing which portions compare finds, their offsets or ratios: ADR 0006's, 0009's and
  0010's method stays, and the Report keeps format version 7. Shipping a localized
  search is the maintainer's decision after the spike, with a superseding ADR and a new
  format version, in a later release unless the maintainer amends this brief.
- Making compare faster than v0.10.0.
- Lowering a track comparison's peak below v0.10.0's: a track comparison holds one
  track of each side, which this release does not bound further.
- Editions held in several Evidence Sets, and changing inspect, verify, import, export,
  acquire, validate or view.

## Requirements

### Memory

- **Editions.** An edition comparison does not hold either edition's samples or downmix
  at the common rate for the whole run. It reads a track's audio when a step needs it,
  from a source that cannot have changed since compare checked the Evidence Set against
  its Integrity Baseline: either the file read again and checked against its File
  Digest as it is read, or a temporary copy of the decoded audio that compare removes
  when it ends, on success, failure or Ctrl-C.
- **Bounds.** Each pair of AC6 peaks, as macOS's peak memory footprint reports it, at
  4 GB or less for A against each edition of about a CD's length, 8 GB or less for the
  two-disc pairs, and no more than v0.10.0 plus 0.3 GB, the noise of the measurement,
  for a track comparison.
- **Growth.** What an edition comparison holds beyond the decimated downmixes and the
  search over them grows with its longest track, not with the editions' length or a
  portion's, at any speed ratio.

### Same results

Compared with v0.10.0's Report for the same pair, every field is equal except
`copyofa_version`, `compared_at` and the measurements' values. The portions, segments,
their frames, offsets, speed ratios and how each was set, the correspondences,
unmatched audio, coverage, method and limitations are equal. Each correlation is within
1e-6, and each value in dB within 0.001 dB, of v0.10.0's. The text result is the same.

### Time

Each comparison of AC6 takes no more than 1.1 times v0.10.0's time for the same pair,
or 2 s more, whichever is longer, both timed back to back on the same Mac, on AC power
with Low Power Mode off. 1.1 leaves room for the noise of the measurement and for
reading audio again; 2 s, for the noise of a track comparison of about 10 s. A pair
that v0.10.0 finishes only by swapping, as *Deviations* may, has no time bound: its
time is recorded.

### Spike: a localized search

Measure, in a probe outside the repository, a coarse search that, once a chain is
established, searches each window of A only near where its neighbors were found, and
the full search only for the windows that no neighbor places. Run it on AC6's edition
pairs and report on its issue, for each pair: its time and v0.10.0's for the search
alone, and whether the primary portions, their offsets and ratios are the same.

## Design decisions

- **How, not what.** As Parking Lot #76 states, a change to how the same result is
  computed needs no ADR and no format version; a change to which portions are found
  does. Everything committed here is the first kind.
- **Bounds measured with macOS's peak memory footprint** (`/usr/bin/time -l`), as
  v0.10.0's AC10 did, so this release's figures compare with the format document's
  table.
- **Float32 or float64 is the implementation's choice,** within the tolerance of Same
  results.
- **The two-disc pairs are compared at 8 GB, not 16:** half a 16 GB Mac leaves room for
  macOS and the collector's other applications.

## Blocking questions

None.

## Stop rule

- Stop and report if the bounds above cannot be met without changing which portions
  compare finds, or if a pair of AC6 cannot meet the time bound.
- The spike stops at its report. No ADR, no change to `src/` and no format version
  follow from it before the maintainer decides.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise.

- **AC1 — Same results.** Every comparison the test suite makes, of tracks and of
  editions, imported and acquired, gives v0.10.0's Report under the rule of Same
  results. A probe outside the repository captures v0.10.0's Reports once and compares
  them; the pull request records the result. The tests that compare stored Reports
  still pass.
- **AC2 — Memory grows with the longest track.** In a test, the peak of NumPy's
  allocations traced by `tracemalloc` during an edition comparison grows by at most
  40 % when each edition doubles from two to four tracks of the same length; the same
  holds with B at +1 %, where one portion spans every track. The pull request records
  that the same test fails on v0.10.0.
- **AC3 — Audio read again is the audio checked.** If compare reads a file again, a
  file changed after the integrity check fails the comparison, with exit 1 and a
  message naming the file. If compare writes temporary files, none remains after a
  comparison that succeeds, one that fails, and one canceled with Ctrl-C (exit 130).
- **AC4 — Schema and view unchanged.** Every Report the test suite produces validates
  against the version 7 schema, and view renders it as before.
- **AC5 — Documented.** `docs/formats/comparison-report.md`'s known limit gives
  AC6's figures for this release and says what memory grows with; the README's
  sentence on compare's memory says the same; AGENTS.md's Architecture section says
  how compare reads a track's audio.
- **AC6 — Real editions (by hand, once).** On the maintainer's Mac, on AC power with
  Low Power Mode off, an agent runs each pair on v0.10.0, then on the new code, back
  to back: A, the 14-track pressing of ADR 0009's spike, against the other pressing,
  the 15-track edition, the 2017 download, the unrelated release, and track 13
  stretched by +1 % and by +41,667 ppm against that track; *Tron: Ares; Divergence*
  against itself; and *Deviations*, the WAV download against the MP3. v0.10.0 runs
  each pair to its end, swapping if it must. Each pair meets the memory and time
  bounds above and gives v0.10.0's Report under the rule of Same results. The pull
  request records the table.
- **AC7 — Spike reported.** The spike's issue records, for each edition pair of AC6,
  the localized search's time and v0.10.0's, and whether the primary portions, offsets
  and ratios are the same, with the probe's method stated.

## Manifesto alignment

- **Practical defaults and feedback:** comparing editions longer than a CD is what
  collectors of reissues and box sets do; a comparison that exhausts memory gives them
  nothing.
- **Reproducibility:** the method and its Reports stay as they are, so this release's
  Reports compare with v0.10.0's.

## Appetite and scope cuts

Appetite: about a day.

If the work outgrows it, cut in this order, keeping the same Reports and the time bound:

1. The spike.
2. Reading the downmix when needed: the locator keeps both editions' joined downmixes
   for the whole run, and only the samples are read when needed. Each edition pair of
   AC6 then peaks at least the float32 samples of both editions below v0.10.0, within
   0.3 GB: 2.75 GB less for two CDs of 65 min, and 6.7 GB less for *Tron: Ares;
   Divergence* against itself, 9.6 GB from 16.24 GB, so that pair still finishes on a
   16 GB Mac. AC2 then covers the samples only. This brief is amended in a
   documentation pull request merged before the cut.

## What needs the maintainer

1. This brief, before implementation starts.
2. The spike's result: whether a localized search becomes a decision, and when.
3. The Mac on AC power with Low Power Mode off while AC6 runs; an agent runs it, and the
   maintainer reviews its results on the pull request.
4. Merges and the release.

The two-disc sets of AC6 are already in the maintainer's vault, imported for the
measurements above: `TRON-ARES`, `DEVIATIONS-WAV` and `DEVIATIONS-MP3`.
