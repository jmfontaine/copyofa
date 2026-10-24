"""Command-line interface for CopyOfA."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import copyofa

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="copyofa",
        description=copyofa.__doc__,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=copyofa.__version__,
    )
    parser.parse_args(argv)
