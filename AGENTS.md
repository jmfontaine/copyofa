# AGENTS.md

Guidance for coding agents working in this repository.

## Project

CopyOfA is a preservation and forensic toolkit for music collectors, rebuilt from a
clean slate. Read these before proposing or doing work:

- [docs/manifesto.md](docs/manifesto.md) is the authority for purpose, principles and
  boundaries.
- [docs/product-map.md](docs/product-map.md) holds the capabilities, collector
  scenarios, core concepts and the Now / Next / Later roadmap. Use its capitalized
  concept names (Evidence Set, Audio Digest, Report, …) with the meanings it gives.

The previous implementation is retired; its last code change is commit `0d04a38`.
Consult its history for lessons learned, not as the architecture to follow.

## Commands

Task runner is [just](https://github.com/casey/just); every recipe runs its tool
through [uv](https://docs.astral.sh/uv/).

```bash
just setup              # Install deps + pre-commit hooks (hooks: main checkout only)
just test               # Run pytest with coverage
just test <path>        # Run one test file or directory
just format             # ruff format + pyproject-fmt + rumdl fmt (Markdown)
just lint-fix           # ruff check --fix + rumdl check --fix
just type-check         # ty check
just verify-types       # Public API type completeness; fails until the first export
just deps-unused        # deptry src
just spell              # cspell against cspell.json
just qa                 # All checks: every pre-commit hook, then verify-types
just deps-update        # Update deps to latest versions
just changelog-preview  # Release notes for unreleased commits
just release-prepare    # Maintainers only: open the PR that sets the release version
just release            # Maintainers only: tag the merged release and publish it
just release-next       # Maintainers only: open the PR for the next development version
```

Run a single test: `just test tests/test_version.py -k matches_installed_metadata`

Before finishing a change, run `just format && just lint-fix && just qa && just test`.
`just qa` runs pre-commit, which sees only files git tracks: `git add` new files
first.

## Language

Write US English in everything you write for this project: code comments,
docstrings, error messages, identifiers, tests, documentation, commit messages
and replies. That means `-ize` and `-yze` (`normalize`, `analyze`), `-or`
(`behavior`, `honor`), `-er` (`center`), a single `l` before a suffix
(`labeling`, `canceled`), and `license` as both noun and verb. Leave other
people's text, such as `LICENSE.txt` or vendored code, as it is.

Optical media are "discs"; "disk" stays correct for other storage and in macOS names
such as `diskutil`.

The project is "CopyOfA" in prose and `copyofa` in identifiers: the repository,
packages, commands, configuration directories, `COPYOFA_*` environment variables, and
the tool name recorded in data. Type names use `CopyOfA` (`CopyOfAError`).

## Conventions

- Python 3.11+, developed on the version in `.python-version`; ruff
  enforces a line length of 88
- ty is the type checker; pyright runs only for `--verifytypes`. The
  package ships `py.typed` (PEP 561), so the public API stays fully typed
- Dependency groups: `dev` holds the tools and includes `test`, which holds only
  what the tests import. CI installs `test` on its own, next to the built wheel, so a
  test cannot lean on a `dev` tool
- Workarounds that are knowingly less than ideal carry a `KLUDGE:` comment
  stating what is wrong and what removes it. Grep for `KLUDGE` before changing
  one; do not add one without a removal condition

## Architecture

What future work on CopyOfA may assume today. Commands and day-to-day
conventions are above; the process for contributors is in
[CONTRIBUTING.md](CONTRIBUTING.md).

### Shape

A Python CLI published to PyPI. The `copyofa` console script calls
`copyofa.cli:main`.

### Language, runtime, and tooling

- Python 3.11+ (`requires-python`); developed on the version in
  `.python-version`
- uv manages dependencies and environments; `uv.lock` is committed, and uv_build
  builds the distributions
- just is the task runner
- ruff formats and lints; pyproject-fmt formats `pyproject.toml`; rumdl formats and
  lints Markdown, configured in `.rumdl.toml`
- ty checks types; pyright `--verifytypes` checks that the public API is fully
  typed
- deptry reports unused and undeclared dependencies
- cspell checks spelling against `cspell.json`; actionlint checks the workflows
- pre-commit holds the one list of checks, run on every commit, by `just qa` and by
  CI. The tools the justfile also runs on their own come from `uv.lock` through
  `uv run`; the general file checks, actionlint and cspell are pinned in
  `.pre-commit-config.yaml`

### Structure

- `src/copyofa/`: the package (src layout)
- `tests/`: the pytest suite
- `scripts/`: distribution checks that CI runs
- `docs/`: durable project documents: the Manifesto, the Product Map, release briefs
  (`docs/briefs/`), architecture decision records (`docs/decisions/`), and the formats
  of the files CopyOfA writes (`docs/formats/`)

### Evidence Set format

An Evidence Set is a BagIt 1.0 bag with SHA-256 manifests, its Preserved Evidence
under `data/` and CopyOfA's records in the `copyofa/` tag directory, as
[ADR 0001](docs/decisions/0001-store-evidence-sets-as-bagit-bags.md) decides.
[docs/formats/evidence-set.md](docs/formats/evidence-set.md) documents the layout, the
Import Record and the Acquisition Record; change it with any change to what import or
acquire writes. Import and acquire create their destination through the staging
directory `src/copyofa/staging.py` manages.
[docs/formats/verification-report.md](docs/formats/verification-report.md) documents
the Report verify prints,
[docs/formats/inspection-report.md](docs/formats/inspection-report.md) the Report
inspect prints,
[docs/formats/comparison-report.md](docs/formats/comparison-report.md) the Report
compare prints and the page view makes of it, and
[docs/formats/validation-result.md](docs/formats/validation-result.md) the result
validate prints; change each with any change to what its command prints.

### Report schemas

Each Report kind and format version has a JSON Schema, draft 2020-12, in
`src/copyofa/schemas/<kind>-report-<version>.schema.json`, as
[ADR 0004](docs/decisions/0004-publish-each-report-format-as-a-json-schema.md)
decides. A schema is strict, self-contained, shipped in the package, and linked from
its format document. `copyofa.validator` maps a `report_kind` and `format_version` to
its file, and `validate` parses a Report as strict JSON, then checks it with
[jsonschema](https://github.com/python-jsonschema/jsonschema), CopyOfA's fourth
runtime dependency. A released schema changes only to fix a disagreement with what
CopyOfA prints; any other change to a Report's fields is a new format version with its
own schema file. The test suite validates every Report it produces against its schema.

`copyofa view` validates a file the same way, then `copyofa.viewer` renders a valid
comparison Report as one self-contained HTML page, with the standard library only.
The page shows every value as the Report records it and the SHA-256 of the file; it
holds no script, no link and no external resource, a Content Security Policy forbids
both, and every text of the Report is escaped, a lone surrogate as `\udcXX`. Each
Report kind and format version `view` supports needs its own rendering.

### Audio decoding

`inspect` and `compare` decode audio with soundfile, whose wheels bundle libsndfile
with FLAC and mpg123, and NumPy. `compare` also resamples with soxr (python-soxr,
bundling libsoxr). These three, with jsonschema (see Report schemas), are the only
runtime dependencies. The Audio Digest is defined on canonical PCM by
[ADR 0002](docs/decisions/0002-define-audio-digest-from-canonical-pcm.md), so any
exact decoder reproduces it. `pyproject.toml` sets a higher NumPy minimum for Python
3.15, its oldest release with wheels for 3.15, so CI's lowest-direct job installs
NumPy instead of building it; soxr's minimum, 0.5, is its oldest release with wheels
for 3.15 (stable ABI). Inspect reads through libsndfile's sequential read
functions rather than soundfile's `read()` (see the `KLUDGE` in
`src/copyofa/inspector.py`), and compare decodes through inspect's code. The
comparison method (resampling, alignment, measurements) is decided in
[ADR 0003](docs/decisions/0003-measure-track-comparisons-on-aligned-decoded-audio.md).

### Disc acquisition

`acquire` reads a plain audio CD with [redumper](https://github.com/superg/redumper),
an external program needed only by acquire, never a Python dependency: build b768 or
later on `PATH`, run once as `redumper disc`, as
[ADR 0005](docs/decisions/0005-acquire-audio-cds-with-redumper.md) decides. Acquire
reads the drive, the table of contents, the offsets and the error counts from
redumper's log, and the tracks' files, ISRCs and CD-Text from its cue sheet. An
acquired set stores redumper's image as 16-bit stereo FLAC, written by libsndfile at
its highest compression level, its state and subchannel as xz, written by Python's
`lzma`, its other files as written, and no track file; each track is a range of the
image the Acquisition Record gives. soundfile's minimum, 0.13, is its first release
that sets a FLAC compression level. Tests run a stand-in `redumper`, defined in
`tests/conftest.py`, that writes small synthetic files and a log in build b768's
format.

### Command conventions

Every command follows the conventions `import` and `verify` set in v0.1.0, as
`src/copyofa/cli.py` implements them:

- A short human-readable result goes to stdout; `--json` prints one JSON document
  instead, as UTF-8 whatever the locale, with lone surrogates (path bytes that
  are not valid UTF-8) escaped as `\uXXXX` so the output stays valid UTF-8. Progress,
  warnings and errors go to stderr
- Exit 0 on success, 1 when the command refused, failed or found a problem (a result
  is still printed when there is one), 2 for invalid arguments or, for a command that
  reads an Evidence Set, a target that is not one, and 130 when canceled with Ctrl-C.
  Import and acquire exit 1 for a source or destination they refuse, acquire also for
  a set it accepted from a disc read with errors, validate and view for a file
  they cannot read, and view for a Report it refuses. View prints an HTML page, not
  JSON, and has no `--json`
- Stdout stays empty whenever no result is produced
- No interactive prompts

### Testing

pytest with coverage (`just test`). CI runs the suite:

- on every supported Python, 3.11 to 3.15
- against the oldest dependency versions `pyproject.toml` allows, with deprecations
  fatal
- against the built wheel, installed into a clean environment

### Distribution

- Wheel and sdist built once by CI and checked by `scripts/check_distributions.py`
  and `twine check --strict`; the same files are published, never rebuilt
- Published to PyPI through trusted publishing from `.github/workflows/publish.yml`
  when a `vX.Y.Z` tag on `main` is pushed; `just release` creates it signed
- Between releases `main` carries a development version, `X.Y.Z.devN`, which sorts
  below `X.Y.Z`
- Release notes generated by git-cliff from the pull request titles on `main`;
  `.cliffignore` leaves out the retired implementation's commits
- License: Apache-2.0

### CI

- `.github/workflows/ci.yml` runs on pushes to `main` and on every pull request:
  every pre-commit hook and `--verifytypes`, then the tests, then
  builds and install-tests the distributions. Actions are pinned to commit
  SHAs, and no checkout keeps its token
- Dependabot opens weekly grouped updates for GitHub Actions and `uv.lock`, with
  `build:` commit messages and the `dependencies` and `build` labels; it moves the
  lock only, never the minimum versions in `pyproject.toml`

### Agent support

Coding agents are expected contributors. They follow this file. Agents
never release.

## Releasing

**Agents never release.** Do not run `just release-prepare`, `just release` or
`just release-next`, create or push a `v*` tag (pushing one publishes to PyPI),
create a GitHub release, or interact with PyPI. Finish the work, run the checks
above, report, and stop.

The process for maintainers is in [CONTRIBUTING.md](CONTRIBUTING.md#releasing).

## Deviations from the shared workflow

None.
