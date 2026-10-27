# Brief: Acquire Damaged Discs

## Goal and context

A collector preserves a CD that keeps read errors after acquire re-reads it, instead of
losing everything the reading produced. The set holds the disc as the drive read it,
and every command that uses its tracks says which frames were not read successfully.

- **Milestone:** [v0.8.0](https://github.com/jmfontaine/copyofa/milestone/8)
- **Product Map capabilities:**
  [Acquire Audio and Record Its Origins](../product-map.md#acquire-audio-and-record-its-origins)
  and
  [Preserve Evidence Throughout Its Lifetime](../product-map.md#preserve-evidence-throughout-its-lifetime)
- **Decision:**
  [ADR 0008: Keep discs with read errors as read](../decisions/0008-keep-discs-with-read-errors-as-read.md)

v0.7.0 made acquire re-read sectors with errors (ADR 0007). A disc whose errors remain
still yields nothing: redumper refuses to split a pressed CD with an error left inside
a track, and acquire deletes the reading. During v0.7.0, a pressed CD that looks
undamaged kept 9 C2 samples in two sectors of track 8 and could not be preserved.

## Primary scenario

Refines [S1](../product-map.md#s1-preserve-a-cd):

1. A collector runs `copyofa acquire --to ~/Archive/damaged-cd`. The disc keeps C2
   errors in two sectors of track 8 after 20 re-reads.
2. Acquire accepts the set and exits 1. stderr says the disc was read with errors; the
   result lists track 8 with its frames not read successfully. The Acquisition Record
   gives track 8's affected frame ranges.
3. `copyofa inspect ~/Archive/damaged-cd` reports every track, and for track 8 the same
   ranges.
4. `copyofa compare ~/Archive/damaged-cd --track-a 8 <another copy>` records the ranges
   with input A, so a reader of the Report knows which part of track 8 is unreliable.
5. `copyofa export ~/Archive/damaged-cd --to ~/Music/damaged-cd` writes all tracks and
   warns on stderr that track 8 holds frames not read successfully, with their ranges.

## In scope

- Acquire runs redumper with `--force-split --leave-unchanged` on every disc (ADR
  0008).
- Acquisition Record format version 2, with each track's error ranges; documented in
  `docs/formats/evidence-set.md`.
- Inspect, compare and export read record versions 1 and 2.
- Inspection Report format version 3 and comparison Report format version 5, which add
  the error ranges of a track; their schemas; view renders version 5.
- Export's warning on stderr for a track with error ranges.

## Out of scope

- Repairing, interpolating or muting unreliable frames, in the set or in exported
  files.
- Combining several readings, from one drive or several, into one set.
- Changing the retry count's default, or other redumper options.
- New fields in the export result; the warning is on stderr only.
- Changing verify, import or validate.
- Discs other than plain audio CDs, which stay in the Later outcome Acquire More Kinds
  of Disc.

## Requirements

### Acquire

- **Reading.** Acquire passes `--force-split --leave-unchanged` to `redumper disc`,
  after `--retries`; the record's `reader.arguments` lists them.
- **Tracks.** Each track's range must still hold exactly redumper's track file. The
  failure that names redumper's generated sectors becomes unreachable and is removed,
  with its documentation.
- **Error ranges.** For each track, acquire reads the state over the track's range and
  records the maximal runs of frames whose state is 0 (not read) or 1 (read with a C2
  error), in order.
- **Exit and result.** A set with any track error range is accepted with exit 1, as a
  disc read with errors already is. The text result's track line keeps its count of
  frames not read successfully.

### Acquisition Record format version 2

Version 1 with one field added to each track, `error_ranges`: a list, empty when the
track has no error, of objects with:

- `first_frame`: the range's first frame, counted from the track's first frame;
- `frame_count`: its length in frames;
- `state`: `not_read` or `c2_error`.

`error_frames` stays, and equals the sum of the ranges' `frame_count`. A record of
version 1 keeps being read: its tracks have no `error_ranges`.

### Inspect

- **Inspection Report format version 3** is version 2 with `error_ranges` added to each
  entry of `disc.tracks`, copied from a version 2 record; absent when the record is
  version 1.
- Inspect's exit status does not change: a track with error ranges that decodes to its
  recorded Audio Digest is `interpreted`, and the set is as acquired.
- Inspect's text result names each track with error ranges.

### Compare

- **Comparison Report format version 5** is version 4 with `error_ranges` added to an
  input's `track`, from a version 2 record; absent otherwise.
- View renders version 5, showing the ranges of each track input.

### Export

- Export writes every track, as today. For each track with error ranges, stderr gets
  `copyofa: warning: track <n> has <count> frames not read successfully`, followed by
  its ranges. The exit status stays 0 when every track was exported.

## Design decisions

- **Reading as read:** decided by ADR 0008.
- **Ranges relative to the track.** A range counted from the track's first frame can be
  read without knowing the image, and matches how inspect, compare and export address a
  track.
- **Inspect and export exit 0 for a damaged track.** Acquire already exits 1 for the
  disc. Inspect checks that the set is as acquired, which it is; export writes what was
  acquired. Both warn instead.
- **New format versions, not changed ones,** for the record and both Reports, as ADR
  0004 requires for Reports.

## Blocking questions

None. One technical point is confirmed during implementation (see Stop rule).

## Stop rule

Stop and report before implementing ranges if redumper b768, with
`--force-split --leave-unchanged`, writes a track file that is not a range of the image
for a sector with errors, or if the image holds anything but zeros for a sector the
drive never read. Confirm both against redumper's source (`cd/cd_split.ixx`,
`cd/cd_dump.ixx`) before writing the stand-in's behavior.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Tests of
acquire run the stand-in `redumper`, which learns `--force-split --leave-unchanged` as
redumper b768 behaves with them.

- **AC1 — Acquired with errors.** A synthetic disc whose state marks frames of track 2
  as not read and others as read with C2 errors is accepted; its record, at format
  version 2, gives track 2's `error_ranges` exactly, with their states, other tracks
  empty lists, and `error_frames` equal to the ranges' total; acquire exits 1.
  redumper received `--force-split --leave-unchanged`.
- **AC2 — Unchanged for a clean disc.** A synthetic disc read without error gives a
  version 2 record whose tracks have empty `error_ranges`, and acquire exits 0.
- **AC3 — Old records.** Inspect, compare and export of a set with a version 1 record
  behave as before: no `error_ranges` in the Reports, no warning.
- **AC4 — Inspect.** Inspect of AC1's set prints a version 3 Report whose track 2 holds
  the record's ranges, exits 0, and names track 2 in its text result.
- **AC5 — Compare.** Compare with `--track-a 2` on AC1's set prints a version 5 Report
  whose input A's `track` holds the ranges. View renders it with the ranges.
- **AC6 — Export.** Export of AC1's set writes every track with its recorded Audio
  Digest, warns on stderr for track 2 with its ranges, and exits 0.
- **AC7 — Schemas.** The inspection Report version 3 and comparison Report version 5
  schemas ship in the package; validate and view accept them; every Report the test
  suite produces validates.
- **AC8 — Documented.** `docs/formats/evidence-set.md` documents record version 2 and
  removes the generated-sector failure; the inspection and comparison Report documents
  document their new versions; `docs/formats/export-result.md` the warning; the README
  and AGENTS.md describe acquire's new options.
- **AC9 — A real disc (by hand, once).** A disc that keeps errors after the re-reads,
  such as the pressed CD of the context, is acquired on the maintainer's drive. Acquire
  exits 1; the record gives the affected track's ranges, consistent with redumper's log;
  verify passes; inspect and export report the same ranges, and export's files play.

## Manifesto alignment

- **Useful partial evidence is kept:** a disc with a few unreliable sectors is
  preserved instead of discarded.
- **Evidence, identity, and conclusions are distinct:** the audio is kept as read and
  never repaired; the record locates what was not read successfully.
- **Accuracy must remain usable:** every command that uses a track says where it is
  unreliable.

## Appetite and scope cuts

Appetite: a few hours to a day.

If the work outgrows it, cut in this order, keeping acquired sets with error ranges in
their record and export's warning:

1. Compare's ranges, with comparison Report format version 5 and its view.
2. Inspect's ranges, with inspection Report format version 3; inspect's text result
   still names the affected tracks from the record.

## What needs the maintainer

1. This brief and ADR 0008, before implementation starts.
2. AC9, acquiring a disc that keeps errors, by hand.
3. Merges and the release.
