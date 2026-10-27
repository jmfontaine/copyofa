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
   gives track 8's error ranges.
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
  `docs/formats/evidence-set.md`, with how to restore and split such a set again.
- Inspect, compare and export read record versions 1 and 2.
- Inspection Report format version 3 and comparison Report format version 5, which add
  a track's error ranges; their schemas; view renders version 5.
- Export's warning on stderr for a track with error ranges.

## Out of scope

- Repairing, interpolating or muting unreliable frames, in the set or in exported
  files.
- Combining several readings, from one drive or several, into one set.
- Changing the retry count's default, or other redumper options.
- New fields in the export result; the warning is on stderr only.
- Changing verify, import or validate.
- A disc whose last track is never read through to the end of the image (see Known
  limit).
- Discs other than plain audio CDs, which stay in the Later outcome Acquire More Kinds
  of Disc.

## What redumper does

Confirmed in redumper b768's source; ADR 0008 relies on it.

- `--force-split` skips only the refusal after redumper checks the tracks for errors
  (`cd/cd_split.ixx`); offsets, the table of contents and sessions are handled as
  before, and acquire still refuses discs with several sessions or a data track.
- `--leave-unchanged` stops redumper from generating sectors: each sector of an audio
  track file is copied from the image with the same offset as the state, so each track
  file is a range of the image.
- A sector the drive never read is never written to the image, so the image holds zeros
  there, with state 0. A sample read with a C2 error holds the data of the first read
  that returned it, with state 1: redumper replaces a sample only with a better state.

### Known limit

When the last track's sectors are never read through to the image's end, the image is
shorter than the track, redumper pads the track file with zeros, and the track file is
no longer a range of the image. Acquire then fails as today, with "found nowhere in the
image". Unread lead-out sectors alone do not cause it.

## Requirements

### Acquire

- **Reading.** Acquire passes `--force-split --leave-unchanged` to `redumper disc`,
  after `--retries`; the record's `reader.arguments` lists them.
- **Tracks.** Each track's range must still hold exactly redumper's track file. The
  failure "found nowhere in the image" stays, for the known limit and for a track of a
  single repeated byte that cannot be placed. Its added sentence about redumper's
  generated sectors, and the code that computes it, go: redumper no longer generates
  sectors.
- **Error ranges.** For each track, acquire reads the state over the track's range and
  records the maximal runs of consecutive frames with the same state, 0 (not read) or 1
  (read with a C2 error), in order. Adjacent frames of different states form separate
  ranges.
- **Exit and result.** A set is accepted with exit 1 when `read_errors` gives SCSI or
  C2 errors or any track has an error range, as a disc read with errors already is.
  This includes a pressed CD whose only errors are in its lead-in or lead-out, which
  redumper now splits: its tracks have no error range, and the result says "Read
  errors: found". The text result's track line gives each affected track's count of
  frames not read successfully, the sum of its ranges.

### Acquisition Record format version 2

Version 1 with each track's `error_frames` replaced by `error_ranges`: a list, empty
when the track has no error, of objects with the following fields. A frame is one
stereo sample, 1/44,100 s, which redumper's log calls a sample.

- `offset_frames`: the range's first frame, counted from the track's first frame;
- `frame_count`: its length in frames, at least 1;
- `state`: `not_read` or `c2_error`.

The ranges are in order, do not overlap, and lie inside the track. The record keeps
every range, however many.

### Reading records

Inspect, compare and export read the record through one reader, which accepts format
versions 1 and 2:

- **Version 1** reads as today. Its tracks have no error ranges, since no version 1
  set has a track with frames not read successfully.
- **Version 2** makes the record unusable, with the reason, when a track lacks
  `error_ranges` or a range breaks the rules above.
- **Any other version** makes the record unusable, with a reason naming the versions
  CopyOfA reads.

Acquire writes version 2.

### Inspect

- **Inspection Report format version 3** is version 2 with `error_ranges` added to each
  entry of `disc.tracks`, copied from a version 2 record; absent when the record is
  version 1.
- Inspect's exit status does not change: a track with error ranges that decodes to its
  recorded Audio Digest is `interpreted`, and the set is as acquired.
- Inspect's text result adds to each affected track's line `, <count> frames not read
  successfully:` and its ranges, written as export's warning writes them.

### Compare

- **Comparison Report format version 5** is version 4 with `error_ranges` added to an
  input's `track`, from a version 2 record; absent otherwise.
- Compare's exit status does not change.
- View renders version 5, showing the ranges of each track input.

### Export

- Export writes every track, as today, and its exit status stays 0 when every track was
  exported. For each track with error ranges, stderr gets one line:

  ```text
  copyofa: warning: track 8 has 7 frames not read successfully: 3:12.093+7 (C2 errors)
  ```

  `<count>` is the total of all the track's ranges; `frame` is singular for 1. Each
  range is its start in the track as a duration, as the text results give durations,
  then `+` and its frame count, then its state, `C2 errors` or `not read`; ranges are
  separated by `, `. At most 10 ranges are listed; more end the line with
  `, and <n> more`. The record and the Reports keep every range, with exact
  `offset_frames`.

## Design decisions

- **Reading as read:** decided by ADR 0008.
- **Ranges relative to the track,** named `offset_frames` so they are not confused with
  the track's `first_frame` in the image. A range counted from the track can be read
  without knowing the image, and matches how inspect, compare and export address a
  track.
- **No count beside the ranges.** `error_frames` would duplicate what the ranges give,
  in a record whose only integrity check is the tag manifest.
- **Inspect, compare and export exit as before.** Acquire already exits 1 for the disc.
  Inspect checks that the set is as acquired, which it is; export writes what was
  acquired. They warn instead.
- **A wholly unread track is kept.** It is all zeros, gets one range over the whole
  track, and shares its Audio Digest with any other unread track of the same length;
  the Evidence Set format says so.
- **New format versions, not changed ones,** for the record and both Reports, as ADR
  0004 requires for Reports.

## Blocking questions

None.

## Stop rule

Stop and report if the by-hand acquisition (AC10) contradicts What redumper does: a
track file of a disc with errors that is not a range of the image away from the known
limit, or an image that holds anything but zeros where the state is 0.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Tests of
acquire run the stand-in `redumper`, extended for `--force-split --leave-unchanged`:
it writes zeros in the image and the track file for frames of state 0, supports frames
of state 1, and refuses to split a disc with errors unless given both options. (b768
itself splits with `--force-split` alone, generating sectors, which acquire never
asks.)

- **AC1 — Acquired with errors.** A synthetic disc whose state marks frames of track 2
  as not read, others as read with C2 errors, and two adjacent frames of different
  states, is accepted; its version 2 record gives track 2's `error_ranges` exactly,
  split at each change of state, and other tracks empty lists; acquire exits 1; and
  redumper received `--force-split --leave-unchanged`. A track with more than 10 ranges
  is recorded with all of them, and a wholly unread track gets one range over the
  track.
- **AC2 — Clean, edge-only and limit discs.** A disc read without error gives a version
  2 record whose tracks have empty `error_ranges`, and acquire exits 0. A disc whose
  only errors are in the lead-in gives empty `error_ranges` and exits 1 with "Read
  errors: found". A disc whose last track is unread through the image's end fails with
  "found nowhere in the image", leaving nothing.
- **AC3 — Old records.** For a set whose record is version 1, inspect and compare
  print Reports of versions 3 and 5 without `error_ranges`, export warns about nothing,
  and their exit statuses are as before. A record of version 3, and a version 2 record
  with an invalid range, make the record unusable with the reason.
- **AC4 — Inspect.** Inspect of AC1's set prints a version 3 Report whose track 2 holds
  the record's ranges, exits 0, and names track 2 in its text result.
- **AC5 — Compare.** Compare with `--track-a 2` on AC1's set prints a version 5 Report
  whose input A's `track` holds the ranges, with the exit status of an unaffected track.
  View renders it with the ranges.
- **AC6 — Export.** Export of AC1's set writes every track with its recorded Audio
  Digest, warns on stderr for track 2 in the documented line, listing 10 ranges and
  `and <n> more` for a track with more, and exits 0.
- **AC7 — Schemas.** The inspection Report version 3 and comparison Report version 5
  schemas ship in the package; validate and view accept them; every Report the test
  suite produces validates.
- **AC8 — Documented.** `docs/formats/evidence-set.md` documents record version 2, the
  new acceptance rules and the known limit, drops the generated-sector failure, and
  says that splitting a restored set again takes `--force-split --leave-unchanged`, as
  the record's `reader.arguments` shows. The inspection Report document names record
  version 2 and documents Report version 3; the comparison Report document documents
  version 5 and lists it among the versions view renders;
  `docs/formats/export-result.md` documents the warning. The README no longer tells a
  collector to raise the retry count for "data errors detected". AGENTS.md's
  Architecture section gives acquire's new options and the view's versions 1 to 5.
- **AC9 — Restoring (by hand, once).** For the set of AC10, the files restored as the
  format document says are redumper's originals, and `redumper split` with the
  record's options rewrites track files with the SHA-256s in the recorded Audio
  Digests.
- **AC10 — A real disc (by hand, once).** A disc that keeps errors after the re-reads,
  such as the pressed CD of the context, is acquired on the maintainer's drive. Acquire
  exits 1; for each affected track, the record's ranges total, per state, the SKIP and
  C2 samples redumper's log gives for that track (a redumper sample is a frame); verify
  passes; inspect and export report the same ranges; and export's files play.

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

1. Compare's ranges, with comparison Report format version 5 and its view; step 4 of
   the scenario goes.
2. Inspect's ranges, with inspection Report format version 3 and its text naming the
   affected tracks; step 3 of the scenario goes.

## What needs the maintainer

1. This brief and ADR 0008, before implementation starts.
2. AC9 and AC10, acquiring a disc that keeps errors by hand and restoring it.
3. Merges and the release.
