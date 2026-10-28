# Compare editions as sequences of their tracks

- **Date:** 2026-10-27
- **Status:** Accepted
- **Related artifacts:**
  [Brief 0007: Compare Editions](../briefs/0007-compare-editions.md);
  [ADR 0006](0006-locate-matching-portions-between-tracks.md), whose method this
  decision applies unchanged; Product Map capability
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
  and scenario [S4](../product-map.md#s4-compare-two-editions)

## Context

Compare measures how two tracks relate (ADRs 0003 and 0006). A collector who owns two
editions of a release wants that for the whole release, and the tracks of two
editions do not line up one to one. Mastering, pressing and the placement of track
indexes move the boundaries; a bonus track is inserted; a track's intro differs; a
track is split in two or a hidden track is appended. ADR 0006 asks to revisit its
method when a release compares whole editions.

A spike on the maintainer's Mac ran ADR 0006's locator, unchanged, on four acquired
sets of *The Downward Spiral* CD and a 24-bit, 96 kHz download of its 2017 edition:

- **Two CD pressings of the same master, with track boundaries placed differently:**
  with each pressing joined into one sequence of its 14 tracks, one primary portion
  covered 3,907.5 s of 3,909.0 s, across every track, at an offset of −37,634 frames
  (0.85 s). Located track by track instead, 11 of the 14 tracks matched exactly, most
  of them partly in the previous track of the other pressing.
- **A 15-track edition, with a bonus track inserted as track 10:** two primary
  portions, before and after the bonus track, at offsets 294.3 s apart, the bonus
  track lasting 294.8 s. The first 19 s of *A Warm Place* matched nowhere in the other
  edition; compare on that pair of tracks alone found the same.
- **The same disc read twice, once with C2 errors left:** one portion over the whole
  disc, at a residual of −96.6 dB.
- **The 2017 download, another master:** 133 primary portions covering 60 % of the CD,
  each in the track of the same title. Within each track, the offset drifts by about
  100 frames over 4 minutes (about 9 parts per million), more than the 32 frames a
  portion tolerates, so the portions are short.
- **An unrelated release:** no portion.

Each run took 117 s to 172 s to locate the portions of two editions of about 65 min,
plus 13 s to 19 s to decode them, at a peak of 4.9 GB to 5.6 GB. Locating each track of
one edition in the whole of the other took the same time and memory as joining both.

## Decision

1. **An edition is an Audio Sequence of its tracks.** Each input is an Evidence Set:
   the tracks of an acquired set in the order of its Acquisition Record, or the audio
   files of an imported set in the order of their paths. The edition's sequence is its
   tracks joined in that order at the common rate, without gap.
2. **Portions are located on the two sequences** with ADR 0006's method and
   parameters, unchanged, so a portion that crosses a track boundary is found whole,
   and a portion means in an edition comparison what it means in a track comparison.
3. **Findings are reported against the tracks.** Each portion is split into segments
   at the track boundaries of both editions; each segment is measured as ADR 0006
   measures a portion, and names its track in each edition. Unmatched audio is
   reported per track. Track correspondences, which tracks of B hold how much of each
   track of A, are derived from the primary segments.
4. **A new comparison Report format version** holds both kinds of comparison, and
   states which one it is, as ADR 0004 requires for any change to a Report's fields.

## Rationale and alternatives

- **Joined sequences** because a moved boundary or a bonus track is where editions
  differ, and only a search that ignores the boundaries finds a portion across them. A
  track of the other edition is a range of a sequence, as a track of an acquired set is
  a range of its disc image.
- **ADR 0006's method unchanged** because it found every relationship of the spike
  that was not a speed difference, and a changed method would make edition portions
  and track portions mean different things.
- **Segments at both editions' boundaries** because the collector reasons about tracks:
  "track 2 of A is in tracks 1 and 2 of B" is the finding the Product Map's S4 asks for,
  and a single portion over a whole disc says nothing about any one track.

Alternatives considered:

- **Every track of A against every track of B.** Rejected: audio that moves less than a
  window across a boundary is lost, a track shorter than 5 s is never found, and a
  portion across tracks is reported in pieces. It costs as much as joining.
- **Each track of A in the whole of B.** Rejected: it finds the same portions, split at
  A's boundaries, at the same cost, and still misses a track of A shorter than 5 s.
- **Matching tracks by Audio Digest first.** Rejected as the method: any shift of a
  boundary changes both digests. Equal digests are still reported.
- **Tolerating drift.** Not adopted now: different masters would then be covered by
  longer portions, but it changes what a portion is. It is a later `alignment` value,
  as ADR 0006 says, if a release needs it.

## Consequences

- Two editions of the same master are described per track, including where their
  boundaries differ and what one edition holds that the other does not.
- Different masters whose speed differs by a few parts per million give many short
  portions and partial coverage; the Report states it, and the correspondences still
  name the matching tracks.
- Time grows with the product of the two editions' lengths, about 2.5 minutes for two
  CDs of 65 min on the maintainer's Mac, and memory with their sum, about 5 GB for the
  search alone. Editions much longer than a CD may not fit in memory; that limit is
  documented, not removed.
- An edition held in several Evidence Sets, such as a set per disc, cannot be compared
  as one.
- Revisit this decision when a release tolerates speed differences, compares editions
  held in several sets, or needs to scale to editions much longer than a CD.
