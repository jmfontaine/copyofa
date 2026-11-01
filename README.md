# CopyOfA

CopyOfA is a preservation and forensic toolkit for music collectors. It acquires and
maintains trustworthy evidence of recorded audio, then lets collectors analyze, compare,
and share what that evidence reveals.

## Status

The project is restarting from a clean slate. Its first release, v0.1.0, preserves a
selected file delivery as an Evidence Set and verifies it later. The second, v0.2.0,
describes the audio in a set: each track's format and properties, an Audio Digest for
lossless audio, and a few measurements. The third, v0.3.0, measures how two preserved
tracks relate, across formats and sample rates. The fourth, v0.4.0, shares a
comparison: a Report can leave out where the Evidence Sets are stored, `view` turns it
into a self-contained HTML page, and `validate` checks any Report against its
published JSON Schema. The fifth, v0.5.0, preserves a plain audio CD: `acquire` reads
it with redumper into an Evidence Set that stores the disc image compressed, `inspect`
and `compare` read its tracks from the image, and `export` writes them as FLAC files.
The sixth, v0.6.0, locates matching portions: `compare` reports which portions of one
track appear in the other, where and how alike, and which audio appears in only one.
The seventh, v0.7.0, has `acquire` ask redumper to re-read sectors it read with
errors, so a lightly scratched CD can be preserved, and show redumper's log when an
acquisition fails. The eighth, v0.8.0, keeps a disc that still has errors as the
drive read it, and inspect, compare and export report which frames were not read
successfully.
The roadmap in the Product Map lists what comes next.

The previous implementation, which archived optical discs bit-exactly with redumper, is
retired. Its last code change is commit `0d04a38` in the Git history. It does not define
the new architecture or release sequence.

## Installation

CopyOfA runs on macOS and Linux with Python 3.11 or later. Install it from PyPI with
[uv](https://docs.astral.sh/uv/):

```bash
uv tool install copyofa
```

## Usage

Preserve files you already own, such as a download purchase, as a new Evidence Set:

```bash
copyofa import ~/Downloads/Album --to /Volumes/Archive/Album \
  --note "Bandcamp purchase" --ref discogs=r123456
```

- Each source, a file or a directory, goes into the set under its base name.
- `--to` names a directory that must not exist yet; the set appears there only once
  every stored copy has been checked against its source.
- `--exclude <pattern>` leaves out files and directories by shell-style pattern;
  operating system metadata files such as `.DS_Store`, symbolic links, and empty
  directories are left out too. Every exclusion is recorded with its reason.
- `--note` and `--ref` record provenance exactly as given; `--ref` repeats.
- `--json` prints the result as JSON. Progress and errors go to stderr.

The command exits 0 when the set is accepted, 1 when the import is refused or fails or
when stdout is closed (closed by the time the result is printed, such as by `| head`,
the set is kept and stderr names it; closed at the start, nothing is imported), 2 for
invalid arguments, and 130 when canceled with Ctrl-C.
[Evidence Set format][evidence-set] describes the set and how to check
it without CopyOfA.

Preserve a plain audio CD by reading it with
[redumper](https://github.com/superg/redumper), build b768 or later, installed
separately:

```bash
copyofa acquire --to /Volumes/Archive/add-violence-cd --note "Bought new"
copyofa acquire --to /Volumes/Archive/add-violence-cd --drive disk6 --json \
  > acquisition.json
```

- Acquire runs `redumper disc` once and keeps everything it wrote but the track files,
  which the disc image reproduces: the image as FLAC, the read status and the
  subchannel as xz, and the small files as written. Each compressed file is decoded
  and checked against redumper's original before the set is accepted.
- The set's Acquisition Record gives the drive, the redumper build, the offsets, the
  read errors, and each track's range in the image, Audio Digest, and ranges of frames
  not read successfully.
- `--drive` names the drive as redumper does, such as `disk6`; without it, redumper
  reads the first drive holding a disc. `--note`, `--ref` and `--json` work as for
  import.
- `--retries` sets how many times redumper re-reads a sector it read with an error,
  20 by default.
- A disc that keeps errors after the re-reads is kept as the drive read it: sectors
  never read hold zeros, samples read with C2 errors hold what the drive returned, and
  the record locates both in each track. Nothing is repaired or generated.
- When the acquisition fails after redumper ran, stderr carries redumper's log before
  the failure message, so the cause is visible without reading the disc again.
- A disc with more than one session or with a data track is refused.

Acquire exits 0 when the set is accepted from a disc read without error, 1 when it is
accepted from a disc read with errors (the set is kept, as evidence of what the drive
read), when stdout is closed (closed by the time the result is printed, the set is
kept and stderr names it; closed at the start, the disc is not read), or when the
acquisition is refused or fails, 2 for invalid arguments, and 130 when canceled.
[Evidence Set format][evidence-set] describes acquired sets and how to restore
redumper's files with `flac` and `xz`.

Later, after moving the set or just to check it, verify it against its Integrity
Baseline:

```bash
copyofa verify /Volumes/Archive/Album
copyofa verify /Volumes/Archive/Album --json > album-verification.json
```

Verify reads every preserved file and reports each one as matching, changed, missing,
unavailable, or not checked, and lists unexpected files under `data/`. Operating
system metadata files that Finder adds while browsing the set are ignored. It writes
nothing into the set. `--json` prints a verification Report, which
[Verification Report format][verification-report] describes.

Verify exits 0 when everything is intact, 1 when it found anything else or stdout is
closed, 2 when the target is not an Evidence Set or the arguments are invalid, and 130
when canceled.

Describe the audio the set holds:

```bash
copyofa inspect /Volumes/Archive/Album
copyofa inspect /Volumes/Archive/Album --json > album-inspection.json
```

Inspect first checks each preserved file against the Integrity Baseline, then decodes
FLAC (8, 16 or 24 bits), integer PCM WAV and MP3, and reports each track's format,
sample rate, bit depth, channels and duration. Other files are reported as not
interpreted, with the reason. `--json` prints an inspection Report, which
[Inspection Report format][inspection-report] describes. For FLAC and WAV it gives an
Audio Digest, which recognizes the same audio after retagging or recompression and
can be reproduced with `flac` or `ffmpeg`. MP3 has none, because its decoded samples
depend on the decoder. The Report also gives each track's peak per channel and its
digital silence at each end, and for FLAC whether the audio matches the MD5 signature
its encoder stored.

For a set made by acquire, inspect also decodes each track of the disc from the image,
over the range the Acquisition Record gives, and reports whether its Audio Digest is
the one recorded at acquisition, and which ranges of its frames the drive did not read
successfully.

Inspect exits 0 when every file was decoded or is not a supported format, 1 when a file
could not be inspected or decoded or its audio differs from its FLAC MD5 signature, or
when a track of an acquired set could not be decoded or differs from its recorded Audio
Digest, or when stdout is closed, 2 when the target is not an Evidence Set or the
arguments are invalid, and 130 when canceled. It writes nothing into the set.

Find which portions of one preserved track appear in another, such as a FLAC track and
the MP3 of the same song from another release:

```bash
copyofa compare "/Volumes/Archive/With Teeth/data/04 The Hand That Feeds.flac" \
  "/Volumes/Archive/Definitive NIN/data/18 The Hand That Feeds.mp3"
copyofa compare <input-a> <input-b> --json > comparison.json
copyofa compare <input-a> <input-b> --json --omit-locations > shareable.json
```

Each input is a file under the `data/` directory of an Evidence Set. To compare a
track of a disc you acquired, give the acquired set and the track number with
`--track-a` or `--track-b`:

```bash
copyofa compare "/Volumes/Archive/Add Violence CD" \
  "/Volumes/Archive/Add Violence/data/01-04 Not Anymore.flac" --track-a 4
```

<!-- rumdl-disable MD013 -->

```text
Track A: track 4 of /Volumes/Archive/Add Violence CD (flac, 44100 Hz, 16-bit, 2 channels, 3:06.733)
Track B: /Volumes/Archive/Add Violence/data/01-04 Not Anymore.flac (flac, 48000 Hz, 24-bit, 2 channels, 3:11.600)
Common sample rate: 44100 Hz
Portion 1, primary: A 4.098-186.720 s, B 4.891-187.513 s, offset +34946 frames (+0.792 s), correlation 0.997, residual (one gain) -22.0 dB
Portion 2, primary: A 8.548-16.714 s, B 17.912-26.078 s, offset +412945 frames (+9.364 s), correlation 0.996, residual (one gain) -21.3 dB
Portion 3, primary: A 17.119-25.294 s, B 9.340-17.515 s, offset -343054 frames (-7.779 s), correlation 0.997, residual (one gain) -22.5 dB
Portion 4, alternate: A 22.365-24.129 s, B 40.300-42.064 s, offset +790945 frames (+17.935 s), correlation 0.983, residual (one gain) -14.8 dB
Portion 5, alternate: A 39.493-41.272 s, B 23.142-24.921 s, offset -721054 frames (-16.350 s), correlation 0.984, residual (one gain) -15.0 dB
Portion 6, alternate: A 66.289-67.779 s, B 112.819-114.309 s, offset +2051978 frames (+46.530 s), correlation 0.958, residual (one gain) -10.8 dB
Portion 7, alternate: A 111.994-113.517 s, B 67.049-68.572 s, offset -1982087 frames (-44.945 s), correlation 0.959, residual (one gain) -11.0 dB
Unmatched in A: 0.000-4.098 s, -36.8 dBFS
Unmatched in A: 186.720-186.733 s, -11.8 dBFS
Unmatched in B: 0.000-4.891 s, -31.1 dBFS
Unmatched in B: 187.513-191.600 s, -20.8 dBFS
```

<!-- rumdl-enable MD013 -->

Compare checks both against their Integrity Baselines and decodes them as inspect does.
It then resamples the one at the higher sample rate to the lower rate and searches for
the portions of track A that appear in track B, each at its own offset. For each
portion it reports its range in both tracks, its offset, and how B relates to A over
it: correlation, gain and the residual level left after that gain. It also reports the
audio that no primary portion covers, with its level. In the example, portion 1 covers
nearly all of the CD track, and B starts 0.792 s later. Portions 2 and 3 match other
places of B for sections of A that portion 1 also covers; the alternates match
sections that better portions already cover, less well. The first 4.1 s of A, and the
first 4.9 s and the last 4.1 s of B, match nothing. When both tracks are lossless and
their Audio Digests are equal, compare reports identical audio. It draws no conclusion
such as "same master". `--json` prints a comparison Report, which
[Comparison Report format][comparison-report] describes, with the method's parameters
and, for a track of an acquired set, the ranges of its frames the drive did not read
successfully.
To share a Report, add `--omit-locations`: it leaves out where each Evidence Set is
stored, which names your disks and often your user account, and the Report says that it
did.

Compare exits 0 when both tracks were compared, whether or not it found a portion, 1
when a track could not be inspected or decoded or is not a supported format, or when
stdout is closed, 2 when an input is not inside an Evidence Set or the arguments are
invalid, and 130 when canceled. It writes nothing into either set.

Compare two editions of a release, track by track, by giving the roots of their
Evidence Sets without `--track-a` or `--track-b`:

```bash
copyofa compare "/Volumes/Archive/TDS CD" "/Volumes/Archive/TDS 2017"
copyofa compare "/Volumes/Archive/TDS CD" "/Volumes/Archive/TDS 2017" --json > tds.json
```

Each edition is the tracks of its set joined in order: an acquired set's in the order
of its Acquisition Record, an imported set's audio files in the order of their paths,
leaving out the files that are not audio, such as a cover image, which it lists.
Compare searches the two editions for matching portions as it searches two tracks, so
it finds audio whose track boundaries moved, a track only one edition holds, or a
changed intro. It prints how much of each edition it found in the other, a line per
track of A naming the tracks of B that hold its audio and how much, and the audio only
one edition holds, per track. The Report splits each portion into segments at the
track boundaries of both editions and measures each. Matching tracks do not make the
editions equivalent, and editions whose speeds differ slightly, such as two masters,
match in short portions only. Two CDs take about three minutes and up to about 9 GB
of memory; much longer editions may not fit in memory. Compare exits 1 when a track
of either edition could not be inspected or decoded, or an edition has no track, and
2 when only one input is the root of a set given without its track option.

Play a disc you acquired, or tag its tracks with other tools, from FLAC files that
export writes:

```bash
copyofa export "/Volumes/Archive/Add Violence CD" --to ~/Music/add-violence
copyofa export "/Volumes/Archive/Add Violence CD" --to ~/Music/add-violence --json \
  > export.json
```

Export checks the set as inspect does, then writes each track of the disc from the
image as a 16-bit stereo FLAC file at 44.1 kHz, `01.flac`, `02.flac` and so on, with no
tag. It decodes each file and checks its Audio Digest against the recorded one before
it accepts the directory. The first track's pregap, the lead-in and the lead-out stay
only in the set. A track holding frames the drive did not read successfully is
written as acquired, and stderr warns about it with its ranges. `--json` prints an
export result, which [Export result format][export-result] describes.

Export exits 0 when every track was exported, 1 when the set is not an acquired set,
cannot be trusted, or the export is refused or fails (the directory is then not
created) or when stdout is closed (closed by the time the result is printed, the
directory is kept and stderr names it; closed at the start, nothing is exported), 2
when the target is not an Evidence Set or the arguments are invalid, and 130 when
canceled. It writes nothing into the set.

Check that a Report, such as one you received, is well formed:

```bash
copyofa validate comparison.json
copyofa validate comparison.json --json > comparison-validation.json
```

Validate parses the file as strict JSON, then checks it against the JSON Schema
published for its Report kind and format version, and reports `valid`, `invalid` with
the location of each problem, or `unsupported` for a kind or version it does not know.
A valid Report is well formed, nothing more: validation does not establish that its
findings are true, who produced it, or anything about the audio. The schemas ship in
the package, so other software can check a Report without CopyOfA. `--json` prints a
validation result, which [Validation result format][validation-result] describes.

Validate exits 0 when the Report is valid, 1 when it is invalid or unsupported, the
file cannot be read, or stdout is closed, 2 when the arguments are invalid, and 130
when canceled. It writes nothing.

Read a comparison Report as a web page, without CopyOfA:

```bash
copyofa view comparison.json > comparison.html
```

View validates the file first, then prints one HTML page that shows every value of
the Report with labels and units, each absent value with its reason, and each
limitation. It gives the SHA-256 of the Report file it was generated from, so a
recipient can check the page against the Report. The page runs no script and loads
nothing, so it opens in any browser, offline. It draws no conclusion from the
measurements. For a Report of the current format, it shows the method's parameters,
a table of the portions with each one's residual windows, the unmatched audio of each
track, and the error ranges of each track of an acquired set. It does not render a
comparison of two editions yet, and refuses one, saying why.
[Comparison Report format][comparison-report] describes it.

View exits 0 when it printed the page, 1 when the Report is invalid, unsupported, not a
comparison Report, of a format version or a scope view does not render, or cannot be
read, or when stdout is closed, 2 when the arguments are invalid, and 130 when
canceled. It prints nothing on stdout otherwise, and writes no file.

## Documents

- [Manifesto][manifesto]: vision, target users, principles and non-goals.
- [Product Map][product-map]: capabilities, collector scenarios, core concepts, and the
  Now / Next / Later roadmap.
- [Briefs][briefs]: the scope and acceptance criteria of planned work.
- [Decisions][decisions]: architecture decision records.
- [Formats][formats]: the files CopyOfA writes.

GitHub release milestones and their issues will hold the committed work.

## Development

With [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
installed:

```bash
just setup  # Install dependencies and git hooks
just qa     # Run all checks
just test   # Run the tests
```

[CONTRIBUTING.md][contributing] covers the development setup, pull requests and
releases; [AGENTS.md][agents] holds the commands and conventions for contributors and
coding agents.

## License

CopyOfA is licensed under the [Apache License 2.0][license].

<!-- Absolute URLs, so the links also work on PyPI. -->

[agents]: https://github.com/jmfontaine/copyofa/blob/main/AGENTS.md
[briefs]: https://github.com/jmfontaine/copyofa/tree/main/docs/briefs
[contributing]: https://github.com/jmfontaine/copyofa/blob/main/CONTRIBUTING.md
[comparison-report]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/comparison-report.md
[decisions]: https://github.com/jmfontaine/copyofa/tree/main/docs/decisions
[evidence-set]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/evidence-set.md
[export-result]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/export-result.md
[formats]: https://github.com/jmfontaine/copyofa/tree/main/docs/formats
[inspection-report]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/inspection-report.md
[license]: https://github.com/jmfontaine/copyofa/blob/main/LICENSE.txt
[manifesto]: https://github.com/jmfontaine/copyofa/blob/main/docs/manifesto.md
[product-map]: https://github.com/jmfontaine/copyofa/blob/main/docs/product-map.md
[validation-result]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/validation-result.md
[verification-report]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/verification-report.md
