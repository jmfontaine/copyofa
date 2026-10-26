# Brief: Preserve an Audio CD

## Goal and context

A collector preserves a plain audio CD as an Evidence Set, then verifies, inspects,
compares and exports its tracks without the disc. The set holds everything meaningful
the reading produced, compressed, and nothing large that the rest reproduces, so the
audio can be analyzed again later, with better methods.

- **Milestone:** [v0.5.0](https://github.com/jmfontaine/copyofa/milestone/5)
- **Product Map capabilities:**
  [Acquire Audio and Record Its Origins](../product-map.md#acquire-audio-and-record-its-origins)
  and
  [Preserve Evidence Throughout Its Lifetime](../product-map.md#preserve-evidence-throughout-its-lifetime)
- **Decision:**
  [ADR 0005: Acquire audio CDs with redumper and store the disc image compressed](../decisions/0005-acquire-audio-cds-with-redumper.md)

v0.1.0 to v0.4.0 preserve, describe, compare and share files a collector already owns.
CDs are where much of a collection's audio comes from, and the Manifesto's first step
is to acquire it. A spike on the maintainer's drive read a pressed CD with redumper,
stored it as about 148 MB, and compared its tracks with a 24-bit download of the same
release; ADR 0005 records what it found.

## Primary scenario

Refines [S1](../product-map.md#s1-preserve-a-cd), with
[S3](../product-map.md#s3-compare-two-tracks) as the use made of the audio later:

1. A collector inserts *Add Violence* and runs
   `copyofa acquire --to ~/Archive/add-violence-cd --note "Bought new"`. Progress on
   stderr names each stage; about three minutes later acquire prints the drive, the
   redumper build, the offsets, the read errors (none), each track with its length and
   Audio Digest, and the size of the set.
2. The set holds the disc image as FLAC, redumper's read status and subchannel as xz,
   its small files as written, and an Acquisition Record. It holds no track file.
3. Months later, `copyofa verify ~/Archive/add-violence-cd` checks every file.
4. `copyofa inspect ~/Archive/add-violence-cd` decodes each track from the image and
   reports its Audio Digest, which matches the one recorded at acquisition.
5. `copyofa compare ~/Archive/add-violence-cd --track-a 3 "<qobuz set>/data/…/03.flac"`
   measures how the CD's third track relates to the download's.
6. `copyofa export ~/Archive/add-violence-cd --to ~/Music/add-violence` writes one FLAC
   file per track, each with the track's Audio Digest, for playback and tagging
   elsewhere.

## In scope

- `copyofa acquire`, which reads a plain audio CD with redumper and accepts it as an
  Evidence Set with an Acquisition Record.
- The contents of an acquired set and the Acquisition Record, documented in
  `docs/formats/evidence-set.md`.
- Verify on an acquired set, unchanged.
- Inspect on an acquired set: inspection Report format version 2, which adds the
  disc's tracks.
- Compare on a track of an acquired set: `--track-a` and `--track-b`, and comparison
  Report format version 3, which records the track. View renders version 3.
- `copyofa export`, which writes the tracks of an acquired set as FLAC files.
- Schemas for the new Report format versions, which validate accepts.

## Out of scope

- Discs other than plain audio CDs: CD-Extra and other multi-session discs, mixed-mode
  discs, data discs, DVDs and others. Acquire refuses them.
- Retries, refining, and keeping a disc redumper could not split into tracks; drive
  speed and other redumper options beyond the drive to use.
- Audio before the first track (in the first track's pregap) as a track of its own.
  The image preserves it; inspect, compare and export ignore it.
- Checking the audio against AccurateRip, CTDB or another database, and any network
  access.
- Tags in exported files, file names from CD-Text, cue sheets for exported files, and
  formats other than FLAC.
- Export from imported sets; export refuses them.
- Compressing imported files: import keeps the bytes a collector delivered.
- Restoring redumper's files with CopyOfA; the format document shows how with `flac`
  and `xz`.
- Acquire with a real drive on platforms other than macOS: it is exercised on macOS
  only. Its tests, and every other command, stay portable.

## Requirements

### Acquire

- **Command.** `copyofa acquire --to <destination> [--drive <drive>] [--note NOTE]
  [--ref reference] [--json]`. `--drive` is passed to redumper's `--drive`, such as
  `disk6`; without it, redumper reads the first drive holding a disc. `--note` and
  `--ref` are recorded as import records them.
- **Before reading.** Acquire refuses, exiting 1 before running redumper, when
  `redumper` is not on `PATH`, its build is older than b768 or cannot be read from
  `redumper --version`, or the destination would be refused by import: it exists, its
  parent does not, a staging directory is left there, or its path, the note or a
  reference is not valid UTF-8.
- **Reading.** Acquire runs `redumper disc` once, with `--drive` when given, writing
  into the staging directory `<destination>.copyofa-staging`. redumper's console output
  is not relayed: progress on stderr names each redumper stage and acquire's own steps.
  redumper's log is preserved instead.
- **Plain audio CDs only.** From redumper's table of contents, a disc with more than
  one session or with a track that is not audio is refused.
- **Tracks.** For each track redumper wrote, acquire finds its range in the image,
  checks that the range holds exactly the track file's bytes, and records its first
  frame and length. A track whose range cannot be found is a failure.
- **Storage.** The set's `data/` holds the files ADR 0005 lists: the image as
  `disc.scram.flac`, the state and the subchannel as `disc.state.xz` and
  `disc.subcode.xz`, and every other file redumper wrote, except the track files, as
  written, named `disc.<extension>`. Each compressed file is decoded and its SHA-256
  compared with the original's before the set is accepted. The track files and the
  uncompressed originals are then deleted.
- **Read errors.** The Acquisition Record gives redumper's SCSI, C2 and subchannel
  error counts, and, for each track, the number of its frames the state does not mark
  as read successfully. A disc redumper read with errors but split into tracks is
  accepted, and acquire exits 1.
- **Acceptance.** As import does, acquire writes the bag in the staging directory,
  renames it to the destination only when every file and tag file is written, and the
  set at the destination is complete. When acquire fails, is refused after reading, or
  is canceled, it deletes the staging directory and nothing is left at the
  destination. A staging directory left by a crash is never reused or deleted: the next
  acquire or import to that destination refuses and names it.

### Acquisition Record

`copyofa/acquisition-record.json`, listed in the tag manifest, records the items
below. A set is an acquired set when its tag manifest lists the record. Inspect,
compare and export use the record only when its SHA-256 matches the tag manifest's,
since it defines where the tracks are; otherwise they decode no track. The record
holds:

- `record_kind` `copyofa.acquisition` and `format_version` 1, the CopyOfA version, and
  when the acquisition started, in UTC;
- the note and the external references, as the Import Record holds them;
- the reader: `redumper`, its build, and the arguments CopyOfA gave it;
- the drive as redumper identified it: vendor, product, firmware revision, and read
  offset;
- the disc: its write offset, its catalog number and its CD-Text album title and
  performer when present, and the image's frames, sample rate, channels and bits per
  sample;
- the read errors above;
- each track: number, first frame and length in the image, Audio Digest, ISRC and
  CD-Text title and performer when present, and the frames not read successfully;
- each stored file: its path in the bag, the name, size and SHA-256 of redumper's
  original, and how it was stored (`flac`, `xz` or as written).

The format document gives every field, how to restore redumper's files with `flac -d
--force-raw-format --endian=little --sign=signed` and `xz -d`, and an example. Values
that redumper does not report are absent, never invented.

### Inspect

- **Inspection Report format version 2** is version 1 with one field added: `disc`,
  present for an acquired set. It holds `tracks`, each track the record gives, in
  order: its number, first frame and length in the image, outcome, reason, Audio
  Digest, the Audio Digest recorded at acquisition, frames, peak, and leading and
  trailing silence, with the same meanings as for a file. When the record cannot be
  used, `disc` holds a `reason` and no track, and inspect exits 1.
- A track is `interpreted` when its range was decoded completely, `failed` when the
  image could not be decoded over it, and `not_inspected` when the image is not
  inspected, such as when it is not the accepted bytes. A track whose Audio Digest
  differs from the recorded one makes inspect exit 1.
- The image file itself keeps its `files` entry, as any FLAC file.
- Inspect prints version 2 from this release on, for every set.

### Compare

- **Tracks of an acquired set.** With `--track-a <number>`, input A is that track of
  the acquired set whose root is the first positional argument; likewise
  `--track-b`. Without the option, an input is a file, as today. The positional
  arguments' names in `--help` become `input-a` and `input-b`. A set root without the
  option is refused as today: it is not under `data/`. A track number the record does
  not list, the option on a set that is not an acquired set, and a record that cannot
  be used make that input `not_inspected` with the reason, and compare exits 1, as for
  a file the set does not list.
- **Comparison Report format version 3** is version 2 with one field added to an
  input given with `--track-a` or `--track-b`: `track`, its number, and its first
  frame and length in the image when the record gives them. In that input, `path`,
  `expected_digest` and `observed_digest` describe the image file, and `path` is
  absent when no usable record names the image; `outcome`, `reason`, the audio
  properties, `frames`, `audio_digest`, `peak` and the silences describe the track,
  with inspect's track outcomes; `flac_md5_signature` is absent, since it covers the
  whole image. Compare prints version 3 from this release on.
- **View** renders version 3, showing each input's track; validate and view keep
  accepting versions 1 and 2.

### Export

- **Command.** `copyofa export <evidence-set> --to <directory> [--json]`.
- **What it writes.** One FLAC file per track of an acquired set, `01.flac`,
  `02.flac`, …, 16-bit stereo at 44.1 kHz, holding exactly the track's frames and no
  tag. Before the directory is accepted, each file is decoded and its Audio Digest
  compared with the recorded one.
- **Integrity first.** Export checks the Integrity Baseline, the Acquisition Record and
  the image as inspect does, and refuses a set that is not an acquired set, whose
  baseline is unusable, whose record cannot be used, or whose image is not the
  accepted bytes.
- **Destination.** The directory must not exist and its parent must; export refuses a
  staging directory `<directory>.copyofa-staging` left there, writes in a new one, and
  renames it when every file is written and checked, deleting it on failure or
  cancellation.
- **Result.** The exported files, each with its track number and Audio Digest; the
  set's `manifest_sha256`; and what export leaves out: the first track's pregap, the
  lead-in and the lead-out. Documented in `docs/formats/export-result.md`.

### Output and exit codes

Acquire and export follow the command conventions in AGENTS.md:

- A short result on stdout; `--json` prints the acquisition result (the set's path and
  its Acquisition Record) or the export result instead. Progress, warnings and errors
  go to stderr; stdout stays empty when no result is produced.
- Acquire exits 0 when the set was accepted with no read error, 1 when it was accepted
  with read errors, refused or failed, 2 for invalid arguments, and 130 when canceled.
- Export exits 0 when every track was exported, 1 when it refused or failed, 2 for
  invalid arguments or a target that is not an Evidence Set, and 130 when canceled.

## Design decisions

- **Reading and storage:** decided by ADR 0005.
- **The set's root names an acquired disc.** Compare and export take the Evidence Set,
  not a file in it, because a track is not a file. `--track-a` and `--track-b` keep
  each input explicit.
- **Exit 1 for read errors, with the set kept.** The set is evidence of what the drive
  read, errors included, and the Product Map keeps useful partial evidence; the exit
  status still tells a script that the reading was not clean.
- **No tags in exports.** Tagging is external, and the exported files' Audio Digests
  tie them to the set without any.
- **New format versions, not changed ones.** Inspection and comparison Reports gain a
  field each, so each gets a new format version and schema, as ADR 0004 requires.

## Blocking questions

None.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Tests of
acquire run a stand-in `redumper` that writes small synthetic files and a log in the
format of build b768.

- **AC1 — Acquired.** For a synthetic plain audio CD, acquire accepts a set whose
  `data/` holds the image as FLAC, the state and subchannel as xz and the small files
  as written, and no track file; decoding each stored file gives the original's
  SHA-256 the record gives; each track's range holds exactly its track file's bytes;
  and the Acquisition Record holds every documented field the synthetic disc
  provides. `--note`, `--ref` and `--drive` reach the record and redumper's arguments.
- **AC2 — Refusals before reading.** A missing `redumper`, a build older than b768,
  an unreadable version, an existing destination, a missing parent, a left staging
  directory, and a note that is not valid UTF-8 each make acquire exit 1 without
  running redumper, with nothing on stdout and nothing written.
- **AC3 — Refusals and failures after reading.** A disc with a data track, a disc with
  two sessions, redumper exiting non-zero, a missing track file, a track file found
  nowhere in the image, and a log acquire cannot read each make acquire exit 1 with the
  reason, nothing on stdout, and neither the destination nor the staging directory
  left.
- **AC4 — Read errors.** A synthetic disc whose state marks frames of track 2 as
  unread is accepted, records the counts for track 2 only, and makes acquire exit 1.
- **AC5 — Verify.** Verify reports an acquired set intact and exits 0, and reports a
  changed byte in `disc.scram.flac` and a changed Acquisition Record.
- **AC6 — Inspect.** Inspect of an acquired set prints a version 2 Report whose `disc`
  lists every track with the recorded Audio Digest. A set whose record, with the tag
  manifest rewritten to match, gives a wrong Audio Digest for one track makes inspect
  exit 1. A record edited without rewriting the tag manifest gives `disc` a reason and
  no track, and inspect exits 1. Inspect of an imported set prints version 2 without
  `disc`.
- **AC7 — Compare.** Compare of track 2 of an acquired set with a FLAC file of the same
  audio reports identical audio, in a version 3 Report whose input A holds `track` and
  no `flac_md5_signature`. An unknown track number and `--track-a` on an imported set
  each make that input `not_inspected` and compare exit 1; a set root without the
  option exits 2. View renders a version 3 Report with the track.
- **AC8 — Export.** Export writes one FLAC file per track with the recorded Audio
  Digests and no tag, and refuses an imported set, a set with a changed image, a set
  whose record does not match the tag manifest, an existing destination and a left
  staging directory, leaving nothing behind.
- **AC9 — Command conventions.** Acquire and export print their result, or JSON with
  `--json`; exit 130 when canceled, with the staging directory deleted and nothing on
  stdout.
- **AC10 — Schemas.** The inspection Report version 2 and comparison Report version 3
  schemas ship in the package, and every Report the test suite produces validates.
- **AC11 — Documented.** `docs/formats/evidence-set.md` documents acquired sets, the
  Acquisition Record, the acquisition result `--json` prints, and how to restore
  redumper's files; the inspection and comparison Report documents their new versions
  and compare's new synopsis; `docs/formats/export-result.md` the export result. The
  README shows acquire, export and compare on a track. The Architecture section of
  AGENTS.md records redumper as an external program, the stored formats, soundfile's
  new minimum, and the new document.
- **AC12 — A real disc (by hand, once).** *Add Violence* is acquired on the
  maintainer's drive into a set of about 148 MB. Verify passes. Inspect gives the five
  Audio Digests the spike recorded, starting `1e9b66e1`, `7ce35410`, `ec9ef8df`,
  `a4c11150` and `7cb0b19d`. Compare of track 1 with the Qobuz download's first track
  gives an offset of −4240 frames and a residual of −37.5 dB, as in the spike. Export
  writes five FLAC files that play in Music. `flac -d --force-raw-format` and `xz -d`
  restore redumper's files with the SHA-256s the record gives, and `redumper split` on
  them rewrites the five track files, whose SHA-256s are the hashes in the recorded
  Audio Digests.

## Manifesto alignment

- **Audio and provenance are the scope; provenance should identify the source:** the
  Acquisition Record keeps the catalog number, ISRCs and CD-Text the disc carries, the
  drive and the reader, and invents nothing.
- **Accuracy must remain usable:** any drive redumper supports is accepted, and its
  limits are recorded rather than refused.
- **Evidence, identity, and conclusions are distinct:** the image and redumper's
  records are preserved as read; tracks, digests and exports are derived from them and
  say so.
- **Results should be reproducible and durable:** every file kept can be restored to
  redumper's bytes with standard tools, the track files can be split again, and the
  audio analyzed again, without the disc.
- **Preservation is a lifecycle:** an acquired set is verified, inspected and exported
  like any other.

## Appetite and scope cuts

Appetite: a few hours to a couple of days.

If the work outgrows it, cut in this order, keeping an acquired, verifiable set whose
tracks can be exported. Taking the first cut also narrows the v0.5.0 entry in the
Product Map and the milestone description, which promise comparing the tracks; update
them at the release review.

1. Compare on tracks of an acquired set, with comparison Report format version 3 and
   its view. A collector exports and imports the tracks to compare them.
2. Peak and silence for tracks in inspect; Audio Digests stay.
3. CD-Text in the Acquisition Record; the files that hold it stay preserved.

## Delivery notes

Recorded at the v0.5.0 release review.

- **Delivered within the appetite**, with no scope cut, as a stack of pull requests from
  one unattended agent: `copyofa acquire` in
  [#96](https://github.com/jmfontaine/copyofa/pull/96), inspection Report format version
  2 in [#97](https://github.com/jmfontaine/copyofa/pull/97), compare on a track with
  comparison Report format version 3 and its view in
  [#98](https://github.com/jmfontaine/copyofa/pull/98), and `copyofa export` in
  [#99](https://github.com/jmfontaine/copyofa/pull/99). AC1–AC10 have tests against a
  stand-in `redumper`; the stack's agent review checked AC11. AC12, on the maintainer's
  drive: *Add Violence* was acquired into 148,047,406 bytes in 159 seconds, with the
  five Audio Digests of the spike; verify, inspect, compare (−4240 frames, −37.5 dB) and
  export gave the expected results; `flac -d` and `xz -d` restored redumper's files
  exactly, and `redumper split` on them rewrote the track files; the maintainer played
  the exported files in Music. A second acquisition from the merged code gave the same
  five Audio Digests.
- **Clarified during delivery:**
  - Subchannel Q errors are recorded but are not read errors: they do not make acquire
    exit 1, since the audio comes from the main channel. *Add Violence* reads with
    134 to 145 of them, depending on the read.
  - Export also refuses a destination inside the Evidence Set, so it never adds files
    to the set.
  - An exported file's "no tag" is a Vorbis comment block holding only libFLAC's
    vendor string, which libsndfile always writes.
  - `redumper split` needs `--overwrite` to rewrite the track files from restored
    files.
- **Found in review:** with redumper's defaults, the Read errors requirement is mostly
  unreachable. A C2 or skipped sector inside a track, or a C2 sector in the lead-in or
  lead-out, makes redumper b768 refuse to split a pressed CD, and on a CD-R it fills
  sectors with C2 errors at a track's edges, so the track is found nowhere in the
  image. Only skipped sectors confined to the lead-in or lead-out, and on a CD-R C2
  errors confined to them, give a set accepted with exit 1. The maintainer kept
  redumper's defaults (no `--leave-unchanged`, no `--force-split`);
  `docs/formats/evidence-set.md` states which discs fail, and damaged discs move to
  the Later outcome Acquire More Kinds of Disc.
- **Learning:** checking the stand-in against redumper's source found what the
  synthetic tests could not: the stand-in wrote track files equal to the image even
  where the state marked frames unread, which real redumper never does. A stand-in for
  an external program should be checked against that program's source or output for
  each behavior a test relies on.
