# Brief: Compare Editions

## Goal and context

A collector who owns two editions of a release learns how their audio relates, track by
track, in one comparison: which tracks of one edition hold which audio of the other,
where track boundaries differ, what only one edition holds, and how alike the matching
audio is.

- **Milestone:** [v0.9.0](https://github.com/jmfontaine/copyofa/milestone/9)
- **Product Map capabilities:**
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
  and
  [Share and Evaluate Findings](../product-map.md#share-and-evaluate-findings)
- **Decision:**
  [ADR 0009: Compare editions as sequences of their tracks](../decisions/0009-compare-editions-as-sequences-of-their-tracks.md)

Compare measures two tracks (ADRs 0003 and 0006). Comparing two editions today takes
one run per pair of tracks, chosen by the collector, and misses audio that crosses a
track boundary. ADR 0009 records the spike on the maintainer's sets of *The Downward
Spiral*: located on whole editions, ADR 0006's method finds moved boundaries, an
inserted bonus track and a changed intro, and two CDs of about 65 min take about 2.5
minutes.

## Primary scenario

Refines [S4](../product-map.md#s4-compare-two-editions):

1. A collector has acquired a CD into `~/Archive/tds-cd` and imported a download of
   another edition into `~/Archive/tds-2017`.
2. `copyofa compare ~/Archive/tds-cd ~/Archive/tds-2017` compares the two editions:
   every track of the CD with every audio file of the download, in order.
3. The text result gives how much of each edition was found in the other, a line per
   track of A naming the tracks of B that hold its audio and how much, and the audio
   only one edition holds, per track.
4. `--json` prints a comparison Report of format version 6 whose measurements give the
   portions, each split into segments at both editions' track boundaries and measured,
   the track correspondences, the unmatched audio per track and the coverage.
5. `copyofa view` renders it as one page another collector can read without the audio.

## In scope

- Compare of two Evidence Sets given by their roots, without `--track-a` or
  `--track-b`: an edition comparison (ADR 0009).
- Comparison Report format version 6, with `scope`, `tracks` or `editions`; its schema;
  track comparisons print version 6 too, otherwise unchanged from version 5.
- Compare's text result for an edition comparison.
- View renders version 6 of both scopes.

## Out of scope

- Changing ADR 0006's method or parameters, including tolerating speed or drift
  differences between masters.
- An edition held in several Evidence Sets, such as one set per disc, or part of a set:
  choosing tracks or files, excluding a bonus track.
- Comparing a track with an edition.
- Interpreting the findings: naming a relationship ("same master", "remaster", "bonus
  track"), or a score for the editions.
- Reducing the memory or time of the search (Parking Lot: "Bound compare's memory on
  long tracks").
- Changing inspect, verify, import, export or validate, apart from validate accepting
  version 6.

## Requirements

### Inputs

- **Choosing the comparison.** Two inputs that are both Evidence Set roots, without
  `--track-a` or `--track-b`, are an edition comparison. Two tracks are compared as
  today. Any other combination, such as a set root and a file, or one track option
  without the other while both inputs are set roots, exits 2 with a message saying
  compare takes two tracks or two editions. A root that is not an Evidence Set exits 2,
  as today.
- **An acquired set's edition** is its tracks in the order of its Acquisition Record,
  each checked and decoded as compare checks a track input today, with its error
  ranges.
- **An imported set's edition** is its files that inspect interprets as audio, in the
  order of their paths from the set's root, compared by Unicode code point. Each is
  checked and decoded as compare checks a file input today. Files inspect does not
  interpret as audio, such as a cover image, are excluded and listed with their
  outcome and reason.
- **Nothing measured.** When a track of either edition is not `interpreted`, or an
  edition has no track, the Report has no `measurements`, gives the reason, and compare
  exits 1, as it does today when a track input is not `interpreted`.

### Comparison

As ADR 0009 decides:

- **Common rate** is the lowest sample rate of all tracks of both editions. Every track
  at a higher rate is resampled to it as compare resamples a track today.
- **Sequences.** Each edition's tracks, mixed down, are joined in order without gap,
  and portions are located on the two sequences with ADR 0006's method and parameters.
  No search is skipped for equal Audio Digests.
- **Segments.** Each portion is split at every track boundary of either edition that
  falls inside it. Each segment is measured as compare measures a portion today:
  correlation, gain and residual on the downmix, and for each channel when its two
  tracks have the same channel count, with the residual of each one-second window. The
  block-gain residual stays per portion.
- **Correspondences.** For each pair of a track of A and a track of B that share
  primary segments: the frames they share, the share of each track that is, and
  `identical_audio` when both tracks have the same Audio Digest.
- **Unmatched audio** is reported per track, as ranges of that track that no primary
  portion covers, with whether each is digitally silent and otherwise its level, as
  today.
- **Coverage.** For each edition, the frames of its sequence that primary portions
  cover, and its total frames.

### Comparison Report format version 6

Version 5 with `scope`. A track comparison is version 5 with `format_version` 6 and
`scope` `tracks`. An edition comparison has `scope` `editions` and:

- `inputs.a` and `inputs.b`: `evidence_set` (left out by `--omit-locations`, as
  today), `integrity_baseline`, `tracks`, one entry per track of the edition in order,
  each with its `position` from 1 and the fields of a version 5 track input other than
  `evidence_set` and `integrity_baseline`; and `excluded`, the files of an imported set
  left out of its edition, each with `path`, `outcome` and `reason`, empty for an
  acquired set.
- `measurements`: `sequences`, the start frame and frames of each track in its
  edition's sequence at the common rate; `portions`, each with its rank, ranges in the
  two sequences, offset, block-gain residual and `segments`, each naming the position
  of its track and its range in that track for each edition, with its measurements;
  `correspondences`; `unmatched`, per edition, each range naming its track's position;
  `coverage`; and `absent`, as version 5 gives it.
- `limitations`: version 5's, and that an edition comparison treats each edition as
  its tracks in order, that portions across a speed difference are short and leave
  coverage partial, and that matching tracks do not establish that the editions are
  equivalent.

Exact field names and the schema are settled in implementation and documented in
`docs/formats/comparison-report.md`.

### Text result

An edition comparison prints, after the progress of each track on stderr:

- each edition: its set, its number of tracks and its duration;
- the common rate;
- the coverage of each edition, as time found and percentage;
- one line per track of A: the time of it found in B, of its duration, and the tracks
  of B holding it, with the time in each; tracks are named by number for an acquired
  set and by path for an imported one;
- one line per unmatched range, as today, naming its edition and track.

### View

View renders comparison Report version 6: a track comparison with version 5's layout,
plus its `scope`; an edition comparison with its own layout, giving the inputs and
their tracks, the coverage, the correspondences, the unmatched ranges per track, and
every portion with its segments and their measurements, under the same rules as
today's page.

## Design decisions

- **Editions as sequences, ADR 0006 unchanged:** decided by ADR 0009.
- **Set roots without track options** mean editions, since a set root alone is refused
  today; no new option or command.
- **One format version for both scopes,** because compare prints one current version,
  and a consumer reads `scope` before anything else.
- **Path order for imported files,** because downloads number their files, and the
  order of the manifest is the order of import, not of the release.
- **No digest shortcut,** because equal tracks inside different editions still need
  their place in each sequence; equal digests are reported per correspondence.

## Known limit

Time grows with the product of the editions' lengths, and memory with their sum: the
spike's search over two CDs of about 65 min took about 2.5 minutes at a peak of 5.6 GB,
before the per-channel measurements. Editions much longer than a CD, such as a box set
imported as one set, may exhaust memory. The comparison Report document states it.

## Blocking questions

None.

## Stop rule

Stop and report if compare on the maintainer's two CD pressings (AC10) does not give the
spike's single primary portion at −37,634 frames, or if any by-hand comparison of AC10
needs more than 12 GB.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Synthetic
editions are acquired sets made with the stand-in `redumper` and imported sets of small
generated files.

- **AC1 — Moved boundaries.** Two acquired editions of the same audio whose track
  boundaries differ give a version 6 Report with `scope` `editions`: one primary
  portion, segments at the boundaries of both editions, correspondences pairing each
  track with its neighbors as the boundaries place them, nothing unmatched but the
  audio outside the shared range, full coverage within it, and exit 0.
- **AC2 — Inserted and changed audio.** Against AC1's edition A, an edition with a
  track inserted and the start of a later track replaced gives two primary portions;
  the inserted track and the replaced start are unmatched in that edition's tracks, the
  original start is unmatched in A's, and the correspondences give each track's share.
- **AC3 — Imported edition.** An imported set of 48 kHz files, with a cover image,
  against an acquired edition: the files form the edition in path order, the image is
  in `excluded`, the common rate is 44,100 Hz, and correspondences pair the tracks of
  the same audio.
- **AC4 — Refusals and failures.** A set root against a file, and a set root against a
  set root with only `--track-a`, exit 2 with the message. A track that is not
  `interpreted` in either edition, and an edition with no track, give a Report without
  `measurements`, with the reason, and exit 1.
- **AC5 — Track comparisons.** A track comparison prints version 6 with `scope`
  `tracks`, and otherwise the fields and values version 5 gave.
- **AC6 — Text result.** AC2's comparison prints the coverage, one line per track of A
  with the tracks of B holding it, and the unmatched ranges by edition and track.
- **AC7 — Schema and view.** The version 6 schema ships in the package; validate
  accepts both scopes; every Report the test suite produces validates. View renders
  version 6 of both scopes, the edition layout with the coverage, correspondences,
  segments and unmatched ranges, and with every text escaped.
- **AC8 — Locations.** `--omit-locations` leaves out both editions' `evidence_set`,
  listed in `omitted`.
- **AC9 — Documented.** `docs/formats/comparison-report.md` documents version 6 of both
  scopes, how editions are formed and compared, the known limit, and version 5 among
  the earlier versions; the README says compare compares editions; AGENTS.md's
  Architecture section gives edition comparison, ADR 0009 and view's versions 1 to 6.
- **AC10 — Real editions (by hand, once).** On the maintainer's Mac, from the sets of
  ADR 0009's spike: the two CD pressings give one primary portion at −37,634 frames;
  the 15-track edition gives two primary portions with its bonus track unmatched; the
  CD against the 2017 download, imported, gives correspondences between the tracks of
  the same title. Each comparison takes under 5 minutes and under 10 GB at its peak, and
  its view opens in a browser.

## Manifesto alignment

- **Discography researchers** compare releases to understand differences in masters,
  versions and edits: the comparison says where two editions share audio and where
  they differ, track by track.
- **Measurements and interpretations should remain distinguishable:** the Report
  measures and locates; it names no relationship, and states that matching tracks do
  not make the editions equivalent.
- **Sharing and interoperability matter:** the Report and its view carry the segments
  and their measurements, so another collector sees the basis of every correspondence.

## Appetite and scope cuts

Appetite: about a day.

If the work outgrows it, cut in this order, keeping edition comparisons with their
Report, schema and text result:

1. View's edition layout: view refuses a version 6 edition comparison with a reason;
   step 5 of the scenario goes.
2. Per-channel measurements of segments: segments are measured on the downmix only.

## What needs the maintainer

1. This brief and ADR 0009, before implementation starts.
2. AC10: importing the 2017 download and running the three comparisons by hand.
3. Merges and the release.
