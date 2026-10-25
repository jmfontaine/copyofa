# Brief: Describe the Audio in an Evidence Set

## Goal and context

A collector learns what audio an Evidence Set holds: the format and properties of each
track, an Audio Digest that recognizes the same audio despite retagging or
recompression, and a few exact measurements. All of it lands in a Report another
program can read.

- **Milestone:** [v0.2.0](https://github.com/jmfontaine/copyofa/milestone/2)
- **Product Map capability:** [Understand Audio](../product-map.md#understand-audio);
  the Report also starts
  [Share and Evaluate Findings](../product-map.md#share-and-evaluate-findings)
- **Decision:**
  [ADR 0002: Define Audio Digest from canonical PCM](../decisions/0002-define-audio-digest-from-canonical-pcm.md)

This is the first release that decodes audio. It brings the decoding and the Audio
Digest that comparison and discovery will build on, and the second kind of Report.

## Primary scenario

Refines [S2](../product-map.md#s2-use-audio-files-already-owned): a collector analyzes
the supported audio in a delivery they preserved with v0.1.0.

1. A collector has preserved a FLAC album and an MP3 album as Evidence Sets.
2. They run `copyofa inspect /Volumes/Archive/Album`. CopyOfA first checks each listed
   file against the Integrity Baseline, then decodes it.
3. The result lists each track with its format, sample rate, bit depth, channels and
   duration, and the cover, the scans and the cue sheet as not interpreted.
4. `--json` prints an inspection Report. For each FLAC track it gives an Audio Digest
   that `flac -d … | shasum -a 256` reproduces without CopyOfA, the peak of each
   channel, the digital silence at each end, and whether the audio matches the FLAC
   file's own MD5 signature.
5. For the MP3 album, the Report gives the same properties and measurements, names the
   decoder they depend on, and says why the tracks have no Audio Digest.
6. A track damaged since acceptance is reported as not inspected, and the command exits
   non-zero.

## In scope

- `copyofa inspect <evidence-set>` with `--json`.
- Decoding FLAC, integer PCM WAV, and MP3 (MPEG-1/2 Layer III).
- Per track: format, encoding, sample rate, channels, bits per sample (PCM), frames,
  Audio Digest (FLAC and WAV), per-channel peak, leading and trailing digital
  silence, and the FLAC MD5 signature check.
- An inspection Report, documented in `docs/formats/inspection-report.md`.

## Out of scope

- Other formats: AIFF, ALAC, WavPack, Monkey's Audio, Ogg Vorbis, Opus, AAC, MPEG
  Layers I and II, DSD, and 32-bit float PCM. They are reported as not interpreted.
- Audio Digest for MP3 or any lossy format (ADR 0002).
- Ranges, cue sheets, and assembled Audio Sequences; a file is one Audio Sequence.
- Reading tags or embedded artwork, and reading inside archives.
- Loudness, spectral, clipping or anomaly analysis beyond the measurements above.
- Inspecting files outside an Evidence Set.
- Writing the Report into the Evidence Set; it goes to stdout.
- A portable human-readable view of the Report, and validating a received Report.
- Comparison of tracks or editions.

## Requirements

### What is inspected

- **Integrity first.** Inspect checks the records as `verify` does, then inspects each
  file `manifest-sha256.txt` lists, in its order. When the Integrity Baseline is
  unusable, no file is decoded, and each entry the manifest still parses to is
  reported not inspected.
- **Only accepted bytes.** Each file is read completely and its SHA-256 compared with
  the manifest's before its findings count. A file that is missing, unreadable, not a
  regular file (a directory, a symbolic link, a special file such as a named pipe, or
  a path through a symbolic link), or whose digest differs is reported not inspected
  with the reason, and is not decoded. Inspect follows no symbolic link inside the set
  and never blocks on a special file.
- **Stable while inspected.** A file whose size or modification time changes between
  the digest and the end of decoding is reported not inspected.
- **Unlisted files.** Files the manifest does not list are not looked for or inspected;
  `verify` reports them. The Report states this limitation.

### Interpretation

- **Supported audio.** A file whose content libsndfile identifies as FLAC, WAV with
  integer PCM samples, or MP3 Layer III is decoded completely. A supported file that
  stops decoding early, such as a truncated FLAC file, is reported failed with the
  decoder's reason.
- **Expected but unrecognized.** A file named `*.flac`, `*.wav` or `*.mp3`
  (case-insensitive) whose content libsndfile cannot open is reported failed with the
  decoder's reason.
- **Everything else** is reported not interpreted, whatever its name: content in a
  format or encoding outside the supported list, such as AIFF, float WAV or MP3 Layer
  II, with a reason that names what was recognized, and content nothing recognizes,
  with a reason that says so. Not interpreted makes no claim that the file holds no
  audio.

### Findings per decoded file

- **Properties:** format (`flac`, `wav`, `mp3`), encoding (such as `pcm_16`, `pcm_24`,
  `mpeg_layer_iii`), sample rate, channel count, bits per sample for PCM, and frames
  (sample frames per channel). Duration is frames divided by sample rate; the human
  result shows it, the Report does not repeat it.
- **Audio Digest** for FLAC and WAV, as ADR 0002 defines it. MP3 files have none, and
  their entry states why.
- **Peak:** the largest absolute sample value per channel. For PCM it is the exact
  integer; for MP3 it is the decoded 32-bit float value, which depends on the decoder.
- **Digital silence:** the number of leading and of trailing frames in which every
  channel is exactly zero. A file of only zero frames reports all its frames as
  leading silence and none as trailing.
- **FLAC MD5 signature:** for FLAC, `matching` when the MD5 in STREAMINFO equals the MD5
  of the canonical PCM byte stream, `differs` when not, and `absent` when the encoder
  wrote all zeros.

### Output and exit codes

Inspect follows the command conventions in AGENTS.md:

- The human result gives one line per decoded file (path, format, sample rate, bits
  per sample, channels, duration) and a count per outcome. `--json` prints the
  inspection Report instead.
- Progress, one line per file, goes to stderr.
- Exit 0 when the baseline is usable, every listed file was decoded or not interpreted,
  and no FLAC MD5 signature differs. Exit 1 otherwise, still printing the result.
  Exit 2 for invalid arguments or a target that is not an Evidence Set. Exit 130 when
  canceled, with nothing on stdout.
- Inspect writes nothing into the Evidence Set.

## Design decisions

- **Decoder.** [soundfile](https://github.com/bastibe/python-soundfile), whose wheels
  bundle libsndfile with FLAC and mpg123 support, and NumPy for the sample arithmetic.
  These are CopyOfA's first runtime dependencies. PCM is read as 32-bit integers and
  shifted back to its bit depth, which a probe confirmed is exact for 8-, 16- and
  24-bit FLAC; MP3 is read as 32-bit floats.
- **Outcomes.** `interpreted`: decoded completely, with findings. `not_interpreted`:
  not a supported format; not a problem. `failed`: expected to be supported but could
  not be decoded. `not_inspected`: the bytes could not be read or are not the accepted
  ones.
- **Inspection Report format.** A JSON document with `report_kind`
  `copyofa.inspection` and a `format_version`. It records: the CopyOfA version; the
  inspection time in UTC; the Evidence Set path, as the verification Report records
  it; the Integrity Baseline used (its `manifest-sha256.txt` SHA-256, usability and
  problems, as in the verification Report); the method, naming the decoder and its
  version; one entry per listed file with its path, File Digest, outcome, reason when
  not interpreted, and the findings above when interpreted; a count per outcome; and
  the limitations that apply to the whole Report, including that an Audio Digest
  establishes neither source nor acquisition accuracy.
- **Not an Evidence Set** means what it means for `verify`.

## Blocking questions

None.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise. Test audio is
generated by the tests; no recording is committed.

- **AC1 — Audio Digest.** For generated 16- and 24-bit FLAC and WAV files, the Report
  gives the `pcm1` Audio Digest of ADR 0002, equal to a value the test computes
  independently from the generated samples. The same samples in FLAC and in WAV get the
  same Audio Digest; a FLAC file re-encoded at another compression level, or with a tag
  added, gets a different File Digest and the same Audio Digest. By hand, once: the
  Audio Digest of a real FLAC track equals the hash of
  `flac -d --force-raw-format --endian=little --sign=signed -c` piped to
  `shasum -a 256`.
- **AC2 — Properties.** For FLAC, WAV and MP3 files of known parameters, the Report
  gives their format, encoding, sample rate, channels, bits per sample (PCM only) and
  frames.
- **AC3 — MP3 without Audio Digest.** An MP3 file is interpreted with properties and
  measurements, has no Audio Digest, and its entry says why; the method names the
  decoder and its version.
- **AC4 — Measurements.** For a generated signal with known leading and trailing
  zero frames and known per-channel peaks, the Report gives those values, for PCM
  exactly. An all-zero file reports all frames as leading silence.
- **AC5 — FLAC MD5 signature.** A FLAC file reports `matching`. With its STREAMINFO MD5
  altered it reports `differs` and the command exits 1; with it zeroed it reports
  `absent` and the command exits 0.
- **AC6 — Material not interpreted.** A JPEG, a text file, a ZIP, and an AIFF file are
  reported not interpreted with a reason, and the command exits 0 when nothing else is
  wrong. A truncated FLAC file and a `.mp3` that is not MP3 are reported failed, and
  the command exits 1.
- **AC7 — Integrity first.** A payload file modified, deleted, made unreadable, replaced
  by a directory, by a symbolic link, and by a named pipe are each reported not
  inspected with the reason and not decoded, without blocking, and the command exits
  1. With `manifest-sha256.txt` edited, no file is decoded and the command exits 1.
- **AC8 — Command conventions.** Inspect follows the output and exit-code rules above:
  `--json` prints the Report, progress goes to stderr, a target that is not an Evidence
  Set exits 2 with empty stdout, Ctrl-C exits 130 with empty stdout, and the Evidence
  Set's files are unchanged afterward.
- **AC9 — Report documented.** `docs/formats/inspection-report.md` describes the Report
  and matches the implementation, including how to reproduce an Audio Digest with
  `flac` or `ffmpeg`. The README shows the command.
- **AC10 — Real collection (by hand, once).** Inspecting an Evidence Set imported from
  one of the maintainer's FLAC albums and one MP3 album completes with exit 0, and
  every track is interpreted.

## Manifesto alignment

- **Evidence, identity, and conclusions are distinct:** File Digest and Audio Digest
  are separate fields; the same samples in FLAC and WAV resolve to one Audio Digest
  while each file keeps its own File Digest; the Report states that a digest
  recognizes identical audio without saying what it is.
- **Results should be reproducible and durable:** Audio Digest is defined on a byte
  stream standard tools produce, and decoder-dependent values name their decoder and
  its version.
- **Measurements and interpretations should remain distinguishable:** measurements are
  exact counts and values, and the Report draws no conclusion from them. Files that
  were not interpreted, could not be decoded, or were not the accepted bytes are
  reported with their reason, never silently skipped.
- **Sharing and interoperability matter:** the inspection Report is a documented JSON
  format that other programs, such as an external recording catalog, can read without
  CopyOfA.
- **Accuracy must remain usable:** inspect reads the set without changing it, so it can
  run on any archive at any time.

## Appetite and scope cuts

Appetite: one day.

If the work outgrows it, cut in this order, keeping FLAC and MP3 decoding, Audio
Digest, and the inspection Report:

1. WAV support.
2. The FLAC MD5 signature check.
3. Digital silence.
4. Progress output on stderr.
