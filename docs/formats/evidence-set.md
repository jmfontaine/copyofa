# Evidence Set format

An Evidence Set is a [BagIt 1.0](https://www.rfc-editor.org/rfc/rfc8493) bag, as
[ADR 0001](../decisions/0001-store-evidence-sets-as-bagit-bags.md) decides.
`copyofa import` creates it from files a collector owns, `copyofa acquire` from a CD
(see [Acquired sets](#acquired-sets)); this document describes what it contains and how
to check it without CopyOfA.

## Layout

```text
Album/
├── bagit.txt
├── bag-info.txt
├── manifest-sha256.txt
├── tagmanifest-sha256.txt
├── copyofa/
│   └── import-record.json
└── data/
    ├── Album/
    │   ├── 01.flac
    │   └── scans.zip
    └── notes.txt
```

- `data/` holds the Preserved Evidence and nothing else. Each source given to
  `copyofa import` goes under `data/` by its base name, as `cp -R` would place it: a
  directory `~/Downloads/Album` becomes `data/Album/…`, a file `notes.txt` becomes
  `data/notes.txt`. File contents are stored byte for byte.
- `bagit.txt` is the bag declaration, always the same two lines:

  ```text
  BagIt-Version: 1.0
  Tag-File-Character-Encoding: UTF-8
  ```

- `bag-info.txt` holds three elements:
  - `Bagging-Date`: the import or acquisition date in UTC, as `YYYY-MM-DD`.
  - `Payload-Oxum`: the payload's total size in bytes and its number of files,
    separated by a dot, such as `1048576.12`.
  - `Bag-Software-Agent`: `copyofa` and the version that created the set.
- `manifest-sha256.txt` is the Integrity Inventory: one line per payload file, with its
  SHA-256 digest in lowercase hexadecimal, two spaces, and its path from the bag root,
  such as `data/Album/01.flac`. Each line ends with a line feed.
- `tagmanifest-sha256.txt` has the same format and lists every other file CopyOfA
  writes: `bagit.txt`, `bag-info.txt`, `manifest-sha256.txt`, and
  `copyofa/import-record.json`, or `copyofa/acquisition-record.json` in an acquired
  set. With `manifest-sha256.txt`, it forms the Integrity Baseline.
- `copyofa/` is CopyOfA's tag directory. It holds the Import Record, or the Acquisition
  Record. `copyofa/recovery/` is reserved for recovery information, such as PAR2 files,
  that a later version may add; neither import nor acquire creates it.

Paths in both manifests use `/` as separator. As BagIt requires, three characters are
percent-encoded in a path: `%` as `%25`, a carriage return as `%0D`, and a line feed as
`%0A`. Every other character, including spaces and non-ASCII letters, appears as is, in
UTF-8.

## Import Record

`copyofa/import-record.json` is a UTF-8 JSON object:

| Field | Content |
| --- | --- |
| `record_kind` | Always `copyofa.import`. |
| `format_version` | The version of this record's format, `1`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that imported the set. |
| `imported_at` | The import time in UTC, such as `2026-10-24T18:30:00Z`. It is not an acquisition time. |
| `sources` | One object per source, in the order given: `given`, the path as typed on the command line; `resolved`, its absolute path with every parent directory's symbolic links resolved; `stored_as`, its path in the bag, such as `data/Album`. |
| `note` | The `--note` text, exactly as supplied. Absent when no note was given. |
| `external_references` | The `--ref` values, exactly as supplied and in the order given. Absent when none was given. |
| `exclusions` | Everything under the sources that was not preserved, one object each, possibly an empty list. |

The record holds no acquisition time and no other provenance: CopyOfA records what the
collector supplied and invents nothing.

Each exclusion has a `path`, where the item would have been in the bag, such as
`data/Album/.DS_Store`, and a `reason`:

| `reason` | Excluded item |
| --- | --- |
| `exclude_pattern` | A file or directory matching an `--exclude` pattern, which the `pattern` field gives. A directory is excluded whole, without being listed, and recorded once. |
| `operating_system_metadata` | An operating system metadata file (see below). |
| `symbolic_link` | A symbolic link. Import does not follow links. |
| `special_file` | A file that is neither regular nor a directory, such as a socket or a named pipe. |
| `empty_directory` | A directory with no entries, which BagIt cannot represent. |

An `--exclude` pattern is a shell-style pattern, as Python's `fnmatch` reads it, matched
case-sensitively against the item's name and against its path under `data/`, such as
`Album/scans/back.png`. `*` also matches `/` in a path.

## Import result

`copyofa import --json` prints, instead of its short human-readable result, a JSON
object with `evidence_set`, the absolute path of the new set; `import_record`, the
Import Record as written; and `counts`, with the numbers of preserved `files`,
payload `bytes`, and `exclusions`. It is not a Report. Like every `--json` output of
CopyOfA, it is UTF-8, whatever the locale. Import refuses file names that are not
valid UTF-8, but a path given on the command line, such as the Evidence Set's own path
in a Report, may not be: each byte that is not valid UTF-8 then appears as a `\udcXX`
escape, so the output stays valid UTF-8 and Python's `json` turns it back into the
original path.

## Operating system metadata files

Operating systems create and rewrite some files while a collector browses folders, so
they are not evidence. Import never preserves them, and `copyofa verify` ignores them
under `data/`, so browsing a set in Finder does not make it fail verification:

- `.DS_Store`
- AppleDouble files, whose names start with `._`
- `Icon` followed by a carriage return, which holds a custom folder icon
- `Thumbs.db`
- `desktop.ini`

## How an Evidence Set is accepted

Before copying anything, import refuses, exiting 1 and creating nothing, when:

- a source does not exist, has no base name (`/`), or is neither a regular file nor a
  directory;
- a source is itself a symbolic link. Import never follows links, so name the link's
  target instead;
- two sources are the same file or directory, or one lies inside the other;
- two sources share a base name. Base names are compared case-insensitively and after
  Unicode normalization, as a case-insensitive volume, the default on macOS, compares
  them: `Album` and `album` are refused together even on a case-sensitive volume,
  because the set must stay valid once moved to a macOS volume;
- the destination exists, its parent does not exist or cannot be opened, or it lies
  inside a source;
- a staging directory left by an earlier import or acquire exists (see below);
- the path of a source or of the destination, or a name in a directory import lists
  (not one inside an excluded directory), is not valid UTF-8, which BagIt manifests
  require;
- the `--note` text, a `--ref` value or an `--exclude` pattern is not valid UTF-8,
  which the Import Record requires;
- the selection leaves no file to preserve.

It also fails before copying anything when a selected directory cannot be listed or a
selected file cannot be opened; the error names it, and excluding it lets the rest be
imported.

Import then reads each source file once, computing its SHA-256 while copying it into a
staging directory, `<destination>.copyofa-staging`, beside the destination. It then
re-reads the stored copy and compares digests, and fails if they differ or if the
source file's size or modification time changed during the copy. Only when every file
and tag file is written does it rename the staging directory to the destination. A
set at the destination is therefore complete. If syncing the destination's parent
directory fails after that rename, the set is kept and import warns on stderr. A
staging directory left behind by a crash is never reused or deleted by CopyOfA: the
next import or acquire to that destination refuses and names it.

## Acquired sets

`copyofa acquire` reads a plain audio CD with
[redumper](https://github.com/superg/redumper), build b768 or later, in one
`redumper disc` run, as
[ADR 0005](../decisions/0005-acquire-audio-cds-with-redumper.md) decides. It gives
redumper `--image-name=disc`, so each file redumper writes is named
`disc.<extension>`, and the set keeps every one of them but the track files:

```text
add-violence-cd/
├── bagit.txt
├── bag-info.txt
├── manifest-sha256.txt
├── tagmanifest-sha256.txt
├── copyofa/
│   └── acquisition-record.json
└── data/
    ├── disc.cdtext
    ├── disc.cue
    ├── disc.fulltoc
    ├── disc.log
    ├── disc.scram.flac
    ├── disc.state.xz
    ├── disc.subcode.xz
    └── disc.toc
```

| Stored file | redumper's file | Stored as |
| --- | --- | --- |
| `data/disc.scram.flac` | `disc.scram`, the disc image: every stereo frame from the lead-in to the lead-out, as read | FLAC, 16-bit stereo at 44.1 kHz, written by libsndfile at its highest compression level |
| `data/disc.state.xz` | `disc.state`, one byte per frame of the image: whether, and how, it was read | xz |
| `data/disc.subcode.xz` | `disc.subcode`, the subchannel: track and index positions, ISRCs, the catalog number, CD-Text | xz |
| `data/disc.<extension>` | Every other file redumper writes, such as the tables of contents (`.toc`, `.fulltoc`), the CD-Text (`.cdtext`), the cue sheet (`.cue`) and the run's log (`.log`) | As written |
| `data/disc_<language code>.cue` | A further cue sheet, which redumper writes for each CD-Text language after the first, such as `disc_09.cue` | As written |

The track files redumper writes, `disc (Track 1).bin` and so on (`disc (Track
01).bin` on a disc of ten tracks or more), or `disc.bin` for a disc of one track, are
not kept: each is a range of the image, which the Acquisition Record gives, and
`redumper split` writes them again from the stored files (see
[Restoring redumper's files](#restoring-redumpers-files)). Nor are the lead-in and
lead-out, which redumper also writes as `disc (Track 0).bin` and `disc (Track A).bin`
when they hold audio: the image holds them. A file is stored only when redumper wrote
it; the image, the state, the cue sheet and the log are always there.

In this section a frame is one stereo sample pair of the image, 4 bytes.

### Acquisition Record

`copyofa/acquisition-record.json` is a UTF-8 JSON object. A set is an acquired set when
its tag manifest lists the record. Since the record defines where the tracks are,
CopyOfA reads a track only when the record's SHA-256 matches the tag manifest's. Values
redumper does not report are absent, never invented.

| Field | Content |
| --- | --- |
| `record_kind` | Always `copyofa.acquisition`. |
| `format_version` | The version of this record's format, `1`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that acquired the set. |
| `acquired_at` | When the acquisition started, in UTC, such as `2026-10-25T22:59:35Z`. |
| `note` | The `--note` text, exactly as supplied. Absent when no note was given. |
| `external_references` | The `--ref` values, exactly as supplied and in the order given. Absent when none was given. |
| `reader` | The program that read the disc: `name`, always `redumper`; `build`, as `redumper --version` gives it, such as `b768`; `arguments`, the arguments CopyOfA gave it, in order. redumper ran in a directory inside the staging directory, so its image path is its default, `.`. |
| `drive` | The drive as redumper's log identifies it: `vendor`, `product`, `firmware_revision` (the revision level the drive reports), and `read_offset`, the read offset in samples redumper applied. |
| `disc` | What the disc says about itself and its image: `write_offset`, the disc's write offset in samples redumper found; `catalog`, its catalog number; `title` and `performer`, the album's CD-Text; and `image`, with `path` (`data/disc.scram.flac`), `frames`, `sample_rate` (44100), `channels` (2) and `bits_per_sample` (16). |
| `read_errors` | redumper's error counts for the whole disc, from its log: `scsi_samples`, the samples of sectors the drive failed to read; `c2_samples`, the samples the drive flagged with C2 errors; and `subchannel_q_sectors`, the sectors whose subchannel Q redumper found in error. |
| `tracks` | One object per track, in disc order (see below). |
| `stored_files` | One object per stored file, sorted by path (see below). |

Each track has:

| Field | Content |
| --- | --- |
| `number` | The track number. |
| `first_frame` | The track's first frame in the image, counted from 0. |
| `frame_count` | The track's length in frames. Its range in the image holds exactly the bytes of redumper's track file. |
| `audio_digest` | The track's Audio Digest, as [ADR 0002](../decisions/0002-define-audio-digest-from-canonical-pcm.md) defines it: `pcm1:44100:2:16:` and the SHA-256 of redumper's track file, which is the track's canonical PCM. |
| `isrc` | The track's ISRC, from the cue sheet. Absent when the disc gives none. |
| `title`, `performer` | The track's CD-Text, from the cue sheet. Each is absent when the disc gives none. |
| `error_frames` | The number of the track's frames redumper's state does not mark as read successfully: state 0, not read, or 1, read with a C2 error. |

Each stored file has:

| Field | Content |
| --- | --- |
| `path` | Its path in the bag, such as `data/disc.scram.flac`. |
| `storage` | How it was stored: `flac`, `xz`, or `as_written`. |
| `original_name` | The name of redumper's file, such as `disc.scram`. |
| `original_size` | The size of redumper's file, in bytes. |
| `original_sha256` | The SHA-256 of redumper's file. Decoding the stored file gives these bytes. |

The catalog number, the ISRCs and the CD-Text come from redumper's cue sheet,
`disc.cue`, which holds the first CD-Text language. redumper copies CD-Text into it as
the disc holds it, so acquire decodes it in the character set the CD-Text's block size
information in `disc.cdtext` declares: ISO 8859-1, also when there is none, ASCII, or
MS-JIS. CD-Text in another character set, or that does not decode in its own, is
absent from the record; the stored files keep it. The drive, the table of contents,
the offsets and the error counts come from redumper's log.

The record of the *Add Violence* CD:

```json
{
  "record_kind": "copyofa.acquisition",
  "format_version": 1,
  "copyofa_version": "0.5.0.dev0",
  "acquired_at": "2026-10-25T22:59:35Z",
  "note": "Bought new",
  "reader": {
    "name": "redumper",
    "build": "b768",
    "arguments": [
      "disc",
      "--image-name=disc",
      "--drive=disk6"
    ]
  },
  "drive": {
    "vendor": "PLEXTOR",
    "product": "CD-R PX-W5224A",
    "firmware_revision": "1.04",
    "read_offset": 30
  },
  "disc": {
    "write_offset": -12,
    "catalog": "0602557897975",
    "title": "ADD VIOLENCE",
    "performer": "NINE INCH NAILS",
    "image": {
      "path": "data/disc.scram.flac",
      "frames": 98719290,
      "sample_rate": 44100,
      "channels": 2,
      "bits_per_sample": 16
    }
  },
  "read_errors": {
    "scsi_samples": 0,
    "c2_samples": 0,
    "subchannel_q_sectors": 140
  },
  "tracks": [
    {
      "number": 1,
      "first_frame": 26548188,
      "frame_count": 9285108,
      "audio_digest": "pcm1:44100:2:16:1e9b66e1364ea7c6e7d1fbfa95bf3a77970aecf5670074994c404cd0baa9f942",
      "title": "LESS THAN",
      "isrc": "TCADE1704630",
      "error_frames": 0
    },
    {
      "number": 2,
      "first_frame": 35833296,
      "frame_count": 11012064,
      "audio_digest": "pcm1:44100:2:16:7ce354106aff3aa7576b6d79b3690e598c1236127d1bfb79d77990c522ee379a",
      "title": "THE LOVERS",
      "isrc": "TCADE1704652",
      "error_frames": 0
    },
    {
      "number": 3,
      "first_frame": 46845360,
      "frame_count": 12527928,
      "audio_digest": "pcm1:44100:2:16:ec9ef8df3a670ca4d403b8deee88cc191e0b970c200e5a0bd0685f1d41c1f1a6",
      "title": "THIS ISN'T THE PLACE",
      "isrc": "TCADE1704653",
      "error_frames": 0
    },
    {
      "number": 4,
      "first_frame": 59373288,
      "frame_count": 8234940,
      "audio_digest": "pcm1:44100:2:16:a4c1115007e9541e58afc583e803addb25e76251e99a1dec77f6dd5512d9fee3",
      "title": "NOT ANYMORE",
      "isrc": "TCADE1704656",
      "error_frames": 0
    },
    {
      "number": 5,
      "first_frame": 67608228,
      "frame_count": 31052868,
      "audio_digest": "pcm1:44100:2:16:7cb0b19d5310c6af4400746e4c24694dd8c593296157149249e9320c661b055a",
      "title": "THE BACKGROUND WORLD",
      "isrc": "TCADE1704659",
      "error_frames": 0
    }
  ],
  "stored_files": [
    {
      "path": "data/disc.cdtext",
      "storage": "as_written",
      "original_name": "disc.cdtext",
      "original_size": 238,
      "original_sha256": "bd18550b603ba9759c008dd5fa0743d94772aeddf8e00d123ce418c257bd631c"
    },
    {
      "path": "data/disc.cue",
      "storage": "as_written",
      "original_name": "disc.cue",
      "original_size": 676,
      "original_sha256": "8181f2cf16faf9d86ec423a30bbc470a5caf54f451875ec847ebabbd413974dd"
    },
    {
      "path": "data/disc.fulltoc",
      "storage": "as_written",
      "original_name": "disc.fulltoc",
      "original_size": 92,
      "original_sha256": "a1178b635ddc3b154d4d8c88b7f2a0b67aadf564cec9d1f23d850955481c8314"
    },
    {
      "path": "data/disc.log",
      "storage": "as_written",
      "original_name": "disc.log",
      "original_size": 4038,
      "original_sha256": "68d41e15c4bbcb3f1d90e210c252aa37a42e26ce95fc88fb4a6972df7bb23416"
    },
    {
      "path": "data/disc.scram.flac",
      "storage": "flac",
      "original_name": "disc.scram",
      "original_size": 394877160,
      "original_sha256": "c58041824547cbd5405aea0f0cff3a6a042632115cf86ec765b5561cceefbf90"
    },
    {
      "path": "data/disc.state.xz",
      "storage": "xz",
      "original_name": "disc.state",
      "original_size": 98719290,
      "original_sha256": "dfaa98d24dccea681e2204e930716b82b0521ab851ecc35534a9aba96dc76413"
    },
    {
      "path": "data/disc.subcode.xz",
      "storage": "xz",
      "original_name": "disc.subcode",
      "original_size": 16117440,
      "original_sha256": "0c7e8b253b29f4e450be15c2ae3e925ff34048248357e4344ef7a6920f870415"
    },
    {
      "path": "data/disc.toc",
      "storage": "as_written",
      "original_name": "disc.toc",
      "original_size": 52,
      "original_sha256": "25b8f4879095020f14e33034b08c58d173ac6a31e01d98282d0478f0bf0dabe2"
    }
  ]
}
```

### Acquisition result

`copyofa acquire --json` prints, instead of its short human-readable result, a JSON
object with `evidence_set`, the absolute path of the new set, and
`acquisition_record`, the Acquisition Record as written. It is not a Report. Like
every `--json` output of CopyOfA, it is UTF-8, whatever the locale, and a path byte
that is not valid UTF-8 appears as a `\udcXX` escape.

### How an acquired set is accepted

Before reading the disc, acquire refuses, exiting 1 and creating nothing, when:

- `redumper` is not on `PATH`, or `redumper --version` does not give its build or gives
  one older than b768;
- the destination exists, its parent does not exist or cannot be opened, a staging
  directory left by an earlier import or acquire exists beside it, or its path is not
  valid UTF-8;
- the `--note` text, a `--ref` value or the `--drive` value is not valid UTF-8, which
  the Acquisition Record requires.

It then runs `redumper disc` once, in a directory inside the staging directory
`<destination>.copyofa-staging`. redumper's console output is not relayed: stderr
names each redumper stage, such as `redumper stage: dump`, and acquire's own steps.
After reading, acquire refuses or fails, exiting 1 and deleting the staging directory,
when:

- redumper exits with a status other than 0;
- the disc has more than one session or a track that is not audio, according to the
  table of contents in redumper's log;
- the log does not identify the drive, or gives no table of contents or no error
  counts; the cue sheet is missing, cannot be read, or lists other tracks than the
  table of contents;
- the image is missing or not a whole number of frames, or the state does not hold one
  byte per frame of the image;
- a track file is missing, or its bytes are found nowhere in the image at a frame
  boundary;
- redumper wrote a file that is neither a track file nor named `disc.<extension>` or
  `disc_<language code>.cue`;
- a stored file does not decode to the SHA-256 of redumper's original.

Each track's range is found where the previous track's ends, or else by searching the
image for the track's bytes; a track of a single repeated byte, such as digital
silence, that starts the disc is found where the next track begins. A range is
accepted only when it starts at a frame boundary and holds exactly the bytes of the
track file, so a disc whose every track is a single repeated byte fails: nothing
places its tracks in the image. Once every
file is stored and checked, acquire deletes the track files and redumper's
uncompressed originals, writes the tag files, and renames the staging directory to the
destination, as import does. When acquire is canceled, it stops redumper and deletes
the staging directory.

A disc read with errors is accepted, since the set is evidence of what the drive read,
but acquire exits 1: when `read_errors` gives SCSI or C2 errors, or a track has
`error_frames`. Subchannel errors alone do not count: the audio is read from the main
channel.

### Restoring redumper's files

`flac` and `xz` restore redumper's files exactly; CopyOfA is not needed. From the set's
`data/` directory, into an empty directory `~/restored`:

```bash
flac -d --force-raw-format --endian=little --sign=signed \
  -o ~/restored/disc.scram disc.scram.flac
xz -dc disc.state.xz > ~/restored/disc.state
xz -dc disc.subcode.xz > ~/restored/disc.subcode
cp disc.cdtext disc.cue disc.fulltoc disc.log disc.toc ~/restored/
shasum -a 256 ~/restored/*
```

Each SHA-256 is the `original_sha256` the record gives for that name. Copy only the
files the set holds. redumper can then split the image into track files again, whose
SHA-256s are the hashes in the tracks' Audio Digests:

```bash
cd ~/restored
redumper split --image-name=disc --overwrite
```

`--overwrite` lets it rewrite the cue sheet, which it writes again unchanged; it also
appends to `disc.log`.

## Checking a set without CopyOfA

From the bag root, `shasum`, which ships with macOS, checks both manifests:

```bash
cd /Volumes/Archive/Album
shasum -a 256 -c tagmanifest-sha256.txt
shasum -a 256 -c manifest-sha256.txt
```

Each prints `OK` per file and exits 0 when every listed file matches. On Linux,
`sha256sum -c` reads the same files. Three limits apply:

- A line whose path contains `%25`, `%0D`, or `%0A` names a file whose name holds `%`,
  a carriage return, or a line feed. `shasum` does not decode them and reports that
  file as missing; check it by hand under its decoded name.
- `shasum` checks only the files listed. It does not report files added under `data/`.
- The Library of Congress validator, `bagit.py --validate <set>` (for example through
  `uvx --from bagit bagit.py`), also checks that no file under `data/` is unlisted. It
  reports a set invalid once Finder has added a `.DS_Store` to it, and bagit.py 1.9.0
  does not decode `%25`
  ([bagit-python#157](https://github.com/LibraryOfCongress/bagit-python/issues/157)),
  so it also reports a set with `%` in a file name invalid.
  CopyOfA's own check, `copyofa verify`, ignores operating system metadata files and
  decodes every path; [Verification Report format](verification-report.md) describes
  it.
