set quiet := true

# List the available recipes
_list:
    just --list

# Check for unused or undeclared deps
deps-unused:
    uv run deptry src

# Update deps to latest versions
deps-update:
    uv lock --upgrade
    uv sync --all-groups

# Run formatters
format:
    # pyproject-fmt exits 1 after reformatting; only fail if the file is still off.
    uv run pyproject-fmt pyproject.toml || uv run pyproject-fmt --check pyproject.toml
    uv run ruff format
    uv run rumdl fmt

# Check formatting without modifying files
format-check:
    uv run pyproject-fmt --check pyproject.toml
    uv run ruff format --check
    uv run rumdl fmt --check

# Run linters
lint:
    uv run ruff check
    uv run rumdl check

# Run linters and fix issues
lint-fix:
    uv run ruff check --fix
    uv run rumdl check --fix

# Run pre-commit on all files
pre-commit:
    uv run pre-commit run --all-files

# Install pre-commit hooks (main checkout only)
pre-commit-install:
    #!/usr/bin/env bash
    set -euo pipefail
    # Linked worktrees share the main checkout's .git/hooks: installing from one
    # would replace the hook every checkout uses and point it at this worktree's
    # .venv, which disappears with the worktree.
    common_dir=$(git rev-parse --path-format=absolute --git-common-dir)
    if [ "$(git rev-parse --path-format=absolute --git-dir)" != "$common_dir" ]; then
        echo "Error: this is a linked worktree; it shares the hooks in $common_dir/hooks with every other checkout. Install hooks from the main checkout instead." >&2
        exit 1
    fi
    uv run pre-commit install

# Update pre-commit hooks to latest versions
pre-commit-update:
    uv run pre-commit autoupdate --freeze

# Run all quality assurance checks: every pre-commit hook on all tracked files
qa: pre-commit

# Set local dev environment up (hooks: main checkout only)
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    uv sync --all-groups
    # Same guard as pre-commit-install: a linked worktree must not replace the
    # hook it shares with every other checkout.
    if [ "$(git rev-parse --path-format=absolute --git-dir)" = "$(git rev-parse --path-format=absolute --git-common-dir)" ]; then
        uv run pre-commit install
    else
        echo "Linked worktree: skipped installing the git hooks, which the main checkout's hooks already cover"
    fi
    echo "Run 'source .venv/bin/activate' to activate the Python virtual environment"

# Check spelling against cspell.json, the word list VS Code also uses
spell:
    uv run pre-commit run cspell --all-files

# Run tests with coverage
[positional-arguments]
test *args:
    # --cov takes an optional source; --cov-config ends it, so a test path stays a test path.
    uv run pytest --cov --cov-config=pyproject.toml "$@"

# Run type checker
type-check:
    uv run ty check
