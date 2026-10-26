# Brief: Locate Matching Portions Between Tracks

## Goal and context

A collector compares two tracks and learns which portions of one appear in the other,
where, and how alike they are, and which audio appears in only one, instead of one
offset whose measurements mix the aligned audio with the rest.

- **Milestone:** [v0.6.0](https://github.com/jmfontaine/copyofa/milestone/6)
- **Product Map capability:**
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
- **Decision:**
  [ADR 0006: Locate matching portions between tracks](../decisions/0006-locate-matching-portions-between-tracks.md),
  which supersedes the alignment of
  [ADR 0003](../decisions/0003-measure-track-comparisons-on-aligned-decoded-audio.md)

Since v0.3.0, compare aligns two tracks with one global offset. That handles leading
silence and encoder delay, but an edit (a cut, an inserted or repeated section, a
different intro) moves part of the audio, and the measurements then mix the part that
lines up with the part that does not. Comparing the *Add Violence* CD with its 2025
download showed it: the tracks differ in length and in places, and one offset cannot
say where.

## Primary scenario

Refines [S3](../product-map.md#s3-compare-two-tracks), its partial matches and their
affected ranges:

1. A collector compares track 4 of their *Add Violence* CD with the download's:
   `copyofa compare ~/Archive/add-violence-cd --track-a 4 "<download set>/data/…/04.flac"`.
2. Compare reports one portion covering most of the track, with its ranges in each,
   its offset and its measurements; two shorter portions where the song repeats a
   section; the first 4 s of the CD, where the download's intro is louder, as audio of
   A not matched; and the last 4.1 s of the download as audio of B that the CD does
   not hold, with its level.
3. The collector shares the Report and its view, as v0.4.0 allows; a reader sees
   where the two tracks agree and where they do not, without an interpretation.

## In scope

- Compare finds and measures portions with the method ADR 0006 decides, for every
  pair of inputs it accepts today: files, and tracks of acquired CDs.
- Comparison Report format version 4: portions and unmatched ranges in place of the
  offset and overlap, and every method parameter in `method`. Its schema, which
  validate accepts with versions 1 to 3.
- Compare's short human result lists the portions and the unmatched ranges.
- View renders version 4.

## Out of scope

- Speed, pitch and drift differences; they give no portion, which the Report states.
  The search finds no portion in an input shorter than one window (5 s) either;
  identical audio still gets its portion.
- Comparing whole discs or releases as such (the Later outcome Compare Editions).
  Compare still takes two inputs, which may be long.
- Choosing thresholds or the window length; they are fixed.
- Bridging short gaps, grouping nearby portions, or naming a difference ("edit",
  "remaster").
- Optimizing memory or speed.
- Changing inspect, export, or comparison Reports of earlier versions.

## Requirements

### Method

- **As ADR 0006 decides,** on the downmixes at the common rate of ADR 0003. Decoding,
  resampling, the identical-audio shortcut and the undefined values of ADR 0003 stand.
- **Identical audio** keeps its shortcut: when both inputs have an Audio Digest and the
  digests are equal, the Report states it and gives one primary portion covering both
  inputs at offset 0, found without a search and measured as ADR 0003 measures
  identical audio.

### Comparison Report format version 4

- **`method`** gives ADR 0003's decoder, resampler and common rate, `alignment`
  `windowed_portions`, and `parameters`: every value ADR 0006 decision 7 lists, with
  its unit. ADR 0006 is the authority for that list.
- **`measurements`** holds, in place of `offset` and `overlap`:
  - `portions`: each with its `rank` (`primary` or `alternate`), its range in A and
    in B (`start_frame` and `frames`), its `offset`, its residual after the per-block
    gains, and ADR 0003's `downmix` and `channels` measurements over it, residual
    windows included, and its own `absent` for each of these values the audio leaves
    undefined (such as the residual of identical audio, or `channels` when the channel
    counts differ), with the reason. Primaries come first, in A's order, then
    alternates.
  - `unmatched`: for A and for B, the ranges no primary portion covers, each with
    `start_frame`, `frames`, whether it is `digitally_silent`, and, when it is not, its
    `level_dbfs` as ADR 0006 defines it.
  - `identical_audio`, as in version 3.
  - `absent`: why `portions` is empty, such as "no portion found", an input shorter
    than one window, or a track with no frames.
- **`limitations`** state the method's limits instead of version 3's sentence on one
  global offset: portions shorter than about 2.5 s may be missed, the search finds no
  portion in inputs shorter than 5 s, and speed or drift differences give none.
- Frames are counted at `common_sample_rate`. Inputs and everything else stay as in
  version 3. Compare prints version 4 from this release on; validate and view keep
  accepting versions 1 to 3.

### Human result and view

- Compare's short result lists each portion (rank, ranges in seconds, offset,
  correlation, residual) and each unmatched range (seconds, level), or says that no
  portion was found.
- View renders version 4: the method's parameters, a table of portions, and the
  unmatched ranges of each input, with each portion's residual windows. It keeps
  rendering versions 1 to 3 as today.

### Exit codes

Unchanged: compare exits 0 when both inputs were interpreted and compared, whether or
not a portion was found.

## Design decisions

- **Method and parameters:** decided by ADR 0006.
- **Portions replace the global offset** rather than sitting next to it: its
  measurements mix aligned and unaligned audio, and when there is one portion, its
  offset is the global one.
- **Alternates are reported, ranked,** not dropped: a repeated section really matches
  several places, and the reader decides what that means.
- **Unmatched ranges carry their level,** so that a near-silent tail and audible audio
  that only one input holds read differently, as measurements.

## Blocking questions

None.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Tests build
their inputs from generated signals, so that each expected portion is known; they
ship no recording. Existing compare tests whose signals are shorter than one window
(5 s) are given longer signals where they need a portion.

- **AC1 — Edits found.** From a generated signal, variants with a cut, an inserted
  section from another signal, a repeated section, added leading and trailing silence, a
  linear fade-in and fade-out, a crossfade at a cut, a shift, a 0.3 s replacement and an
  inverted polarity each give the expected primary portions, with no extra primary
  portion and every offset exact. Every boundary is within 32 frames of the expected
  one, except that a fade's boundary is within four blocks (8192 frames) of the frame
  where the fade reaches silence, and any boundary inside a crossfade counts as
  expected. The same holds after resampling B to 48 kHz, at 24 bits, and with a
  −1.5 dB gain.
- **AC2 — Repeats and no match.** B holding a section of A twice, once exact and once
  with noise added about 20 dB below it, gives the noisy copy as an alternate, ranked
  after the primary; two exact copies give two primaries. Two unrelated generated
  signals give no portion, with the reason in `absent`, and compare exits 0; so do
  inputs shorter than 5 s whose Audio Digests differ.
- **AC3 — Unmatched ranges.** Audio that only A holds and audio that only B holds are
  reported as unmatched with their level; digital silence is flagged and has no level.
- **AC4 — Identical audio.** Two inputs with equal Audio Digests give
  `identical_audio` true and one primary portion over both at offset 0, whose residual
  is absent with its reason.
- **AC5 — Report.** Compare prints format version 4 with every parameter ADR 0006
  decision 7 lists in `method`; the version 4 schema ships in the package; every
  comparison Report the test suite produces validates; validate accepts versions 1 to
  4.
- **AC6 — Results and view.** The short result lists the portions and unmatched
  ranges, or says no portion was found. View renders a version 4 Report with
  portions, alternates, unmatched ranges and no portion, and still renders versions 1
  to 3.
- **AC7 — Documented.** `docs/formats/comparison-report.md` documents version 4, how
  version 3 differs, the method and each parameter, with an example. The README shows
  a comparison with portions. The Architecture section of AGENTS.md records the new
  alignment and ADR 0006.
- **AC8 — Real audio (by hand, once).**
  - *The Downward Spiral* (2017) FLAC against MP3: each of three tracks gives one
    primary portion at offset 0 and no other primary portion.
  - Track 3 of the acquired *Add Violence* CD located in the CD's own image, compared
    as `--track-a 3` against the set's `data/disc.scram.flac`: one primary portion
    covering the whole track, whose range in B starts at frame 46845360.
  - The CD's track 4 against the download's: one primary portion at +34,946 frames,
    the download's last 4.1 s unmatched at about −21 dBFS and not digitally silent,
    and the repeated section as two more portions. Track 3: primary portions at
    −4,075 frames with gaps in A, as the spike found.

## Manifesto alignment

- **Measurements and interpretations should remain distinguishable:** portions,
  unmatched ranges and their levels are measurements; the Report never says "edit",
  "same" or "different".
- **Results should be reproducible and durable:** the method's parameters are fixed
  and stated in each Report, and earlier format versions keep their meaning.
- **Discover anomalies and unexpected relationships** (the Manifesto's purpose):
  compare now says where two tracks differ, not only how much.

## Appetite and scope cuts

Appetite: a few hours.

If the work outgrows it, cut in this order, keeping portions, unmatched ranges and a
valid version 4 Report:

1. Residual windows per portion in the view; they stay in the Report.
2. Per-channel measurements per portion; the downmix measurements stay.
3. The level of unmatched ranges; the ranges and the digital-silence flag stay.

## Delivery notes

Recorded at the v0.6.0 release review.

- **Delivered within the appetite**, with no scope cut, as a stack of pull requests
  from one unattended agent: portions in compare with comparison Report format version
  4 in [#108](https://github.com/jmfontaine/copyofa/pull/108), and the view of version
  4 in [#109](https://github.com/jmfontaine/copyofa/pull/109). AC1–AC6 have tests
  built from generated signals, with stored version 3 Reports for the older formats;
  the whole suite holds 517 tests. The stack's agent review checked AC7. AC8, on the
  maintainer's machine: *The Downward Spiral* FLAC against MP3 gave one primary
  portion at offset 0 for each of three tracks; track 3 of the acquired *Add Violence*
  CD was found in the CD's own image at frame 46845360; against the 2025 download,
  track 4 gave a primary portion at +34,946 frames and the download's last 4.1 s
  unmatched at −20.8 dBFS, and track 3 gave ten primary portions at −4,075 frames with
  35.7 s of the CD unmatched. The maintainer read the track 4 page in Safari, the
  manual check of #106.
- **Changed during delivery:** AC1's fade clause did not describe the method: a
  fade's boundary falls about three blocks inside the fade, where the end rule's gain
  stops fitting, not where the fade reaches −80 dBFS. The spike had scored fades as
  zones. [#107](https://github.com/jmfontaine/copyofa/pull/107) bounded a fade's
  boundary to four blocks of its silent end, with the maintainer's agreement, and
  recorded in ADR 0006 the details the implementation settled, among them a
  B-position energy floor that became a Report parameter.
- **Clarified during delivery:**
  - Repeats whose residual is within 3 dB of the main portion's are primaries: track 4
    of *Add Violence* has three primary portions, the main one and the song's two
    repeated sections, and four short alternates.
  - Levels of unmatched audio take all channels, as ADR 0006 defines them; the spike
    measured the downmix, so the download's track 3 tail reads −49.9 dBFS rather than
    −52.
  - Compare's short result labels its residual "(one gain)", since a portion is
    accepted on its residual after the per-block gains.
- **Found in review:** the agent's own reviews fixed ends at a track's edge not
  placed to the frame, a silence rule relative to B that skipped quiet copies, a core
  shorter than one block being rejected, a crash on a 1 Hz input, a candidate repeated
  at 16 Hz and below (fixed and checked with a probe, without a test), a crash in the
  view on a Report without a common sample rate, and a bare "absent" level for
  digitally silent audio. The stack's agent review found the B-position energy floor
  changing results without being stated in the Report; it became a parameter, which
  is what fixed, stated parameters are for. A fade's boundary sits about 1,600 frames
  inside AC1's bound, so retuning the end rule could break it.
- **Learning:** an acceptance criterion written during plan review, without checking
  it against the spike's scoring, contradicted the method the spike validated. A
  criterion that pins a measured value should cite the evidence that supports it.
