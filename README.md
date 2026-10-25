# CopyOfA

CopyOfA is a preservation and forensic toolkit for music collectors. It acquires and
maintains trustworthy evidence of recorded audio, then lets collectors analyze, compare,
and share what that evidence reveals.

## Status

The project is restarting from a clean slate. Its first release, v0.1.0, preserves a
selected file delivery as an Evidence Set and verifies it later. The next, v0.2.0,
describes the audio in a set. The roadmap in the Product Map lists what comes next.

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

The command exits 0 when the set is accepted, 1 when the import is refused or fails,
2 for invalid arguments, and 130 when canceled with Ctrl-C.
[Evidence Set format][evidence-set] describes the set and how to check
it without CopyOfA.

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

Verify exits 0 when everything is intact, 1 when it found anything else, 2 when the
target is not an Evidence Set or the arguments are invalid, and 130 when canceled.

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
depend on the decoder.

Inspect exits 0 when every file was decoded or is not a supported format, 1 when a
file could not be inspected or decoded, 2 when the target is not an Evidence Set or
the arguments are invalid, and 130 when canceled. It writes nothing into the set.

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
[decisions]: https://github.com/jmfontaine/copyofa/tree/main/docs/decisions
[evidence-set]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/evidence-set.md
[formats]: https://github.com/jmfontaine/copyofa/tree/main/docs/formats
[inspection-report]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/inspection-report.md
[license]: https://github.com/jmfontaine/copyofa/blob/main/LICENSE.txt
[manifesto]: https://github.com/jmfontaine/copyofa/blob/main/docs/manifesto.md
[product-map]: https://github.com/jmfontaine/copyofa/blob/main/docs/product-map.md
[verification-report]: https://github.com/jmfontaine/copyofa/blob/main/docs/formats/verification-report.md
