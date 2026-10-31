"""Render a comparison Report as a self-contained HTML page.

The page holds every value of the Report as the Report records it, with labels and
units and no interpretation. It has no script and loads nothing, and a Content
Security Policy forbids both. See docs/formats/comparison-report.md.
"""

from __future__ import annotations

import dataclasses
import enum
import html
import json
import unicodedata
from typing import TYPE_CHECKING, Any

import copyofa
from copyofa import comparator

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

SUPPORTED_KINDS = frozenset({comparator.REPORT_KIND})
"""The kinds of Report this module renders."""


class _Measurements(enum.Enum):
    """How a page lays out the method and the measurements of a Report."""

    ALIGNMENT = enum.auto()
    """The method; one alignment, its overlap, and the values measured over it."""
    PORTIONS = enum.auto()
    """The method and its parameters; the portions and the unmatched audio."""
    EDITIONS = enum.auto()
    """The editions and their tracks; the method and its parameters; the coverage,
    the correspondences, the portions with their segments, and the unmatched audio of
    each track."""


@dataclasses.dataclass(frozen=True)
class _Layout:
    """How a page lays out a Report of one format version."""

    measurements: _Measurements
    error_ranges: bool
    """Whether the page shows the error ranges of each track input."""


_LAYOUTS: dict[tuple[int, str | None], _Layout] = {
    (1, None): _Layout(_Measurements.ALIGNMENT, error_ranges=False),
    (2, None): _Layout(_Measurements.ALIGNMENT, error_ranges=False),
    (3, None): _Layout(_Measurements.ALIGNMENT, error_ranges=False),
    (4, None): _Layout(_Measurements.PORTIONS, error_ranges=False),
    (5, None): _Layout(_Measurements.PORTIONS, error_ranges=True),
    (6, comparator.TRACKS): _Layout(_Measurements.PORTIONS, error_ranges=True),
    (6, comparator.EDITIONS): _Layout(_Measurements.EDITIONS, error_ranges=True),
}
"""The layout of each comparison Report format version this module renders and, from
version 6, of each scope of that version: a version before 6 has no scope, None."""

SUPPORTED_FORMAT_VERSIONS: frozenset[int] = frozenset(
    version for version, _ in _LAYOUTS
)
"""The comparison Report format versions this module renders, each with its layout."""

SUPPORTED_SCOPES: frozenset[str] = frozenset(
    scope for _, scope in _LAYOUTS if scope is not None
)
"""The scopes of comparison Reports from format version 6 this module renders."""

_ABSENT = "absent"
_LEFT_OUT = "left out"

_POLICY = "default-src 'none'; style-src 'unsafe-inline'"

_STYLE = """\
body { font-family: system-ui, sans-serif; line-height: 1.4; margin: 2rem auto;
  max-width: 70rem; padding: 0 1rem; }
h1, h2, h3 { line-height: 1.2; }
table { border-collapse: collapse; margin: 0.5rem 0 1.5rem; }
th, td { border: 1px solid #999; padding: 0.25rem 0.6rem; text-align: left;
  vertical-align: top; }
thead th, tbody th { font-weight: 600; }
td { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
td ul, td ol { margin: 0; padding-left: 1.2rem; }
.absent { font-style: italic; }
.wide { overflow-x: auto; }
.wide td { overflow-wrap: normal; white-space: nowrap; }"""


def render(report: dict[str, Any], sha256: str) -> str:
    """Return the HTML page of a valid comparison Report of a supported format version.

    sha256 is the SHA-256 of the exact bytes the Report was read from. Every text of
    the Report is escaped, and a character that is not printable, such as a lone
    surrogate (a path byte that is not valid UTF-8), is shown as its escape, such as
    `\\udc80`, so the page is valid UTF-8 and inert. Raises ValueError for a format
    version not in SUPPORTED_FORMAT_VERSIONS, or a scope it has no layout for.
    """
    version = report["format_version"]
    scope = report.get("scope")
    layout = _LAYOUTS.get((version, scope))
    if layout is None:
        raise ValueError(
            f"cannot render comparison Report format version {version}"
            + ("" if scope is None else f" of scope {scope}")
        )
    inputs = report["inputs"]
    if layout.measurements is _Measurements.EDITIONS:
        title = (
            f"Comparison of {_edition_name(inputs, 'a')} and "
            f"{_edition_name(inputs, 'b')}"
        )
        sections = [
            *_editions_section(inputs),
            *_method_section(report["method"], layout.measurements),
            *_edition_measurements_section(report),
        ]
    else:
        title = (
            f"Comparison of {comparator.input_name(inputs['a'])} and "
            f"{comparator.input_name(inputs['b'])}"
        )
        sections = [
            *_inputs_section(inputs, error_ranges=layout.error_ranges),
            *_method_section(report["method"], layout.measurements),
            *_measurements_section(
                report.get("measurements"), report["method"], layout.measurements
            ),
        ]
    body = [
        "<h1>Comparison Report</h1>",
        *_report_section(report, sha256),
        "<h2>This page</h2>",
        _table(None, [("Generated by CopyOfA version", _text(copyofa.__version__))]),
        (
            "<p>The page shows the values of the Report as it records them, with "
            "labels and units added and no conclusion drawn. Absent means that the "
            "Report holds no value there.</p>"
        ),
        *sections,
        "<h2>Limitations</h2>",
        _items(report["limitations"]),
    ]
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            f'<meta http-equiv="Content-Security-Policy" content="{_POLICY}">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_text(title)}</title>",
            f"<style>\n{_STYLE}\n</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
            "",
        ]
    )


def _report_section(report: dict[str, Any], sha256: str) -> list[str]:
    rows = [
        ("SHA-256 of the Report file", f"<code>{_text(sha256)}</code>"),
        ("Report kind", _show(report, "report_kind")),
        ("Format version", _show(report, "format_version")),
    ]
    # From format version 6, which states what the Report compares.
    if "scope" in report:
        rows.append(("Scope", _show(report, "scope")))
    rows += [
        ("CopyOfA version that ran the comparison", _show(report, "copyofa_version")),
        ("Compared at (UTC)", _show(report, "compared_at")),
        ("Left out of the Report (JSON Pointers)", _list(report, "omitted")),
    ]
    return ["<h2>Report</h2>", _table(None, rows)]


def _inputs_section(inputs: dict[str, Any], *, error_ranges: bool) -> list[str]:
    fields: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Evidence Set location", lambda e: _show(e, "evidence_set", _LEFT_OUT)),
        *_BASELINE_FIELDS,
        *_checked_fields(error_ranges=error_ranges),
    ]
    parts = [
        "<h2>Inputs</h2>",
        _table(
            ["", "Track A", "Track B"],
            [(label, show(inputs["a"]), show(inputs["b"])) for label, show in fields],
        ),
    ]
    if error_ranges:
        for name in ("a", "b"):
            ranges = inputs[name].get("track", {}).get("error_ranges")
            if ranges:
                parts += [
                    f"<h3>Error ranges: track {name.upper()}</h3>",
                    _error_ranges_table(ranges),
                ]
    return parts


_BASELINE_FIELDS: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
    (
        "Integrity Baseline manifest SHA-256",
        lambda e: _show(e["integrity_baseline"], "manifest_sha256", code=True),
    ),
    (
        "Integrity Baseline usable",
        lambda e: _show(e["integrity_baseline"], "usable"),
    ),
    (
        "Integrity Baseline problems",
        lambda e: _list(e["integrity_baseline"], "problems"),
    ),
]


def _checked_fields(
    *, error_ranges: bool
) -> list[tuple[str, Callable[[dict[str, Any]], str]]]:
    """Return the rows of a checked file or track: its path, track and findings."""
    fields: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Path in the Evidence Set", lambda e: _show(e, "path")),
        ("Track of the acquired disc", lambda e: _show(e.get("track", {}), "number")),
        (
            "First frame of the track in the image",
            lambda e: _show(e.get("track", {}), "first_frame"),
        ),
        (
            "Frames of the track in the image",
            lambda e: _show(e.get("track", {}), "frame_count"),
        ),
    ]
    if error_ranges:
        fields.append(("Error ranges of the track", _error_ranges_count))
    fields += [
        ("Outcome", lambda e: _show(e, "outcome")),
        ("Reason", lambda e: _show(e, "reason")),
        ("Format", lambda e: _show(e, "format")),
        ("Encoding", lambda e: _show(e, "encoding")),
        ("Sample rate (Hz)", lambda e: _show(e, "sample_rate")),
        ("Channels", lambda e: _show(e, "channels")),
        ("Bits per sample", lambda e: _show(e, "bits_per_sample")),
        ("Frames", lambda e: _show(e, "frames")),
        ("Duration (computed from frames and sample rate)", _duration),
        ("Expected File Digest", lambda e: _show(e, "expected_digest", code=True)),
        ("Observed File Digest", lambda e: _show(e, "observed_digest", code=True)),
        ("Audio Digest", lambda e: _show(e, "audio_digest", code=True)),
        ("Peak of each channel", _peak),
        ("Leading silence (frames)", lambda e: _show(e, "leading_silence_frames")),
        ("Trailing silence (frames)", lambda e: _show(e, "trailing_silence_frames")),
        ("FLAC MD5 signature", lambda e: _show(e, "flac_md5_signature")),
        ("Limitations", lambda e: _list(e, "limitations")),
    ]
    return fields


def _edition_name(inputs: dict[str, Any], name: str) -> str:
    """Name an edition by its Evidence Set location, or by its letter when the Report
    leaves the location out."""
    return inputs[name].get("evidence_set", f"edition {name.upper()}")


def _editions_section(inputs: dict[str, Any]) -> list[str]:
    """Return the editions of a Report of scope `editions`, then each one's tracks
    and excluded files."""
    fields: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Evidence Set location", lambda e: _show(e, "evidence_set", _LEFT_OUT)),
        *_BASELINE_FIELDS,
        ("Tracks", lambda e: _counted(e["tracks"], "track")),
        ("Excluded files", lambda e: _counted(e["excluded"], "file")),
        ("Reason the edition has no track", lambda e: _show(e, "reason")),
    ]
    parts = [
        "<h2>Editions</h2>",
        _table(
            ["", "Edition A", "Edition B"],
            [(label, show(inputs["a"]), show(inputs["b"])) for label, show in fields],
        ),
    ]
    rows: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Position", lambda e: _show(e, "position")),
        *_checked_fields(error_ranges=True),
    ]
    for name in ("a", "b"):
        edition = f"edition {name.upper()}"
        for track in inputs[name]["tracks"]:
            heading = f"Track of {edition} at position {_scalar(track['position'])}"
            parts += [
                f"<h3>{heading}</h3>",
                _table(None, [(label, show(track)) for label, show in rows]),
            ]
            ranges = track.get("track", {}).get("error_ranges")
            if ranges:
                parts += [
                    f"<h4>{heading}: error ranges</h4>",
                    _error_ranges_table(ranges),
                ]
        excluded = inputs[name]["excluded"]
        parts.append(f"<h3>Excluded files: {edition}</h3>")
        if excluded:
            parts.append(
                _table(
                    ["Path in the Evidence Set", "Outcome", "Reason"],
                    [
                        (
                            _show(file, "path"),
                            _show(file, "outcome"),
                            _show(file, "reason"),
                        )
                        for file in excluded
                    ],
                )
            )
        else:
            parts.append("<p>No excluded file.</p>")
    return parts


def _counted(items: Sequence[Any], noun: str) -> str:
    if not items:
        return "none"
    return f"{len(items)} {noun if len(items) == 1 else noun + 's'}, listed below"


def _error_ranges_count(entry: dict[str, Any]) -> str:
    """Return how many error ranges a track input holds, listed below the inputs."""
    ranges = entry.get("track", {}).get("error_ranges")
    if ranges is None:
        return _absent(None)
    if not ranges:
        return "none"
    return f"{len(ranges)} {'range' if len(ranges) == 1 else 'ranges'}, listed below"


def _error_ranges_table(ranges: Sequence[dict[str, Any]]) -> str:
    return _table(
        ["Offset from the track's first frame (frames)", "Frames", "State"],
        [
            (
                _show(extent, "offset_frames"),
                _show(extent, "frame_count"),
                _show(extent, "state"),
            )
            for extent in ranges
        ],
    )


def _method_section(method: dict[str, Any], layout: _Measurements) -> list[str]:
    fields = (
        ("Decoder", "decoder"),
        ("Decoder version", "decoder_version"),
        ("Resampler", "resampler"),
        ("Resampler version", "resampler_version"),
        ("Resampler quality", "resampler_quality"),
        ("Common sample rate (Hz)", "common_sample_rate"),
        ("Alignment", "alignment"),
    )
    parts = [
        "<h2>Method</h2>",
        _table(None, [(label, _show(method, key)) for label, key in fields]),
    ]
    if layout is not _Measurements.ALIGNMENT:
        parts += [
            "<h3>Parameters</h3>",
            _table(
                ["Parameter", "Value"],
                [
                    (f"<code>{_text(name)}</code>", _scalar(value))
                    for name, value in method["parameters"].items()
                ],
            ),
        ]
    return parts


def _measurements_section(
    measurements: dict[str, Any] | None, method: dict[str, Any], layout: _Measurements
) -> list[str]:
    if measurements is None:
        return [
            "<h2>Measurements</h2>",
            "<p>The tracks were not measured: the Report holds no measurements.</p>",
        ]
    if layout is _Measurements.PORTIONS:
        return _portions_section(measurements, method.get("common_sample_rate"))
    # _Measurements.ALIGNMENT: one alignment, its overlap, and the values measured
    # over it.
    absent = measurements.get("absent", {})
    alignment = [("Identical audio", _show(measurements, "identical_audio"))]
    if "offset" in measurements:
        offset = measurements["offset"]
        alignment += [
            ("Offset (frames)", _show(offset, "frames")),
            ("Offset (seconds)", _show(offset, "seconds")),
        ]
    else:
        alignment.append(("Offset", _absent(absent.get("offset"))))
    parts = [
        "<h2>Measurements</h2>",
        "<h3>Alignment</h3>",
        _table(None, alignment),
        "<h3>Overlap</h3>",
    ]
    if "overlap" in measurements:
        overlap = measurements["overlap"]
        parts.append(
            _table(
                ["", "Track A", "Track B"],
                [
                    (label, _show(overlap["a"], key), _show(overlap["b"], key))
                    for label, key in (
                        ("Start frame", "start_frame"),
                        ("Frames", "frames"),
                        ("Fraction of the track", "fraction"),
                    )
                ],
            )
        )
    else:
        parts.append(f"<p>{_absent(absent.get('overlap'))}</p>")

    series = [("Downmix", measurements["downmix"])]
    series += [
        (f"Channel {number}", values)
        for number, values in enumerate(measurements.get("channels", []), 1)
    ]
    parts += ["<h3>Values</h3>", _values_table(series)]
    if "channels" not in measurements:
        parts.append(f"<p>Channels: {_absent(absent.get('channels'))}</p>")
    for name, values in series:
        if "residual_windows" in values:
            parts += [
                f"<h3>Residual windows: {_text(name)}</h3>",
                _windows(values, "overlap"),
            ]
    return parts


def _portions_section(measurements: dict[str, Any], rate: int | None) -> list[str]:
    """Return the measurements of a Report of format version 4: its portions."""
    portions = measurements["portions"]
    if portions:
        count = len(portions)
        listed = f"{count} {'portion' if count == 1 else 'portions'}, listed below"
    else:
        listed = _absent(measurements.get("absent", {}).get("portions"))
    parts = [
        "<h2>Measurements</h2>",
        "<h3>Overview</h3>",
        _table(
            None,
            [
                ("Identical audio", _show(measurements, "identical_audio")),
                ("Portions", listed),
            ],
        ),
    ]
    if portions:
        # Many columns of full-precision numbers: the table scrolls rather than
        # breaking a number across lines.
        table = _portions_table(portions, rate)
        parts += ["<h3>Portions</h3>", f'<div class="wide">\n{table}\n</div>']
    for number, portion in enumerate(portions, 1):
        parts += _portion_section(number, portion)
    for name in ("a", "b"):
        parts.append(f"<h3>Unmatched audio: track {name.upper()}</h3>")
        parts.append(_unmatched_table(measurements["unmatched"][name], rate))
    return parts


def _portions_table(portions: Sequence[dict[str, Any]], rate: int | None) -> str:
    rows = []
    for number, portion in enumerate(portions, 1):
        downmix = portion["downmix"]
        rows.append(
            (
                str(number),
                _show(portion, "rank"),
                _show(portion["a"], "start_frame"),
                _show(portion["a"], "frames"),
                _seconds(portion["a"], rate),
                _show(portion["b"], "start_frame"),
                _show(portion["b"], "frames"),
                _seconds(portion["b"], rate),
                _show(portion["offset"], "frames"),
                _show(portion["offset"], "seconds"),
                _show(portion, "block_gain_residual_db"),
                _show(downmix, "correlation"),
                _show(downmix, "gain_db"),
                _show(downmix, "residual_db"),
            )
        )
    return _table(
        [
            "Portion",
            "Rank",
            "Track A start frame",
            "Track A frames",
            "Track A range (s, computed)",
            "Track B start frame",
            "Track B frames",
            "Track B range (s, computed)",
            "Offset (frames)",
            "Offset (seconds)",
            "Residual after the per-block gains (dB)",
            "Downmix correlation",
            "Downmix gain (dB)",
            "Downmix residual (dB)",
        ],
        rows,
    )


def _portion_section(number: int, portion: dict[str, Any]) -> list[str]:
    """Return the values of a portion, for the downmix and each channel, with their
    residual windows."""
    rank = _text(portion["rank"])
    return _series_section(f"Portion {number} ({rank})", portion, "portion", "h3")


def _series_section(
    heading: str, measured: dict[str, Any], origin: str, level: str
) -> list[str]:
    """Return the values measured over a portion or a segment, for the downmix and
    each channel, with their residual windows."""
    series = [("Downmix", measured["downmix"])]
    series += [
        (f"Channel {channel}", values)
        for channel, values in enumerate(measured.get("channels", []), 1)
    ]
    parts = [f"<{level}>{heading}: values</{level}>", _values_table(series)]
    if "channels" not in measured:
        reason = measured.get("absent", {}).get("channels")
        parts.append(f"<p>Channels: {_absent(reason)}</p>")
    for name, values in series:
        if "residual_windows" in values:
            parts += [
                f"<{level}>{heading}: residual windows, {_text(name)}</{level}>",
                _windows(values, origin),
            ]
    return parts


def _edition_measurements_section(report: dict[str, Any]) -> list[str]:
    """Return the measurements of a Report of scope `editions`."""
    measurements = report.get("measurements")
    if measurements is None:
        return [
            "<h2>Measurements</h2>",
            "<p>The editions were not measured: the Report holds no measurements.</p>",
            _table(None, [("Measurements", _show(report, "measurements"))]),
        ]
    rate = report["method"].get("common_sample_rate")
    names = {
        name: {
            track.get("position"): comparator.input_name(track)
            for track in report["inputs"][name]["tracks"]
        }
        for name in ("a", "b")
    }

    def track(name: str, position: Any) -> str:
        """Name the track of an edition at a position, as its input gives it."""
        if position not in names[name]:
            return _absent("the Report lists no track at this position")
        return _text(names[name][position])

    portions = measurements["portions"]
    if portions:
        count = len(portions)
        listed = f"{count} {'portion' if count == 1 else 'portions'}, listed below"
    else:
        listed = _absent(measurements.get("absent", {}).get("portions"))
    coverage = measurements["coverage"]
    parts = [
        "<h2>Measurements</h2>",
        "<h3>Overview</h3>",
        _table(None, [("Portions", listed)]),
        "<h3>Coverage</h3>",
        _table(
            ["", "Edition A", "Edition B"],
            [
                (label, show(coverage["a"]), show(coverage["b"]))
                for label, show in (
                    (
                        "Frames found in the other edition, each counted once",
                        lambda c: _show(c, "matched_frames"),
                    ),
                    (
                        "Duration found in the other edition (computed)",
                        lambda c: _frames_duration(c, "matched_frames", rate),
                    ),
                    ("Frames of the edition", lambda c: _show(c, "frames")),
                    (
                        "Duration of the edition (computed)",
                        lambda c: _frames_duration(c, "frames", rate),
                    ),
                )
            ],
        ),
        "<h3>Correspondences</h3>",
    ]
    correspondences = measurements["correspondences"]
    if correspondences:
        table = _table(
            [
                "Track of A (position)",
                "Track of A",
                "Frames of A found in B",
                "Fraction of A found in B",
                "Track of B (position)",
                "Track of B",
                "Frames of B found in A",
                "Fraction of B found in A",
                "Identical audio",
            ],
            [
                (
                    _show(pair["a"], "position"),
                    track("a", pair["a"].get("position")),
                    _show(pair["a"], "matched_frames"),
                    _show(pair["a"], "fraction"),
                    _show(pair["b"], "position"),
                    track("b", pair["b"].get("position")),
                    _show(pair["b"], "matched_frames"),
                    _show(pair["b"], "fraction"),
                    _show(pair, "identical_audio"),
                )
                for pair in correspondences
            ],
        )
        parts.append(f'<div class="wide">\n{table}\n</div>')
    else:
        parts.append("<p>No correspondence.</p>")
    for name in ("a", "b"):
        parts += [
            f"<h3>Sequence: edition {name.upper()}</h3>",
            _table(
                [
                    "Position",
                    "Track",
                    "Start frame in the sequence",
                    "Frames",
                    "Range (s, computed)",
                ],
                [
                    (
                        _show(entry, "position"),
                        track(name, entry.get("position")),
                        _show(entry, "start_frame"),
                        _show(entry, "frames"),
                        _seconds(entry, rate),
                    )
                    for entry in measurements["sequences"][name]
                ],
            ),
        ]
    if portions:
        table = _edition_portions_table(portions, rate)
        parts += ["<h3>Portions</h3>", f'<div class="wide">\n{table}\n</div>']
    for number, portion in enumerate(portions, 1):
        rank = _text(portion["rank"])
        heading = f"Portion {number} ({rank})"
        table = _segments_table(portion["segments"], rate, track)
        parts += [
            f"<h3>{heading}: segments</h3>",
            f'<div class="wide">\n{table}\n</div>',
        ]
        for segment_number, segment in enumerate(portion["segments"], 1):
            parts += _series_section(
                f"{heading}, segment {segment_number}", segment, "segment", "h4"
            )
    for name in ("a", "b"):
        parts.append(f"<h3>Unmatched audio: edition {name.upper()}</h3>")
        unmatched = measurements["unmatched"][name]
        # Each track of the sequence in order, then any other position an unmatched
        # range gives, so the page shows every range the Report holds.
        positions = [entry.get("position") for entry in measurements["sequences"][name]]
        positions += [
            position
            for position in dict.fromkeys(part.get("position") for part in unmatched)
            if position not in positions
        ]
        for position in positions:
            heading = (
                f"Edition {name.upper()}, position {_scalar(position)}: "
                f"{track(name, position)}"
            )
            parts += [
                f"<h4>{heading}</h4>",
                _unmatched_table(
                    [part for part in unmatched if part.get("position") == position],
                    rate,
                ),
            ]
    return parts


def _edition_portions_table(
    portions: Sequence[dict[str, Any]], rate: int | None
) -> str:
    return _table(
        [
            "Portion",
            "Rank",
            "Edition A start frame",
            "Edition A frames",
            "Edition A range (s, computed)",
            "Edition B start frame",
            "Edition B frames",
            "Edition B range (s, computed)",
            "Offset (frames)",
            "Offset (seconds)",
            "Residual after the per-block gains (dB)",
            "Segments",
        ],
        [
            (
                str(number),
                _show(portion, "rank"),
                _show(portion["a"], "start_frame"),
                _show(portion["a"], "frames"),
                _seconds(portion["a"], rate),
                _show(portion["b"], "start_frame"),
                _show(portion["b"], "frames"),
                _seconds(portion["b"], rate),
                _show(portion["offset"], "frames"),
                _show(portion["offset"], "seconds"),
                _show(portion, "block_gain_residual_db"),
                str(len(portion["segments"])),
            )
            for number, portion in enumerate(portions, 1)
        ],
    )


def _segments_table(
    segments: Sequence[dict[str, Any]],
    rate: int | None,
    track: Callable[[str, Any], str],
) -> str:
    rows = []
    for number, segment in enumerate(segments, 1):
        cells = [str(number)]
        for name in ("a", "b"):
            extent = segment[name]
            cells += [
                _show(extent, "position"),
                track(name, extent.get("position")),
                _show(extent, "start_frame"),
                _show(extent, "frames"),
                _seconds(extent, rate),
            ]
        downmix = segment["downmix"]
        cells += [
            _show(downmix, "correlation"),
            _show(downmix, "gain_db"),
            _show(downmix, "residual_db"),
        ]
        rows.append(tuple(cells))
    return _table(
        [
            "Segment",
            *(
                header
                for name in ("A", "B")
                for header in (
                    f"Track of {name} (position)",
                    f"Track of {name}",
                    f"Start frame in the track of {name}",
                    "Frames",
                    f"Range in the track of {name} (s, computed)",
                )
            ),
            "Downmix correlation",
            "Downmix gain (dB)",
            "Downmix residual (dB)",
        ],
        rows,
    )


def _frames_duration(values: dict[str, Any], key: str, rate: int | None) -> str:
    """Format a count of frames at the common sample rate as a duration."""
    if key not in values:
        return _absent(None)
    if rate is None:
        return _absent("the Report holds no common sample rate")
    return format_duration(int(values[key]), int(rate))


def _unmatched_table(ranges: Sequence[dict[str, Any]], rate: int | None) -> str:
    if not ranges:
        return "<p>No unmatched range.</p>"
    return _table(
        [
            "Start frame",
            "Frames",
            "Range (s, computed)",
            "Digitally silent",
            "Level (dBFS)",
        ],
        [
            (
                _show(extent, "start_frame"),
                _show(extent, "frames"),
                _seconds(extent, rate),
                _show(extent, "digitally_silent"),
                # The Report gives a level only to a range that is not silent.
                _show(
                    extent,
                    "level_dbfs",
                    "no level (digitally silent)"
                    if extent.get("digitally_silent") is True
                    else _ABSENT,
                ),
            )
            for extent in ranges
        ],
    )


def _seconds(extent: dict[str, Any], rate: int | None) -> str:
    """Format a range of frames at a sample rate as seconds, such as `4.098-186.720`,
    or mark it absent when the Report holds no common sample rate."""
    if rate is None:
        return _absent("the Report holds no common sample rate")
    start, frames = int(extent["start_frame"]), int(extent["frames"])
    return f"{start / rate:.3f}-{(start + frames) / rate:.3f}"


def _values_table(series: Sequence[tuple[str, dict[str, Any]]]) -> str:
    def windows(values: dict[str, Any]) -> str:
        if "residual_windows" not in values:
            return _show(values, "residual_windows")
        count = len(values["residual_windows"])
        return f"{count} {'window' if count == 1 else 'windows'}, listed below"

    fields: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Correlation", lambda v: _show(v, "correlation")),
        ("Gain (dB)", lambda v: _show(v, "gain_db")),
        ("Residual (dB)", lambda v: _show(v, "residual_db")),
        ("Residual windows", windows),
    ]
    return _table(
        ["", *(_text(name) for name, _ in series)],
        [(label, *(show(values) for _, values in series)) for label, show in fields],
    )


def _windows(values: dict[str, Any], origin: str) -> str:
    windows = values["residual_windows"]
    if not windows:
        return "<p>No windows.</p>"
    return _table(
        [f"Start frame (from the start of the {origin})", "Frames", "Residual (dB)"],
        [
            (
                _show(window, "start_frame"),
                _show(window, "frames"),
                _show(window, "residual_db"),
            )
            for window in windows
        ],
    )


def _show(
    values: dict[str, Any],
    key: str,
    absent: str = _ABSENT,
    *,
    code: bool = False,
) -> str:
    """Return the HTML of a value as the Report holds it, or of its absence.

    The reason a value is absent is the one in the `absent` member of the object that
    would hold it, when there is one.
    """
    if key in values:
        text = _scalar(values[key])
        return f"<code>{text}</code>" if code else text
    return _absent(values.get("absent", {}).get(key), absent)


def _absent(reason: str | None, label: str = _ABSENT) -> str:
    text = label if reason is None else f"{label}: {reason}"
    return f'<span class="absent">{_text(text)}</span>'


def _scalar(value: Any) -> str:
    """Return a string, number or boolean as the Report writes it, escaped."""
    if isinstance(value, str):
        return _text(value)
    return html.escape(json.dumps(value), quote=True)


def _list(values: dict[str, Any], key: str) -> str:
    if key not in values:
        return _absent(None)
    return _items(values[key])


def _items(items: list[str]) -> str:
    if not items:
        return "none"
    entries = "".join(f"<li>{_text(item)}</li>" for item in items)
    return f"<ul>{entries}</ul>"


def _peak(entry: dict[str, Any]) -> str:
    if "peak" not in entry:
        return _absent(None)
    return ", ".join(_scalar(value) for value in entry["peak"]) or "none"


def _duration(entry: dict[str, Any]) -> str:
    if "frames" not in entry or "sample_rate" not in entry:
        return _absent(None)
    # JSON Schema accepts 44100.0 as an integer; a hand-edited Report may hold one.
    return format_duration(int(entry["frames"]), int(entry["sample_rate"]))


def format_duration(frames: int, sample_rate: int) -> str:
    """Format frames as a duration, such as `3:07.250` or `1:02:03.000`."""
    milliseconds = frames * 1000 // sample_rate
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}.{milliseconds:03}"
    return f"{minutes}:{seconds:02}.{milliseconds:03}"


def _table(header: Sequence[str] | None, rows: Sequence[tuple[str, ...]]) -> str:
    """Build a table from cells of HTML.

    The first cell of a row is its label when the table has no header or its first
    header is blank.
    """
    lines = ["<table>"]
    if header is not None:
        cells = "".join(f'<th scope="col">{cell}</th>' for cell in header)
        lines.append(f"<thead><tr>{cells}</tr></thead>")
    lines.append("<tbody>")
    labeled = header is None or header[0] == ""
    for row in rows:
        first, rest = (row[0], row[1:]) if labeled else ("", row)
        label = f'<th scope="row">{first}</th>' if labeled else ""
        cells = "".join(f"<td>{cell}</td>" for cell in rest)
        lines.append(f"<tr>{label}{cells}</tr>")
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)


# Control, format (such as bidirectional overrides), surrogate, private-use and
# unassigned characters, and line and paragraph separators. Spaces such as U+00A0 are
# shown as they are: harmless in HTML, and common in titles.
_ESCAPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def _text(text: str) -> str:
    """Escape text for HTML, showing each character that could hide or reorder text
    as its escape: a lone surrogate, a path byte that is not valid UTF-8, as `\\udc80`.
    """
    shown = "".join(
        repr(c)[1:-1] if unicodedata.category(c) in _ESCAPED_CATEGORIES else c
        for c in text
    )
    return html.escape(shown, quote=True)
