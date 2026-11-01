from __future__ import annotations

import hashlib
import json
import os
import shutil
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema
import numpy as np
import pytest
from conftest import (
    RATE,
    closed_stdout,
    requires_permissions,
    signal,
    snapshot,
    write_audio,
)

from copyofa import comparator, inspector, validator, verifier

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Outcome, Run

    MakeSet = Callable[[Callable[[Path], None]], Path]

KINDS = {
    "verification": (verifier.REPORT_KIND, verifier.REPORT_FORMAT_VERSION),
    "inspection": (inspector.REPORT_KIND, inspector.REPORT_FORMAT_VERSION),
    "comparison": (comparator.REPORT_KIND, comparator.REPORT_FORMAT_VERSION),
}
SCHEMA_FILES = sorted(
    entry.name
    for entry in resources.files("copyofa").joinpath("schemas").iterdir()
    if entry.name.endswith(".schema.json")
)
# Version 3 comparison Reports that compare 0.6.0.dev0 printed, kept as they were so
# validate keeps accepting what that version printed: the Report of 2.5 s tracks that
# align at an offset, the same with the locations left out, and one whose input A is
# a track of an acquired set.
STORED = Path(__file__).parent / "reports" / "comparison-3"
# Version 4 and 5 comparison Reports that compare 0.8.0.dev0 and 0.9.0.dev0 printed,
# kept as they were so validate keeps accepting what those versions printed;
# tests/test_view.py lists them.
STORED_4 = Path(__file__).parent / "reports" / "comparison-4"
STORED_5 = Path(__file__).parent / "reports" / "comparison-5"
STORED_REPORTS = {
    "comparison_v3": "measured",
    "comparison_omitted": "locations_omitted",
    "comparison_track": "acquired_track",
}


def as_version_1(document: dict[str, Any]) -> dict[str, Any]:
    """Return a version 3 comparison Report that holds its locations as version 1."""
    assert document["omitted"] == []
    return {
        key: 1 if key == "format_version" else value
        for key, value in document.items()
        if key != "omitted"
    }


@pytest.fixture
def reports(run: Run, make_set: MakeSet, tmp_path: Path) -> dict[str, Path]:
    """Save a verification, an inspection and a comparison Report of real sets.

    The comparison Report is the current version's: B is the first 5 s of A's noise, 2 s
    later, in 24 bits and with a little noise added. It holds one portion, the silence
    before B as an unmatched range of B and the last second of A as one of A. Version 1
    to 3 comparison Reports come from the stored Reports compare printed in version 3.
    """
    noise = signal(6 * RATE, 2, 16)
    dither = signal(5 * RATE, 2, 12, seed=2)
    delayed = np.vstack(
        [np.zeros((2 * RATE, 2), np.int32), (noise[: 5 * RATE] << 8) + dither]
    )
    a = make_set(lambda source: write_audio(source / "a.flac", noise, 16, "FLAC"))
    b = make_set(lambda source: write_audio(source / "b.wav", delayed, 24, "WAV"))
    commands = {
        "verification": ("verify", a),
        "inspection": ("inspect", a),
        "comparison": ("compare", a / "data/Album/a.flac", b / "data/Album/b.wav"),
    }
    saved = {}
    for kind, arguments in commands.items():
        outcome = run(*arguments, "--json")
        assert outcome.code == 0, outcome.err
        saved[kind] = tmp_path / f"{kind}.json"
        saved[kind].write_text(outcome.out)
    for key, name in STORED_REPORTS.items():
        saved[key] = tmp_path / f"{key}.json"
        shutil.copyfile(STORED / f"{name}.json", saved[key])
    saved["comparison_v1"] = tmp_path / "comparison_v1.json"
    version_3 = json.loads(saved["comparison_v3"].read_text())
    saved["comparison_v1"].write_text(json.dumps(as_version_1(version_3)))
    return saved


def validate(
    run: Run, path: Path | str, *options: str
) -> tuple[Outcome, dict[str, Any]]:
    """Run `validate --json` and return the validation result it printed."""
    outcome = run("validate", path, "--json", *options)
    return outcome, json.loads(outcome.out) if outcome.out else {}


def save(directory: Path, document: Any, name: str = "edited.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(document))
    return path


def edited(path: Path, change: Callable[[Any], None]) -> Any:
    document = json.loads(path.read_text())
    change(document)
    return document


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_each_schema_is_draft_2020_12_and_named_for_its_reports(name: str) -> None:
    text = resources.files("copyofa").joinpath("schemas", name).read_text("utf-8")
    schema = json.loads(text)

    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/jmfontaine/copyofa/main/"
        f"src/copyofa/schemas/{name}"
    )
    assert schema["title"]
    assert schema["description"]
    kind = schema["properties"]["report_kind"]["const"]
    version = schema["properties"]["format_version"]["const"]
    assert name == f"{kind.removeprefix('copyofa.')}-report-{version}.schema.json"
    assert validator.load_schema(kind, version) == schema


@pytest.mark.parametrize(("kind", "version"), KINDS.values(), ids=KINDS)
def test_every_report_kind_that_commands_print_has_a_schema(
    kind: str, version: int
) -> None:
    assert validator.load_schema(kind, version) is not None


@pytest.mark.parametrize("kind", KINDS)
def test_validate_accepts_each_kind_of_report(
    run: Run, reports: dict[str, Path], kind: str
) -> None:
    path = reports[kind]

    outcome, result = validate(run, path)

    assert outcome.code == 0, outcome.err
    assert result == {
        "outcome": "valid",
        "report": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "report_kind": KINDS[kind][0],
        "format_version": KINDS[kind][1],
        "problems": [],
        "copyofa_version": result["copyofa_version"],
        "limitations": result["limitations"],
    }
    assert result["limitations"]
    assert outcome.err == ""


def test_validate_prints_a_short_result(run: Run, reports: dict[str, Path]) -> None:
    path = reports["comparison"]

    outcome = run("validate", path)

    assert outcome.code == 0, outcome.err
    lines = outcome.out.splitlines()
    assert lines[0] == "Result: valid"
    assert f"SHA-256: {hashlib.sha256(path.read_bytes()).hexdigest()}" in lines
    assert "Report kind: copyofa.comparison" in lines
    assert "Format version: 6" in lines
    assert "Limitations:" in lines
    assert "Traceback" not in outcome.out + outcome.err


def test_validate_accepts_a_path_that_is_not_valid_utf8(
    run: Run, reports: dict[str, Path], tmp_path: Path
) -> None:
    document = edited(
        reports["inspection"],
        lambda report: report.update(evidence_set=f"{chr(0xDCFF)}/Set"),
    )

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"


def test_validate_returns_the_parsed_document(
    reports: dict[str, Path],
) -> None:
    validation = validator.validate(str(reports["verification"]))

    assert validation.document == json.loads(reports["verification"].read_text())
    assert validation.result["outcome"] == validator.VALID


def test_validate_makes_the_path_absolute_without_normalizing_it(
    run: Run,
    reports: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path)

    _, result = validate(run, "sub/../verification.json")

    assert result["report"] == str(tmp_path.resolve() / "sub/../verification.json")


# What each edit does to a valid Report, and where the schema finds the problem.
EDITS: dict[str, tuple[str, Callable[[Any], None], str]] = {
    "a missing required field": (
        "verification",
        lambda report: report.pop("checked_at"),
        "",
    ),
    "a missing required field in a list item": (
        "verification",
        lambda report: report["payload"][0].pop("expected_digest"),
        "/payload/0",
    ),
    "a value of the wrong type": (
        "verification",
        lambda report: report.update(copyofa_version=1),
        "/copyofa_version",
    ),
    "a count that is negative": (
        "inspection",
        lambda report: report["counts"].update(failed=-1),
        "/counts/failed",
    ),
    "an unknown field": (
        "inspection",
        lambda report: report.update(surprise=True),
        "",
    ),
    "an unknown field in a nested object": (
        "comparison",
        lambda report: report["inputs"]["a"].update(surprise=True),
        "/inputs/a",
    ),
    "a member that names a schema to fetch": (
        "comparison",
        lambda report: report.update({"$ref": "http://example.invalid/schema"}),
        "",
    ),
    "a value outside an enumeration": (
        "verification",
        lambda report: report["payload"][0].update(outcome="intact"),
        "/payload/0/outcome",
    ),
    "a decoder that is not libsndfile": (
        "inspection",
        lambda report: report["method"].update(decoder="ffmpeg"),
        "/method/decoder",
    ),
    "a digest that is too short": (
        "verification",
        lambda report: report["payload"][0].update(expected_digest="abc"),
        "/payload/0/expected_digest",
    ),
    "a digest in uppercase": (
        "inspection",
        lambda report: report["files"][0].update(
            observed_digest=report["files"][0]["observed_digest"].upper()
        ),
        "/files/0/observed_digest",
    ),
    "a digest that ends with a line feed": (
        "verification",
        lambda report: report["payload"][0].update(
            expected_digest=report["payload"][0]["expected_digest"][:-1] + "a\n"
        ),
        "/payload/0/expected_digest",
    ),
    "an audio digest that ends with a line feed": (
        "inspection",
        lambda report: report["files"][0].update(
            audio_digest=report["files"][0]["audio_digest"] + "\n"
        ),
        "/files/0/audio_digest",
    ),
    "a malformed timestamp": (
        "comparison",
        lambda report: report.update(compared_at="2026-10-25 18:30:00"),
        "/compared_at",
    ),
    "a correlation above 1": (
        "comparison",
        lambda report: report["measurements"]["portions"][0]["downmix"].update(
            correlation=1.5
        ),
        "/measurements/portions/0/downmix/correlation",
    ),
    "a measurement that is neither present nor absent": (
        "comparison",
        lambda report: report["measurements"]["portions"][0]["downmix"].pop("gain_db"),
        "/measurements/portions/0/downmix",
    ),
    "a correlation above 1 in version 3": (
        "comparison_v3",
        lambda report: report["measurements"]["downmix"].update(correlation=1.5),
        "/measurements/downmix/correlation",
    ),
    "a measurement that is neither present nor absent in version 3": (
        "comparison_v3",
        lambda report: report["measurements"]["downmix"].pop("gain_db"),
        "/measurements/downmix",
    ),
    "a non-silent unmatched range without its level": (
        "comparison",
        lambda report: report["measurements"]["unmatched"]["a"][0].pop("level_dbfs"),
        "/measurements/unmatched/a/0",
    ),
    "a digitally silent unmatched range with a level": (
        "comparison",
        lambda report: report["measurements"]["unmatched"]["b"][0].update(
            level_dbfs=-90.0
        ),
        "/measurements/unmatched/b/0",
    ),
    "portions that are listed and absent": (
        "comparison",
        lambda report: report["measurements"].update(
            absent={"portions": "no portion was found"}
        ),
        "/measurements/portions",
    ),
    "no portion without a reason": (
        "comparison",
        lambda report: report["measurements"].update(portions=[]),
        "/measurements/portions",
    ),
    "a method parameter that is missing": (
        "comparison",
        lambda report: report["method"]["parameters"].pop("block_frames"),
        "/method/parameters",
    ),
    "a method parameter that has another value": (
        "comparison",
        lambda report: report["method"]["parameters"].update(window_seconds=6),
        "/method/parameters/window_seconds",
    ),
    "a portion rank that is neither primary nor alternate": (
        "comparison",
        lambda report: report["measurements"]["portions"][0].update(rank="secondary"),
        "/measurements/portions/0/rank",
    ),
    "a portion without its block-gain residual or a reason": (
        "comparison",
        lambda report: report["measurements"]["portions"][0].pop(
            "block_gain_residual_db"
        ),
        "/measurements/portions/0",
    ),
    "an evidence_set that is neither present nor omitted": (
        "comparison",
        lambda report: report["inputs"]["a"].pop("evidence_set"),
        "/inputs/a",
    ),
    "an interpreted file without its findings": (
        "inspection",
        lambda report: report["files"][0].pop("peak"),
        "/files/0",
    ),
    "a non-interpreted file with a finding": (
        "comparison",
        lambda report: report["inputs"]["a"].update(
            outcome="failed", reason="it cannot be decoded"
        ),
        "/inputs/a",
    ),
}


@pytest.mark.parametrize("name", EDITS)
def test_validate_finds_each_problem_of_a_schema_at_its_pointer(
    run: Run, reports: dict[str, Path], tmp_path: Path, name: str
) -> None:
    kind, change, location = EDITS[name]
    document = edited(reports[kind], change)
    path = save(tmp_path, document)

    outcome, result = validate(run, path)

    assert outcome.code == 1
    assert outcome.err == ""
    assert result["outcome"] == "invalid"
    assert result["report_kind"] == document["report_kind"]
    assert result["format_version"] == document["format_version"]
    assert location in {problem["location"] for problem in result["problems"]}
    assert all(problem["message"] for problem in result["problems"])


def test_validate_accepts_a_comparison_report_of_format_version_1(
    run: Run, reports: dict[str, Path]
) -> None:
    path = reports["comparison_v1"]

    outcome, result = validate(run, path)

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["report_kind"] == "copyofa.comparison"
    assert result["format_version"] == 1
    assert result["problems"] == []


def test_validate_accepts_a_comparison_report_of_format_version_2(
    run: Run, reports: dict[str, Path], tmp_path: Path
) -> None:
    document = edited(
        reports["comparison_v3"], lambda report: report.update(format_version=2)
    )

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 2
    assert result["problems"] == []


@pytest.mark.parametrize("name", STORED_REPORTS)
def test_validate_accepts_a_comparison_report_of_format_version_3(
    run: Run, reports: dict[str, Path], name: str
) -> None:
    outcome, result = validate(run, reports[name])

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 3
    assert result["problems"] == []


@pytest.mark.parametrize("name", sorted(path.stem for path in STORED_4.glob("*.json")))
def test_validate_accepts_a_comparison_report_of_format_version_4(
    run: Run, name: str
) -> None:
    outcome, result = validate(run, STORED_4 / f"{name}.json")

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 4
    assert result["problems"] == []


@pytest.mark.parametrize("name", sorted(path.stem for path in STORED_5.glob("*.json")))
def test_validate_accepts_a_comparison_report_of_format_version_5(
    run: Run, name: str
) -> None:
    outcome, result = validate(run, STORED_5 / f"{name}.json")

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 5
    assert result["problems"] == []


def test_validate_accepts_a_comparison_report_of_format_version_6(
    run: Run, reports: dict[str, Path]
) -> None:
    document = json.loads(reports["comparison"].read_text())
    assert document["scope"] == "tracks"
    assert document["measurements"]["portions"]
    assert document["measurements"]["unmatched"]["a"]
    assert document["measurements"]["unmatched"]["b"]

    outcome, result = validate(run, reports["comparison"])

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 6
    assert result["problems"] == []


def test_validate_accepts_a_comparison_report_of_format_version_6_without_a_portion(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> None:
    # Tracks shorter than one 5 s window have no portion, and say why.
    sets = [
        make_set(
            lambda source, seed=seed: write_audio(
                source / "a.flac", signal(RATE, 2, 16, seed=seed), 16, "FLAC"
            )
        )
        for seed in (1, 2)
    ]
    comparison = run(
        "compare",
        sets[0] / "data/Album/a.flac",
        sets[1] / "data/Album/a.flac",
        "--json",
    )
    assert comparison.code == 0, comparison.err
    document = json.loads(comparison.out)
    assert document["measurements"]["portions"] == []
    assert document["measurements"]["absent"]["portions"]

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 6


@pytest.mark.parametrize(
    ("scope", "location"), [(None, ""), ("albums", "/scope"), ("Tracks", "/scope")]
)
def test_validate_requires_the_scope_of_a_comparison_report_of_format_version_6(
    run: Run, reports: dict[str, Path], tmp_path: Path, scope: str | None, location: str
) -> None:
    document = json.loads(reports["comparison"].read_text())
    if scope is None:
        del document["scope"]
    else:
        document["scope"] = scope

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert result["format_version"] == 6
    assert location in {problem["location"] for problem in result["problems"]}


def test_validate_refuses_a_scope_in_a_comparison_report_of_format_version_5(
    run: Run, tmp_path: Path
) -> None:
    document = json.loads((STORED_5 / "files.json").read_text())
    document["scope"] = "tracks"

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"


def test_validate_requires_evidence_set_in_a_comparison_report_of_version_1(
    run: Run, reports: dict[str, Path], tmp_path: Path
) -> None:
    document = edited(
        reports["comparison_v1"],
        lambda report: report["inputs"]["a"].pop("evidence_set"),
    )

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert "/inputs/a" in {problem["location"] for problem in result["problems"]}


def test_validate_rejects_omitted_in_a_comparison_report_of_version_1(
    run: Run, reports: dict[str, Path], tmp_path: Path
) -> None:
    document = edited(
        reports["comparison_v1"], lambda report: report.update(omitted=[])
    )

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert "" in {problem["location"] for problem in result["problems"]}


def test_validate_accepts_a_comparison_report_that_leaves_locations_out(
    run: Run, reports: dict[str, Path]
) -> None:
    document = json.loads(reports["comparison_omitted"].read_text())
    assert document["omitted"] == ["/inputs/a/evidence_set", "/inputs/b/evidence_set"]

    outcome, result = validate(run, reports["comparison_omitted"])

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 3


# Edits to a version 3 comparison Report that break the rule that each input's
# `evidence_set` is present exactly when `omitted` does not list it.
LOCATION_EDITS: dict[str, tuple[str, Callable[[Any], None], str]] = {
    "an evidence_set that is neither present nor omitted": (
        "comparison_v3",
        lambda report: report["inputs"]["a"].pop("evidence_set"),
        "/inputs/a",
    ),
    "an evidence_set that is present and omitted": (
        "comparison_v3",
        lambda report: report.update(omitted=["/inputs/b/evidence_set"]),
        "/inputs/b",
    ),
    "an evidence_set that is present when both are omitted": (
        "comparison_omitted",
        lambda report: report["inputs"]["a"].update(evidence_set="/Volumes/Archive"),
        "/inputs/a",
    ),
    "an evidence_set that is absent but no longer omitted": (
        "comparison_omitted",
        lambda report: report.update(omitted=["/inputs/a/evidence_set"]),
        "/inputs/b",
    ),
    "a Report without omitted": (
        "comparison_v3",
        lambda report: report.pop("omitted"),
        "",
    ),
    "an omitted pointer to another value": (
        "comparison_omitted",
        lambda report: report.update(omitted=["/inputs/a/path"]),
        "/omitted/0",
    ),
    "an omitted pointer that is repeated": (
        "comparison_omitted",
        lambda report: report.update(
            omitted=["/inputs/a/evidence_set", "/inputs/a/evidence_set"]
        ),
        "/omitted",
    ),
    "an omitted that is not a list": (
        "comparison_omitted",
        lambda report: report.update(omitted="/inputs/a/evidence_set"),
        "/omitted",
    ),
}


@pytest.mark.parametrize("name", LOCATION_EDITS)
def test_validate_finds_an_evidence_set_that_omitted_does_not_account_for_invalid(
    run: Run, reports: dict[str, Path], tmp_path: Path, name: str
) -> None:
    base, change, location = LOCATION_EDITS[name]
    document = edited(reports[base], change)

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert outcome.err == ""
    assert result["outcome"] == "invalid"
    assert result["format_version"] == 3
    assert location in {problem["location"] for problem in result["problems"]}


def test_validate_prints_each_problem_with_its_location(
    run: Run, reports: dict[str, Path], tmp_path: Path
) -> None:
    def change(report: Any) -> None:
        report["payload"][0]["outcome"] = "intact"
        report.pop("checked_at")

    path = save(tmp_path, edited(reports["verification"], change))

    outcome = run("validate", path)

    assert outcome.code == 1
    lines = outcome.out.splitlines()
    assert lines[0] == "Result: invalid"
    problems = [line for line in lines if line.startswith("  ")]
    assert any(line.startswith("  /payload/0/outcome: ") for line in problems)
    assert any(line.startswith("  (document): ") for line in problems)
    assert "Traceback" not in outcome.out + outcome.err


# The document that a malformed Report would be, as the file's bytes.
MALFORMED: dict[str, bytes] = {
    "text that is not JSON": b"this is not JSON",
    "a JSON text cut short": b'{"report_kind": "copyofa.verification",',
    "a byte order mark": b'\xef\xbb\xbf{"report_kind": 1}',
    "bytes that are not UTF-8": b'{"report_kind": "\xff\xfe"}',
    "NaN": b'{"report_kind": "copyofa.verification", "format_version": NaN}',
    "Infinity": b'{"report_kind": "copyofa.verification", "x": Infinity}',
    "minus Infinity": b'{"report_kind": "copyofa.verification", "x": -Infinity}',
    "a number too large for a float": b'{"x": 1e999}',
    "a number with too many digits": b'{"x": ' + b"9" * 6000 + b"}",
    "a repeated member name": b'{"report_kind": "a", "report_kind": "a"}',
    "a repeated member name in a nested object": b'{"x": [{"a": 1, "a": 1}]}',
    "an empty file": b"",
}


@pytest.mark.parametrize("name", MALFORMED)
def test_validate_finds_a_file_that_is_not_strict_json_invalid(
    run: Run, tmp_path: Path, name: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(MALFORMED[name])

    outcome, result = validate(run, path)

    assert outcome.code == 1
    assert outcome.err == ""
    assert result["outcome"] == "invalid"
    assert result["sha256"] == hashlib.sha256(MALFORMED[name]).hexdigest()
    assert "report_kind" not in result
    [problem] = result["problems"]
    assert problem["location"] == ""
    assert problem["message"].endswith(".")


# How deep the parser nests depends on the platform: Python 3.14 on Linux parses
# these, then finds no report_kind; elsewhere the parser gives up. Invalid either way.
NESTED: dict[str, bytes] = {
    "arrays": b"[" * 100_000 + b"]" * 100_000,
    "objects": b'{"x":' * 100_000 + b"1" + b"}" * 100_000,
}


@pytest.mark.parametrize("name", NESTED)
def test_validate_finds_a_document_nested_100_000_deep_invalid(
    run: Run, tmp_path: Path, name: str
) -> None:
    path = tmp_path / "nested.json"
    path.write_bytes(NESTED[name])

    outcome, result = validate(run, path)

    assert outcome.code == 1
    assert outcome.err == ""
    assert result["outcome"] == "invalid"
    assert result["problems"]
    for problem in result["problems"]:
        assert problem["location"] == ""
        assert problem["message"].endswith(".")


def test_validate_describes_a_file_that_is_not_strict_json_in_words(
    run: Run, tmp_path: Path
) -> None:
    messages = {}
    for name in ("an empty file", "a repeated member name", "NaN"):
        path = tmp_path / "bad.json"
        path.write_bytes(MALFORMED[name])
        messages[name] = validate(run, path)[1]["problems"][0]["message"]

    assert "empty" in messages["an empty file"]
    assert "repeats" in messages["a repeated member name"]
    assert "report_kind" in messages["a repeated member name"]
    assert "NaN" in messages["NaN"]


@pytest.mark.parametrize("depth", [900, 5000])
@pytest.mark.parametrize("field", ["copyofa_version", "surprise"])
def test_validate_never_fails_on_the_nesting_of_a_value(
    run: Run, reports: dict[str, Path], tmp_path: Path, depth: int, field: str
) -> None:
    document = edited(reports["verification"], lambda r: r.update({field: "NESTED"}))
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(document).replace('"NESTED"', "[" * depth + "]" * depth))

    outcome, result = validate(run, path)

    assert outcome.code == 1
    assert outcome.err == ""
    assert result["outcome"] == "invalid"


NOT_REPORTS: dict[str, Any] = {
    "a document that is not an object": [],
    "a string": "copyofa.verification",
    "a number": 1,
    "a boolean": True,
    "null": None,
}


@pytest.mark.parametrize("name", NOT_REPORTS)
def test_validate_finds_a_document_that_is_not_an_object_invalid(
    run: Run, tmp_path: Path, name: str
) -> None:
    outcome, result = validate(run, save(tmp_path, NOT_REPORTS[name]))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert [problem["location"] for problem in result["problems"]] == [""]
    assert "report_kind" not in result
    assert "format_version" not in result


KIND = {"report_kind": "copyofa.verification"}
HEADERS: dict[str, tuple[dict[str, Any], str, dict[str, Any]]] = {
    "without report_kind": ({"format_version": 1}, "", {"format_version": 1}),
    "without format_version": ({**KIND}, "", {**KIND}),
    "a report_kind that is not a string": (
        {"report_kind": 1, "format_version": 1},
        "/report_kind",
        {"format_version": 1},
    ),
    "a format_version of '2'": (
        {**KIND, "format_version": "2"},
        "/format_version",
        {**KIND},
    ),
    "a format_version of 0": ({**KIND, "format_version": 0}, "/format_version", KIND),
    "a negative format_version": (
        {**KIND, "format_version": -1},
        "/format_version",
        KIND,
    ),
    "a format_version of 1.0": (
        {**KIND, "format_version": 1.0},
        "/format_version",
        KIND,
    ),
    "a format_version that is a boolean": (
        {**KIND, "format_version": True},
        "/format_version",
        KIND,
    ),
    "a format_version that is null": (
        {**KIND, "format_version": None},
        "/format_version",
        KIND,
    ),
}


@pytest.mark.parametrize("name", HEADERS)
def test_validate_finds_a_report_without_a_usable_kind_or_version_invalid(
    run: Run, tmp_path: Path, name: str
) -> None:
    document, location, known = HEADERS[name]

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert location in {problem["location"] for problem in result["problems"]}
    found = {
        field: result[field]
        for field in ("report_kind", "format_version")
        if field in result
    }
    assert found == known


def test_validate_finds_an_unknown_kind_unsupported(run: Run, tmp_path: Path) -> None:
    document = {"report_kind": "copyofa.reconstruction", "format_version": 1}

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert outcome.err == ""
    assert result["outcome"] == "unsupported"
    assert result["report_kind"] == "copyofa.reconstruction"
    assert result["format_version"] == 1
    [problem] = result["problems"]
    assert problem["location"] == ""
    assert "copyofa.reconstruction" in problem["message"]


@pytest.mark.parametrize("kind", KINDS)
def test_validate_finds_a_format_version_it_has_no_schema_for_unsupported(
    run: Run, reports: dict[str, Path], tmp_path: Path, kind: str
) -> None:
    document = edited(reports[kind], lambda report: report.update(format_version=99))

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "unsupported"
    assert result["report_kind"] == KINDS[kind][0]
    assert result["format_version"] == 99
    [problem] = result["problems"]
    assert problem["location"] == ""
    assert "99" in problem["message"]


def test_validate_prints_an_unsupported_report_without_a_traceback(
    run: Run, tmp_path: Path
) -> None:
    path = save(tmp_path, {"report_kind": "x\ny", "format_version": 99})

    outcome = run("validate", path)

    assert outcome.code == 1
    assert outcome.out.startswith("Result: unsupported\n")
    assert "x\ny" not in outcome.out
    assert "Traceback" not in outcome.out + outcome.err


def test_validate_exits_1_for_a_missing_file(run: Run, tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    for options in ((), ("--json",)):
        outcome = run("validate", missing, *options)

        assert outcome.code == 1
        assert outcome.out == ""
        assert outcome.err == f"copyofa: {missing} does not exist.\n"


def test_validate_exits_1_for_a_directory(run: Run, tmp_path: Path) -> None:
    outcome = run("validate", tmp_path, "--json")

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.startswith(f"copyofa: {tmp_path} is a directory")
    assert "Traceback" not in outcome.err


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_validate_exits_1_for_a_named_pipe_without_waiting_for_it(
    run: Run, tmp_path: Path
) -> None:
    pipe = tmp_path / "pipe.json"
    os.mkfifo(pipe)

    outcome = run("validate", pipe)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err == f"copyofa: {pipe} is not a regular file.\n"


@requires_permissions
def test_validate_exits_1_for_a_file_it_cannot_read(
    run: Run, reports: dict[str, Path]
) -> None:
    path = reports["verification"]
    path.chmod(0)
    try:
        outcome = run("validate", path)
    finally:
        path.chmod(0o644)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.startswith(f"copyofa: {path} cannot be read: ")


@pytest.mark.parametrize(
    "arguments", [(), ("--json",), ("a.json", "b.json"), ("a.json", "--yaml")]
)
def test_validate_exits_2_on_invalid_arguments(
    run: Run, arguments: tuple[str, ...]
) -> None:
    outcome = run("validate", *arguments)

    assert outcome.code == 2
    assert outcome.out == ""


@pytest.mark.parametrize("options", [(), ("--json",)])
def test_validate_canceled_prints_nothing(
    run: Run,
    reports: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    options: tuple[str, ...],
) -> None:
    def interrupted(data: bytes) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(validator, "_parse", interrupted)

    outcome = run("validate", reports["verification"], *options)

    assert outcome.code == 130
    assert outcome.out == ""


@pytest.mark.parametrize("options", [(), ("--json",)])
def test_validate_reports_a_closed_stdout(run: Run, options: tuple[str, ...]) -> None:
    with closed_stdout():
        outcome = run("validate", STORED / "measured.json", *options)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err == "copyofa: stdout closed\n"


@pytest.mark.parametrize("valid", [True, False])
def test_validate_changes_nothing(
    run: Run, reports: dict[str, Path], tmp_path: Path, valid: bool
) -> None:
    if not valid:
        reports["verification"].write_text("{")
    before = snapshot(tmp_path)

    run("validate", reports["verification"])
    run("validate", reports["verification"], "--json")

    assert snapshot(tmp_path) == before


def test_validate_accepts_an_inspection_report_of_format_version_1(
    run: Run, reports: dict[str, Path], tmp_path: Path
) -> None:
    document = edited(
        reports["inspection"], lambda report: report.update(format_version=1)
    )

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 1


def test_validate_accepts_a_stored_inspection_report_of_format_version_2(
    run: Run,
) -> None:
    path = Path(__file__).parent / "reports/inspection-2/acquired_set.json"

    outcome, result = validate(run, path)

    assert outcome.code == 0, outcome.err
    assert result["outcome"] == "valid"
    assert result["format_version"] == 2


DISC_EDITS: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "disc at version 1": (lambda report: report.update(format_version=1), ""),
    "both a reason and tracks": (
        lambda report: report["disc"].update(reason="edited"),
        "/disc",
    ),
    "an interpreted track without its Audio Digest": (
        lambda report: report["disc"]["tracks"][0].pop("audio_digest"),
        "/disc/tracks/0",
    ),
    "a failed track with an Audio Digest": (
        lambda report: report["disc"]["tracks"][0].update(
            outcome="failed", reason="edited"
        ),
        "/disc/tracks/0",
    ),
    "an Audio Digest that is not of a CD": (
        lambda report: report["disc"]["tracks"][0].update(
            recorded_audio_digest="pcm1:48000:2:16:" + "0" * 64
        ),
        "/disc/tracks/0/recorded_audio_digest",
    ),
    "an error range of an unknown state": (
        lambda report: report["disc"]["tracks"][0].update(
            error_ranges=[{"offset_frames": 0, "frame_count": 1, "state": "skipped"}]
        ),
        "/disc/tracks/0/error_ranges/0/state",
    ),
    "an empty error range": (
        lambda report: report["disc"]["tracks"][0].update(
            error_ranges=[{"offset_frames": 0, "frame_count": 0, "state": "not_read"}]
        ),
        "/disc/tracks/0/error_ranges/0/frame_count",
    ),
    "error ranges at version 2": (
        lambda report: report.update(format_version=2),
        "/disc/tracks/0",
    ),
}


@pytest.mark.parametrize("name", DISC_EDITS)
def test_validate_checks_the_disc_of_an_inspection_report(
    run: Run, acquired_set: Path, tmp_path: Path, name: str
) -> None:
    change, location = DISC_EDITS[name]
    report = run("inspect", acquired_set, "--json")
    assert report.code == 0, report.err
    document = json.loads(report.out)
    change(document)

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert location in {problem["location"] for problem in result["problems"]}


def as_failed_without_range(entry: dict[str, Any]) -> None:
    """Turn an interpreted track input into a failed one that has no range."""
    for key in [*FINDINGS, "track"]:
        entry.pop(key, None)
    entry.update(outcome="failed", reason="edited", track={"number": 1})


# What an interpreted input holds beyond a failed one.
FINDINGS = (
    "format",
    "encoding",
    "sample_rate",
    "channels",
    "bits_per_sample",
    "frames",
    "audio_digest",
    "peak",
    "leading_silence_frames",
    "trailing_silence_frames",
)


# jsonschema reports a value a `false` subschema forbids at the object holding it.
TRACK_EDITS: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "a track at version 2": (
        lambda report: report.update(format_version=2),
        "/inputs/a",
    ),
    "a FLAC MD5 signature for a track": (
        lambda report: report["inputs"]["a"].update(flac_md5_signature="matching"),
        "/inputs/a",
    ),
    "an interpreted track without its range": (
        lambda report: report["inputs"]["a"]["track"].pop("first_frame"),
        "/inputs/a/track",
    ),
    "a failed track without its range": (
        lambda report: as_failed_without_range(report["inputs"]["a"]),
        "/inputs/a/track",
    ),
    "a File Digest without the image's path": (
        lambda report: report["inputs"]["a"].pop("path"),
        "/inputs/a",
    ),
    "neither a path nor a track": (
        lambda report: report["inputs"]["b"].pop("path"),
        "/inputs/b",
    ),
}


@pytest.mark.parametrize("version", [3, 4, 5, 6])
@pytest.mark.parametrize("name", TRACK_EDITS)
def test_validate_checks_the_track_input_of_a_comparison_report(
    run: Run, acquired_set: Path, tmp_path: Path, name: str, version: int
) -> None:
    change, location = TRACK_EDITS[name]
    if version == 3:
        document = json.loads((STORED / "acquired_track.json").read_text())
    elif version == 4:
        document = json.loads((STORED_4 / "acquired_track.json").read_text())
    elif version == 5:
        document = json.loads((STORED_5 / "acquired_track.json").read_text())
    else:
        report = run(
            "compare",
            acquired_set,
            acquired_set / "data/disc.scram.flac",
            "--track-a",
            "1",
            "--json",
        )
        assert report.code == 0, report.err
        document = json.loads(report.out)
    assert document["format_version"] == version
    intact, unedited = validate(run, save(tmp_path, document, "intact.json"))
    assert intact.code == 0, intact.err
    assert unedited["outcome"] == "valid"
    change(document)

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert location in {problem["location"] for problem in result["problems"]}


ERROR_RANGE_EDITS: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "error ranges at version 4": (
        lambda report: report.update(format_version=4),
        "/inputs/a/track",
    ),
    "an error range of an unknown state": (
        lambda report: report["inputs"]["a"]["track"]["error_ranges"][0].update(
            state="skipped"
        ),
        "/inputs/a/track/error_ranges/0/state",
    ),
    "an error range without its offset": (
        lambda report: report["inputs"]["a"]["track"]["error_ranges"][0].pop(
            "offset_frames"
        ),
        "/inputs/a/track/error_ranges/0",
    ),
    "an empty error range": (
        lambda report: report["inputs"]["a"]["track"]["error_ranges"][0].update(
            frame_count=0
        ),
        "/inputs/a/track/error_ranges/0/frame_count",
    ),
}


@pytest.mark.parametrize("name", ERROR_RANGE_EDITS)
def test_validate_checks_the_error_ranges_of_a_track_input(
    run: Run, damaged_set: Path, tmp_path: Path, name: str
) -> None:
    change, location = ERROR_RANGE_EDITS[name]
    report = run(
        "compare",
        damaged_set,
        damaged_set / "data/disc.scram.flac",
        "--track-a",
        "2",
        "--json",
    )
    assert report.code == 0, report.err
    document = json.loads(report.out)
    assert document["format_version"] == 6
    assert document["inputs"]["a"]["track"]["error_ranges"]
    change(document)

    outcome, result = validate(run, save(tmp_path, document))

    assert outcome.code == 1
    assert result["outcome"] == "invalid"
    assert location in {problem["location"] for problem in result["problems"]}
