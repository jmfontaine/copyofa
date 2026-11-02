# Comparison Report format

`copyofa compare <input-a> <input-b> [--track-a <number>] [--track-b <number>] --json`
prints a comparison Report: a JSON document measuring how the audio of two tracks
preserved in [Evidence Sets](evidence-set.md) relates. Each input is a file in a set,
or, with `--track-a` or `--track-b`, a track of an
[acquired set](evidence-set.md#acquired-sets). Given the roots of two sets without
either option, compare measures how two editions relate instead, each the tracks of
its set (see [Comparing editions](#comparing-editions)). Like every `--json` output of
CopyOfA, it is UTF-8, whatever the locale; a path that is not valid UTF-8 keeps each
invalid byte as a `\udcXX` escape (see [Import result](evidence-set.md#import-result)).
Save it with a shell redirect:

```bash
copyofa compare "/Volumes/Archive/With Teeth/data/04 The Hand That Feeds.flac" \
  "/Volumes/Archive/Definitive NIN/data/18 The Hand That Feeds.mp3" --json > htf.json
copyofa compare "/Volumes/Archive/Add Violence CD" \
  "/Volumes/Archive/Add Violence/data/01-01 Less Than.flac" --track-a 1 --json \
  > less-than.json
copyofa compare "/Volumes/Archive/TDS CD" "/Volumes/Archive/TDS 2017" --json \
  > tds.json
```

A Report holds measurements: the portions of track A found in track B, each with its
offset, speed ratio, correlation, gain and residual, and the audio that only one track
holds. It draws no conclusion from them, such as "same master" or "match".
[ADR 0003](../decisions/0003-measure-track-comparisons-on-aligned-decoded-audio.md)
records how the tracks are decoded and measured,
[ADR 0006](../decisions/0006-locate-matching-portions-between-tracks.md) how portions
are located and why that method was chosen, and
[ADR 0010](../decisions/0010-locate-portions-across-speed-differences.md) how they are
located where the speed of the two differs.
[ADR 0009](../decisions/0009-compare-editions-as-sequences-of-their-tracks.md) records
why two editions are compared as sequences of their tracks.

It has seven format versions, each with its JSON Schema:
[comparison-report-7.schema.json](../../src/copyofa/schemas/comparison-report-7.schema.json)
for version 7, which this document describes and `compare` prints,
[comparison-report-6.schema.json](../../src/copyofa/schemas/comparison-report-6.schema.json)
for [version 6](#format-version-6),
[comparison-report-5.schema.json](../../src/copyofa/schemas/comparison-report-5.schema.json)
for [version 5](#format-version-5),
[comparison-report-4.schema.json](../../src/copyofa/schemas/comparison-report-4.schema.json)
for [version 4](#format-version-4),
[comparison-report-3.schema.json](../../src/copyofa/schemas/comparison-report-3.schema.json)
for [version 3](#format-version-3),
[comparison-report-2.schema.json](../../src/copyofa/schemas/comparison-report-2.schema.json)
for [version 2](#format-version-2), and
[comparison-report-1.schema.json](../../src/copyofa/schemas/comparison-report-1.schema.json)
for [version 1](#format-version-1). [`copyofa validate`](validation-result.md) checks a
Report against the schema of its version.

To share a Report without saying where its Evidence Sets are stored, leave the
locations out when you compare, as
[described below](#leaving-out-evidence-set-locations):

```bash
copyofa compare <input-a> <input-b> --json --omit-locations > htf.json
```

## How compare works

1. **Finding each set.** Each track is the path of a file inside an Evidence Set. Its
   set is the nearest directory above it that holds `bagit.txt`, and the file must lie
   under that set's `data/`. Otherwise compare exits 2. Under a directory that cannot
   be searched, such as a set root without search permission, the set is the nearest
   directory whose `data/` holds the file; its records then cannot be read, and the
   input is `not_inspected`.

   With `--track-a <number>`, input A is instead that track of the acquired set whose
   root is input A, and likewise `--track-b` for input B. The root must be an Evidence
   Set, else compare exits 2. Two set roots given without either option are two
   editions, compared as [Comparing editions](#comparing-editions) describes. A set
   root given without its option beside any other input, such as a file, a plain
   directory or a set root given with its option, exits 2 with the message
   `compare takes two tracks or two editions: <root> is the root of an Evidence Set
   given without a track number, but the other input is not a set root given without
   one. Give two set roots without track numbers to compare editions, or a track
   number with each set root to compare tracks.`
2. **Integrity first.** Each input is checked as `inspect` checks a file (see
   [Inspection Report format](inspection-report.md#how-inspect-works)): the Integrity
   Baseline must be usable, `manifest-sha256.txt` must list the file, and the file must
   be the accepted bytes. It is then decoded with libsndfile: FLAC, WAV or MP3, with
   inspect's rules, outcomes and reasons. A track input is checked as inspect checks
   a track (see
   [Inspection Report format](inspection-report.md#how-inspect-works)): the Acquisition
   Record must be usable and list the track, and the disc image must be the accepted
   bytes; the image is then decoded over the track's range. When either input is not
   `interpreted`, nothing is measured.
3. **Common rate.** When the sample rates differ, the track at the higher rate is
   resampled to the lower one with libsoxr at its `VHQ` quality. Measurements cover
   only the band of that common rate.
4. **Locating portions.** Each track is mixed down to mono, the mean of its channels. A
   portion is a range of A that appears in B along one line: frame *n* of A lines up
   with frame *n* + offset + ratio·(*n* − start) of B, where start is the portion's
   first frame of A, offset where B is then, and ratio its speed ratio, B's frames per
   frame of A minus one. At a ratio of 0, B is at the same speed and the offset is a
   whole number of frames. When both tracks have an Audio Digest and the digests are
   equal, there is no search: one primary portion covers both tracks at offset 0 and
   ratio 0. Otherwise compare searches with the fixed [parameters](#parameters) below,
   in these stages:
   - **Speed estimate.** The speed of B against A is first estimated in two levels. At
     each, both downmixes are decimated with libsoxr at its `HQ` quality and filtered
     as the coarse search below filters them, and A is cut into its windows of 5 s.
     Windows of A evenly spread among those that give evidence, or all of them when
     there are fewer, are each stretched by every ratio of the level with libsoxr at
     its `HQ` quality, cut from an excerpt a quarter of a window longer on each side,
     and correlated with all of B as the coarse search correlates a window; the ratio
     with the highest sum of the windows' best scores is kept. The first level
     decimates by 128, takes 8 windows and the ratios from −45,000 to +45,000 ppm in
     steps of 1,500 ppm; the second decimates by 16, takes 12 windows and the ratios
     within 1,000 ppm of the first level's, in steps of 200 ppm. The estimate is the
     second level's ratio when the mean of its windows' best scores at that ratio is
     at least 0.25, and 0 otherwise.
   - **Coarse search.** Both downmixes are decimated by 16 with libsoxr at its `HQ`
     quality, then filtered with a first difference of coefficient 0.5:
     *y*[*n*] = *x*[*n*] − 0.5·*x*[*n* − 1]. A is cut into windows of 5 s, without
     overlap. A window whose energy is at most 10⁻⁴ of the mean window energy gives no
     evidence. For each other window, compare takes the magnitude of its normalized
     cross-correlation with every position of B that holds the whole window. Up to
     three positions that score at least 0.4, and lie at least 0.5 s apart, are
     candidates. A position of B whose energy under the window is at most 10⁻¹⁰ of B's
     whole energy gives no candidate, so that rounding errors in the running sum of
     that energy cannot pass for a match where B is next to silent. Candidates of
     neighboring windows, with at most one window skipped between them, whose offsets
     differ by at most 32 frames form a chain. A track shorter than one window gives
     no candidate, and neither does a track at a sample rate under 2 Hz, where a
     window holds no frame of the decimated audio. When the estimate is not 0, A's
     decimated downmix is stretched by it, as a whole, with libsoxr at its `HQ`
     quality before it is cut into windows, and each candidate's window and offset are
     mapped back to A's frames; chained candidates then still agree within 32 frames
     of the estimate's line, so a chain holds a ratio within about ±145 ppm of the
     estimate.
   - **Ratio.** Chains are refined at the common rate, strongest first. A chain whose
     windows all lie inside a portion already found whose line passes within 32
     frames of its strongest window's coarse position in B is not refined again. A
     line through the chain's candidates, the best of each window, by least squares,
     leaving out the farthest while it lies more than 32 frames from the line, gives
     a first ratio; a chain of one window takes the estimate. When the first ratio is
     20 ppm or more from 0, B is stretched by it, as described under **Stretched
     refinement** below. Then each window within 12 windows of the strongest one is
     placed against B, or the stretched B, to a fraction of a frame: the whole frame
     is that of its best normalized correlation within 40 frames of its coarse
     position, not at the edge of that search, and the fraction the slope of the
     phase of the cross-spectrum there, each frequency weighted by its magnitude times
     its frequency; each offset belongs to its window's middle frame. A line through
     the offsets of the windows that score at least 0.5 of the best, leaving out the
     farthest while it lies more than 4 frames or three standard deviations from the
     line, from at least 4 windows, corrects the first ratio. With fewer windows, the
     ratio is the first one, or 0 when it is under 20 ppm. A ratio within 0.05 ppm of
     0 is 0, and the chain is refined at one offset as ADR 0006 refines it, in the
     stages that follow; any other ratio is refined as **Stretched refinement**
     describes.
   - **Offset.** The core of a chain is its strongest
     window and the neighboring windows that score at least 0.85 of it, up to 20 s.
     The offset is the integer within 32 frames of the strongest window's coarse offset
     that maximizes |Σ*ab*| / √Σ*b*² over the core, taken over the frames of the core
     that have a frame of B at every offset searched.
   - **Blocks.** The core is cut into blocks of 2048 frames. With *p* the mean power of
     A's downmix in a block and *g* the block's own least-squares gain, a block where
     *p* is zero is neutral when B's mean power is at most 10⁻⁶ (−60 dBFS), and refutes
     the match otherwise. Any other block confirms the match when its residual
     Σ(*a* − *g*·*b*)² is at most 0.2·Σ*a*² (−7 dB), and otherwise refutes it, unless
     *p* is below −80 dBFS, where it is neutral: quiet audio can confirm a match but
     never refute it. A chain gives no portion when its core has no confirming block,
     or when fewer than half of its non-neutral blocks confirm.
   - **Growth.** The run of the core without a refuting block that holds the most
     confirming blocks grows outward, from its first and last confirming blocks, block
     by block, until a block refutes the match. Compare never bridges a short gap.
   - **Ends.** Each end is then placed to the frame. With *g* the least-squares gain
     over the eight blocks inside the block edge, the end is the frame, between eight
     blocks inside and one block outside that edge, that ends the maximum-scoring
     prefix or suffix of 0.2·*a*[*n*]² − (*a*[*n*] − *g*·*b*[*n* + offset])². That
     range stops where either track does; of equally scoring prefixes or suffixes,
     the shortest is taken.
   - **Stretched refinement.** A chain at a ratio other than 0 is refined on B
     stretched along its line by a windowed-sinc interpolator of 32 taps (Kaiser
     window, β 9, cutoff 0.96 of the Nyquist frequency, 1,024 phases, each scaled to a
     gain of 1 at 0 Hz; frames outside B count as zero), over the core and 40 s on
     either side. Offset, blocks, growth and ends run as above against the stretched
     B, and the line moves by the whole frames the offset finds. When the grown
     portion ends within two blocks of an edge of the stretched region and B goes on
     there, the region grows on that side by 40 s or its own width, whichever is more,
     and the refinement runs again. The line is then fitted again on the 5 s windows of
     the grown portion: each placed as under **Ratio**, within 12 frames, those
     scoring at least 0.3, leaving out the farthest while it lies more than 3 frames
     from the line, from at least 3 windows. When the refitted line lies within 0.3
     frame of the line refined on at both ends of the portion, the portion keeps the
     refitted line, and its ratio is confirmed; otherwise the refinement repeats on it,
     at most 10 times. When no pass holds, the portion keeps the line of the last pass
     that gave a portion: its ratio is not converged when a refit succeeded, and its
     first ratio when the portion had too few windows to refit at the first pass. The
     portion's ratio is given to 0.01 ppm and its offset to 0.01 frame; a ratio that
     rounds to 0 is refined at one offset instead, at the same speed. `ratio_fit`
     records which.
   - **Holes.** Windows of the chain left outside the portion are refined again, so a
     portion after a hole is kept.
   - **Acceptance.** A portion is kept when it is at least 1 s long and its residual
     after the per-block gains, 10·log10(Σ*ₖ*Σ(*a* − *gₖ*·*b*)² / Σ*a*²) over its blocks
     *k*, counted from its start, is at most −10 dB, with *b* B along the portion's
     line as the Report gives it. A portion whose residual is undefined because *a* −
     *gₖ*·*b* is zero throughout is kept.
   - **Merging and ranking.** Portions whose lines lie within 2 frames of each other at
     both ends of the frames of A they share, and whose ranges of A overlap or touch,
     are merged; the merged portion takes the line of the longer one, and with it how
     its ratio was set, and its residual is taken again over its range. A portion is
     an alternate when portions whose
     residual after the per-block gains is at least 3 dB lower cover 90 % or more of
     its range of A. For that comparison, residuals below −60 dB and undefined ones
     count as −60 dB, so exact repeats tie and are all primary. Compare reports every
     portion, primaries first, then alternates, each in order of A.
5. **Measurements.** A portion's range of B starts at the frame nearest its line at its
   first frame of A, a half rounding up, and ends likewise; at a ratio other than 0,
   the two ranges differ in length. Compare measures each portion over its range of
   A: the correlation, the gain and the residual on the downmix, and for each channel
   when both tracks have the same channel count, with the residual of each one-second
   window. At a ratio of 0, B is its range; at any other ratio, B is stretched along
   the portion's line by the interpolator above, one value per frame of A, the
   downmix and each channel alike.
6. **Unmatched audio.** The ranges of A and of B that no primary portion covers are
   reported, each with whether it is digitally silent and, when it is not, its level.
   Alternates do not shrink them. Compare measures both on the samples at the common
   rate. When it finds no portion, the Report says why, and each track is one
   unmatched range.

The search finds no portion in a track shorter than 5 s, identical audio excepted, and
may miss a portion shorter than about 2.5 s. It finds a speed difference of up to
±4.5 % when the windows of the estimate match, each portion at its own constant ratio.
The estimate is one per comparison, so a portion whose ratio lies more than about 145
ppm from it is missed whatever its length, and a short excerpt at a different speed
inside unrelated audio may not raise it. A portion shorter than 20 s has fewer than 4
windows to correct its first ratio: it keeps that ratio, or 0 when it is under 20 ppm,
so it lasts only as far as its remaining drift passes the block test. Unless the
stretched refinement refits it, from at least 3 windows, the Report gives that first
ratio, from the coarse offsets or the estimate, not one refined to a fraction of a
frame, and its `ratio_fit` says so: `first_ratio`.
Pitch is not corrected: a ratio changes speed and pitch together, as a clock or a
turntable does. A tempo change that keeps the pitch gives no portion, nor does a speed
that varies within a portion beyond what the block test absorbs; a step in offset,
such as an edit, is a portion of its own. The interpolator cuts off at 96 % of the
Nyquist frequency, and a resampler that made B may cut off lower: in a quiet passage
that holds much of its energy above that, such as the noise-shaped dither between two
notes, the block test refutes the match, so a track resampled whole can match as
several portions at one ratio, each ending at such a passage. A boundary at a fade
falls about three blocks inside it, where the gain fitted over the eight blocks inside
the edge stops fitting the faded audio, not where the fade gets quiet; a boundary at a
crossfade falls where the other audio refutes the match. In music that repeats a
section, one range of A matches several places in B, and each is a portion. The
Report's `limitations` state this.

The text result gives each portion's speed ratio when it is not 0, followed by a note
when the ratio is not confirmed: `not converged` or `first ratio`, as in
`speed ratio -41670.47 ppm (first ratio)`. A confirmed ratio has no note, and a
comparison at the same speed prints no ratio.

Compare writes nothing into either set.

## Comparing editions

Given the roots of two Evidence Sets, and neither `--track-a` nor `--track-b`, compare
compares two editions, as
[ADR 0009](../decisions/0009-compare-editions-as-sequences-of-their-tracks.md)
decides: each edition is the tracks of its set, joined into one sequence, and portions
are located on the two sequences, so a portion that crosses a track boundary is found
whole. The Report's `scope` is `editions`, and its fields are those
[Edition comparisons](#edition-comparisons) describes.

1. **Forming each edition.** An acquired set's edition is its tracks in the order of
   its Acquisition Record, each checked and decoded as a track input is. An imported
   set's edition is the files its manifest lists, in the order of their paths from the
   set's root, compared by Unicode code point, each checked and decoded as a file input
   is. A file inspect reports `not_interpreted`, such as a cover image or a format
   CopyOfA does not decode, is excluded from the edition and listed with its outcome
   and reason. A file that is `failed` or `not_inspected`, such as an audio file
   modified since import, stays a track of the edition. An edition whose set's
   Integrity Baseline is unusable, or whose Acquisition Record cannot be used, has no
   track, and the Report says why.
2. **Nothing measured.** When a track of either edition is not `interpreted`, or an
   edition has no track, nothing is measured: the Report has no `measurements`, gives
   the reason, and compare exits 1.
3. **Common rate.** The common rate is the lowest sample rate of all tracks of both
   editions, read before any track is decoded: 44,100 Hz for an acquired set, and the
   rate in its header for a file. A track at a higher rate is resampled to it, as a
   track input is, as soon as it is decoded; its samples at its own rate are not kept.
4. **Sequences.** Each edition's tracks, mixed down, are joined in order without gap,
   and portions are located on the two sequences as on two tracks, with the same
   method and parameters. No search is skipped for equal Audio Digests.
5. **Segments.** Each portion is split at every track boundary of either edition that
   falls inside it. A boundary of B starts the next segment at the first frame of A at
   or after the position of that track's first frame on the portion's line. Each
   segment takes the portion's ratio and its own offset, within its two tracks, at its
   first frame, and is measured as a portion of two tracks is: the correlation, the
   gain and the residual on the downmix, and for each channel when its two tracks have
   the same channel count, with the residual of each one-second window. The residual
   after the per-block gains stays per portion.
6. **Correspondences, unmatched audio and coverage.** The primary segments pair each
   track of A with the tracks of B that hold its audio, and give how much of each
   track the pair shares. The ranges of each track that no primary portion covers are
   unmatched, with whether each is digitally silent and otherwise its level. Each
   edition's coverage is how much of its sequence primary portions cover. Primary
   portions can overlap where audio repeats, so every count of matched audio counts a
   frame once.

Each portion takes its own ratio, so tracks whose speeds differ, as between different
masters, each match at their own ratio and offset. The speed estimate is one per
comparison, so a track whose speed differs from that of most others by more than about
145 ppm may be missed. Coverage stays bounded by the audio: different masters still
leave unmatched audio the block test refutes. Tracks that match do not establish that
the editions are equivalent. The Report's `limitations` state both.

The text result's line for each track of A gives, for each track of B that holds its
audio, the speed ratio of their primary segments when it is not 0, or the range of
their ratios when they differ, counting only the segments at the same speed or
confirmed, as in `at +9.05 ppm`. When it leaves segments out, it says how many and
how their ratios were set, as in `at +9.05 ppm (2 segments left out: first ratio)`;
when it counts none, it gives the range of the others and how they were set, as in
`at +9.08 ppm (first ratio)`. A track of B holding a track of A at the same speed gets
no ratio.

**Known limit.** Time grows with the product of the editions' lengths, and memory with
their sum. In ADR 0009's spike, the search over two CDs of about 65 min took about 2.5
minutes at a peak of 4.9 GB to 5.3 GB, and 5.6 GB for a CD against a 96 kHz download,
before the per-channel measurements. A whole comparison, measurements included, needs
more memory. Version 7 adds the speed estimate and the stretched refinement of each
chain at a ratio other than 0, so its cost grows with the audio that drifts. Run back
to back on one Mac on mains power, version 6 (CopyOfA 0.9.0) and version 7 took, with
A the 14-track CD pressing of ADR 0009's spike and the peak as macOS's peak memory
footprint:

| Input B | Version 6 | Version 7 |
| --- | --- | --- |
| Another CD pressing | 154 s, 8.45 GB | 205 s, 8.51 GB |
| The 15-track edition | 186 s, 9.02 GB | 249 s, 8.37 GB |
| The 96 kHz download, imported | 200 s, 8.46 GB | 387 s, 8.68 GB |
| An unrelated release | 199 s, 11.31 GB | 227 s, 10.84 GB |
| Track 13 of A, stretched by +1 %, against that track | 2.0 s, 0.86 GB | 10.5 s, 1.08 GB |
| Track 13 of A, stretched by +41,667 ppm, against that track | 2.1 s, 0.88 GB | 10.0 s, 1.04 GB |

Editions much longer than a CD, such as a box set imported as one set, may exhaust
memory.

## Fields

| Field | Content |
| --- | --- |
| `report_kind` | Always `copyofa.comparison`. |
| `format_version` | The version of this format, `7`. A later change to the fields increments it. |
| `scope` | What the Report compares: `tracks`, two tracks, or `editions`, two editions (see [Edition comparisons](#edition-comparisons)). The fields below are those of `tracks`. |
| `copyofa_version` | The version of CopyOfA that ran the comparison. |
| `compared_at` | The comparison time in UTC, such as `2026-10-25T18:30:00Z`. |
| `omitted` | The JSON Pointers of the values the Report leaves out, each of `/inputs/a/evidence_set` and `/inputs/b/evidence_set` at most once; `[]` when it leaves out nothing. See [Leaving out Evidence Set locations](#leaving-out-evidence-set-locations). |
| `inputs` | `a` and `b`: each input, described below. |
| `method` | How the tracks were decoded, resampled and searched for portions, described below. |
| `measurements` | The measurements, described below; absent when either input is not `interpreted`. |
| `absent` | Only in a comparison of editions: `measurements`, the reason they are absent; present exactly when they are. |
| `limitations` | Sentences stating what the whole Report does not establish or did not examine. |

### Inputs

Each of `inputs.a` and `inputs.b` holds:

- `evidence_set`: the path of the Evidence Set holding the track, as the
  verification Report records it. It is absent when `omitted` lists its pointer, such
  as `/inputs/a/evidence_set`, and present otherwise.
- `integrity_baseline`: that set's baseline, `manifest_sha256`, `usable` and
  `problems`, as in the verification Report.
- The track's entry, with the fields of a `files` entry of the
  [inspection Report](inspection-report.md#fields): `path` in the set, `outcome`,
  `expected_digest`, `observed_digest` (the File Digest), `reason` when the outcome
  is not `interpreted`, and for interpreted audio its properties (`format`,
  `encoding`, `sample_rate`, `channels`, `bits_per_sample`, `frames`), its
  `audio_digest` if it has one, and inspect's other findings.

An input is `not_inspected` with the reason `manifest-sha256.txt does not list it`
when the manifest does not list it, and with `the Integrity Baseline is unusable`,
without decoding, when its set's baseline is unusable. `expected_digest` is then
absent when the manifest does not list the file.

An input given with `--track-a` or `--track-b` also holds `track`: its `number`, and
its `first_frame` and `frame_count` in the image when the Acquisition Record lists the
track. When that record is format version 2, `track` also holds `error_ranges`: the
track's frames the drive did not read successfully, as the
[inspection Report](inspection-report.md#fields) gives them for a track, a list,
empty when there are none, of ranges with `offset_frames` from the track's first
frame, `frame_count` and `state`, `not_read` or `c2_error`. It is absent for a record
of format version 1, which gives no error ranges. The ranges change neither the
measurements nor the exit code. In such an input:

- `path`, `expected_digest` and `observed_digest` describe the disc image, such as
  `data/disc.scram.flac`; `path` and `expected_digest` are absent when no usable
  Acquisition Record names the image.
- `outcome`, `reason`, the audio properties, `frames`, `audio_digest`, `peak` and the
  silences describe the track, with inspect's track outcomes: `interpreted`, `failed`
  and `not_inspected`.
- `flac_md5_signature` is absent: it covers the whole image, not the track.

A track input is `not_inspected` with the reason
`the Evidence Set is not an acquired set: tagmanifest-sha256.txt does not list
copyofa/acquisition-record.json` when the set is not an acquired set, with
`the Acquisition Record lists no track <number>` when the record does not list it, and
with the reason inspect gives `disc` when the record cannot be used.

### Method

| Field | Content |
| --- | --- |
| `decoder` | Always `libsndfile`. |
| `decoder_version` | Its version, such as `1.2.2`. The version of the mpg123 library that libsndfile uses for MP3 is not available to CopyOfA. |
| `resampler` | Always `libsoxr`. It is named even when both tracks have the same rate and nothing is resampled. |
| `resampler_version` | Its version, such as `0.1.3-14-ga66f3ee`. |
| `resampler_quality` | Always `VHQ`, libsoxr's very high quality preset. |
| `common_sample_rate` | The lower of the two sample rates, at which every measurement is made; absent when nothing is measured. |
| `alignment` | Always `speed_tolerant_portions`: the tracks are aligned by portions, each at its own offset and speed ratio, found with the speed estimate, windows, blocks and stretched refinement described above. |
| `parameters` | The fixed parameters of the search, listed below. Every value is the same in every Report of this version; the Report states them because the result moves with them. |

### Parameters

Each name ends in its unit when it has one. Frames are counted at
`common_sample_rate`.

The coarse search counts in frames of the decimated audio, at `common_sample_rate` /
`decimation_factor`, so it rounds three seconds-valued parameters to whole decimated
frames, with Python's `round`, which takes a half to the even integer:

- a window of A holds round(`window_seconds` × `common_sample_rate` /
  `decimation_factor`) decimated frames, and the windows of A start every
  round(`hop_seconds` × `common_sample_rate` / `decimation_factor`) decimated frames;
  at the common rate, both are that number times `decimation_factor`;
- two candidates of a window lie at least round(`candidate_separation_seconds` ×
  `common_sample_rate` / `decimation_factor`) decimated frames apart, and at least
  one.

At 44.1 kHz, a window holds round(5 × 44100 / 16) = 13,781 decimated frames, so it is
13,781 × 16 = 220,496 frames long, not 220,500, and the windows of A start every
220,496 frames; two candidates lie at least round(0.5 × 44100 / 16) = 1,378 decimated
frames apart. Three uses are not rounded. The search does not run, and finds no
portion, when a track is shorter than `window_seconds` × `common_sample_rate` frames:
220,500 at 44.1 kHz, though a window is 220,496. `core_seconds` and
`minimum_portion_seconds` are compared with frame counts as `core_seconds` ×
`common_sample_rate` and `minimum_portion_seconds` × `common_sample_rate`.

Each level of the speed estimate cuts its windows the same way at its own decimation
factor: at 44.1 kHz and a factor of 128, a window holds round(5 × 44100 / 128) = 1,723
decimated frames. When the estimate is not 0, the windows of A are cut after A's
decimated downmix is stretched by it, so at the common rate each starts at its start
in the stretched audio times `decimation_factor`, divided by 1 + the estimate and
rounded to the nearest frame.
`stretch_margin_seconds` is counted as `stretch_margin_seconds` ×
`common_sample_rate` frames.

| Parameter | Value | Unit | Meaning |
| --- | --- | --- | --- |
| `decimation_factor` | `16` | factor | Decimation of both downmixes for the coarse search. |
| `decimation_quality` | `"HQ"` | | libsoxr quality preset of that decimation. |
| `first_difference_coefficient` | `0.5` | coefficient | *c* of the first difference *y*[*n*] = *x*[*n*] − *c*·*x*[*n* − 1] applied after decimation. |
| `window_seconds` | `5` | s | Length of each window of A, rounded to whole decimated frames as above. |
| `hop_seconds` | `5` | s | Distance between the starts of two windows of A, rounded to whole decimated frames as above. |
| `silent_window_energy_ratio` | `0.0001` | ratio | A window of A whose energy is at most this fraction of the mean window energy gives no evidence. |
| `b_position_energy_floor` | `1e-10` | ratio | A position of B whose energy under the window is at most this fraction of B's whole energy gives no candidate. |
| `candidate_threshold` | `0.4` | correlation | Least magnitude of the normalized cross-correlation of a candidate. |
| `candidates_per_window` | `3` | candidates | Most candidates per window. |
| `candidate_separation_seconds` | `0.5` | s | Least distance between two candidates of a window, rounded to whole decimated frames as above. |
| `skipped_windows` | `1` | windows | Most windows skipped between two chained candidates. |
| `chaining_tolerance_frames` | `32` | frames | Most difference between the offsets of two chained candidates, and between the offsets of a chain and of a portion already found. |
| `core_ratio` | `0.85` | ratio | Least score, relative to the strongest window, of a window that joins the core. |
| `core_seconds` | `20` | s | Longest core. |
| `refinement_radius_frames` | `32` | frames | Distance from the coarse offset over which the offset is searched. |
| `block_frames` | `2048` | frames | Length of a block. |
| `matched_block_residual_ratio` | `0.2` | ratio | Most residual, relative to the energy of A in the block, of a block that confirms the match (−7 dB). |
| `core_confirming_ratio` | `0.5` | ratio | Least fraction of the non-neutral blocks of the core that confirm. |
| `evidence_floor_dbfs` | `-80` | dBFS | A block of A below this mean power is neutral instead of refuting. |
| `silence_against_signal_dbfs` | `-60` | dBFS | Where A is zero in a block, B above this mean power refutes the match. |
| `end_range_inside_blocks` | `8` | blocks | Blocks inside the edge of a portion that place its end. |
| `end_range_outside_blocks` | `1` | blocks | Blocks outside the edge of a portion that place its end. |
| `acceptance_residual_db` | `-10` | dB | Greatest residual after the per-block gains of a kept portion. |
| `minimum_portion_seconds` | `1` | s | Shortest kept portion. |
| `merge_tolerance_frames` | `2` | frames | Most difference between the offsets of two merged portions. |
| `alternate_margin_db` | `3` | dB | Least amount by which another portion's residual must be lower to rank this one as an alternate. |
| `alternate_coverage_ratio` | `0.9` | ratio | Least fraction of a portion's range of A that better portions cover to make it an alternate. |
| `equal_residual_floor_db` | `-60` | dB | Residuals below it, and undefined ones, count as this value when ranking. |
| `estimate_decimation_factors` | `[128, 16]` | factors | Decimation of both downmixes at each level of the speed estimate. |
| `estimate_windows` | `[8, 12]` | windows | Most windows of A stretched and correlated at each level of the speed estimate. |
| `estimate_range_ppm` | `45000` | ppm | The first level of the speed estimate tries the ratios from minus to plus this value. |
| `estimate_steps_ppm` | `[1500, 200]` | ppm | Distance between the ratios tried at each level of the speed estimate. |
| `estimate_span_ppm` | `1000` | ppm | The second level tries the ratios within this distance of the first level's. |
| `estimate_adoption_score` | `0.25` | correlation | Least mean of the windows' best scores at the second level's ratio for the estimate to be that ratio instead of 0. |
| `first_line_outlier_frames` | `32` | frames | A candidate farther than this from a chain's first line is left out of it. |
| `first_ratio_stretch_ppm` | `20` | ppm | Least distance of a chain's first ratio from 0 for B to be stretched by it before its windows are placed. |
| `ratio_windows` | `12` | windows | Windows on each side of a chain's strongest one that correct its first ratio. |
| `ratio_minimum_windows` | `4` | windows | Fewest windows that correct the first ratio. |
| `ratio_radius_frames` | `40` | frames | Distance from a window's coarse position over which it is placed to correct the first ratio. |
| `ratio_window_score_ratio` | `0.5` | ratio | Least score, relative to the best, of a window that corrects the first ratio. |
| `ratio_outlier_frames` | `4` | frames | A window farther than this from the corrected line is left out of it. |
| `ratio_outlier_deviations` | `3` | deviations | A window farther than this many standard deviations from the corrected line is left out of it. |
| `ratio_snap_ppm` | `0.05` | ppm | A ratio within this distance of 0 is 0. |
| `stretch_taps` | `32` | taps | Length of the interpolator that stretches B. |
| `stretch_kaiser_beta` | `9` | β | Shape of the interpolator's Kaiser window. |
| `stretch_cutoff_ratio` | `0.96` | ratio | Cutoff of the interpolator, relative to the Nyquist frequency. |
| `stretch_phases` | `1024` | phases | Fractions of a frame at which the interpolator has its taps. |
| `stretch_margin_seconds` | `40` | s | Audio stretched on either side of a chain's core, and least growth of the stretched region. |
| `refit_window_score` | `0.3` | correlation | Least score of a window of a grown portion that fits its line again. |
| `refit_minimum_windows` | `3` | windows | Fewest windows that fit a grown portion's line again. |
| `refit_radius_frames` | `12` | frames | Distance over which each window of a grown portion is placed to fit its line again. |
| `refit_outlier_frames` | `3` | frames | A window farther than this from the refitted line is left out of it. |
| `convergence_frames` | `0.3` | frames | Most distance between the refitted line and the line refined on, at both ends of the portion, for the refinement to stop. |
| `maximum_passes` | `10` | passes | Most refinements of a portion along its line. |

### Measurements

Track B is measured against track A. Frames are counted at `common_sample_rate`.

| Field | Content |
| --- | --- |
| `identical_audio` | `true` when both tracks have an Audio Digest and the digests are equal; absent otherwise. `portions` then holds one primary portion at offset 0, found without a search, unless the tracks have no frames, and its residuals are absent. |
| `portions` | The portions found, each described below; `[]` when there is none. Primary portions come first, then alternates, each in order of A. |
| `unmatched` | `a` and `b`: the ranges of each track that no primary portion covers, each described below. |
| `absent` | `portions`, the reason `portions` is empty; present exactly when it is. |

Each entry of `portions` holds:

- `rank`: `primary`, or `alternate` when better-matching portions cover 90 % or more of
  its range of A, as described above.
- `a` and `b`: the portion's range in each track, as its `start_frame` and its length
  in `frames`; at a ratio other than 0, the two lengths differ.
- `offset`: `frames` and `seconds`, where B is at the portion's first frame of A. A
  positive offset means the range of B starts that many frames later than the range
  of A. `frames` is an integer at a ratio of 0, and otherwise a number to 0.01 frame.
- `speed_ratio_ppm`: the portion's speed ratio, B's frames per frame of A minus one, in
  parts per million, to 0.01 ppm; `0` when B is at the same speed. Frame *n* of A
  lines up with frame *n* + `offset.frames` + `speed_ratio_ppm`·10⁻⁶·(*n* −
  `a.start_frame`) of B. A positive ratio means B holds more frames for the same
  audio: it plays slower, and lower, than A at the same rate.
- `ratio_fit`: how the portion's ratio was set, as **Stretched refinement** above
  describes:
  - `same_speed`: the ratio is 0, however it came to be 0, and only then;
  - `confirmed`: the ratio is not 0, and a refit of its line on B stretched along it
    held within 0.3 frame;
  - `not_converged`: the ratio is not 0, and a refit succeeded but none held, because
    the passes ran out or a later pass ended early; the portion keeps the line of the
    last pass that gave one;
  - `first_ratio`: the ratio is not 0, and no refit succeeded, so it is its chain's
    ratio before stretched refinement, the first ratio, corrected when **Ratio** had
    4 windows or more to correct it: the portion had too few windows of 5 s scoring at
    least 0.3 to refit, as a portion shorter than about 15 s does.

  A merged portion takes the value of the portion whose line it takes.
- `block_gain_residual_db`: the residual after the per-block gains, on the downmix,
  10·log10(Σ*ₖ*Σ(*a* − *gₖ*·*b*)² / Σ*a*²) dB over the blocks *k* of 2048 frames
  counted from the start of the portion. It differs from the residual of `downmix`,
  which uses one gain for the whole portion.
- `downmix`: the values below, measured on the mono downmixes.
- `channels`: the values below for each channel, in order, pairing the channels by
  position; present only when both tracks have the same channel count.
- `absent`: for each of `block_gain_residual_db` and `channels` that is absent, why.

`downmix` and each entry of `channels` hold, over the portion, with *a* and *b* the
samples of A and B:

- `correlation`: the Pearson correlation coefficient of *a* and *b*, from −1 to 1. A
  polarity inversion shows as a negative correlation, which the Report does not
  interpret.
- `gain_db`: the least-squares gain *g* that maps B onto A, *a* ≈ *g*·*b*, as
  20·log10|*g*| dB. Track B at half the amplitude of A gives +6.02 dB. A negative *g*
  has the sign of the correlation.
- `residual_db`: the level of *a* − *g*·*b* relative to A,
  10·log10(Σ(*a* − *g*·*b*)² / Σ*a*²) dB. The lower it is, the less of A the gained
  B leaves unexplained; about 0 dB means B explains none of it.
- `residual_windows`: the residual over each one-second window of the portion, in
  order: its `start_frame` from the start of the portion, its length in `frames`
  (shorter for the last window when the portion is not a whole number of seconds),
  and its `residual_db`.
- `absent`: for each of these values that is absent, why. A window whose residual is
  absent holds its own `absent` with the reason.

Each entry of `unmatched.a` and `unmatched.b` holds a range that no primary portion
covers, in order:

- `start_frame` and `frames`: the range in that track.
- `digitally_silent`: `true` when every sample of every channel in the range is zero,
  at the common rate.
- `level_dbfs`: present only when the range is not digitally silent: the level of the
  range, 10·log10 of the mean power of all its samples of all channels at the common
  rate, in dB relative to full scale.

A value that the audio leaves undefined is absent, never NaN or infinity:

| Absent value | When |
| --- | --- |
| `portions` | The reason in `measurements.absent`: `track A has no frames` or `track B has no frames`; `track A is shorter than one window of 5 s` or `track B is shorter than one window of 5 s`; `the downmix of track A is zero throughout` or `the downmix of track B is zero throughout`; or `no portion was found`. |
| `block_gain_residual_db` | The audio is identical, or *a* − *g*·*b* after the per-block gains is zero throughout the portion. |
| `channels` of a portion | The tracks have different channel counts. |
| `correlation` | A track is constant over the portion. |
| `gain_db` | Track B is zero over the portion, or the gain is exactly zero. |
| `residual_db`, `residual_windows` | The audio is identical, or the gain is undefined. |
| `residual_db` of the portion or of a window | Track A is zero over it, or *a* − *g*·*b* is exactly zero over it. |

### Edition comparisons

A Report of `scope` `editions` has the fields above, with these differences.

Each of `inputs.a` and `inputs.b` is an edition, and holds:

- `evidence_set` and `integrity_baseline`, as an input of two tracks does.
- `tracks`: one entry per track of the edition, in order, each with its `position`,
  from 1, and the fields of an input of two tracks other than `evidence_set` and
  `integrity_baseline`: those of a track input, `track` and the disc image's `path`
  among them, for an acquired set, and those of a file input for an imported set. A
  track's `outcome` is `interpreted`, `failed` or `not_inspected`.
- `excluded`: the files of an imported set left out of its edition, in order, each
  with `path`, `outcome`, always `not_interpreted`, and `reason`; `[]` for an acquired
  set.
- `reason`: present only when the edition has no track because its set's Integrity
  Baseline is unusable, `the Integrity Baseline is unusable`, or its Acquisition
  Record cannot be used, with the reason inspect gives `disc`.

`method.common_sample_rate` is the lowest sample rate of all tracks of both editions,
and absent when nothing is measured.

When nothing is measured, the Report has no `measurements`, and its `absent` holds
`measurements`, the reason: for an edition with no track, `edition A has no track`,
followed by `:` and the edition's `reason` when it has one; for an edition with tracks
that are not interpreted, `the track at position 2 of edition B is not interpreted` or
`the tracks at positions 2 and 5 of edition B are not interpreted`. When both editions
give a reason, the two are joined by `; `.

Otherwise `measurements` measures edition B against edition A, with frames counted at
`common_sample_rate`:

| Field | Content |
| --- | --- |
| `sequences` | `a` and `b`: each track of the edition, in order, with its `position`, its `start_frame` in the edition's sequence, and its length in `frames`. |
| `portions` | The portions found on the two sequences, each described below; `[]` when there is none. Primary portions come first, then alternates, each in order of A. |
| `correspondences` | Each pair of a track of A and a track of B that primary segments join, described below, in order of A's position, then of B's. |
| `unmatched` | `a` and `b`: the ranges of the edition's tracks that no primary portion covers, in order, each with its track's `position` and the fields of an unmatched range of two tracks, its `start_frame` counted from the start of its track. |
| `coverage` | `a` and `b`: `matched_frames`, the frames of the edition's sequence that primary portions cover, each counted once, and `frames`, the frames of its sequence. |
| `absent` | `portions`, the reason `portions` is empty; present exactly when it is. The reasons are those of two tracks, naming an edition instead: `edition A has no frames`, `edition A is shorter than one window of 5 s`, `the downmix of edition A is zero throughout`, the same for B, or `no portion was found`. |

Each entry of `portions` holds `rank`, `a`, `b`, `offset`, `speed_ratio_ppm`,
`ratio_fit`, `block_gain_residual_db` and `absent` as a portion of two tracks does, its
ranges and its offset being in the two sequences, and instead of `downmix` and
`channels`:

- `segments`: the portion split at every track boundary of either edition inside it,
  in order, each with:
  - `a` and `b`: the segment's track in each edition, by its `position`, and the
    segment's range in that track, as its `start_frame` from the track's start and its
    length in `frames`; at a ratio other than 0, the two lengths differ;
  - `offset`: `frames` and `seconds`, where B is within its track at the segment's
    first frame of A, from that frame's position in its own track: a whole number of
    frames at a ratio of 0, and otherwise a number to 0.01 frame;
  - `speed_ratio_ppm`: the portion's ratio;
  - `ratio_fit`: how the portion's ratio was set;
  - `downmix` and `channels`: the values of a portion of two tracks, measured over the
    segment; `channels` is present only when the two tracks have the same channel
    count;
  - `absent`: `channels`, why it is absent, when it is.

The reasons of a segment's absent values name the segment where those of a portion of
two tracks name the portion, such as `track A is constant over the segment`.

Each entry of `correspondences` holds:

- `a` and `b`: the track's `position`, `matched_frames`, the frames of it that the
  pair's primary segments cover, each counted once, and `fraction`, those frames over
  the track's frames.
- `identical_audio`: `true` when both tracks have an Audio Digest and the digests are
  equal; absent otherwise.

`limitations` holds the sentences of a comparison of two tracks, then three more: that
each edition is compared as its tracks joined in order without gap, that the speed
estimate is one per comparison, so a track whose speed differs from that of most
others by more than about 145 ppm may be missed, and that tracks that match do not
establish that the editions are equivalent.

## Leaving out Evidence Set locations

An Evidence Set's absolute path names the collector's disks and often their user
account, which a Report meant for someone else need not say. The option
`--omit-locations` of `copyofa compare` leaves out where each Evidence Set is stored:
neither input has `evidence_set`, and `omitted` lists both pointers, so a reader can
tell "left out" from "never recorded":

```json
"omitted": ["/inputs/a/evidence_set", "/inputs/b/evidence_set"]
```

`omitted` comes right after `compared_at`, before `inputs`. The option applies to both
inputs, and nothing else is left out: each input's `path` in its set, its
`integrity_baseline` (so `manifest_sha256` still identifies the set's Integrity
Baseline), and the comparison time stay. Compare leaves the locations out when it
produces the Report, not in a later step, so the Report is an original and not an
edited copy. Removing locations from a Report already saved means comparing again.

The human-readable result of `compare --omit-locations` shows each track as its path
inside its set, such as `data/04 The Hand That Feeds.flac`, instead of
`<evidence_set>/<path>`, and a track input as `track 1 of data/disc.scram.flac` instead
of `track 1 of <evidence_set>`. Neither it nor the JSON holds the path of either set.
Compare may still name a path given on the command line on stderr, such as in an error.

The schema requires an input's `evidence_set` exactly when `omitted` does not list it.
Without the option, compare prints `"omitted": []`.

## Format version 6

Compare printed format version 6 in CopyOfA 0.9. It is version 7 located with
[ADR 0006](../decisions/0006-locate-matching-portions-between-tracks.md)'s method
alone, each portion at one offset, without
[ADR 0010](../decisions/0010-locate-portions-across-speed-differences.md)'s speed
estimate, ratio and stretched refinement. `copyofa validate` and `copyofa view` still
accept it, and the version 6 schema is unchanged. A Report with `speed_ratio_ppm` or
`ratio_fit` is not valid at version 6. In version 6:

- `format_version` is `6`.
- `method.alignment` is always `windowed_portions`, and `method.parameters` holds
  those up to `equal_residual_floor_db`, without the ones ADR 0010 adds.
- A portion, of two tracks or of two editions, has no `speed_ratio_ppm` or
  `ratio_fit`, its `offset.frames` is always an integer, and its ranges of A and of B
  have the same length. A segment has no `offset`, `speed_ratio_ppm` or `ratio_fit`,
  and its ranges have the same length.
- In place of the three sentences about speed, pitch and short excerpts,
  `limitations` states that speed, pitch and drift differences give no portion. A
  comparison of editions states, in place of the sentence about the speed estimate,
  that where the speeds of two editions differ, even by a few parts per million,
  portions are short and the coverage stays partial.

## Format version 5

Compare printed format version 5 in CopyOfA 0.8. It is version 6 without `scope`:
`format_version` is `5`, and the Report has no `scope`. `copyofa validate` and
`copyofa view` still accept it, and the version 5 schema is unchanged. A Report with
`scope` is not valid at version 5.

## Format version 4

Compare printed format version 4 in CopyOfA 0.6 and 0.7. It is version 5 without error
ranges: `format_version` is `4`, and no input's `track` holds `error_ranges`.
`copyofa validate` and `copyofa view` still accept it, and the version 4 schema is
unchanged. A Report with `error_ranges` is not valid at version 4.

## Format version 3

Compare printed format version 3 in CopyOfA 0.5. It differs from versions 4 to 6 in
`method` and `measurements`, from versions 5 and 6 also in its inputs, whose `track`
never holds `error_ranges`, and from version 6 in having no `scope`; `omitted` and
the other fields are the same.
`copyofa validate` and `copyofa view` still accept it, and the version 3 schema is
unchanged. A Report with `portions` is not valid at version 3. In version 3:

- `format_version` is `3`.
- `method.alignment` is always `downmix_cross_correlation`: one global offset, at the
  lag with the largest magnitude of the FFT cross-correlation of the mono downmixes,
  in whole frames at the common rate. `method` has no `parameters`.
- `measurements` holds `identical_audio`, `offset` (`frames` and `seconds`, as
  `offset` of a portion), `overlap`, `downmix`, `channels` and `absent`, and no
  `portions` or `unmatched`. `overlap` gives, for `a` and `b`, where the aligned
  tracks overlap: its `start_frame`, its length in `frames` (the same for both), and
  the `fraction` of the track it covers.
- `downmix` and `channels` are measured over the overlap, not over a portion, and
  their `residual_windows` count `start_frame` from the start of the overlap. With
  identical audio, the offset is 0 and the residual is absent.
- `absent` holds a reason for each of `offset`, `overlap` and `channels` that is
  absent: `offset`, `overlap` and every value of `downmix` and `channels` are absent
  when a track has no frames or, for audio that is not identical, a downmix is zero
  throughout. The reasons for the other values say "overlap" where versions 4 to 6
  say "portion".
- `limitations` state that one global offset aligns the tracks, and not the limits of
  the search for portions.

## Format version 2

Compare printed format version 2 in CopyOfA 0.4. It is [version 3](#format-version-3)
without track
inputs: `format_version` is `2`, no input holds `track`, and each input's `path` is
always present. `copyofa validate` and `copyofa view` still accept it, and the version
2 schema is unchanged. A Report with `track` is not valid at version 2.

## Format version 1

Compare printed format version 1 before CopyOfA 0.4.0. It is version 2 without
`omitted`: `format_version` is `1`, and each input's `evidence_set` is always present.
`copyofa validate` and `copyofa view` still accept it, and the version 1 schema is
unchanged. A Report with `omitted` is not valid at version 1.

## Example

Track 4 of an acquired set of *Add Violence* (2017 CD) against track 4 of the 2025
digital reissue (24-bit, 48 kHz FLAC), with track input A:

```json
{
  "report_kind": "copyofa.comparison",
  "format_version": 7,
  "scope": "tracks",
  "copyofa_version": "0.10.0",
  "compared_at": "2026-10-26T03:15:12Z",
  "omitted": [],
  "inputs": {
    "a": {
      "evidence_set": "/Volumes/Archive/Add Violence CD",
      "integrity_baseline": {
        "manifest_sha256": "8c86…",
        "usable": true,
        "problems": []
      },
      "path": "data/disc.scram.flac",
      "track": {
        "number": 4,
        "first_frame": 59373288,
        "frame_count": 8234940,
        "error_ranges": []
      },
      "outcome": "interpreted",
      "expected_digest": "4ad6…",
      "observed_digest": "4ad6…",
      "format": "flac",
      "encoding": "pcm_16",
      "sample_rate": 44100,
      "channels": 2,
      "bits_per_sample": 16,
      "frames": 8234940,
      "audio_digest": "pcm1:44100:2:16:a4c1…",
      "peak": [32768, 32768],
      "leading_silence_frames": 0,
      "trailing_silence_frames": 0
    },
    "b": {
      "evidence_set": "/Volumes/Archive/Add Violence",
      "integrity_baseline": {
        "manifest_sha256": "a871…",
        "usable": true,
        "problems": []
      },
      "path": "data/01-04 Not Anymore.flac",
      "outcome": "interpreted",
      "expected_digest": "416f…",
      "observed_digest": "416f…",
      "format": "flac",
      "encoding": "pcm_24",
      "sample_rate": 48000,
      "channels": 2,
      "bits_per_sample": 24,
      "frames": 9196800,
      "audio_digest": "pcm1:48000:2:24:aeb2…",
      "peak": [8136205, 8135850],
      "leading_silence_frames": 0,
      "trailing_silence_frames": 0,
      "flac_md5_signature": "absent"
    }
  },
  "method": {
    "decoder": "libsndfile",
    "decoder_version": "1.2.2",
    "resampler": "libsoxr",
    "resampler_version": "0.1.3-14-ga66f3ee",
    "resampler_quality": "VHQ",
    "common_sample_rate": 44100,
    "alignment": "speed_tolerant_portions",
    "parameters": {
      "decimation_factor": 16,
      "decimation_quality": "HQ",
      "first_difference_coefficient": 0.5,
      "window_seconds": 5,
      "hop_seconds": 5,
      "silent_window_energy_ratio": 0.0001,
      "b_position_energy_floor": 1e-10,
      "candidate_threshold": 0.4,
      "candidates_per_window": 3,
      "candidate_separation_seconds": 0.5,
      "skipped_windows": 1,
      "chaining_tolerance_frames": 32,
      "core_ratio": 0.85,
      "core_seconds": 20,
      "refinement_radius_frames": 32,
      "block_frames": 2048,
      "matched_block_residual_ratio": 0.2,
      "core_confirming_ratio": 0.5,
      "evidence_floor_dbfs": -80,
      "silence_against_signal_dbfs": -60,
      "end_range_inside_blocks": 8,
      "end_range_outside_blocks": 1,
      "acceptance_residual_db": -10,
      "minimum_portion_seconds": 1,
      "merge_tolerance_frames": 2,
      "alternate_margin_db": 3,
      "alternate_coverage_ratio": 0.9,
      "equal_residual_floor_db": -60,
      "estimate_decimation_factors": [128, 16],
      "estimate_windows": [8, 12],
      "estimate_range_ppm": 45000,
      "estimate_steps_ppm": [1500, 200],
      "estimate_span_ppm": 1000,
      "estimate_adoption_score": 0.25,
      "first_line_outlier_frames": 32,
      "first_ratio_stretch_ppm": 20,
      "ratio_windows": 12,
      "ratio_minimum_windows": 4,
      "ratio_radius_frames": 40,
      "ratio_window_score_ratio": 0.5,
      "ratio_outlier_frames": 4,
      "ratio_outlier_deviations": 3,
      "ratio_snap_ppm": 0.05,
      "stretch_taps": 32,
      "stretch_kaiser_beta": 9,
      "stretch_cutoff_ratio": 0.96,
      "stretch_phases": 1024,
      "stretch_margin_seconds": 40,
      "refit_window_score": 0.3,
      "refit_minimum_windows": 3,
      "refit_radius_frames": 12,
      "refit_outlier_frames": 3,
      "convergence_frames": 0.3,
      "maximum_passes": 10
    }
  },
  "measurements": {
    "portions": [
      {
        "rank": "primary",
        "a": {
          "start_frame": 180743,
          "frames": 8053618
        },
        "b": {
          "start_frame": 215689,
          "frames": 8053618
        },
        "offset": {
          "frames": 34946,
          "seconds": 0.7924263038548753
        },
        "speed_ratio_ppm": 0.0,
        "ratio_fit": "same_speed",
        "block_gain_residual_db": -22.031079860026253,
        "downmix": {
          "correlation": 0.996859930941858,
          "gain_db": 0.17258339349911697,
          "residual_db": -22.027127851256214,
          "residual_windows": [
            {
              "start_frame": 0,
              "frames": 44100,
              "residual_db": -14.254952251218452
            },
            {
              "start_frame": 44100,
              "frames": 44100,
              "residual_db": -25.7788955812312
            }
          ]
        },
        "channels": [
          {
            "correlation": 0.9964346736830453,
            "gain_db": 0.16887083154952615,
            "residual_db": -21.476451970147288,
            "residual_windows": [
              {
                "start_frame": 0,
                "frames": 44100,
                "residual_db": -14.21993421849833
              }
            ]
          },
          {
            "correlation": 0.9970458322784992,
            "gain_db": 0.17422724464395617,
            "residual_db": -22.29176581443863,
            "residual_windows": [
              {
                "start_frame": 0,
                "frames": 44100,
                "residual_db": -14.261034741456669
              }
            ]
          }
        ]
      },
      {
        "rank": "alternate",
        "a": {
          "start_frame": 986278,
          "frames": 77805
        },
        "b": {
          "start_frame": 1777223,
          "frames": 77805
        },
        "offset": {
          "frames": 790945,
          "seconds": 17.935260770975056
        },
        "speed_ratio_ppm": 0.0,
        "ratio_fit": "same_speed",
        "block_gain_residual_db": -15.019716761815886,
        "downmix": {
          "correlation": 0.9831640250215374,
          "gain_db": -0.06247275865201059,
          "residual_db": -14.764025652478612,
          "residual_windows": [
            {
              "start_frame": 0,
              "frames": 44100,
              "residual_db": -15.408633596777289
            },
            {
              "start_frame": 44100,
              "frames": 33705,
              "residual_db": -13.965842497247705
            }
          ]
        },
        "channels": [
          {
            "correlation": 0.9836046127542462,
            "gain_db": -0.05836424650597183,
            "residual_db": -14.87822744416375,
            "residual_windows": [
              {
                "start_frame": 0,
                "frames": 44100,
                "residual_db": -15.510480197953989
              },
              {
                "start_frame": 44100,
                "frames": 33705,
                "residual_db": -14.089329066628428
              }
            ]
          },
          {
            "correlation": 0.9827297376306026,
            "gain_db": -0.06607907358359948,
            "residual_db": -14.654369543351907,
            "residual_windows": [
              {
                "start_frame": 0,
                "frames": 44100,
                "residual_db": -15.308154125421096
              },
              {
                "start_frame": 44100,
                "frames": 33705,
                "residual_db": -13.85453140244729
              }
            ]
          }
        ]
      }
    ],
    "unmatched": {
      "a": [
        {
          "start_frame": 0,
          "frames": 180743,
          "digitally_silent": false,
          "level_dbfs": -36.77583985814157
        },
        {
          "start_frame": 8234361,
          "frames": 579,
          "digitally_silent": false,
          "level_dbfs": -11.76307533610161
        }
      ],
      "b": [
        {
          "start_frame": 0,
          "frames": 215689,
          "digitally_silent": false,
          "level_dbfs": -31.061533712318802
        },
        {
          "start_frame": 8269307,
          "frames": 180253,
          "digitally_silent": false,
          "level_dbfs": -20.795944160919614
        }
      ]
    }
  },
  "limitations": [
    "No measurement says whether the tracks share a master, a mix or a source; …",
    "MP3 is lossy: the measurements of an MP3 depend on its decoder.",
    "Tracks at different sample rates are compared at the lower rate, after …",
    "Portions shorter than about 2.5 s may be missed, and the search finds no …",
    "Speed differences up to ±4.5 % are found, each portion at its own constant …",
    "Pitch is not corrected: a speed ratio changes speed and pitch together. …",
    "A short excerpt at a different speed may be missed.",
    "A boundary inside audio below -80 dBFS is placed at the nearest frame …",
    "A boundary at a fade falls about three blocks of 2048 frames inside it, where …",
    "In music that repeats a section, one range of a track can match several …",
    "Channels are paired in the order each file stores them."
  ]
}
```

The example is shortened: a Report holds all 64 hexadecimal digits of each digest,
every residual window, not just the first ones, and the whole of each limitation. It
also holds all seven portions: three primary, four alternate. The example keeps the
first, and the fourth, an alternate. The primary portion covers A from 4.098 s to
186.720 s, and B starts 34946 frames, about 0.792 s, later. The first 4.1 s of A and
the first 4.9 s of B, and the last 4.1 s of B, at −20.8 dBFS, match no primary
portion.

## Viewing a Report

`copyofa view <report>` prints a comparison Report as one HTML page, which a reader
opens in any browser, without CopyOfA and offline. Save it with a shell redirect:

```bash
copyofa view htf.json > htf.html
```

View first validates the file as [`copyofa validate`](validation-result.md) does, and
refuses a Report that is invalid, unsupported, or of another kind. It supports
comparison Reports only, of format version 1, 2, 3, 4, 5, 6 or 7, and renders each
version, and from version 6 each scope, with its own layout: a version 6 Report of
scope `tracks` with version 5's layout, plus its scope, and one of scope `editions`
with the edition layout below; a version 7 Report with version 6's layout of its
scope, plus the offset, speed ratio and how it was set of each portion and segment. It
also refuses a valid comparison Report of any other format version, such as one a
later CopyOfA printed, rather than show it with a layout that could leave fields out:
it prints nothing on stdout and one line on stderr naming the file, its format version
and the versions view supports, and exits 1. It refuses a Report of a scope it has no
layout for the same way: the line names the file and its scope, and the scopes view
supports.

The page shows every field of the Report with its value as the Report records it, and
adds only labels and units, for each track a duration computed from its frames and
sample rate, for versions 4 to 7 each range also in seconds, computed from its frames
and the common sample rate, and for an edition comparison each edition's coverage also
as durations, computed the same way, and each track's name, as the inputs give it,
beside its position. For a comparison of tracks, it gives:

- the SHA-256 of the exact bytes of the file it was generated from, the Report's kind
  and format version, for versions 6 and 7 its scope, and the CopyOfA version that
  generated
  the page, which is not the Report's own `copyofa_version`, also shown;
- what the Report leaves out: its `omitted` list, or that it holds none, and for
  version 1 that the Report has no such field;
- for each input, its Evidence Set location, or that it is left out, Integrity
  Baseline, path, track number, first frame and frame count, outcome and reason,
  properties, File Digests, Audio Digest, peak, silence, FLAC MD5 signature and
  limitations;
- for versions 5 to 7, for each track input, how many error ranges its `track`
  holds, or that it holds none, and a table of them, one row each in the Report's
  order: offset from the track's first frame, frames, and state;
- the method, and for versions 4 to 7 a table of its parameters, each by its name in
  the Report, a parameter with one value per stage, from version 7, as its values in
  order;
- for versions 1 to 3, the measurements: identical audio, offset, overlap, and for the
  downmix and each channel the correlation, gain and residual, with one table of
  residual windows for each of them;
- for versions 4 to 7, the measurements:
  - identical audio, and how many portions the Report holds, or why it holds none;
  - a table of the portions, in the Report's order, one row each: rank, start frame
    and frames in A and in B, offset in frames and seconds, for version 7 at the
    portion's first frame and followed by its speed ratio in ppm and how it was set,
    residual after the per-block gains, and the correlation, gain and residual of the
    downmix;
  - for each portion, the correlation, gain and residual of the downmix and of each
    channel, with one table of residual windows for each of them;
  - for each track, its unmatched ranges: start frame, frames, whether the range is
    digitally silent, and its level, or "no level (digitally silent)" for a silent
    range, which has none; or that the track has no unmatched range;
- each absent value, marked absent with its reason; when the Report holds no
  measurements, the page says that the tracks were not measured;
- the Report's limitations, word for word.

For a comparison of editions, a version 6 or 7 Report of scope `editions`, the page
gives
the same Report details and what it leaves out, the method with its parameters, then:

- for each edition, its Evidence Set location, or that it is left out, Integrity
  Baseline, how many tracks and excluded files it holds, and the reason it has no
  track, when the Report gives one;
- for each track of each edition, in the Report's order, its position and every field
  a track input of a comparison of tracks shows, error ranges included;
- for each edition, its excluded files, one row each: path, outcome and reason; or
  that it has none;
- when the Report holds no measurements, that the editions were not measured, and the
  reason the Report gives;
- otherwise, the measurements:
  - how many portions the Report holds, or why it holds none;
  - the coverage of each edition: the frames found in the other edition, each counted
    once, and the frames of the edition;
  - a table of the correspondences, one row each: each track's position and name, its
    frames found in the other edition and their fraction, and whether the audio is
    identical;
  - each edition's sequence, one row per track: position, name, start frame in the
    sequence, frames, and range in seconds;
  - a table of the portions, one row each: rank, start frame and frames in A and in
    B, offset in frames and seconds, for version 7 at the portion's first frame and
    followed by its speed ratio in ppm and how it was set, residual after the per-block
    gains, and how many segments it holds;
  - for each portion, a table of its segments, one row each: in A and in B the
    track's position and name, the start frame and frames in the track, and its range
    in seconds, for version 7 the segment's offset at its first frame, in frames and
    seconds, its speed ratio in ppm and how it was set, then the correlation, gain and
    residual of the downmix; and for each segment, the values of the downmix, and of
    each channel when the Report gives them, with one table of residual windows for
    each of them;
  - for each track of each edition, its unmatched ranges, as for a comparison of
    tracks, or that it has none;
- each absent value, marked absent with its reason;
- the Report's limitations, word for word.

The page draws no conclusion from the measurements: it has no verdict and no
threshold, and does not color a value as good or bad.

The page is self-contained and inert. It is one HTML5 document in UTF-8 with its
styles inline. It has no script, no link and no external resource, and a Content
Security Policy that forbids both. Every text of the Report is escaped. A character
that could hide or reorder text, such as a control character, a bidirectional
override, or a lone surrogate for a path byte that is not valid UTF-8, appears as its
escape, such as `\udc80`; spaces such as U+00A0 appear as they are.

View exits 0 when it printed the page, and 1 when the file cannot be read or the
Report is invalid, unsupported, not a comparison Report, or of a format version or a
scope view does not render, with the reason on stderr and nothing on stdout. It exits
2 for invalid arguments and 130 when canceled with Ctrl-C. It also exits 1, with
`copyofa: stdout closed` on stderr, when stdout is closed before or while it prints the
page. It has no `--json` option and writes no file.

## Exit codes

`copyofa compare` exits 0 when both inputs are `interpreted` and were compared, whether
or not it found a portion, even when a value is absent. It exits 1 when either input is
`not_inspected`, `failed` or `not_interpreted`, and still prints its result or Report,
without measurements. For two editions, it exits 0 when they were measured, and 1 when
nothing was measured: a track of either edition is not `interpreted`, or an edition
has no track. It exits 2, printing nothing on stdout, when a file is not under the
`data/` directory of an Evidence Set, an input given with `--track-a` or `--track-b` is
not an Evidence Set, a set root is given without its option and the other input is not
a set root given without its option, or the arguments are invalid, such as a track
number that is not a whole number
from 1, and 130 when canceled with Ctrl-C. It also exits 1, with
`copyofa: stdout closed` on stderr, when stdout is closed before or while it prints its
result or Report. mpg123 may write notes about damaged MP3 frames to stderr.
