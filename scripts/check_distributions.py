#!/usr/bin/env python
"""Check the contents of built distributions before they are published.

Usage: ``python scripts/check_distributions.py dist``

Both the wheel and the sdist must carry every file under the package source,
``src/copyofa/``, data files and the PEP 561 marker included. The wheel
must install nothing else, and neither may carry build or editor leftovers.

The test suite cannot make these checks: it runs from the source tree, where a
wheel missing a data file looks fine.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path
from typing import NoReturn

PACKAGE = "copyofa"
SOURCE = Path(__file__).resolve().parent.parent / "src" / PACKAGE
SDIST_REQUIRED = ("PKG-INFO", "pyproject.toml", "README.md", "LICENSE.txt")
# Build and editor leftovers that must never be published.
LEFTOVER_PARTS = frozenset(
    {
        "__pycache__",
        ".DS_Store",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".vscode",
    }
)
LEFTOVER_SUFFIXES = (".coverage", ".pyc", ".pyo", ".swp", "~")


def fail(message: str) -> NoReturn:
    print(f"check_distributions: {message}", file=sys.stderr)
    raise SystemExit(1)


def is_leftover(name: str) -> bool:
    return bool(LEFTOVER_PARTS.intersection(Path(name).parts)) or name.endswith(
        LEFTOVER_SUFFIXES
    )


def package_files() -> list[str]:
    names = (path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*"))
    files = sorted(
        name for name in names if (SOURCE / name).is_file() and not is_leftover(name)
    )
    if not files:
        fail(f"found no package files under {SOURCE}")
    return files


def check_leftovers(archive: str, names: list[str]) -> None:
    leftovers = [name for name in names if is_leftover(name)]
    if leftovers:
        fail(f"{archive} contains {', '.join(leftovers)}")


def check_wheel(path: Path, expected: list[str]) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()

    missing = [
        f"{PACKAGE}/{name}" for name in expected if f"{PACKAGE}/{name}" not in names
    ]
    if missing:
        fail(f"{path.name} is missing {', '.join(missing)}")

    if not any(name.endswith(".dist-info/licenses/LICENSE.txt") for name in names):
        fail(f"{path.name} is missing its license file")

    # Anything else at the top level would be installed next to the package.
    roots = {name.split("/")[0] for name in names}
    stray = sorted(
        root for root in roots if root != PACKAGE and not root.endswith(".dist-info")
    )
    if stray:
        fail(f"{path.name} installs more than {PACKAGE}: {', '.join(stray)}")

    check_leftovers(path.name, names)
    print(f"check_distributions: {path.name} ok ({len(names)} files)")


def check_sdist(path: Path, expected: list[str]) -> None:
    # Everything sits under "<name>-<version>/", the archive's own name.
    root = path.name.removesuffix(".tar.gz")
    with tarfile.open(path) as archive:
        names = [
            name[len(root) + 1 :]
            for name in archive.getnames()
            if name.startswith(f"{root}/")
        ]

    required = [*SDIST_REQUIRED, *(f"src/{PACKAGE}/{name}" for name in expected)]
    missing = [name for name in required if name not in names]
    if missing:
        fail(f"{path.name} is missing {', '.join(missing)}")

    check_leftovers(path.name, names)
    print(f"check_distributions: {path.name} ok ({len(names)} files)")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: check_distributions.py DIST_DIR")
    dist = Path(sys.argv[1])
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        fail(
            f"expected one wheel and one sdist in {dist}, "
            f"found {len(wheels)} and {len(sdists)}"
        )
    expected = package_files()
    check_wheel(wheels[0], expected)
    check_sdist(sdists[0], expected)


if __name__ == "__main__":
    main()
