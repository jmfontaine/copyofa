from __future__ import annotations

from importlib.metadata import version

import pytest

import copyofa
from copyofa.cli import main


def test_version_matches_installed_metadata() -> None:
    # Fails once __version__ is set by hand instead of read from the metadata.
    assert copyofa.__version__ == version("copyofa")


def test_cli_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"{copyofa.__version__}\n"
