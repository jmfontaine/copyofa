# Contributing to CopyOfA

Contributions are welcome, including bug fixes, new features, documentation, and test
coverage. This guide covers the development setup and pull request process.

For larger changes, please open an issue first so we can discuss the approach before you
invest significant time.

## Reporting Bugs and Requesting Features

Before opening an issue, search
[existing issues](https://github.com/jmfontaine/copyofa/issues) to
avoid duplicates, then pick the bug or feature form. An idea that is not ready to be an
issue belongs in
[Discussions](https://github.com/jmfontaine/copyofa/discussions/categories/ideas).

**Bug reports** should include:

- Python and CopyOfA versions (`python --version`, `copyofa --version`)
- The smallest input or code that reproduces the problem
- The full traceback or error message

**Feature requests**: describe the problem you want to solve, not just the solution.

## Setup

```bash
git clone https://github.com/jmfontaine/copyofa.git
cd copyofa
just setup
```

`just setup` requires only [uv](https://docs.astral.sh/uv/) and
[just](https://github.com/casey/just) on your PATH. It installs all dependencies,
including pre-commit from the `dev` dependency group, and then installs the git hooks.
In a linked git worktree it skips the hooks, which the main checkout's hooks already
cover.

> [!TIP]
> If just isn't installed, run the underlying commands directly. See
> [`justfile`](justfile) for what each recipe runs; most are one-line `uv run` commands.
> For example, `just test` runs `uv run pytest --cov --cov-config=pyproject.toml`.

## Development Workflow

Key commands:

```bash
just format        # Auto-format code, pyproject.toml and Markdown
just lint-fix      # Auto-fix lint issues
just qa            # All checks: every pre-commit hook, then verify-types
just test          # Tests with coverage
just type-check    # Run ty
just verify-types  # Check the public API is fully typed
```

Run `just --list` to see all available commands.

## Testing

```bash
just test                                  # All tests
just test tests/test_version.py            # Single file
just test tests/test_version.py -k version # Matching tests
```

## Code Style

- Python 3.11+; formatting and linting use ruff, with a line length of 88,
  and rumdl for Markdown (`just format`, `just lint-fix`)
- Type checking with ty (`just type-check`) and a fully typed public API
  (`just verify-types`)
- Use US English in code, comments, docs, and commit messages
- Write pull request titles as
  [Conventional Commits](https://www.conventionalcommits.org/) without a scope, as
  `<type>: <description>` (e.g., `fix: reject an empty name`). Use one of `feat`, `fix`,
  `perf`, `refactor`, `docs`, `test`, `build`, `ci` or `chore` as the type, and
  `<type>!:` for a breaking change (e.g., `feat!: drop Python 3.11`)

## Submitting a Pull Request

1. Fork the repository and create a branch from `main` (e.g., `fix/empty-name`)
2. Make your changes and add or update tests
3. Run `just qa` and `just test` to catch issues before CI does
4. Push your branch and open a pull request against `main`. Give it a Conventional
   Commit title, and link the issue it resolves with `Closes #N` in the description (the
   pull request template has a line for it)

Please sign your commits when you can (`git commit -S`; edits made in GitHub's web
editor are signed by GitHub). If you can't, say so in the pull request: a maintainer
can still merge it.

### Pull Request Checklist

- [ ] Add or update tests, then run `just test`
- [ ] Run `just qa` and confirm it passes
- [ ] Update the README if the change affects user-visible behavior

### What to Expect

A maintainer usually reviews pull requests within a few days. Change requests are a
normal part of the collaborative process. Push any additional commits to the same
branch; there is no need to squash, and commit messages on the branch are free-form.
Pull requests are squash-merged, so the pull request title becomes the commit on `main`
(with the pull request number appended), and git-cliff builds the release notes from it:
write it as a Conventional Commit, with `!` before the colon for a breaking change.

## Releasing

Maintainers only. `main` changes only through pull requests; the only direct push is
the signed tag. Between releases `main` carries a development version,
`X.Y.Z.devN`, which sorts below `X.Y.Z`, so a build from `main` never passes for the
release. Each recipe below runs from an up-to-date, clean `main`.

1. Run `just changelog-preview` to review the release notes, which
   [git-cliff](https://git-cliff.org/) generates from the pull request titles since the
   last tag
2. Run `just release-prepare`. It opens the pull request `chore: release vX.Y.Z`, which
   sets the version to `X.Y.Z`, the development version without its `.devN`, in
   `pyproject.toml` and `uv.lock` (pass another `X.Y.Z` to release that instead).
   Squash-merging it is the go/no-go point
3. Run `git checkout main && git pull --ff-only`, then `just release`. It refuses any
   version but a plain `X.Y.Z` and any existing tag, creates a signed `vX.Y.Z` tag,
   pushes only the tag, and monitors the publish workflow
4. Run `just release-next`, which refuses unless the tag is on `origin`. It opens the
   pull request `chore: start X.(Y+1).0 development` (`just release-next patch` or
   `major` for the others). Squash-merge it

Both version pull requests are skipped in the release notes.

The tag triggers `.github/workflows/publish.yml`. The workflow verifies that the tagged
commit is on `main`, runs all CI checks, publishes the wheel and sdist that CI built and
tested to PyPI, and then creates the GitHub release with the same notes. If a tag
doesn't match the package version, the workflow stops before uploading.

If a job fails after the PyPI upload, rerun the workflow. It skips files already on PyPI
and creates the GitHub release only if one doesn't already exist. A release cannot be
replaced once uploaded: if a broken version reaches PyPI, yank it there, then release
the fix as the next patch with `just release-prepare X.Y.(Z+1)` once `main` is on a
development version, or `just release-next patch` first if it is still on `X.Y.Z`.

Publishing uses [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no
token is stored. It requires a GitHub environment named `pypi` and a trusted publisher
on PyPI configured with exactly these values: owner `jmfontaine`, repository
`copyofa`, workflow `publish.yml`, and environment `pypi`. Before the first
release, the PyPI project doesn't exist yet, so register it as a
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
for the project name `copyofa`. The first upload creates the project.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE.txt).
