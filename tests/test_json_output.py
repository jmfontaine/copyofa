from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from copyofa import cli

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import Run


def test_json_escapes_names_that_are_not_valid_utf8(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    # Python's stand-in for the Latin-1 byte 0xE9 in a Linux file name; macOS file
    # systems refuse such names, so the formatter is checked directly.
    name = "data/caf\udce9.flac"

    cli._print_json({"path": name, "note": "café"})

    out = capsysbinary.readouterr().out
    assert b'"data/caf\\udce9.flac"' in out
    assert '"note": "café"'.encode() in out
    assert json.loads(out.decode("utf-8", errors="strict")) == {
        "path": name,
        "note": "café",
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_json_refuses_a_number_that_is_not_finite(
    capsysbinary: pytest.CaptureFixture[bytes], value: float
) -> None:
    with pytest.raises(ValueError, match="not JSON compliant"):
        cli._print_json({"measurements": [1.0, value]})

    assert capsysbinary.readouterr().out == b""


def test_json_is_utf8_whatever_the_locale(tmp_path: Path) -> None:
    source = tmp_path / "Café ✓"
    source.mkdir()
    (source / "track.flac").write_bytes(b"audio")
    command = "import sys; from copyofa.cli import main; sys.exit(main(sys.argv[1:]))"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            command,
            "import",
            source,
            "--to",
            tmp_path / "Set",
            "--json",
        ],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "latin-1"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout.decode("utf-8", errors="strict"))
    assert document["import_record"]["sources"][0]["given"] == str(source)
    assert "Café ✓".encode() in result.stdout


def test_inspect_json_prints_non_ascii_characters_as_utf8(
    run: Run, tmp_path: Path
) -> None:
    source = tmp_path / "Été"
    source.mkdir()
    (source / "notes.txt").write_text("summer\n")
    assert run("import", source, "--to", tmp_path / "Set").code == 0

    outcome = run("inspect", tmp_path / "Set", "--json")

    assert outcome.code == 0
    assert '"path": "data/Été/notes.txt"' in outcome.out
