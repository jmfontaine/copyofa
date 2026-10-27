# Inspection Report format

`copyofa inspect <evidence-set> --json` prints an inspection Report: a JSON document
describing the audio in an [Evidence Set](evidence-set.md). Like every `--json` output
of CopyOfA, it is UTF-8, whatever the locale; a path that is not valid UTF-8 keeps
each invalid byte as a `\udcXX` escape (see
[Import result](evidence-set.md#import-result)). Save it with a shell redirect:

```bash
copyofa inspect /Volumes/Archive/Album --json > album-inspection.json
```

A Report describes each preserved file's format and properties and, for lossless
audio, gives its Audio Digest. For an [acquired set](evidence-set.md#acquired-sets), it
also describes each track of the disc. It draws no conclusion about where the audio
comes from or how well it was acquired.

Inspect prints format version 3. Its JSON Schema is
[inspection-report-3.schema.json](../../src/copyofa/schemas/inspection-report-3.schema.json);
that of [format version 2](#format-version-2) is
[inspection-report-2.schema.json](../../src/copyofa/schemas/inspection-report-2.schema.json),
and that of [format version 1](#format-version-1) is
[inspection-report-1.schema.json](../../src/copyofa/schemas/inspection-report-1.schema.json);
[`copyofa validate`](validation-result.md) checks a Report against the schema of its
version.

## How inspect works

1. **Integrity first.** Inspect checks the Integrity Baseline as `verify` does (see
   [Verification Report format](verification-report.md#how-verify-checks-a-set)). When
   it is unusable, no file is decoded: each entry of `manifest-sha256.txt`, when it
   can still be parsed, is reported `not_inspected`.
2. **Only accepted bytes.** Each file the manifest lists is read completely, in the
   manifest's order, and its SHA-256 compared with the manifest's before it is decoded;
   the disc image of an acquired set is read first (see below). Inspect follows no
   symbolic link inside the set and never blocks on a special file. A file whose size
   or modification time changes between that check and the end of its decoding is
   reported `not_inspected`.
3. **Interpretation.** For content that starts as FLAC, after any ID3v2 tag, inspect
   reads the STREAMINFO block first. It then decodes, with libsndfile:
   - FLAC at 8, 16 or 24 bits whose STREAMINFO gives a length;
   - WAV with integer PCM samples of 8 to 32 bits, including WAVE_FORMAT_EXTENSIBLE;
   - MP3 (MPEG-1 or MPEG-2 Layer III).

   Everything else is `not_interpreted`, whatever its name: other formats, such as
   AIFF, ALAC, Ogg Vorbis, RF64 or Sony Wave64; other encodings, such as float WAV or
   MPEG Layer II; FLAC at other depths, such as 20 or 32 bits; and FLAC whose
   STREAMINFO gives no length. A file that is not interpreted may still hold audio.
   Inspect does not open archives or read tags and embedded artwork.

4. **Tracks of an acquired set.** When the tag manifest lists the Acquisition Record,
   inspect reads it once, and uses it only when the Integrity Baseline is usable and
   the bytes read have the SHA-256 the tag manifest records, parse as JSON, and give
   format version 1 or 2 of `copyofa.acquisition`, a disc image that
   `manifest-sha256.txt` lists, 16-bit stereo at 44.1 kHz, and a number, a range and
   an Audio Digest for each track, with valid error ranges in a version 2 record (see
   [Evidence Set format](evidence-set.md#acquisition-record)). Inspect then reads the
   disc image completely once, before any file is
   decoded, and compares its SHA-256 with the manifest's as for a file. It decodes the
   image's own entry, then each track in the record's order, from that one opening of
   the image: a track is decoded over its range, from its first frame for its frame
   count. A track is `not_inspected` when the image is not the accepted bytes, or when
   the image's size or modification time changed between that check and the end of
   the track's decoding, with the reason a file gets when it changes while inspected.

Files that `manifest-sha256.txt` does not list are not inspected; `verify` reports
them. Inspect writes nothing into the set.

## Outcomes

Each listed file gets exactly one outcome:

| Outcome | Meaning |
| --- | --- |
| `interpreted` | The file is the accepted bytes and was decoded completely. |
| `not_interpreted` | The content is not a supported format, encoding or depth; the reason names what was recognized, if anything. Not a problem. |
| `failed` | The content is supported audio or FLAC, or the name ends in `.flac`, `.wav` or `.mp3` (in any case), but the file could not be opened or decoded completely. |
| `not_inspected` | The file is missing, could not be read, is not a regular file, is not the accepted bytes, changed while inspected, or the Integrity Baseline is unusable. |

Each track of an acquired set gets exactly one of these outcomes:

| Outcome | Meaning |
| --- | --- |
| `interpreted` | The image is the accepted bytes, and its range was decoded completely. |
| `failed` | The image could not be decoded over the range: it is not 16-bit stereo FLAC at 44.1 kHz, the range ends after the image, or decoding stopped. |
| `not_inspected` | The image was not inspected, for any reason a file is `not_inspected`, such as when it is not the accepted bytes. |

The image file itself keeps its entry in `files`, as any FLAC file.

## Fields

| Field | Content |
| --- | --- |
| `report_kind` | Always `copyofa.inspection`. |
| `format_version` | The version of this format, `3`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that ran the inspection. |
| `inspected_at` | The inspection time in UTC, such as `2026-10-25T18:30:00Z`. |
| `evidence_set` | The Evidence Set's path, as the verification Report records it. |
| `integrity_baseline` | The baseline used: `manifest_sha256`, `usable` and `problems`, as in the verification Report. |
| `method` | `decoder`, always `libsndfile`, and `decoder_version`, such as `1.2.2`. The version of the mpg123 library that libsndfile uses for MP3 is not available to CopyOfA. |
| `files` | One entry per entry of `manifest-sha256.txt`, in its order; empty when that manifest is missing or cannot be parsed. |
| `disc` | For an acquired set, a set whose tag manifest lists `copyofa/acquisition-record.json`: either `tracks`, one entry per track of the Acquisition Record, in its order, or, when the record cannot be used, `reason`, a sentence saying why, and no track. Absent for any other set. |
| `counts` | The number of files per outcome: `interpreted`, `not_interpreted`, `failed` and `not_inspected`. |
| `limitations` | Sentences stating what the whole Report does not establish or did not examine. |

Each entry of `files` holds:

- `path`: the path from the set's root, decoded, such as `data/Album/01.flac`.
- `outcome`: one of the outcomes above.
- `expected_digest`: the SHA-256 the manifest records.
- `observed_digest`: the File Digest, the SHA-256 of the file as read; present only
  when the file was read completely.
- `reason`: why the outcome is not `interpreted`, as a sentence that may end with the
  library's own message; absent when it is.

An `interpreted` entry also holds:

- `format`: `flac`, `wav` or `mp3`.
- `encoding`: libsndfile's encoding, in lowercase: `pcm_s8`, `pcm_u8`, `pcm_16`,
  `pcm_24`, `pcm_32` or `mpeg_layer_iii`.
- `sample_rate`: frames per second.
- `channels`: the channel count.
- `bits_per_sample`: for FLAC and WAV, the stored sample size: STREAMINFO's for FLAC,
  and the container's for WAV, not a smaller valid-bits value.
- `frames`: the sample frames per channel that were decoded. Duration is `frames`
  divided by `sample_rate`. For FLAC it is the length STREAMINFO declares: inspect
  reports a FLAC file that ends early as `failed`, but does not decode frames beyond
  that length. For MP3 it is whatever the decoder produced, which depends on its
  handling of the encoder delay and padding; an MP3 that was cut short cannot be told
  apart from a shorter recording.
- `audio_digest`: for FLAC and WAV, the Audio Digest (see below).
- `peak`: the largest absolute sample value of each channel, in channel order. For
  FLAC and WAV it is an exact integer at the bits per sample, so a 16-bit file at full
  scale gives 32768 for its lowest value; 8-bit WAV samples count from their signed
  value. For MP3 it is the decoded floating-point value, where 1.0 is full scale; it
  depends on the decoder, and decoded MP3 often exceeds 1.0.
- `leading_silence_frames` and `trailing_silence_frames`: the number of frames at the
  start and at the end in which every channel is exactly zero. A file that is silent
  throughout reports all its frames as leading silence and none as trailing. For MP3
  they depend on the decoder, and lossy encoding rarely leaves exact zeros next to
  sound.
- `flac_md5_signature`: for FLAC, whether the decoded audio matches the MD5 signature
  its encoder stored in STREAMINFO, an MD5 of the same byte stream the Audio Digest
  hashes: `matching`, `differs`, or `absent` when the encoder stored zeros. `differs`
  means the file is not the audio its encoder wrote, and makes inspect exit 1.
- `limitations`: for MP3, why it has no Audio Digest.

Each entry of `tracks` holds:

- `number`, `first_frame` and `frame_count`: the track's number and its range in the
  image, in frames, as the Acquisition Record gives them.
- `outcome`: one of the track outcomes above.
- `reason`: why the outcome is not `interpreted`; absent when it is. For a track
  `not_inspected`, it names the image and says why it was not inspected.
- `audio_digest`: the Audio Digest of the decoded range; present only when
  `interpreted`.
- `recorded_audio_digest`: the Audio Digest the Acquisition Record gives, computed at
  acquisition from redumper's track file.
- `frames`, `peak`, `leading_silence_frames` and `trailing_silence_frames`: as for a
  file, measured over the range; present only when `interpreted`.
- `error_ranges`: the track's frames the drive did not read successfully, copied from
  an Acquisition Record of format version 2, whatever the track's outcome: a list,
  empty when the track has none, of ranges with `offset_frames`, the range's first
  frame counted from the track's first frame, `frame_count`, and `state`, `not_read`
  or `c2_error` (see [Evidence Set format](evidence-set.md#acquisition-record)).
  Absent when the record is format version 1, which gives no error ranges.

A track whose `audio_digest` differs from its `recorded_audio_digest` is not the audio
acquired, and makes inspect exit 1. A track with error ranges that decodes to its
recorded Audio Digest is `interpreted`: the set is as acquired, and its ranges change
neither the outcome nor the exit code. The text result ends the line of each such
`interpreted` track with `,` and the same description of its ranges, grouped into
areas, as export's warning gives (see
[Export result format](export-result.md#frames-not-read-successfully)), such as, for
track 14:

```text
, 2 frames not read successfully, in 1 area: 4:05.389 (2 frames with C2 errors)
```

## Audio Digest

An Audio Digest recognizes identical decoded audio, as
[ADR 0002](../decisions/0002-define-audio-digest-from-canonical-pcm.md) defines it:

```text
pcm1:<sample rate>:<channels>:<bits per sample>:<sha256>
```

`<sha256>` is the SHA-256 of every sample frame in order, the channels of each frame
interleaved, each sample a signed little-endian integer in 1, 2, 3 or 4 bytes for 8,
16, 24 or 32 bits; 8-bit WAV samples, stored unsigned, have 128 subtracted. Retagging a
FLAC file, changing its compression level, or converting it to a WAV file of the same
sample size keeps its Audio Digest. Lossy audio, such as MP3, has none, because its
decoded samples differ from one decoder to another.

Reproduce the hash without CopyOfA with `flac` or `ffmpeg`, giving ffmpeg the format
that matches the bits per sample (`s8`, `s16le`, `s24le` or `s32le`): ffmpeg converts
silently to any format it is given, and a mismatched one gives another hash.

```bash
flac -d --force-raw-format --endian=little --sign=signed -c 01.flac | shasum -a 256
ffmpeg -i 01.flac -f s24le - | shasum -a 256
```

## Format version 2

Inspect printed format version 2 from CopyOfA 0.5.0 to 0.7.0. It is version 3 without
`error_ranges`, and `format_version` is `2`. `copyofa validate` still accepts it, and
the version 2 schema is unchanged. A Report with `error_ranges` is not valid at
version 2.

## Format version 1

Inspect printed format version 1 before CopyOfA 0.5.0. It is version 2 without
`disc`, and `format_version` is `1`. `copyofa validate` still accepts it, and the
version 1 schema is unchanged. A Report with `disc` is not valid at version 1.

## Example

```json
{
  "report_kind": "copyofa.inspection",
  "format_version": 3,
  "copyofa_version": "0.8.0",
  "inspected_at": "2026-10-25T18:30:00Z",
  "evidence_set": "/Volumes/Archive/Album",
  "integrity_baseline": {
    "manifest_sha256": "bf4b…",
    "usable": true,
    "problems": []
  },
  "method": {
    "decoder": "libsndfile",
    "decoder_version": "1.2.2"
  },
  "files": [
    {
      "path": "data/Album/01.flac",
      "outcome": "interpreted",
      "expected_digest": "0673…",
      "observed_digest": "0673…",
      "format": "flac",
      "encoding": "pcm_24",
      "sample_rate": 96000,
      "channels": 2,
      "bits_per_sample": 24,
      "frames": 30270376,
      "audio_digest": "pcm1:96000:2:24:75e1…",
      "peak": [8108127, 8107460],
      "leading_silence_frames": 0,
      "trailing_silence_frames": 0,
      "flac_md5_signature": "matching"
    },
    {
      "path": "data/Album/02.mp3",
      "outcome": "interpreted",
      "expected_digest": "44c0…",
      "observed_digest": "44c0…",
      "format": "mp3",
      "encoding": "mpeg_layer_iii",
      "sample_rate": 44100,
      "channels": 2,
      "frames": 10696320,
      "peak": [1.2177221775054932, 1.1910574436187744],
      "leading_silence_frames": 1,
      "trailing_silence_frames": 96,
      "limitations": [
        "MP3 is lossy: its decoded samples, and so its frame count, depend on …"
      ]
    },
    {
      "path": "data/Album/cover.jpg",
      "outcome": "not_interpreted",
      "expected_digest": "456f…",
      "observed_digest": "456f…",
      "reason": "no supported audio format was recognized"
    }
  ],
  "counts": {
    "interpreted": 2,
    "not_interpreted": 1,
    "failed": 0,
    "not_inspected": 0
  },
  "limitations": [
    "Only the files manifest-sha256.txt lists are inspected; verify reports …",
    "An Audio Digest recognizes identical decoded audio. It does not say …",
    "A file that is not interpreted may still hold audio, in a format …"
  ]
}
```

The example is shortened: a Report holds all 64 hexadecimal digits of each digest, and
the whole of each limitation.

The `disc` of an acquired set, *Add Violence* by Nine Inch Nails (2017 CD), with two
of its five tracks; its image, `data/disc.scram.flac`, has its own entry in `files`:

```json
"disc": {
  "tracks": [
    {
      "number": 1,
      "first_frame": 26548188,
      "frame_count": 9285108,
      "outcome": "interpreted",
      "audio_digest": "pcm1:44100:2:16:1e9b66e1…",
      "recorded_audio_digest": "pcm1:44100:2:16:1e9b66e1…",
      "frames": 9285108,
      "peak": [28930, 28922],
      "leading_silence_frames": 0,
      "trailing_silence_frames": 0,
      "error_ranges": []
    },
    {
      "number": 5,
      "first_frame": 67608228,
      "frame_count": 31052868,
      "outcome": "interpreted",
      "audio_digest": "pcm1:44100:2:16:7cb0b19d…",
      "recorded_audio_digest": "pcm1:44100:2:16:7cb0b19d…",
      "frames": 31052868,
      "peak": [32768, 32768],
      "leading_silence_frames": 0,
      "trailing_silence_frames": 356,
      "error_ranges": []
    }
  ]
}
```

When the Acquisition Record cannot be used, `disc` holds only the reason:

```json
"disc": {
  "reason": "the Acquisition Record's digest differs from the tag manifest's"
}
```

## Exit codes

`copyofa inspect` exits 0 when the Integrity Baseline is usable, every listed file is
`interpreted` or `not_interpreted`, no FLAC MD5 signature differs, and, for an acquired
set, the Acquisition Record can be used and every track is `interpreted` with its
recorded Audio Digest. It exits 1 otherwise, and still prints its result or Report. It
exits 2, printing nothing on stdout, when the target is not an Evidence Set or the
arguments are invalid, and 130 when canceled with Ctrl-C. It also exits 1, with
`copyofa: stdout closed` on stderr, when stdout is closed before or while it prints its
result or Report. mpg123 may write notes about damaged MP3 frames to stderr.
