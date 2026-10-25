# CopyOfA

CopyOfA is a preservation and forensic toolkit for music collectors. It acquires and
maintains trustworthy evidence of recorded audio, then lets collectors analyze, compare,
and share what that evidence reveals.

## Status

The project is restarting from a clean slate. The first release, v0.1.0, is in
progress: see the roadmap in the Product Map. CopyOfA can preserve a selected file
delivery as an Evidence Set.

The previous implementation, which archived optical discs bit-exactly with redumper, is
retired. Its last code change is commit `0d04a38` in the Git history. It does not define
the new architecture or release sequence.

## Usage

CopyOfA is not published; from a checkout, run it as `uv run copyofa`. Preserve files
you already own, such as a download purchase, as a new Evidence Set:

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
[Evidence Set format](docs/formats/evidence-set.md) describes the set and how to check
it without CopyOfA.

## Documents

- [Manifesto](docs/manifesto.md): vision, target users, principles and non-goals.
- [Product Map](docs/product-map.md): capabilities, collector scenarios, core concepts,
  and the Now / Next / Later roadmap.
- [Briefs](docs/briefs/): the scope and acceptance criteria of planned work.
- [Decisions](docs/decisions/): architecture decision records.
- [Formats](docs/formats/): the files CopyOfA writes.

GitHub release milestones and their issues will hold the committed work.

## Development

With [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
installed:

```bash
just setup  # Install dependencies and git hooks
just qa     # Run all checks
just test   # Run the tests
```

[AGENTS.md](AGENTS.md) holds the commands and conventions for contributors and coding
agents.

## License

CopyOfA is licensed under the [Apache License 2.0](LICENSE.txt).
