# Comparison Report format

`copyofa compare <input-a> <input-b> [--track-a <number>] [--track-b <number>] --json`
prints a comparison Report: a JSON document measuring how the audio of two tracks
preserved in [Evidence Sets](evidence-set.md) relates. Each input is a file in a set,
or, with `--track-a` or `--track-b`, a track of an
[acquired set](evidence-set.md#acquired-sets). Like every `--json` output of CopyOfA, it
is UTF-8, whatever the locale; a path that is not valid UTF-8 keeps each invalid byte as
a `\udcXX` escape (see [Import result](evidence-set.md#import-result)). Save it with a
shell redirect:

```bash
copyofa compare "/Volumes/Archive/With Teeth/data/04 The Hand That Feeds.flac" \
  "/Volumes/Archive/Definitive NIN/data/18 The Hand That Feeds.mp3" --json > htf.json
copyofa compare "/Volumes/Archive/Add Violence CD" \
  "/Volumes/Archive/Add Violence/data/01-01 Less Than.flac" --track-a 1 --json \
  > less-than.json
```

A Report holds measurements: the portions of track A found in track B, each with its
offset, correlation, gain and residual, and the audio that only one track holds. It
draws no conclusion from them, such as "same master" or "match".
[ADR 0003](../decisions/0003-measure-track-comparisons-on-aligned-decoded-audio.md)
records how the tracks are decoded and measured, and
[ADR 0006](../decisions/0006-locate-matching-portions-between-tracks.md) how portions
are located and why that method was chosen.

It has five format versions, each with its JSON Schema:
[comparison-report-5.schema.json](../../src/copyofa/schemas/comparison-report-5.schema.json)
for version 5, which this document describes and `compare` prints,
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
   Set, else compare exits 2. A set root given without the option is refused as any
   path outside `data/`: compare exits 2.
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
   portion is a range of A that appears in B at one offset. When both tracks have an
   Audio Digest and the digests are equal, there is no search: one primary portion
   covers both tracks at offset 0. Otherwise compare searches with the fixed
   [parameters](#parameters) below, in these stages:
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
     window holds no frame of the decimated audio.
   - **Offset.** Chains are refined at the common rate, strongest first. A chain whose
     windows all lie inside a portion already found at an offset within 32 frames of
     its strongest window's is not refined again. The core of a chain is its strongest
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
   - **Holes.** Windows of the chain left outside the portion are refined again, so a
     portion after a hole is kept.
   - **Acceptance.** A portion is kept when it is at least 1 s long and its residual
     after the per-block gains, 10·log10(Σ*ₖ*Σ(*a* − *gₖ*·*b*)² / Σ*a*²) over its blocks
     *k*, counted from its start, is at most −10 dB. A portion whose residual is
     undefined because *a* − *gₖ*·*b* is zero throughout is kept.
   - **Merging and ranking.** Portions whose offsets differ by at most 2 frames and
     whose ranges of A overlap or touch are merged; the merged portion takes the offset
     of the longer one. A portion is an alternate when portions whose residual after
     the per-block gains is at least 3 dB lower cover 90 % or more of its range of A.
     For that comparison, residuals below −60 dB and undefined ones count as −60 dB, so
     exact repeats tie and are all primary. Compare reports every portion, primaries
     first, then alternates, each in order of A.
5. **Measurements.** Compare measures each portion over its ranges: the correlation,
   the gain and the residual on the downmix, and for each channel when both tracks
   have the same channel count, with the residual of each one-second window.
6. **Unmatched audio.** The ranges of A and of B that no primary portion covers are
   reported, each with whether it is digitally silent and, when it is not, its level.
   Alternates do not shrink them. Compare measures both on the samples at the common
   rate. When it finds no portion, the Report says why, and each track is one
   unmatched range.

The search finds no portion in a track shorter than 5 s, identical audio excepted, and
may miss a portion shorter than about 2.5 s. A speed, pitch or drift difference gives
no portion. A boundary at a fade falls about three blocks inside it, where the gain
fitted over the eight blocks inside the edge stops fitting the faded audio, not where
the fade gets quiet; a boundary at a crossfade falls where the other audio refutes the
match. In music that repeats a section, one range of A matches several places in B,
and each is a portion. The Report's `limitations` state this.

Compare writes nothing into either set.

## Fields

| Field | Content |
| --- | --- |
| `report_kind` | Always `copyofa.comparison`. |
| `format_version` | The version of this format, `5`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that ran the comparison. |
| `compared_at` | The comparison time in UTC, such as `2026-10-25T18:30:00Z`. |
| `omitted` | The JSON Pointers of the values the Report leaves out, each of `/inputs/a/evidence_set` and `/inputs/b/evidence_set` at most once; `[]` when it leaves out nothing. See [Leaving out Evidence Set locations](#leaving-out-evidence-set-locations). |
| `inputs` | `a` and `b`: each input, described below. |
| `method` | How the tracks were decoded, resampled and searched for portions, described below. |
| `measurements` | The measurements, described below; absent when either input is not `interpreted`. |
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
| `alignment` | Always `windowed_portions`: the tracks are aligned by portions, each at its own offset, found with the windows and blocks described above. |
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
  in `frames`, the same for both.
- `offset`: `frames`, an integer, and `seconds`. A positive offset means the range of B
  starts that many frames later than the range of A: frame *n* of A lines up with frame
  *n* + `frames` of B.
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

## Format version 4

Compare printed format version 4 in CopyOfA 0.6 and 0.7. It is version 5 without error
ranges: `format_version` is `4`, and no input's `track` holds `error_ranges`.
`copyofa validate` and `copyofa view` still accept it, and the version 4 schema is
unchanged. A Report with `error_ranges` is not valid at version 4.

## Format version 3

Compare printed format version 3 in CopyOfA 0.5. It differs from versions 4 and 5 in
`method` and `measurements`, and from version 5 also in its inputs, whose `track`
never holds `error_ranges`; `omitted` and the other fields are the same.
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
  throughout. The reasons for the other values say "overlap" where versions 4 and 5
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
  "format_version": 5,
  "copyofa_version": "0.8.0",
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
    "alignment": "windowed_portions",
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
      "equal_residual_floor_db": -60
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
    "Speed, pitch and drift differences give no portion.",
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
comparison Reports only, of format version 1, 2, 3, 4 or 5, and renders each version
with its own layout. It also refuses a valid comparison Report of any other format
version, such as one a later CopyOfA printed, rather than show it with a layout that
could leave fields out: it prints nothing on stdout and one line on stderr naming the
file, its format version and the versions view supports, and exits 1.

The page shows every field of the Report with its value as the Report records it, and
adds only labels and units, for each track a duration computed from its frames and
sample rate, and for versions 4 and 5 each range also in seconds, computed from its
frames and the common sample rate. It gives:

- the SHA-256 of the exact bytes of the file it was generated from, the Report's kind
  and format version, and the CopyOfA version that generated the page, which is not
  the Report's own `copyofa_version`, also shown;
- what the Report leaves out: its `omitted` list, or that it holds none, and for
  version 1 that the Report has no such field;
- for each input, its Evidence Set location, or that it is left out, Integrity
  Baseline, path, track number, first frame and frame count, outcome and reason,
  properties, File Digests, Audio Digest, peak, silence, FLAC MD5 signature and
  limitations;
- for version 5, for each track input, how many error ranges its `track` holds, or
  that it holds none, and a table of them, one row each in the Report's order: offset
  from the track's first frame, frames, and state;
- the method, and for versions 4 and 5 a table of its parameters, each by its name in
  the Report;
- for versions 1 to 3, the measurements: identical audio, offset, overlap, and for the
  downmix and each channel the correlation, gain and residual, with one table of
  residual windows for each of them;
- for versions 4 and 5, the measurements:
  - identical audio, and how many portions the Report holds, or why it holds none;
  - a table of the portions, in the Report's order, one row each: rank, start frame
    and frames in A and in B, offset in frames and seconds, residual after the
    per-block gains, and the correlation, gain and residual of the downmix;
  - for each portion, the correlation, gain and residual of the downmix and of each
    channel, with one table of residual windows for each of them;
  - for each track, its unmatched ranges: start frame, frames, whether the range is
    digitally silent, and its level, or "no level (digitally silent)" for a silent
    range, which has none; or that the track has no unmatched range;
- each absent value, marked absent with its reason; when the Report holds no
  measurements, the page says that the tracks were not measured;
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
Report is invalid, unsupported, not a comparison Report, or of a format version view
does not render, with the reason on stderr and nothing on stdout. It exits 2 for
invalid arguments and 130 when canceled with Ctrl-C. It also exits 1, with
`copyofa: stdout closed` on stderr, when stdout is closed before or while it prints the
page. It has no `--json` option and writes no file.

## Exit codes

`copyofa compare` exits 0 when both inputs are `interpreted` and were compared, whether
or not it found a portion, even when a value is absent. It exits 1 when either input is
`not_inspected`, `failed` or
`not_interpreted`, and still prints its result or Report, without measurements. It
exits 2, printing nothing on stdout, when a file is not under the `data/` directory
of an Evidence Set, an input given with `--track-a` or `--track-b` is not an Evidence
Set, or the arguments are invalid, such as a track number that is not a whole number
from 1, and 130 when canceled with Ctrl-C. It also exits 1, with
`copyofa: stdout closed` on stderr, when stdout is closed before or while it prints its
result or Report. mpg123 may write notes about damaged MP3 frames to stderr.
