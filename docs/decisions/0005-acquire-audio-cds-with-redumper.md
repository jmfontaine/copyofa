# Acquire audio CDs with redumper and store the disc image compressed

- **Date:** 2026-10-25
- **Status:** Accepted; in decision 1, redumper's default retry count superseded by
  [ADR 0007](0007-re-read-sectors-with-errors-when-acquiring.md), and its default split
  by [ADR 0008](0008-keep-discs-with-read-errors-as-read.md)
- **Related artifacts:**
  [Brief 0004: Preserve an Audio CD](../briefs/0004-preserve-an-audio-cd.md);
  [ADR 0001](0001-store-evidence-sets-as-bagit-bags.md) and
  [ADR 0002](0002-define-audio-digest-from-canonical-pcm.md); Product Map capabilities
  [Acquire Audio and Record Its Origins](../product-map.md#acquire-audio-and-record-its-origins)
  and
  [Preserve Evidence Throughout Its Lifetime](../product-map.md#preserve-evidence-throughout-its-lifetime),
  and scenario [S1](../product-map.md#s1-preserve-a-cd)

## Context

CopyOfA so far preserves files a collector already owns. Preserving a CD means reading
it: the audio, where each track starts, the disc's own identifiers, and how well each
frame was read. The collector must be able to analyze the audio again later, with
better methods, without the disc, so the Evidence Set must hold everything meaningful
the reading produced, and nothing large that can be derived from the rest.

The retired implementation read discs with
[redumper](https://github.com/superg/redumper) but accepted only one patched build and
one PLEXTOR drive, through a list of known-bad drive and build combinations, and ran
redumper stage by stage with resumable decisions. Nobody else could run it, and the
stages were most of its complexity. The bug that made the list necessary, a JMicron USB
bridge that corrupted lead-in reads, is fixed upstream.

A spike on the maintainer's PLEXTOR PX-W5224A, through that JMicron bridge, read a
5-track pressed audio CD with redumper b768 in one `redumper disc` run of 177 seconds,
without `sudo`, with no SCSI or C2 error, and with its lead-in verified. A second run,
with macOS's Audio CD volume mounted this time, wrote the same image and track files;
its state and subchannel differed in the lead-in and in the subchannel errors it
corrected. redumper wrote:

| File | Size (MB) | Content |
| --- | --- | --- |
| `.scram` | 395 | The disc image: every stereo frame from the lead-in to the lead-out, as read, about 98 MB of it zeros for the area the drive never reached |
| `.state` | 99 | One byte per frame of the image: whether it was read, and how |
| `.subcode` | 16 | The subchannel: track and index positions, ISRCs, the catalog number, CD-Text |
| Track `.bin` files | 288 | Each track's audio, cut from the image at the table of contents, with the disc's write offset applied |
| `.toc`, `.fulltoc`, `.cdtext`, `.cue`, `.log` | under 0.01 | The drive's tables of contents, CD-Text, the cue sheet, and the run's log |

`redumper split`, run on a copy of the image, state, subchannel and tables of contents
alone, rewrote all five track files byte for byte, and each track file equals a
contiguous range of the image. An audio CD's image is plain 16-bit stereo PCM at 44.1
kHz, so it compresses as audio: libsndfile wrote it as a 147.5 MB FLAC file in 4
seconds, decoded it back to the same SHA-256 in 1.5 seconds, and read track 3 from it
by seeking to its first frame, again with the SHA-256 of redumper's track file. zstd at
its highest level made 269 MB of the image. xz reduced the state to 15 KB and the
subchannel to 0.55 MB. The set would hold about 148 MB, where redumper's files take
about 800 MB and the track files alone 288 MB.

## Decision

1. **redumper reads the disc.** `copyofa acquire` runs `redumper disc` once per disc,
   with redumper's own drive detection, offsets and defaults, and requires redumper
   build b768 or later on `PATH`. It refuses no drive and no bridge: the Acquisition
   Record names the drive, the redumper build and the offsets, so what was used stays
   visible. redumper is an external program, not a Python dependency, and only acquire
   needs it.
2. **Plain audio CDs only.** A disc with more than one session, or with a track that is
   not audio, is refused, and nothing is preserved.
3. **Preserve everything meaningful, once.** The Preserved Evidence is every file
   redumper writes except the track `.bin` files, which the rest reproduces byte for
   byte. The image is stored as FLAC, the state and the subchannel as xz, and every
   other file as written:
   - `data/disc.scram.flac`: the image as 16-bit stereo FLAC at 44.1 kHz, written by
     libsndfile at its highest compression level. soundfile's minimum rises to 0.13,
     its first release that sets a FLAC compression level;
   - `data/disc.state.xz` and `data/disc.subcode.xz`: written with Python's `lzma`;
   - `data/disc.toc`, `data/disc.fulltoc`, `data/disc.cdtext`, `data/disc.cue` and
     `data/disc.log`, each when redumper writes it.

   Before the set is accepted, each compressed file is decoded and its SHA-256
   compared with the original's. The Acquisition Record gives each original's name,
   size and SHA-256, so `flac -d --force-raw-format --endian=little --sign=signed` and
   `xz -d` restore redumper's files exactly, and `redumper split` can run on them again.
4. **A track is a range of the image.** Acquire finds each track's first frame in the
   image, checks that the range holds exactly the bytes of redumper's track file, and
   records its first frame and length. CopyOfA reads a track by decoding that range of
   the FLAC file. It needs neither redumper nor redumper's layout of the image to
   analyze a preserved disc. The SHA-256 of redumper's track file, which is the
   canonical PCM of ADR 0002, is the hash in the track's Audio Digest.
5. **An Acquisition Record.** `copyofa/acquisition-record.json` records the
   acquisition: when it ran, the drive, the redumper build and command, the offsets,
   the read errors, what the disc says about itself (catalog number, ISRCs, CD-Text),
   each track's range, Audio Digest and frames not read successfully, and each stored
   file. Its format is documented in `docs/formats/evidence-set.md`. The tag manifest
   lists it, and CopyOfA uses it only when the tag manifest lists it and its SHA-256
   matches, since it defines where the tracks are.

## Rationale and alternatives

- **redumper** reads what other rippers do not: the lead-in and lead-out, the
  subchannel, C2 error pointers, and the disc's write offset, and it knows
  the read offset of most drives. It is maintained, runs on macOS without special
  privileges, and produces the dumps the Redump project accepts.
- **One `redumper disc` run** keeps acquire a single command that succeeds or fails.
  The retired implementation's stages, decisions and resumes cost more than they
  saved.
- **The image, not the track files,** because only the image holds the first track's
  pregap, the lead-in and the lead-out, and only the image, the state and the
  subchannel let a later redumper split the disc again. The track files are then
  redundant, and the largest file to drop.
- **The state and the subchannel** because they are evidence of this reading: two
  reads of the same disc gave the same audio but different read status in the lead-in
  and different subchannel errors.
- **FLAC for the image** because the image of an audio CD is audio: FLAC is lossless,
  stores it in 37% of its size, any FLAC decoder restores it, and libsndfile, already
  bundled with soundfile, writes and seeks it. zstd saved half as much, and its Python
  module is standard only from Python 3.14.
- **xz for the state and subchannel** because Python's `lzma` writes it with no new
  dependency, `xz` restores it on any system, and it reduced them to 0.6 MB together.
- **Track ranges recorded at acquisition** because redumper's layout of the image is
  its own and may change between builds. Checking each range against redumper's track
  file when both exist proves the range once, and the record keeps it.

Alternatives considered:

- **Keeping redumper's files uncompressed.** Rejected: about 800 MB for a 288 MB disc,
  most of it zeros, per-frame flags and the track files' second copy of the audio.
- **Keeping only the track files.** Rejected: it loses the pregap, the lead-in, the
  lead-out and the per-frame read status, and a better split later would need the
  disc.
- **Keeping both the track files and the image.** Rejected: the track files duplicate
  the image.
- **Another ripper, such as cd-paranoia or cdrdao.** Rejected: they capture less of
  the disc, without the lead-in or C2 status, and neither finds the disc's
  write offset.
- **Refusing drives or bridges known to misbehave.** Rejected: the bug that motivated
  it is fixed, and a list of refusals is what kept the retired implementation from
  anyone else's hardware.

## Consequences

- Acquire needs redumper installed separately, at build b768 or later. CI cannot read
  a disc: acquisition tests run against a stand-in `redumper` that writes small
  synthetic files, and a real disc is acquired by hand for each release that changes
  acquisition.
- Acquire reads the drive, the offsets and the error counts from redumper's log, whose
  format redumper may change. A log acquire cannot read fails the acquisition with the
  reason; the minimum build is the one tested.
- A preserved disc holds no playable track file. `copyofa export` writes them, and
  inspect and compare read tracks from the image.
- Every set stores the image whole, about 148 MB for a 27-minute disc. The zeros of
  the unread area cost almost nothing once compressed.
- soundfile's minimum rises from 0.12 to 0.13.
- Revisit this decision to support other discs (CD-Extra, mixed mode, audio before the
  first track), damaged discs that need retries or refining, or when redumper changes
  the files it writes.
