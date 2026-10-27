from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from conftest import (
    RATE,
    closed_stdout,
    run_without_stdout,
    signal,
    snapshot,
    write_audio,
)

import copyofa
from copyofa import validator, viewer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from conftest import Run

    MakeSet = Callable[[Callable[[Path], None]], Path]

CSP = "default-src 'none'; style-src 'unsafe-inline'"
# Elements and attributes that would make a page load something or run something.
ACTIVE_TAGS = {"script", "link", "img", "iframe", "a", "object", "embed", "form"}
ACTIVE_ATTRIBUTES = {"href", "src", "action", "srcset", "data"}


class Page(HTMLParser):
    """A page parsed into its tags, its text nodes and its tables."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.nodes: list[str] = []
        self.title = ""
        self.tables: dict[str, list[list[str]]] = {}
        self._in_title = False
        self._heading: list[str] | None = None
        self._last_heading = ""
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.feed(text)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3"):
            self._heading = []
        elif tag == "table":
            self._rows = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3"):
            assert self._heading is not None
            self._last_heading = "".join(self._heading)
            self._heading = None
        elif tag == "table":
            assert self._last_heading not in self.tables
            self.tables[self._last_heading] = self._rows
        elif tag == "tr":
            assert self._row is not None
            self._rows.append(self._row)
            self._row = None
        elif tag in ("td", "th"):
            assert self._row is not None
            assert self._cell is not None
            self._row.append("\n".join(self._cell))
            self._cell = None

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        self.nodes.append(text)
        if self._in_title:
            self.title += text
        if self._heading is not None:
            self._heading.append(text)
        if self._cell is not None:
            self._cell.append(text)

    def row(self, heading: str, label: str) -> list[str]:
        """Return the cells after the label of the one row of a table that has it."""
        rows = [row[1:] for row in self.tables[heading] if row[0] == label]
        assert len(rows) == 1, (heading, label)
        return rows[0]

    def meta(self, **attributes: str) -> list[dict[str, str | None]]:
        return [
            found
            for tag, found in self.tags
            if tag == "meta"
            and all(found.get(name) == value for name, value in attributes.items())
        ]


# Version 3 comparison Reports that compare 0.6.0.dev0 printed, one per case, kept as
# they were so the page keeps rendering versions 1 to 3: `measured` (2.5 s, B is A at
# half amplitude 1234 frames later, so the last window is short), `lossy` (A FLAC, B
# MP3), `identical`, `silent_channel`, `silent_track`, `silent_window`, `mono`,
# `not_interpreted`, `not_inspected`, `locations_omitted` (compared with
# --omit-locations) and `acquired_track` (A is track 2 of an acquired set).
REPORTS = Path(__file__).parent / "reports" / "comparison-3"
CASES = sorted(path.stem for path in REPORTS.glob("*.json"))


@pytest.fixture
def report_of(tmp_path: Path) -> Callable[[str], tuple[Path, dict[str, Any]]]:
    """Copy a stored version 3 Report into the test's directory; return it."""

    def _report_of(name: str) -> tuple[Path, dict[str, Any]]:
        path = tmp_path / f"{name}.json"
        shutil.copyfile(REPORTS / f"{name}.json", path)
        return path, json.loads(path.read_text(encoding="utf-8"))

    return _report_of


def test_every_case_is_stored() -> None:
    assert CASES == [
        "acquired_track",
        "identical",
        "locations_omitted",
        "lossy",
        "measured",
        "mono",
        "not_inspected",
        "not_interpreted",
        "silent_channel",
        "silent_track",
        "silent_window",
    ]


def _version_4_signals(name: str) -> tuple[np.ndarray, np.ndarray]:
    """Return tracks A and B of a version 4 case, as write_audio takes them."""
    if name == "portions":
        # A holds 12 s that B holds after 1 s of digital silence, then 2 s that B does
        # not hold. B then holds 3 s that A does not, then a copy of 6 s of the shared
        # audio with noise added about 24 dB below it: an alternate portion.
        shared = signal(12 * RATE, 2, 16, seed=11) >> 2
        only_a = signal(2 * RATE, 2, 16, seed=12) >> 2
        only_b = signal(3 * RATE, 2, 16, seed=13) >> 2
        hiss = signal(6 * RATE, 2, 16, seed=14) >> 6
        silence = np.zeros((RATE, 2), np.int32)
        noisy = shared[4 * RATE : 10 * RATE] + hiss
        return np.vstack([shared, only_a]), np.vstack([silence, shared, only_b, noisy])
    if name == "no_portion":
        return signal(6 * RATE, 2, 16, seed=21), signal(6 * RATE, 2, 16, seed=22)
    if name == "identical":
        samples = signal(6 * RATE, 2, 16, seed=23)
        return samples, samples
    assert name == "mono"
    stereo = signal(6 * RATE, 2, 16, seed=24) >> 1
    return stereo, stereo.sum(axis=1, keepdims=True, dtype=np.int32) >> 1


VERSION_4_CASES = ["portions", "no_portion", "identical", "mono"]
"""Version 4 Reports that the tests have compare print: `portions` (a primary and an
alternate portion, and unmatched audio in both tracks, digitally silent and not),
`no_portion` (unrelated tracks), `identical`, and `mono` (A stereo, B its mono
downmix, so a portion has no channels)."""


@pytest.fixture
def version_4(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> Callable[[str], tuple[Path, dict[str, Any]]]:
    """Have compare print a version 4 Report of a case; return it."""

    def _version_4(name: str) -> tuple[Path, dict[str, Any]]:
        a, b = _version_4_signals(name)
        first = make_set(lambda source: write_audio(source / "a.flac", a, 16, "FLAC"))
        second = make_set(lambda source: write_audio(source / "b.flac", b, 16, "FLAC"))
        outcome = run(
            "compare",
            first / "data/Album/a.flac",
            second / "data/Album/b.flac",
            "--json",
        )
        assert outcome.code == 0, outcome.err
        path = tmp_path / f"{name}-4.json"
        path.write_text(outcome.out, encoding="utf-8")
        report = json.loads(outcome.out)
        assert report["format_version"] == 4
        return path, report

    return _version_4


@pytest.fixture(params=[*CASES, *(f"version 4: {name}" for name in VERSION_4_CASES)])
def case(
    request: pytest.FixtureRequest,
    report_of: Callable[[str], tuple[Path, dict[str, Any]]],
    version_4: Callable[[str], tuple[Path, dict[str, Any]]],
) -> tuple[Path, dict[str, Any]]:
    name = request.param
    if name.startswith("version 4: "):
        return version_4(name.removeprefix("version 4: "))
    return report_of(name)


def view(run: Run, path: Path) -> Page:
    outcome = run("view", path)
    assert outcome.code == 0, outcome.err
    assert outcome.err == ""
    return Page(outcome.out)


def leaves(value: Any, path: tuple[str | int, ...] = ()) -> Iterator[tuple[Any, Any]]:
    """Yield the path and the value of every scalar of a JSON document."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, (*path, index))
    else:
        yield path, value


def number(value: Any) -> str:
    return json.dumps(value)


def shown(value: Any) -> str:
    """Return a value as a page shows it: a string as it is, else as JSON writes it."""
    return value if isinstance(value, str) else number(value)


def edit(path: Path, change: Callable[[dict[str, Any]], None]) -> Path:
    """Save a copy of a Report with a change, in the JSON a Report is printed as."""
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    edited = path.with_name(f"edited-{path.name}")
    # ensure_ascii escapes a lone surrogate, as `\udc80`, so the file is UTF-8.
    edited.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return edited


def test_view_holds_every_value_of_the_report(
    run: Run, case: tuple[Path, dict[str, Any]]
) -> None:
    path, report = case

    page = view(run, path)

    nodes = set(page.nodes)
    text = "\n".join(page.nodes)
    for where, value in leaves(report):
        if "peak" in where:
            continue
        if isinstance(value, str):
            assert value in text, where
        else:
            assert number(value) in nodes, where
    for entry in report["inputs"].values():
        if "peak" in entry:
            assert ", ".join(number(value) for value in entry["peak"]) in nodes


def test_view_holds_the_limitations_word_for_word(
    run: Run, case: tuple[Path, dict[str, Any]]
) -> None:
    path, report = case

    page = view(run, path)

    assert report["limitations"]
    for limitation in report["limitations"]:
        assert limitation in page.nodes
    for entry in report["inputs"].values():
        for limitation in entry.get("limitations", []):
            assert limitation in page.nodes


def test_view_ties_the_page_to_its_report(
    run: Run, case: tuple[Path, dict[str, Any]]
) -> None:
    path, report = case

    page = view(run, path)

    assert hashlib.sha256(path.read_bytes()).hexdigest() in page.nodes
    assert report["report_kind"] in page.nodes
    assert str(report["format_version"]) in page.nodes
    assert copyofa.__version__ in page.nodes


def test_view_tells_the_version_that_made_the_page_from_the_reports(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("measured")
    older = edit(path, lambda report: report.update(copyofa_version="0.0.1"))

    page = view(run, older)

    assert "0.0.1" in page.nodes
    assert copyofa.__version__ in page.nodes
    assert hashlib.sha256(older.read_bytes()).hexdigest() in page.nodes


def test_view_is_self_contained_and_inert(
    run: Run, case: tuple[Path, dict[str, Any]]
) -> None:
    path, _ = case

    page = view(run, path)

    assert page.text.startswith("<!DOCTYPE html>")
    assert [attributes["charset"] for attributes in page.meta(charset="utf-8")] == [
        "utf-8"
    ]
    csp = page.meta(**{"http-equiv": "Content-Security-Policy"})
    assert [attributes["content"] for attributes in csp] == [CSP]
    assert "<script" not in page.text.lower()
    assert "://" not in page.text
    tags = {tag for tag, _ in page.tags}
    assert "style" in tags
    assert not tags & ACTIVE_TAGS
    assert not {name for _, attributes in page.tags for name in attributes} & (
        ACTIVE_ATTRIBUTES
    )
    assert not any(
        name.startswith("on") for _, attributes in page.tags for name in attributes
    )
    assert "<head>" in page.text
    assert page.title


def test_view_names_both_tracks_in_the_title(
    run: Run, case: tuple[Path, dict[str, Any]]
) -> None:
    path, report = case

    page = view(run, path)

    for entry in report["inputs"].values():
        assert entry["path"] in page.title
        if "track" in entry:
            assert f"track {entry['track']['number']} of {entry['path']}" in page.title


def test_view_shows_the_measurements(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("measured")
    measurements = report["measurements"]
    offset, overlap = measurements["offset"], measurements["overlap"]

    page = view(run, path)

    assert page.row("Alignment", "Offset (frames)") == [str(offset["frames"])]
    assert page.row("Alignment", "Offset (seconds)") == [number(offset["seconds"])]
    for label, key in (
        ("Start frame", "start_frame"),
        ("Frames", "frames"),
        ("Fraction of the track", "fraction"),
    ):
        assert page.row("Overlap", label) == [
            number(overlap["a"][key]),
            number(overlap["b"][key]),
        ]
    series = [("Downmix", measurements["downmix"])] + [
        (f"Channel {n}", values) for n, values in enumerate(measurements["channels"], 1)
    ]
    assert len(series) == 3
    assert page.tables["Values"][0] == ["", *(name for name, _ in series)]
    for label, key in (
        ("Correlation", "correlation"),
        ("Gain (dB)", "gain_db"),
        ("Residual (dB)", "residual_db"),
    ):
        assert page.row("Values", label) == [
            number(values[key]) for _, values in series
        ]
    for name, values in series:
        rows = page.tables[f"Residual windows: {name}"][1:]
        assert len(rows) == 3
        assert rows == [
            [
                str(window["start_frame"]),
                str(window["frames"]),
                number(window["residual_db"]),
            ]
            for window in values["residual_windows"]
        ]


def test_view_shows_the_properties_and_digests_of_each_input(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("lossy")
    a, b = report["inputs"].values()

    page = view(run, path)

    for label, key in (
        ("Evidence Set location", "evidence_set"),
        ("Path in the Evidence Set", "path"),
        ("Outcome", "outcome"),
        ("Format", "format"),
        ("Encoding", "encoding"),
        ("Sample rate (Hz)", "sample_rate"),
        ("Channels", "channels"),
        ("Frames", "frames"),
        ("Expected File Digest", "expected_digest"),
        ("Observed File Digest", "observed_digest"),
        ("Leading silence (frames)", "leading_silence_frames"),
        ("Trailing silence (frames)", "trailing_silence_frames"),
    ):
        assert page.row("Inputs", label) == [shown(a[key]), shown(b[key])], label
    assert page.row("Inputs", "Audio Digest")[0] == a["audio_digest"]
    assert "audio_digest" not in b
    assert "absent" in page.row("Inputs", "Audio Digest")[1]
    assert page.row("Inputs", "Bits per sample")[0] == str(a["bits_per_sample"])
    assert page.row("Inputs", "FLAC MD5 signature")[0] == a["flac_md5_signature"]
    assert page.row("Inputs", "Peak of each channel") == [
        ", ".join(number(value) for value in a["peak"]),
        ", ".join(number(value) for value in b["peak"]),
    ]
    baseline = a["integrity_baseline"]
    assert (
        page.row("Inputs", "Integrity Baseline manifest SHA-256")[0]
        == (baseline["manifest_sha256"])
    )
    assert page.row("Inputs", "Integrity Baseline usable")[0] == "true"
    assert page.row("Inputs", "Limitations")[1] == "\n".join(b["limitations"])
    seconds = a["frames"] / a["sample_rate"]
    assert (
        f"{int(seconds // 60)}:{int(seconds % 60):02}"
        in page.row("Inputs", "Duration (computed from frames and sample rate)")[0]
    )
    method = report["method"]
    assert page.row("Method", "Decoder version") == [method["decoder_version"]]
    assert page.row("Method", "Common sample rate (Hz)") == [
        str(method["common_sample_rate"])
    ]


def test_view_shows_each_location_that_the_report_leaves_out_as_left_out(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("locations_omitted")
    assert report["omitted"] == ["/inputs/a/evidence_set", "/inputs/b/evidence_set"]

    page = view(run, path)

    assert page.row("Inputs", "Evidence Set location") == ["left out", "left out"]
    assert page.row("Report", "Left out of the Report (JSON Pointers)") == [
        "/inputs/a/evidence_set\n/inputs/b/evidence_set"
    ]
    assert page.row("Report", "Format version") == ["3"]
    assert page.row("Inputs", "Path in the Evidence Set") == [
        entry["path"] for entry in report["inputs"].values()
    ]
    assert "/Volumes/Archive" not in page.text


def test_view_shows_that_the_report_leaves_nothing_out(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("measured")
    assert report["omitted"] == []

    page = view(run, path)

    assert page.row("Report", "Left out of the Report (JSON Pointers)") == ["none"]
    assert page.row("Inputs", "Evidence Set location") == [
        entry["evidence_set"] for entry in report["inputs"].values()
    ]


def test_view_shows_a_comparison_report_of_format_version_1(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("measured")

    def as_version_1(document: dict[str, Any]) -> None:
        del document["omitted"]
        document["format_version"] = 1

    older = edit(path, as_version_1)
    assert validator.validate(str(older)).result["format_version"] == 1

    page = view(run, older)

    assert page.row("Report", "Format version") == ["1"]
    assert "absent" in page.row("Report", "Left out of the Report (JSON Pointers)")[0]
    assert page.row("Inputs", "Evidence Set location") == [
        entry["evidence_set"] for entry in report["inputs"].values()
    ]
    assert page.row("Alignment", "Offset (frames)") == [
        str(report["measurements"]["offset"]["frames"])
    ]


def test_view_shows_a_long_track_as_hours(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("measured")
    frames = (3 * 3600 + 25 * 60 + 7) * RATE + RATE // 2
    edited = edit(path, lambda report: report["inputs"]["a"].update(frames=frames))

    page = view(run, edited)

    assert page.row("Inputs", "Frames")[0] == str(frames)
    duration = "Duration (computed from frames and sample rate)"
    assert page.row("Inputs", duration)[0] == "3:25:07.500"


def test_view_shows_a_series_without_windows(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("measured")
    edited = edit(
        path,
        lambda report: report["measurements"]["downmix"].update(residual_windows=[]),
    )

    page = view(run, edited)

    assert page.row("Values", "Residual windows")[0].startswith("0 ")
    assert "Residual windows: Downmix" not in page.tables
    assert "Residual windows: Channel 1" in page.tables


def test_view_shows_identical_audio(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("identical")

    page = view(run, path)

    assert report["measurements"]["identical_audio"] is True
    assert page.row("Alignment", "Identical audio") == ["true"]
    for reason in report["measurements"]["downmix"]["absent"].values():
        assert any(reason in node for node in page.nodes)


def test_view_shows_why_each_value_is_absent(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    for name in ("silent_track", "silent_channel"):
        path, report = report_of(name)

        page = view(run, path)

        reasons = [value for where, value in leaves(report) if "absent" in where]
        assert reasons, name
        for reason in reasons:
            assert any(reason in node for node in page.nodes), (name, reason)
        if name == "silent_track":
            assert "absent" in page.row("Alignment", "Offset")[0]


def test_view_shows_why_a_window_has_no_residual(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("silent_window")
    windows = report["measurements"]["downmix"]["residual_windows"]
    absent = [window for window in windows if "absent" in window]
    assert absent

    page = view(run, path)

    rows = page.tables["Residual windows: Downmix"][1:]
    for window in absent:
        row = next(row for row in rows if row[0] == str(window["start_frame"]))
        assert window["absent"]["residual_db"] in row[2]


def test_view_shows_why_channels_are_absent(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("mono")
    reason = report["measurements"]["absent"]["channels"]

    page = view(run, path)

    assert "Channel 1" not in page.tables["Values"][0]
    assert any(reason in node for node in page.nodes)


@pytest.mark.parametrize("name", ["not_interpreted", "not_inspected"])
def test_view_says_when_the_tracks_were_not_measured(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]], name: str
) -> None:
    path, report = report_of(name)
    assert "measurements" not in report

    page = view(run, path)

    assert "not measured" in " ".join(page.nodes)
    assert "Values" not in page.tables
    assert page.row("Inputs", "Reason")[1] == report["inputs"]["b"]["reason"]
    assert page.row("Inputs", "Outcome")[1] == report["inputs"]["b"]["outcome"]
    assert "absent" in page.row("Method", "Common sample rate (Hz)")[0]


def test_view_shows_text_of_the_report_as_text(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("identical")
    # Three texts put into the Report by hand: a path with markup and an entity, a
    # path the Report records as `\udc80` (a byte that is not valid UTF-8), and a
    # limitation with markup.
    name = '<script>alert("1")&amp;\'.flac'
    surrogate = "data/Album/caf\udc80.flac"
    markup = "<b>bold</b> & <script>x</script>"

    def change(report: dict[str, Any]) -> None:
        report["inputs"]["a"]["path"] = f"data/Album/{name}"
        report["inputs"]["b"]["path"] = surrogate
        report["limitations"].append(markup)

    edited = edit(path, change)
    assert validator.validate(str(edited)).result["outcome"] == validator.VALID

    page = view(run, edited)

    assert f"data/Album/{name}" in page.nodes
    assert surrogate not in "".join(page.nodes)
    assert "data/Album/caf\\udc80.flac" in page.nodes
    assert markup in page.nodes
    assert "<script" not in page.text.lower()
    assert "&lt;script&gt;" in page.text
    assert {tag for tag, _ in page.tags} & {"script", "b"} == set()
    assert f"data/Album/{name}" in page.title
    assert "data/Album/caf\\udc80.flac" in page.title


def test_render_returns_text_that_encodes_as_utf8() -> None:
    report = {
        "report_kind": "copyofa.comparison",
        "format_version": 1,
        "copyofa_version": "x\udc83",
        "compared_at": "2026-10-25T18:30:00Z",
        "inputs": {
            name: {
                "evidence_set": "/Sets/\udc80",
                "integrity_baseline": {"usable": True, "problems": ["\udc81"]},
                "path": f"data/\udc82{name}.flac",
                "outcome": "not_inspected",
                "reason": "\u202e\x00",
            }
            for name in "ab"
        },
        "method": {
            "decoder": "libsndfile",
            "decoder_version": "1",
            "resampler": "libsoxr",
            "resampler_version": "1",
            "resampler_quality": "VHQ",
            "alignment": "downmix_cross_correlation",
        },
        "limitations": ["\udc84"],
    }

    page = viewer.render(report, "0" * 64)

    page.encode("utf-8")
    assert "\\udc80" in page
    assert "\\u202e" in page
    assert "\\x00" in page


def test_view_writes_utf8_whatever_the_locale(
    report_of: Callable[[str], tuple[Path, dict[str, Any]]],
) -> None:
    path, _ = report_of("not_interpreted")
    edited = edit(
        path, lambda report: report["inputs"]["a"].update(path="data/Été \u2713.flac")
    )
    command = "import sys; from copyofa.cli import main; sys.exit(main(sys.argv[1:]))"

    result = subprocess.run(
        [sys.executable, "-c", command, "view", edited],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "latin-1"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "data/Été \u2713.flac".encode() in result.stdout
    Page(result.stdout.decode("utf-8", errors="strict"))


def test_view_reports_a_closed_stdout(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("lossy")

    with closed_stdout():
        outcome = run("view", path)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err == "copyofa: stdout closed\n"


@pytest.mark.parametrize("command", [["view"], ["validate"], ["validate", "--json"]])
def test_a_closed_stdout_ends_the_process_with_one_line(
    report_of: Callable[[str], tuple[Path, dict[str, Any]]], command: list[str]
) -> None:
    path, _ = report_of("lossy")
    main = "import sys; from copyofa.cli import main; sys.exit(main(sys.argv[1:]))"
    reader, writer = os.pipe()
    os.close(reader)

    try:
        result = subprocess.run(
            [sys.executable, "-c", main, *command, path],
            stdout=writer,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        os.close(writer)

    assert result.returncode == 1
    assert result.stderr == b"copyofa: stdout closed\n"


@pytest.mark.parametrize("command", [["view"], ["validate"], ["validate", "--json"]])
def test_a_stdout_closed_before_the_start_ends_the_process_with_one_line(
    report_of: Callable[[str], tuple[Path, dict[str, Any]]], command: list[str]
) -> None:
    path, _ = report_of("lossy")

    result = run_without_stdout(*command, path)

    assert result.returncode == 1
    assert result.stderr == b"copyofa: stdout closed\n"


def test_view_refuses_an_invalid_report(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("measured")
    edited = edit(path, lambda report: report.update(copyofa_version=5))

    outcome = run("view", edited)

    assert outcome.code == 1
    assert outcome.out == ""
    assert "not a valid" in outcome.err
    assert "/copyofa_version" in outcome.err
    assert "Traceback" not in outcome.err


def test_view_refuses_text_that_is_not_json(run: Run, tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{", encoding="utf-8")

    outcome = run("view", path)

    assert outcome.code == 1
    assert outcome.out == ""
    assert "not a valid" in outcome.err
    assert "Traceback" not in outcome.err


def test_view_refuses_an_unsupported_report(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, _ = report_of("measured")
    edited = edit(path, lambda report: report.update(format_version=99))

    outcome = run("view", edited)

    assert outcome.code == 1
    assert outcome.out == ""
    assert "not a supported" in outcome.err
    assert "99" in outcome.err


def test_view_refuses_a_valid_report_of_another_kind(
    run: Run, make_set: MakeSet, tmp_path: Path
) -> None:
    evidence_set = make_set(
        lambda source: write_audio(source / "a.flac", signal(1000, 2, 16), 16, "FLAC")
    )
    inspection = run("inspect", evidence_set, "--json")
    assert inspection.code == 0, inspection.err
    path = tmp_path / "inspection.json"
    path.write_text(inspection.out, encoding="utf-8")
    assert validator.validate(str(path)).result["outcome"] == validator.VALID

    outcome = run("view", path)

    assert outcome.code == 1
    assert outcome.out == ""
    assert "comparison Reports only" in outcome.err


def test_view_refuses_a_file_it_cannot_read(run: Run, tmp_path: Path) -> None:
    for unreadable in (tmp_path / "missing.json", tmp_path):
        outcome = run("view", unreadable)

        assert outcome.code == 1
        assert outcome.out == ""
        assert outcome.err.startswith("copyofa: ")
        assert "Traceback" not in outcome.err


@pytest.mark.parametrize(
    "arguments", [(), ("a.json", "b.json"), ("report.json", "--json")]
)
def test_view_exits_2_on_invalid_arguments(
    run: Run, arguments: tuple[str, ...]
) -> None:
    outcome = run("view", *arguments)

    assert outcome.code == 2
    assert outcome.out == ""


@pytest.mark.parametrize("interrupted", [(validator, "_parse"), (viewer, "render")])
def test_view_canceled_prints_nothing(
    run: Run,
    report_of: Callable[[str], tuple[Path, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    interrupted: tuple[Any, str],
) -> None:
    path, _ = report_of("not_interpreted")

    def cancel(*arguments: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(*interrupted, cancel)

    outcome = run("view", path)

    assert outcome.code == 130
    assert outcome.out == ""


@pytest.mark.parametrize("valid", [True, False])
def test_view_changes_nothing(
    run: Run,
    report_of: Callable[[str], tuple[Path, dict[str, Any]]],
    tmp_path: Path,
    valid: bool,
) -> None:
    path, _ = report_of("not_interpreted")
    if not valid:
        path.write_text("{", encoding="utf-8")
    before = snapshot(tmp_path)

    outcome = run("view", path)

    assert outcome.code == (0 if valid else 1)
    assert snapshot(tmp_path) == before


def test_view_shows_the_track_of_each_input(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("acquired_track")
    track = report["inputs"]["a"]["track"]

    page = view(run, path)

    assert page.row("Inputs", "Track of the acquired disc") == [
        str(track["number"]),
        "absent",
    ]
    assert page.row("Inputs", "First frame of the track in the image") == [
        str(track["first_frame"]),
        "absent",
    ]
    assert page.row("Inputs", "Frames of the track in the image") == [
        str(track["frame_count"]),
        "absent",
    ]
    assert page.row("Inputs", "Path in the Evidence Set")[0] == "data/disc.scram.flac"


def test_view_shows_a_comparison_report_of_format_version_2(
    run: Run, report_of: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = report_of("measured")
    older = edit(path, lambda document: document.update(format_version=2))
    assert validator.validate(str(older)).result["outcome"] == "valid"

    page = view(run, older)

    assert page.row("Report", "Format version") == ["2"]
    assert page.row("Inputs", "Path in the Evidence Set") == [
        entry["path"] for entry in report["inputs"].values()
    ]


def test_view_shows_the_parameters_of_the_method(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = version_4("identical")
    parameters = report["method"]["parameters"]

    page = view(run, path)

    assert page.row("Method", "Alignment") == ["windowed_portions"]
    assert page.tables["Parameters"][1:] == [
        [name, shown(value)] for name, value in parameters.items()
    ]


def seconds(extent: dict[str, Any]) -> str:
    start, frames = extent["start_frame"], extent["frames"]
    return f"{start / RATE:.3f}-{(start + frames) / RATE:.3f}"


def test_view_shows_each_portion(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = version_4("portions")
    portions = report["measurements"]["portions"]
    assert [portion["rank"] for portion in portions] == ["primary", "alternate"]

    page = view(run, path)

    assert page.row("Overview", "Portions") == ["2 portions, listed below"]
    for index, portion in enumerate(portions, 1):
        downmix = portion["downmix"]
        assert page.row("Portions", str(index)) == [
            portion["rank"],
            str(portion["a"]["start_frame"]),
            str(portion["a"]["frames"]),
            seconds(portion["a"]),
            str(portion["b"]["start_frame"]),
            str(portion["b"]["frames"]),
            seconds(portion["b"]),
            str(portion["offset"]["frames"]),
            number(portion["offset"]["seconds"]),
            cell(portion, "block_gain_residual_db"),
            cell(downmix, "correlation"),
            cell(downmix, "gain_db"),
            cell(downmix, "residual_db"),
        ]
        heading = f"Portion {index} ({portion['rank']})"
        series = [("Downmix", downmix)] + [
            (f"Channel {channel}", values)
            for channel, values in enumerate(portion["channels"], 1)
        ]
        assert page.tables[f"{heading}: values"][0] == ["", *(n for n, _ in series)]
        assert page.row(f"{heading}: values", "Residual (dB)") == [
            cell(values, "residual_db") for _, values in series
        ]
        for name, values in series:
            if "residual_windows" not in values:
                continue
            rows = page.tables[f"{heading}: residual windows, {name}"]
            assert rows[0][0] == "Start frame (from the start of the portion)"
            assert rows[1:] == [
                [
                    str(window["start_frame"]),
                    str(window["frames"]),
                    cell(window, "residual_db"),
                ]
                for window in values["residual_windows"]
            ]


def cell(values: dict[str, Any], key: str) -> str:
    """Return the cell of a value: the value, or its absence with its reason."""
    if key in values:
        return number(values[key])
    return f"absent: {values['absent'][key]}"


def test_view_shows_the_unmatched_audio_of_each_track(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = version_4("portions")
    unmatched = report["measurements"]["unmatched"]
    # B's leading silence, and audio that only one track holds.
    assert [extent["digitally_silent"] for extent in unmatched["b"]] == [True, False]
    assert [extent["digitally_silent"] for extent in unmatched["a"]] == [False]

    page = view(run, path)

    for name in ("a", "b"):
        rows = page.tables[f"Unmatched audio: track {name.upper()}"]
        assert rows[0] == [
            "Start frame",
            "Frames",
            "Range (s, computed)",
            "Digitally silent",
            "Level (dBFS)",
        ]
        assert rows[1:] == [
            [
                str(extent["start_frame"]),
                str(extent["frames"]),
                seconds(extent),
                number(extent["digitally_silent"]),
                "no level (digitally silent)"
                if extent["digitally_silent"]
                else number(extent["level_dbfs"]),
            ]
            for extent in unmatched[name]
        ]


def test_view_says_why_no_portion_was_found(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = version_4("no_portion")
    measurements = report["measurements"]
    assert measurements["portions"] == []

    page = view(run, path)

    assert page.row("Overview", "Portions") == [
        f"absent: {measurements['absent']['portions']}"
    ]
    assert "Portions" not in page.tables
    for name in ("a", "b"):
        [extent] = measurements["unmatched"][name]
        rows = page.tables[f"Unmatched audio: track {name.upper()}"][1:]
        assert rows[0][:2] == [str(extent["start_frame"]), str(extent["frames"])]


def test_view_shows_identical_audio_as_one_portion(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = version_4("identical")
    [portion] = report["measurements"]["portions"]

    page = view(run, path)

    assert page.row("Overview", "Identical audio") == ["true"]
    reason = portion["absent"]["block_gain_residual_db"]
    assert page.row("Portions", "1")[9] == f"absent: {reason}"
    assert "Unmatched audio: track A" not in page.tables
    assert "No unmatched range." in page.nodes


def test_view_shows_why_a_portion_has_no_channels(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    path, report = version_4("mono")
    [portion] = report["measurements"]["portions"]

    page = view(run, path)

    assert page.tables["Portion 1 (primary): values"][0] == ["", "Downmix"]
    assert f"absent: {portion['absent']['channels']}" in page.nodes


def test_view_shows_portions_of_a_report_without_a_common_sample_rate(
    run: Run, version_4: Callable[[str], tuple[Path, dict[str, Any]]]
) -> None:
    # The schema lets a Report leave the common sample rate out; the ranges in
    # seconds, which the page computes from it, are then absent.
    path, report = version_4("portions")
    edited = edit(path, lambda document: document["method"].pop("common_sample_rate"))
    assert validator.validate(str(edited)).result["outcome"] == validator.VALID

    page = view(run, edited)

    unavailable = "absent: the Report holds no common sample rate"
    portion = report["measurements"]["portions"][0]
    row = page.row("Portions", "1")
    assert row[1:4] == [
        str(portion["a"]["start_frame"]),
        str(portion["a"]["frames"]),
        unavailable,
    ]
    assert page.tables["Unmatched audio: track B"][1][2] == unavailable
