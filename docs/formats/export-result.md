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
3. **Writing.** For each track, export reads the image completely, checks its SHA-256
   against the payload manifest, and decodes it over the track's range into a new
   FLAC file in the staging directory, written by libsndfile. It fails when the
   decoded range does not have the recorded Audio Digest.
4. **Checking.** Each file is then decoded, and export fails when its Audio Digest is
   not the recorded one.
5. **Acceptance.** Only when every file is written and checked does export rename the
   staging directory to the directory. It deletes the staging directory when it
   refuses, fails or is canceled.

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
with Ctrl-C. It exits 2, printing nothing on stdout, when the target is not an
Evidence Set or the arguments are invalid.
