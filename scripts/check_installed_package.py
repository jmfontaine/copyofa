#!/usr/bin/env python
"""Smoke-check an installed copyofa.

Run it with the interpreter of a clean environment where the wheel or sdist was
installed from its published metadata, not from ``uv.lock``. It checks that the
package is imported from that environment rather than from a checkout, that it
ships its PEP 561 marker, and that ``__version__`` matches the installed
metadata. It also runs the console script, which proves the entry point
was installed, not just that the package imports.

Project-specific checks belong here too: dependency floors the metadata must
enforce, or data files the package reads at runtime.
"""

from __future__ import annotations

import subprocess
import sys
import sysconfig
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

import copyofa


def fail(message: str) -> NoReturn:
    print(f"check_installed_package: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_location() -> None:
    if copyofa.__file__ is None:
        fail("the package has no __file__")
    package = Path(copyofa.__file__).resolve().parent
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    if not package.is_relative_to(site_packages):
        fail(f"imported from {package}, not from {site_packages}")
    if not (package / "py.typed").is_file():
        fail("the installed package has no py.typed marker")
    print(f"check_installed_package: imported from {package}")


def check_version() -> None:
    installed = version("copyofa")
    if copyofa.__version__ != installed:
        fail(
            f"__version__ {copyofa.__version__} does not match "
            f"the installed metadata {installed}"
        )
    print(f"check_installed_package: version {installed}")


def check_console_script() -> None:
    # The script next to this interpreter, not whichever one PATH finds first.
    script = Path(sys.executable).with_name("copyofa")
    if not script.is_file():
        fail(f"no console script at {script}")
    result = subprocess.run(
        [str(script), "--version"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        fail(f"`{script} --version` exited {result.returncode}:\n{result.stderr}")
    if result.stdout.strip() != version("copyofa"):
        fail(f"`{script} --version` printed {result.stdout.strip()!r}")
    print(f"check_installed_package: {script.name} --version ok")


def main() -> None:
    check_location()
    check_version()
    check_console_script()


if __name__ == "__main__":
    main()
