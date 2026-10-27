# Export result format

`copyofa export <evidence-set> --to <directory>` writes each track of an
[acquired set](evidence-set.md#acquired-sets) as a FLAC file in a new directory, so
the disc can be played without CopyOfA. With `--json`, it prints the export result
described here instead of its short human-readable result:

```bash
copyofa export "/Volumes/Archive/Add Violence CD" --to ~/Music/add-violence --json \
  > add-violence-export.json
```

The result is not a Report: it names what export wrote, and ties each file to the set
by its Audio Digest. Like every `--json` output of CopyOfA, it is UTF-8, whatever the
locale, and a path byte that is not valid UTF-8 appears as a `\udcXX` escape.

## What export writes

One FLAC file per track of the Acquisition Record, in its order, named by its track
number: `01.flac`, `02.flac`, and so on. Each file is 16-bit stereo at 44.1 kHz, as
the disc is, and holds exactly the frames of the track's range in the image, decoded
from `data/disc.scram.flac`. It holds no tag and no artwork: its Vorbis comment block
holds only libFLAC's vendor string, which names the encoder. Tagging is left to other
tools; the Audio Digest still ties a file to its set after it is tagged.

Export leaves out what the image holds beyond the tracks:

- the first track's pregap, the audio before the first track's range;
- the lead-in and the lead-out, before the first track and after the last.

Each track's range is where acquire found redumper's track file in the image, so the
files hold the same audio as redumper's track files. Export writes nothing into the set.

## Frames not read successfully

A track whose Acquisition Record, of format version 2, gives error ranges holds frames
the drive did not read successfully (see
[Evidence Set format](evidence-set.md#acquisition-record)). Export writes it as
acquired, never repaired, and once the directory is accepted, stderr gets one line per
such track, in track order, such as this one, wrapped here at each area:

```text
copyofa: warning: track 8 has 44 frames not read successfully, in 3 areas:
  3:18.515-3:18.517 (8 frames with C2 errors),
  3:18.730-3:18.739 (24 frames with C2 errors),
  3:19.375-3:19.380 (12 frames with C2 errors)
```

The count is the total of all the track's ranges, `frame` for 1. Ranges less than one
sector (588 frames) apart, from the end of one to the start of the next, form one
area, so errors scattered over a few milliseconds read as one place. Each area is its
start and end in the track, from its first frame to the frame after its last, as
durations at 44.1 kHz in the form the text results give durations, or only its start
when both read the same; then, in parentheses, `<n> frames not read` for `not_read`
and `<n> frames with C2 errors` for `c2_error`, each only when non-zero, separated by
`, `. Areas are separated by `, `. At most 10 are listed; a track with more ends its
line with `, and <n> more`. The record keeps every range, with exact `offset_frames`.
A set whose record is format version 1 gives no error ranges, so export warns about
nothing. The warning changes neither the export result nor the exit code.

## How export works

1. **Integrity first.** Export checks the set as inspect does (see
   [Inspection Report format](inspection-report.md#how-inspect-works)), and refuses,
   exiting 1 and writing nothing, a set whose Integrity Baseline is unusable, a set
   that is not an acquired set, a set whose Acquisition Record cannot be used, and a
   set whose disc image is not the accepted bytes.
2. **Destination.** The directory must not exist, its parent must, and it must not lie
   inside the Evidence Set. Export refuses a staging directory
   `<directory>.copyofa-staging` left beside it by an earlier import, acquire or
   export, as import does (see
   [How an Evidence Set is accepted](evidence-set.md#how-an-evidence-set-is-accepted)).
3. **Writing.** Export reads the image completely once, checks its SHA-256 against
   the payload manifest, then, for each track, decodes it over the track's range into
   a new FLAC file in the staging directory, written by libsndfile. It refuses when
   the image is not the accepted bytes, or when the image's size or modification time
   changed between that check and the end of a track's decoding. It fails when the
   decoded range does not have the recorded Audio Digest.
4. **Checking.** Each file is then decoded once, and export fails when its Audio
   Digest is not the recorded one.
5. **Acceptance.** Only when every file is written and checked does export rename the
   staging directory to the directory. It deletes the staging directory when it
   refuses, fails or is canceled. Export canceled with Ctrl-C before it has accepted
   the directory, its last step before it prints any warning and its result, leaves
   nothing at its destination, even when the cancellation arrives after the rename:
   it deletes the directory it just renamed and exits 130 with nothing on stdout. A
   Ctrl-C once the directory is accepted, such as one while the result is printed,
   keeps the directory, and export still exits 130.

## Fields

| Field | Content |
| --- | --- |
| `directory` | The absolute path of the directory export created. |
| `evidence_set` | The path of the Evidence Set the tracks come from, as the verification Report records it. |
| `manifest_sha256` | The SHA-256 of the set's `manifest-sha256.txt`, which identifies its Integrity Baseline, as in the verification Report. |
| `files` | One entry per file, in track order: `path`, its name in the directory, such as `01.flac`; `track`, the track number; and `audio_digest`, the Audio Digest of its audio, which is the one the Acquisition Record gives. |
| `left_out` | Sentences stating what the image holds that export does not write. |

## Example

The five tracks of *Add Violence* by Nine Inch Nails (2017 CD):

```json
{
  "directory": "/Users/collector/Music/add-violence",
  "evidence_set": "/Volumes/Archive/Add Violence CD",
  "manifest_sha256": "bc7ecf632c819b962880e070c8a2854aa643876deab6c1f2ac1c38e543ec8d63",
  "files": [
    {
      "path": "01.flac",
      "track": 1,
      "audio_digest": "pcm1:44100:2:16:1e9b66e1…"
    },
    {
      "path": "02.flac",
      "track": 2,
      "audio_digest": "pcm1:44100:2:16:7ce35410…"
    },
    {
      "path": "03.flac",
      "track": 3,
      "audio_digest": "pcm1:44100:2:16:ec9ef8df…"
    },
    {
      "path": "04.flac",
      "track": 4,
      "audio_digest": "pcm1:44100:2:16:a4c11150…"
    },
    {
      "path": "05.flac",
      "track": 5,
      "audio_digest": "pcm1:44100:2:16:7cb0b19d…"
    }
  ],
  "left_out": [
    "The first track's pregap, the audio before the first track's range, which …",
    "The lead-in and the lead-out, which the image holds before the first track …"
  ]
}
```

The example is shortened: a result holds all 64 hexadecimal digits of each digest, and
the whole of each sentence.

## Exit codes

`copyofa export` exits 0 when every track was exported. It exits 1, printing nothing
on stdout and leaving no directory, when it refused or failed, and 130 when canceled
with Ctrl-C. It also exits 1 when stdout is closed: closed at the start (`>&-`), it
exports nothing and stderr says `copyofa: stdout closed`; closed while it prints the
result, such as by `| head`, the directory is kept, complete, and stderr ends with
`copyofa: stdout closed; <directory> was created`. It exits 2, printing nothing
on stdout, when the target is not an Evidence Set or the arguments are invalid.
