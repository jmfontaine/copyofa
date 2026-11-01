# Brief: Compare Masters That Differ in Speed

## Goal and context

A collector who compares two tracks or two editions whose audio runs at slightly
different speeds, such as two transfers made with different clocks, a turntable
running fast or a PAL speed-up, learns where they share audio and at what speed ratio,
instead of getting many short portions or none.

- **Milestone:** [v0.10.0](https://github.com/jmfontaine/copyofa/milestone/10)
- **Product Map capabilities:**
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
  and
  [Share and Evaluate Findings](../product-map.md#share-and-evaluate-findings)
- **Decision:**
  [ADR 0010: Locate portions across speed differences](../decisions/0010-locate-portions-across-speed-differences.md)

A portion of ADR 0006 holds one offset, so audio whose speed differs drifts out of it:
ADR 0006 finds no portion at a difference of 0.1 %, and in v0.9.0 the 2017 download of
*The Downward Spiral* covers 59.8 % of its CD in 133 portions, short in its drifting
tracks. ADR 0010 records the spike: seven of the download's tracks drift at 9 to 11.4
ppm, each at its own ratio; fitting a ratio per portion raises the coverage to 66.2 %
in 93 portions, and, after a first estimate of the speed, recovers synthetic speed
changes up to ±4.2 % to the ppm. The rest of the download is audio that differs, which
no speed handling recovers.

## Primary scenario

Refines [S4](../product-map.md#s4-compare-two-editions), and
[S3](../product-map.md#s3-compare-two-tracks) for two tracks:

1. A collector has acquired a CD into `~/Archive/tds-cd` and imported a download of
   another master into `~/Archive/tds-2017`.
2. `copyofa compare ~/Archive/tds-cd ~/Archive/tds-2017` compares the two editions.
3. The text result gives the coverage, and for each track of A the tracks of B that
   hold its audio, with the speed ratio where it is not 0: "track 1 … in B's track 1
   at +9.0 ppm".
4. `--json` prints a comparison Report of format version 7 whose portions and segments
   each give their speed ratio and offset at their first frame.
5. `copyofa view` renders it, ratios included.

The same holds for two tracks, for example a CD track against the same recording
transferred 1 % fast.

## In scope

- ADR 0010's method in every comparison, of tracks and of editions.
- Comparison Report format version 7, its schema, validate accepting it, compare's text
  result and view's rendering of both scopes.

## Out of scope

- Changing ADR 0006's block test, acceptance, or its refusal to bridge gaps, including
  to raise the coverage of different masters past what ADR 0010 measured.
- Tempo changes that keep the pitch, speeds that vary within a portion, and speed
  differences beyond ±4.5 %.
- Interpreting a ratio: naming a cause ("PAL speed-up", "different clock") or a
  relationship.
- Reducing compare's memory below what v0.9.0 needs (Parking Lot:
  ["Bound compare's memory on long tracks"](https://github.com/jmfontaine/copyofa/discussions/76)).
- Changing inspect, verify, import, export or acquire.

## Requirements

### Comparison

As ADR 0010 decides, for tracks and editions alike:

- **Speed estimate,** then ADR 0006's coarse search and chaining on A stretched by it.
- **A ratio per portion,** fitted near the chain's strongest window, snapped to 0 at
  0.05 ppm or less, so audio at the same speed gives the primary portions, offsets,
  residuals and measurements of format version 6; alternates on repeated sections may
  differ in number and carry small ratios.
- **Refinement, measurements and segments on B stretched** along the portion's line.
- **Memory.** Each comparison of AC10 peaks no higher than v0.9.0 does for the same
  pair on the same Mac, measured with v0.9.0 before the change, with 0.3 GB allowed
  for the noise of the measurement; B is stretched over the region a portion needs,
  never as a whole copy of B.

### Comparison Report format version 7

Version 6 with:

- each portion, and each segment of an edition comparison: its offset at its first
  frame of A to 0.01 frame, an integer when the ratio is 0, and its speed ratio in
  ppm to 0.01, 0 when the speeds agree; its range of B may differ in length from its
  range of A;
- `method.alignment` `speed_tolerant_portions`, and ADR 0010's parameters added to
  `method.parameters`;
- `limitations`: version 6's, with both of its speed sentences, the track
  comparison's "Speed, pitch and drift differences give no portion" and the edition
  comparison's on short portions and partial coverage, replaced by ADR 0010's: speed
  differences up to ±4.5 % are found; a portion more than about 145 ppm from the
  comparison's one speed estimate is missed, such as a track of an edition whose speed
  differs from most others'; pitch is not corrected; tempo changes and speeds that vary
  within a portion are not followed; and a short excerpt at a different speed may be
  missed.

Exact field names and the schema are settled in implementation and documented in
`docs/formats/comparison-report.md`.

### Text result

- A track comparison's line per portion gives its speed ratio when it is not 0.
- An edition comparison's line per track of A gives, for each track of B holding it,
  the speed ratio of its primary segments when it is not 0, or the range of ratios
  when they differ.

### View

View renders version 7 of both scopes, with each portion's and segment's ratio and
offset, under the same rules as today's page, and maps version 7 to its layouts; it
still renders versions 1 to 6.

## Design decisions

- **The method:** decided by ADR 0010.
- **One method for tracks and editions,** as in ADR 0009, so a portion means the same
  in both.
- **Always on, no option,** because one fixed method keeps Reports comparable, as ADR
  0006 decides; at the same speed nothing changes.
- **Ratios in the text result only where they are not 0,** so a comparison at the same
  speed reads as it does today.

## Known limit

The speed estimate adds about 40 s to an edition comparison of two CDs, and stretched
refinement about 2 minutes when many portions drift: the spike's harness took 323 s to
locate the portions of the CD against the download, without decoding or measurements,
where v0.9.0's whole comparison took 168 s. The comparison Report document states the
time a comparison takes.

## Blocking questions

None.

## Stop rule

Stop and report if, in AC10, a pair at the same speed does not give the primary
portions it gave in v0.9.0, the download covers less than 66 % of the CD, a whole
comparison takes 6 minutes or more, or memory cannot be held to the bound above
without changing ADR 0010's method. Six minutes is the spike's added cost over v0.9.0's
168 s, with about 80 s for the stretched measurements the spike did not build.
Stop and report as well if the residuals of −23 to −24 dB the spike left unexplained
at −1 % and +1,000 ppm come from the method, not the test's resampling.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Synthetic
speed changes are made by resampling generated audio with soxr at its `VHQ` quality.
Boundaries are checked within the suite's existing tolerance of 32 frames.

- **AC1 — Same speed, same result.** Every comparison of tracks and of editions the
  test suite made in v0.9.0 gives version 7 with the same primary portions, segments,
  offsets, residuals and measurements as version 6, each at a ratio of 0 with an
  integer offset, and the tests that assert alternates still pass.
- **AC2 — Small speed differences.** A generated track of 150 s against itself at +10
  ppm and at −100 ppm gives one primary portion covering 99 % of it or more, at the
  ratio set to within 0.2 ppm, with a residual after the per-block gains of −30 dB or
  lower.
- **AC3 — Large speed differences.** The same at +1 % and at −41,667 ppm: one primary
  portion covering 99 % or more, at the ratio set to within 0.2 ppm, residual −20 dB or
  lower, the bar set below the spike's unexplained −23.5 dB at −1 %.
- **AC4 — Editions that drift.** Two editions of four generated tracks of 60 s each,
  where B's tracks 2 and 3 are A's at +10 ppm and −100 ppm and each of B's tracks
  starts at a different offset from A's, give a primary portion per track at its ratio,
  segments at both editions' boundaries with their own offsets, correspondences pairing
  each track with its counterpart, and coverage of 99 % or more of each edition.
- **AC5 — Unrelated audio.** Unrelated tracks, and unrelated editions, give no portion.
- **AC6 — Schema.** The version 7 schema ships in the package; validate accepts both
  scopes; every Report the test suite produces validates.
- **AC7 — Text result.** AC2's and AC4's comparisons print the ratios, and AC1's
  print none.
- **AC8 — View.** View renders version 7 of both scopes with ratios and offsets, every
  text escaped, and still renders versions 1 to 6.
- **AC9 — Documented.** `docs/formats/comparison-report.md` documents version 7, the
  method of ADR 0010, the known limit, and version 6 among the earlier versions; the
  README says compare finds audio whose speed differs; AGENTS.md's Architecture
  section gives ADR 0010 and view's versions 1 to 7.
- **AC10 — Real editions (by hand, once).** On the maintainer's Mac, with input A the
  14-track pressing of ADR 0009's spike: the other pressing gives one primary portion
  at −37,634 frames and a ratio of 0; the 15-track edition gives two primary portions,
  its bonus track unmatched; the 2017 download covers 66 % or more of the CD, with the
  longest portion in each of its drifting tracks at 9 to 11.5 ppm; the unrelated
  release gives no portion; and a CD track, exported, stretched with soxr at its `VHQ`
  quality by +1 % and by +41,667 ppm and each imported, gives one portion at its ratio.
  Each comparison meets the memory bound above and takes under 6 minutes, and each
  view opens in a browser.

## Manifesto alignment

- **Discography researchers** compare releases to understand differences in masters and
  transfers: a speed ratio is a measured property of a transfer, and the portions it
  restores show where the masters really differ.
- **Measurements and interpretations should remain distinguishable:** the Report gives
  the ratio it measured, never its cause.
- **Reproducibility:** the method is fixed and its parameters are in every Report.

## Appetite and scope cuts

Appetite: about a day.

If the work outgrows it, cut in this order, keeping speed-tolerant portions with their
Report, schema, text result and view:

1. The ratios in the edition text result: only the Report and view give them.
2. The speed estimate: chains hold ratios within about ±145 ppm of 0, the download's
   drift is still covered, and AC3 and AC10's stretched tracks go. ADR 0010, this
   brief's scenario and limitation, the parameters and the Product Map's "up to 4.5 %"
   are then amended in a documentation pull request merged before the cut.

## What needs the maintainer

1. This brief and ADR 0010, before implementation starts.
2. Merges and the release.

AC10 runs on the maintainer's Mac, from the sets already in its vault and the two
stretched tracks an agent exports, stretches and imports there, so an agent can run
it; the maintainer only reviews its results on the pull request.
