# Comparison Report format

`copyofa compare <track-a> <track-b> --json` prints a comparison Report: a JSON
document measuring how the audio of two tracks preserved in
[Evidence Sets](evidence-set.md) relates. Like every `--json` output of CopyOfA, it is
UTF-8, whatever the locale; a path that is not valid UTF-8 keeps each invalid byte as a
`\udcXX` escape (see [Import result](evidence-set.md#import-result)). Save it with a
shell redirect:

```bash
copyofa compare "/Volumes/Archive/With Teeth/data/04 The Hand That Feeds.flac" \
  "/Volumes/Archive/Definitive NIN/data/18 The Hand That Feeds.mp3" --json > htf.json
```

A Report holds measurements: offset, overlap, correlation, gain and residual. It
draws no conclusion from them, such as "same master" or "match", and has no threshold.
[ADR 0003](../decisions/0003-measure-track-comparisons-on-aligned-decoded-audio.md)
records the method and why it was chosen.

Its JSON Schema is
[comparison-report-1.schema.json](../../src/copyofa/schemas/comparison-report-1.schema.json);
[`copyofa validate`](validation-result.md) checks a Report against it.

## How compare works

1. **Finding each set.** Each track is the path of a file inside an Evidence Set. Its
   set is the nearest directory above it that holds `bagit.txt`, and the file must lie
   under that set's `data/`. Otherwise compare exits 2. Under a directory that cannot
   be searched, such as a set root without search permission, the set is the nearest
   directory whose `data/` holds the file; its records then cannot be read, and the
   input is `not_inspected`.
2. **Integrity first.** Each input is checked as `inspect` checks a file (see
   [Inspection Report format](inspection-report.md#how-inspect-works)): the Integrity
   Baseline must be usable, `manifest-sha256.txt` must list the file, and the file must
   be the accepted bytes. It is then decoded with libsndfile: FLAC, WAV or MP3, with
   inspect's rules, outcomes and reasons. When either input is not `interpreted`,
   nothing is measured.
3. **Common rate.** When the sample rates differ, the track at the higher rate is
   resampled to the lower one with libsoxr at its `VHQ` quality. Measurements cover
   only the band of that common rate.
4. **Alignment.** Each track is mixed down to mono, the mean of its channels. The
   offset is the lag with the largest magnitude of the FFT cross-correlation of the
   two downmixes: one global offset, in whole frames at the common rate.
5. **Measurements.** Over the frames where the aligned tracks overlap, compare
   measures the correlation, the gain and the residual on the downmix, and for each
   channel when both tracks have the same channel count.

Compare writes nothing into either set.

## Fields

| Field | Content |
| --- | --- |
| `report_kind` | Always `copyofa.comparison`. |
| `format_version` | The version of this format, `1`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that ran the comparison. |
| `compared_at` | The comparison time in UTC, such as `2026-10-25T18:30:00Z`. |
| `inputs` | `a` and `b`: each input, described below. |
| `method` | How the tracks were decoded, resampled and aligned, described below. |
| `measurements` | The measurements, described below; absent when either input is not `interpreted`. |
| `limitations` | Sentences stating what the whole Report does not establish or did not examine. |

### Inputs

Each of `inputs.a` and `inputs.b` holds:

- `evidence_set`: the path of the Evidence Set holding the track, as the
  verification Report records it.
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

### Method

| Field | Content |
| --- | --- |
| `decoder` | Always `libsndfile`. |
| `decoder_version` | Its version, such as `1.2.2`. The version of the mpg123 library that libsndfile uses for MP3 is not available to CopyOfA. |
| `resampler` | Always `libsoxr`. It is named even when both tracks have the same rate and nothing is resampled. |
| `resampler_version` | Its version, such as `0.1.3-14-ga66f3ee`. |
| `resampler_quality` | Always `VHQ`, libsoxr's very high quality preset. |
| `common_sample_rate` | The lower of the two sample rates, at which every measurement is made; absent when nothing is measured. |
| `alignment` | Always `downmix_cross_correlation`: one global offset, at the lag with the largest magnitude of the cross-correlation of the mono downmixes. |

### Measurements

Track B is measured against track A. Frames are counted at `common_sample_rate`.

| Field | Content |
| --- | --- |
| `identical_audio` | `true` when both tracks have an Audio Digest and the digests are equal; absent otherwise. The offset is then 0, without a search, unless the tracks have no frames, and the residual is absent. |
| `offset` | `frames`, an integer, and `seconds`. A positive offset means track B starts that many frames later than track A: frame *n* of A lines up with frame *n* + `frames` of B. |
| `overlap` | `a` and `b`: where the aligned tracks overlap in each, as its `start_frame`, its length in `frames` (the same for both), and the `fraction` of the track it covers. |
| `downmix` | The values below, measured on the mono downmixes. |
| `channels` | The values below for each channel, in order, pairing the channels by position; present only when both tracks have the same channel count. |
| `absent` | For each of `offset`, `overlap` and `channels` that is absent, why. |

`downmix` and each entry of `channels` hold, over the overlap, with *a* and *b* the
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
- `residual_windows`: the residual over each one-second window of the overlap, in
  order: its `start_frame` from the start of the overlap, its length in `frames`
  (shorter for the last window when the overlap is not a whole number of seconds),
  and its `residual_db`.
- `absent`: for each of these values that is absent, why. A window whose residual is
  absent holds its own `absent` with the reason.

A value that the audio leaves undefined is absent, never NaN or infinity:

| Absent value | When |
| --- | --- |
| `offset`, `overlap`, and every value of `downmix` and `channels` | A track has no frames, or, for audio that is not identical, a downmix is zero throughout, so the cross-correlation has no maximum. |
| `correlation` | A track is constant over the overlap. |
| `gain_db` | Track B is zero over the overlap, or the gain is exactly zero. |
| `residual_db`, `residual_windows` | The audio is identical, or the gain is undefined. |
| `residual_db` of the overlap or of a window | Track A is zero over it, or *a* − *g*·*b* is exactly zero over it. |

## Example

The Hand That Feeds from *With Teeth* (2019 deluxe, 24-bit, 96 kHz FLAC) against the
same song from *Definitive NIN* (44.1 kHz MP3):

```json
{
  "report_kind": "copyofa.comparison",
  "format_version": 1,
  "copyofa_version": "0.3.0",
  "compared_at": "2026-10-25T18:30:00Z",
  "inputs": {
    "a": {
      "evidence_set": "/Volumes/Archive/With Teeth",
      "integrity_baseline": {
        "manifest_sha256": "6765…",
        "usable": true,
        "problems": []
      },
      "path": "data/04 - Nine Inch Nails - The Hand That Feeds.flac",
      "outcome": "interpreted",
      "expected_digest": "db61…",
      "observed_digest": "db61…",
      "format": "flac",
      "encoding": "pcm_24",
      "sample_rate": 96000,
      "channels": 2,
      "bits_per_sample": 24,
      "frames": 20330556,
      "audio_digest": "pcm1:96000:2:24:4665…",
      "peak": [8108867, 8112205],
      "leading_silence_frames": 0,
      "trailing_silence_frames": 0,
      "flac_md5_signature": "matching"
    },
    "b": {
      "evidence_set": "/Volumes/Archive/Definitive NIN",
      "integrity_baseline": {
        "manifest_sha256": "f265…",
        "usable": true,
        "problems": []
      },
      "path": "data/18 The Hand That Feeds.mp3",
      "outcome": "interpreted",
      "expected_digest": "468e…",
      "observed_digest": "468e…",
      "format": "mp3",
      "encoding": "mpeg_layer_iii",
      "sample_rate": 44100,
      "channels": 2,
      "frames": 9341568,
      "peak": [1.177331566810608, 1.1805001497268677],
      "leading_silence_frames": 1,
      "trailing_silence_frames": 0,
      "limitations": [
        "MP3 is lossy: its decoded samples, and so its frame count, depend on …"
      ]
    }
  },
  "method": {
    "decoder": "libsndfile",
    "decoder_version": "1.2.2",
    "resampler": "libsoxr",
    "resampler_version": "0.1.3-14-ga66f3ee",
    "resampler_quality": "VHQ",
    "common_sample_rate": 44100,
    "alignment": "downmix_cross_correlation"
  },
  "measurements": {
    "offset": {
      "frames": -782,
      "seconds": -0.017732426303854874
    },
    "overlap": {
      "a": {
        "start_frame": 782,
        "frames": 9338567,
        "fraction": 0.9999162682538151
      },
      "b": {
        "start_frame": 0,
        "frames": 9338567,
        "fraction": 0.9996787477220098
      }
    },
    "downmix": {
      "correlation": 0.9705710741571085,
      "gain_db": 1.831632040257753,
      "residual_db": -12.366318859412127,
      "residual_windows": [
        {
          "start_frame": 0,
          "frames": 44100,
          "residual_db": -13.750449944166423
        }
      ]
    },
    "channels": [
      {
        "correlation": 0.9634965094357804,
        "gain_db": 1.7621394736835168,
        "residual_db": -11.446332106961695,
        "residual_windows": [
          {
            "start_frame": 0,
            "frames": 44100,
            "residual_db": -13.577980049906282
          }
        ]
      },
      {
        "correlation": 0.9656206626469909,
        "gain_db": 1.7820362681681134,
        "residual_db": -11.70202333746773,
        "residual_windows": [
          {
            "start_frame": 0,
            "frames": 44100,
            "residual_db": -13.811131366008414
          }
        ]
      }
    ]
  },
  "limitations": [
    "No measurement says whether the tracks share a master, a mix or a source; …",
    "MP3 is lossy: the measurements of an MP3 depend on its decoder.",
    "Tracks at different sample rates are compared at the lower rate, after …",
    "One global offset aligns the tracks: inserted or removed sections, drift …",
    "Channels are paired in the order each file stores them."
  ]
}
```

The example is shortened: a Report holds all 64 hexadecimal digits of each digest,
every residual window, not just the first, and the whole of each limitation. Here
the MP3 starts 782 frames, about 18 ms, earlier than the FLAC.

## Viewing a Report

`copyofa view <report>` prints a comparison Report as one HTML page, which a reader
opens in any browser, without CopyOfA and offline. Save it with a shell redirect:

```bash
copyofa view htf.json > htf.html
```

View first validates the file as [`copyofa validate`](validation-result.md) does, and
refuses a Report that is invalid, unsupported, or of another kind. It supports
comparison Reports only, of format version 1 for now.

The page shows every field of the Report with its value as the Report records it, and
adds only labels and units, and for each track a duration computed from its frames
and sample rate. It gives:

- the SHA-256 of the exact bytes of the file it was generated from, the Report's kind
  and format version, and the CopyOfA version that generated the page, which is not
  the Report's own `copyofa_version`, also shown;
- for each input, its Evidence Set location, Integrity Baseline, path, outcome and
  reason, properties, File Digests, Audio Digest, peak, silence, FLAC MD5 signature
  and limitations;
- the method;
- the measurements: identical audio, offset, overlap, and for the downmix and each
  channel the correlation, gain and residual, with one table of residual windows
  for each of them;
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
Report is invalid, unsupported or not a comparison Report, with the reason on stderr
and nothing on stdout. It exits 2 for invalid arguments and 130 when canceled with
Ctrl-C. It has no `--json` option and writes no file.

## Exit codes

`copyofa compare` exits 0 when both inputs are `interpreted` and were measured, even
when a value is absent. It exits 1 when either input is `not_inspected`, `failed` or
`not_interpreted`, and still prints its result or Report, without measurements. It
exits 2, printing nothing on stdout, when a track is not under the `data/` directory
of an Evidence Set or the arguments are invalid, and 130 when canceled with Ctrl-C.
mpg123 may write notes about damaged MP3 frames to stderr.
