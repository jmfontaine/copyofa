# Keep discs with read errors as read

- **Date:** 2026-10-26
- **Status:** Accepted
- **Supersedes:** in decision 1 of
  [ADR 0005](0005-acquire-audio-cds-with-redumper.md), redumper's default split, and
  decision 4 of [ADR 0007](0007-re-read-sectors-with-errors-when-acquiring.md); their
  other decisions stand
- **Related artifacts:**
  [Brief 0006: Acquire Damaged Discs](../briefs/0006-acquire-damaged-discs.md);
  Product Map capability
  [Acquire Audio and Record Its Origins](../product-map.md#acquire-audio-and-record-its-origins)
  and scenario [S1](../product-map.md#s1-preserve-a-cd)

## Context

Acquire re-reads each sector with a SCSI or C2 error up to 20 times (ADR 0007). A disc
whose errors remain still yields nothing. redumper b768 refuses to split a pressed CD
with an error left inside a track, or with a C2 error in its lead-in or lead-out ("data
errors detected, unable to continue"). It splits a CD-R with C2 errors at a track's
edges, but replaces each sector with an error by a generated sector filled with the
byte 0x55, so the track file matches no range of the image and acquire fails (see
[Evidence Set format](../formats/evidence-set.md#how-an-acquired-set-is-accepted)).

During v0.7.0, a pressed CD that looks undamaged kept 9 C2 samples in two sectors of
track 8 after 20 re-reads, and could not be preserved at all. Its image, state and
subchannel, everything else the reading produced, were deleted with it.

redumper b768 has two options for this (`cd/cd_split.ixx`). `--force-split` splits the
disc despite the errors. `--leave-unchanged` writes each sector with an error into the
track file as the image holds it, instead of generating one.

## Decision

1. **Acquire splits every disc as read.** `copyofa acquire` runs `redumper disc` with
   `--force-split --leave-unchanged`, besides `--retries`, on every disc. On a disc read
   without error, neither option changes the track files.
2. **A track holds what the drive returned.** A sample flagged with a C2 error holds
   the first read that returned it; sectors the drive never read are zeros, since
   redumper never writes them to the image. Each track stays a range of the image that
   holds exactly redumper's track file, as ADR 0005 requires, and its Audio Digest is
   the digest of that range. Nothing is generated.
3. **The record locates the errors.** The Acquisition Record, at a new format version
   2, gives each track the frame ranges its state does not mark as read successfully,
   each as not read or read with C2 errors. Brief 0006 specifies the fields.
4. **Such a set is accepted, and acquire exits 1**, as a disc read with errors already
   is. This supersedes decision 4 of ADR 0007, under which such a disc failed.

## Rationale and alternatives

- **As read** because the set is evidence of what the drive read. The Manifesto keeps
  useful partial evidence, and a disc with two bad sectors out of hundreds of thousands
  is mostly good audio. The record says exactly which frames are unreliable.
- **On every run** because ADR 0005 keeps acquire to one `redumper disc` run, and a
  disc that keeps errors would otherwise need a second read of several minutes.

Alternatives considered:

- **redumper's 0x55 fill (`--force-split` alone).** Rejected: it invents a pattern in
  the audio, and the track no longer matches the image, so its range and Audio Digest
  would no longer come from the image.
- **Keeping the image with no range for a damaged track.** Rejected: the track could
  then be neither inspected, compared nor exported, though most of it was read.
- **A separate option to keep damaged discs.** Rejected: the default would still
  discard the reading, and keeping it would need a second read.

## Consequences

- The Audio Digest of a track with errors identifies this reading, not the disc's
  audio: another reading of the same disc may give another digest. A track never read
  at all is zeros, and shares its digest with any other such track of its length.
- Acquire no longer fails because of redumper's generated sectors; its diagnostic for
  that case goes. It still fails when the last track is never read through to the
  image's end: the image is then shorter than the track, and redumper pads the track
  file.
- Splitting a restored set again, as the Evidence Set format shows, takes
  `--force-split --leave-unchanged`, which the record's `reader.arguments` lists:
  without them, redumper refuses the disc or generates sectors, and the track files no
  longer match the Audio Digests.
- Inspect, compare and export read the new record format, and still read version 1.
