# AGENTS.md

Guidance for coding agents working in this repository.

## Project

CopyOfA is a preservation and forensic toolkit for music collectors, rebuilt from a
clean slate. Read these before proposing or doing work:

- [docs/manifesto.md](docs/manifesto.md) is the authority for purpose, principles and
  boundaries.
- [docs/product-map.md](docs/product-map.md) holds the capabilities, collector
  scenarios, core concepts and the Now / Next / Later roadmap. Use its capitalized
  concept names (Evidence Set, Audio Identity, Report, …) with the meanings it gives.

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
just deps-unused        # deptry src
just spell              # cspell against cspell.json
just qa                 # All checks: every pre-commit hook
just deps-update        # Update deps to latest versions
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
people's text, such as vendored code, as it is.

Optical media are "discs"; "disk" stays correct for other storage and in macOS names
such as `diskutil`.

The project is "CopyOfA" in prose and `copyofa` in identifiers: the repository,
packages, commands, configuration directories, `COPYOFA_*` environment variables, and
the tool name recorded in data. Type names use `CopyOfA` (`CopyOfAError`).

## Conventions

- Python 3.11+, developed on the version in `.python-version`; ruff
  enforces a line length of 88
- ty is the type checker
- Dependency groups: `dev` holds the tools and includes `test`, which holds only what
  the tests import. CI installs `test` on its own, so a test cannot lean on a `dev` tool
- Workarounds that are knowingly less than ideal carry a `KLUDGE:` comment
  stating what is wrong and what removes it. Grep for `KLUDGE` before changing
  one; do not add one without a removal condition

## Architecture

What future work on CopyOfA may assume today. Commands and day-to-day
conventions are above.

### Shape

A Python CLI application, never published: the `Private :: Do Not Upload` classifier
makes PyPI reject any upload. The `copyofa` console script calls
`copyofa.cli:main`.

### Language, runtime, and tooling

- Python 3.11+ (`requires-python`); developed on the version in
  `.python-version`
- uv manages dependencies and environments; `uv.lock` is committed, and uv_build
  builds the package
- just is the task runner
- ruff formats and lints; pyproject-fmt formats `pyproject.toml`; rumdl formats and
  lints Markdown, configured in `.rumdl.toml`
- ty checks types
- deptry reports unused and undeclared dependencies
- cspell checks spelling against `cspell.json`; actionlint checks the workflows
- pre-commit holds the one list of checks, run on every commit, by `just qa` and by
  CI. The tools the justfile also runs on their own come from `uv.lock` through
  `uv run`; the general file checks, actionlint and cspell are pinned in
  `.pre-commit-config.yaml`

### Structure

- `src/copyofa/`: the package (src layout)
- `tests/`: the pytest suite
- `docs/`: durable project documents: the Manifesto, the Product Map, release briefs
  (`docs/briefs/`), architecture decision records (`docs/decisions/`), and the formats
  of the files CopyOfA writes (`docs/formats/`)

### Evidence Set format

An Evidence Set is a BagIt 1.0 bag with SHA-256 manifests, its Preserved Evidence
under `data/` and CopyOfA's records in the `copyofa/` tag directory, as
[ADR 0001](docs/decisions/0001-store-evidence-sets-as-bagit-bags.md) decides.
[docs/formats/evidence-set.md](docs/formats/evidence-set.md) documents the layout and
the Import Record; change it with any change to what import writes.
[docs/formats/verification-report.md](docs/formats/verification-report.md) documents
the Report verify prints; change it with any change to that Report.

### Command conventions

Every command follows the conventions `import` and `verify` set in v0.1.0, as
`src/copyofa/cli.py` implements them:

- A short human-readable result goes to stdout; `--json` prints one JSON document
  instead, ASCII with other characters escaped as `\uXXXX`. Progress, warnings and
  errors go to stderr
- Exit 0 on success, 1 when the command refused, failed or found a problem (a result
  is still printed when there is one), 2 for invalid arguments or a target of the
  wrong kind, and 130 when canceled with Ctrl-C
- Stdout stays empty whenever no result is produced
- No interactive prompts

### Testing

pytest with coverage (`just test`). CI runs it on the development Python.

### Distribution

None.

### CI

- `.github/workflows/ci.yml` runs on pushes to `main` and on every pull request:
  every pre-commit hook, then the tests. Actions are pinned to commit
  SHAs, and no checkout keeps its token
- Dependabot opens weekly grouped updates for GitHub Actions and `uv.lock`, with
  `build:` commit messages and the `dependencies` and `build` labels; it moves the
  lock only, never the minimum versions in `pyproject.toml`

### Agent support

Coding agents are expected contributors. They follow this file.

## Deviations from the shared workflow

None.
