set quiet := true

# List the available recipes
_list:
    just --list

# Preview release notes for unreleased changes
changelog-preview:
    uv run git-cliff --unreleased

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

# Run all quality assurance checks: every pre-commit hook on all tracked files, then the type-completeness audit
qa: pre-commit verify-types

# Tag the merged release version on main, push only the tag, and watch the publish workflow
release: _require-synced-main
    #!/usr/bin/env bash
    set -euo pipefail
    fail() { echo "Error: $*" >&2; exit 1; }
    # ls-remote --exit-code: 0 = tag found, 2 = not found, anything else = the query failed.
    tag_on_origin() {
        local status=0
        git ls-remote --exit-code --tags origin "refs/tags/$1" >/dev/null || status=$?
        case "$status" in
            0) return 0 ;;
            2) return 1 ;;
            *) fail "could not check origin for tag $1" ;;
        esac
    }
    version=$(uv version --short)
    # publish.yml uploads whatever version the tag names, so a development or
    # pre-release version must never be tagged.
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version $version is not a release version (X.Y.Z); run 'just release-prepare' and merge its pull request first"
    tag="v${version}"
    head=$(git rev-parse HEAD)
    if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null; then
        fail "tag $tag already exists locally"
    fi
    if tag_on_origin "$tag"; then
        fail "tag $tag already exists on origin"
    fi
    echo "Creating signed tag $tag..."
    git tag -s "$tag" -m "Release $tag"
    # main changes only through pull requests, so the tag is the only push.
    echo "Pushing $tag to origin..."
    if ! git push origin "refs/tags/$tag"; then
        # A failed push is not proof of rejection: the connection can drop after
        # origin accepted it. Ask origin before touching the local tag.
        if tag_on_origin "$tag"; then
            fail "git push reported an error, but $tag is on origin, so publishing has started; kept the local tag; check 'gh run list --workflow=publish.yml'"
        fi
        git tag -d "$tag" >/dev/null
        fail "push failed; origin has no $tag, so nothing was published; deleted the local tag"
    fi
    echo "Waiting for the publish workflow run for $tag..."
    run_id=""
    for _ in $(seq 24); do
        # A failing gh call (network blip, rate limit) costs one attempt, not the run.
        run_id=$(gh run list --workflow=publish.yml --event=push --branch="$tag" --commit="$head" --limit=1 --json=databaseId --jq='.[0].databaseId // empty') || run_id=""
        [ -n "$run_id" ] && break
        sleep 5
    done
    [ -n "$run_id" ] || fail "no publish run for $tag appeared within 2 minutes; $tag is pushed, so check 'gh run list --workflow=publish.yml'"
    gh run watch --exit-status "$run_id"
    echo "Released $tag. Run 'just release-next' (or 'just release-next patch|major') to start the next development version."

# Open the pull request that starts the next development version: bump is minor, patch or major
[positional-arguments]
release-next bump="minor": _require-synced-main
    #!/usr/bin/env bash
    set -euo pipefail
    fail() { echo "Error: $*" >&2; exit 1; }
    bump=$1
    case "$bump" in
        minor | patch | major) ;;
        *) fail "bump must be minor, patch or major, not '$bump'" ;;
    esac
    current=$(uv version --short)
    [[ "$current" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version $current is not a release version (X.Y.Z), so development is already open"
    # ls-remote --exit-code: 0 = tag found, 2 = not found, anything else = the query failed.
    status=0
    git ls-remote --exit-code --tags origin "refs/tags/v$current" >/dev/null || status=$?
    case "$status" in
        0) ;;
        2) fail "tag v$current is not on origin; release it with 'just release' first" ;;
        *) fail "could not check origin for tag v$current" ;;
    esac
    next=$(uv version --bump "$bump" --dry-run --short)
    # Set .dev0 explicitly: `uv version --bump minor --bump dev` gives .dev1.
    {{ quote(just_executable()) }} _version-pr "release/v$next.dev0" "$next.dev0" \
        "chore: start $next development" \
        "Set the version to $next.dev0 in pyproject.toml and uv.lock, so builds from main sort below the $next release."

# Open the release pull request: version defaults to the development version without its .devN
[positional-arguments]
release-prepare version="": _require-synced-main
    #!/usr/bin/env bash
    set -euo pipefail
    fail() { echo "Error: $*" >&2; exit 1; }
    current=$(uv version --short)
    [[ "$current" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]+$ ]] || fail "version $current is not a development version (X.Y.Z.devN); run 'just release-next' first"
    version=$1
    if [ -z "$version" ]; then
        version=$(uv version --bump stable --dry-run --short)
    elif [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        fail "$version is not a release version (X.Y.Z)"
    fi
    # ls-remote --exit-code: 0 = tag found, 2 = not found, anything else = the query failed.
    status=0
    git ls-remote --exit-code --tags origin "refs/tags/v$version" >/dev/null || status=$?
    case "$status" in
        0) fail "tag v$version already exists on origin" ;;
        2) ;;
        *) fail "could not check origin for tag v$version" ;;
    esac
    {{ quote(just_executable()) }} _version-pr "release/v$version" "$version" \
        "chore: release v$version" \
        "Set the version to $version for release in pyproject.toml and uv.lock. Merging this pull request approves the release; 'just release' on main then tags and publishes it."

# Refuse to go on unless HEAD is main, the working tree is clean, and main equals the freshly fetched origin/main
_require-synced-main:
    #!/usr/bin/env bash
    set -euo pipefail
    fail() { echo "Error: $*" >&2; exit 1; }
    branch=$(git symbolic-ref --quiet --short HEAD) || fail "HEAD is detached; check out main"
    [ "$branch" = main ] || fail "on branch $branch; version changes and releases start from main"
    [ -z "$(git status --porcelain)" ] || fail "working tree is not clean"
    git fetch --quiet origin main || fail "could not fetch main from origin"
    [ "$(git rev-parse HEAD)" = "$(git rev-parse refs/remotes/origin/main)" ] || fail "main is not in sync with origin/main; merge any pending version pull request, then pull"

# Commit a version change on a new branch, open its pull request, and return to main
[positional-arguments]
_version-pr branch version subject body:
    #!/usr/bin/env bash
    set -euo pipefail
    branch=$1 version=$2 subject=$3 body=$4
    trap 'echo "Error: opening the pull request from $branch failed; to retry, run: git switch --force main && git branch -D $branch (and git push origin --delete $branch if it was pushed)" >&2' ERR
    git switch --quiet --create "$branch"
    # --no-sync: relock only; leave the developer's environment (extras, groups) alone.
    uv version --no-sync "$version"
    git add pyproject.toml uv.lock
    git commit --quiet -S -m "$subject" -m "$body"
    git push --quiet --set-upstream origin "$branch"
    # The sections of .github/pull_request_template.md that apply; there is no issue to close.
    pr_body=$(printf '## Summary\n\n%s\n\n## Verification\n\n`uv version --no-sync %s` set the version in pyproject.toml and uv.lock; CI checks the result on this pull request.\n' "$body" "$version")
    gh pr create --base main --head "$branch" --title "$subject" --body "$pr_body"
    git switch --quiet main

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

# Audit public API type annotation coverage
verify-types:
    uv run pyright --ignoreexternal --verifytypes copyofa
