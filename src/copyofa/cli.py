"""Command-line interface for CopyOfA."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import TYPE_CHECKING, Any

import copyofa
from copyofa import (
    acquirer,
    comparator,
    evidence_set,
    inspector,
    validator,
    verifier,
    viewer,
)
from copyofa.errors import CopyOfAError
from copyofa.importer import import_evidence

if TYPE_CHECKING:
    from collections.abc import Sequence

    from copyofa.acquirer import AcquisitionResult
    from copyofa.importer import ImportResult

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_USAGE = 2
EXIT_CANCELED = 130


class _StoreOnce(argparse.Action):
    """Store an option's value, refusing the option when it is repeated."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest) is not None:
            parser.error(f"{option_string} may be given only once")
        setattr(namespace, self.dest, values)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copyofa", description=copyofa.__doc__)
    parser.add_argument("--version", action="version", version=copyofa.__version__)
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.required = True

    importing = commands.add_parser(
        "import",
        help="preserve selected files and directories as a new Evidence Set",
        description=(
            "Preserve selected files and directories as a new Evidence Set. Each "
            "source goes under data/ by its base name."
        ),
    )
    importing.add_argument(
        "sources", nargs="+", metavar="source", help="a file or directory to preserve"
    )
    importing.add_argument(
        "--to",
        required=True,
        metavar="destination",
        help="the Evidence Set to create; it must not exist, its parent must",
    )
    importing.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="pattern",
        help=(
            "exclude files and directories whose name, or path under data/, "
            "matches this shell-style pattern (repeatable)"
        ),
    )
    importing.add_argument(
        "--note", action=_StoreOnce, help="a free-form note about the provenance"
    )
    importing.add_argument(
        "--ref",
        action="append",
        metavar="reference",
        help="an external reference, such as discogs=r123456 (repeatable)",
    )
    importing.add_argument(
        "--json", action="store_true", help="print the result as JSON"
    )
    importing.set_defaults(handler=_import)

    acquiring = commands.add_parser(
        "acquire",
        help="read a plain audio CD with redumper into a new Evidence Set",
        description=(
            "Read a plain audio CD with redumper, build b768 or later, and preserve "
            "everything it wrote but the track files as a new Evidence Set, with an "
            "Acquisition Record. Exits 0 when the set was accepted and the disc read "
            "without error, and 1 when it was read with errors, refused or failed."
        ),
    )
    acquiring.add_argument(
        "--to",
        required=True,
        metavar="destination",
        help="the Evidence Set to create; it must not exist, its parent must",
    )
    acquiring.add_argument(
        "--drive",
        action=_StoreOnce,
        metavar="drive",
        help=(
            "the drive to read, as redumper's --drive names it, such as disk6; "
            "by default, the first drive holding a disc"
        ),
    )
    acquiring.add_argument(
        "--note", action=_StoreOnce, help="a free-form note about the provenance"
    )
    acquiring.add_argument(
        "--ref",
        action="append",
        metavar="reference",
        help="an external reference, such as discogs=r123456 (repeatable)",
    )
    acquiring.add_argument(
        "--json", action="store_true", help="print the result as JSON"
    )
    acquiring.set_defaults(handler=_acquire)

    verifying = commands.add_parser(
        "verify",
        help="check an Evidence Set against its Integrity Baseline",
        description=(
            "Check every file of an Evidence Set against its Integrity Baseline. "
            "Exits 0 when everything is intact and 1 when anything is not."
        ),
    )
    verifying.add_argument("evidence_set", metavar="evidence-set")
    verifying.add_argument(
        "--json", action="store_true", help="print the verification Report as JSON"
    )
    verifying.set_defaults(handler=_verify)

    inspecting = commands.add_parser(
        "inspect",
        help="describe the audio in an Evidence Set",
        description=(
            "Check each file of an Evidence Set against its Integrity Baseline, then "
            "decode the FLAC, WAV and MP3 audio and describe it. Exits 0 when every "
            "file was decoded or is not a supported format, and 1 otherwise."
        ),
    )
    inspecting.add_argument("evidence_set", metavar="evidence-set")
    inspecting.add_argument(
        "--json", action="store_true", help="print the inspection Report as JSON"
    )
    inspecting.set_defaults(handler=_inspect)

    comparing = commands.add_parser(
        "compare",
        help="measure how the audio of two preserved tracks relates",
        description=(
            "Check two tracks preserved in Evidence Sets against their Integrity "
            "Baselines, decode them, align them, and measure how track B relates to "
            "track A. Exits 0 when both were compared and 1 otherwise."
        ),
    )
    for name in ("track-a", "track-b"):
        comparing.add_argument(
            name.replace("-", "_"),
            metavar=name,
            help="a FLAC, WAV or MP3 file under the data/ directory of an Evidence Set",
        )
    comparing.add_argument(
        "--json", action="store_true", help="print the comparison Report as JSON"
    )
    comparing.add_argument(
        "--omit-locations",
        action="store_true",
        help="leave out where each Evidence Set is stored",
    )
    comparing.set_defaults(handler=_compare)
    validating = commands.add_parser(
        "validate",
        help="check a Report against its published JSON Schema",
        description=(
            "Check that a verification, inspection or comparison Report is strict "
            "JSON that matches the JSON Schema for its report_kind and "
            "format_version. Exits 0 when the Report is valid and 1 when it is "
            "invalid, unsupported or cannot be read. A valid Report is well formed, "
            "nothing more."
        ),
    )
    validating.add_argument("report")
    validating.add_argument(
        "--json", action="store_true", help="print the validation result as JSON"
    )
    validating.set_defaults(handler=_validate)

    viewing = commands.add_parser(
        "view",
        help="print a comparison Report as a self-contained HTML page",
        description=(
            "Validate a comparison Report, then print an HTML page that shows every "
            "value of the Report, with the SHA-256 of the file, on stdout. The page "
            "holds no script and loads nothing. Exits 0 when the page was printed "
            "and 1 when the Report is invalid, unsupported, of another kind, or "
            "cannot be read."
        ),
    )
    viewing.add_argument("report")
    viewing.set_defaults(handler=_view)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("copyofa: canceled", file=sys.stderr)
        return EXIT_CANCELED


def _import(args: argparse.Namespace) -> int:
    def progress(path: str, size: int) -> None:
        print(f"Preserved {_printable(path)} ({_count(size, 'byte')})", file=sys.stderr)

    try:
        result = import_evidence(
            args.sources,
            args.to,
            excludes=args.exclude,
            note=args.note,
            references=args.ref,
            progress=progress,
        )
    except (CopyOfAError, OSError) as error:
        print(f"copyofa: {error}", file=sys.stderr)
        return EXIT_PROBLEM
    for warning in result.warnings:
        print(f"copyofa: warning: {warning}", file=sys.stderr)
    if args.json:
        _print_json(result.to_json())
    else:
        _print_import(result)
    return EXIT_OK


def _acquire(args: argparse.Namespace) -> int:
    def progress(message: str) -> None:
        print(_printable(message), file=sys.stderr)

    try:
        result = acquirer.acquire(
            args.to,
            drive=args.drive,
            note=args.note,
            references=args.ref,
            progress=progress,
        )
    except (CopyOfAError, OSError) as error:
        print(f"copyofa: {error}", file=sys.stderr)
        return EXIT_PROBLEM
    for warning in result.warnings:
        print(f"copyofa: warning: {warning}", file=sys.stderr)
    read_errors = acquirer.has_read_errors(result.acquisition_record)
    if read_errors:
        print(
            "copyofa: the Evidence Set was accepted, but the disc was read with errors",
            file=sys.stderr,
        )
    if args.json:
        _print_json(result.to_json())
    else:
        _print_acquisition(result)
    return EXIT_PROBLEM if read_errors else EXIT_OK


def _print_acquisition(result: AcquisitionResult) -> None:
    record = result.acquisition_record
    drive = record["drive"]
    details = []
    if "firmware_revision" in drive:
        details.append(f"firmware {drive['firmware_revision']}")
    if "read_offset" in drive:
        details.append(f"read offset {drive['read_offset']:+}")
    print(f"Accepted Evidence Set {_printable(str(result.evidence_set))}")
    described = f"{drive['vendor']} {drive['product']}"
    if details:
        described = f"{described} ({', '.join(details)})"
    print(_printable(f"Drive: {described}"))
    reader = record["reader"]
    print(_printable(f"Reader: {reader['name']} {reader['build']}"))
    disc = record["disc"]
    if "write_offset" in disc:
        print(f"Disc write offset: {disc['write_offset']:+}")
    errors = record["read_errors"]
    print(
        f"Read errors: "
        f"{'found' if acquirer.has_read_errors(record) else 'none'} "
        f"(SCSI {_count(errors['scsi_samples'], 'sample')}, "
        f"C2 {_count(errors['c2_samples'], 'sample')}; "
        f"subchannel Q {_count(errors['subchannel_q_sectors'], 'sector')})"
    )
    print(f"Tracks: {len(record['tracks'])}")
    for track in record["tracks"]:
        duration = viewer.format_duration(
            track["frame_count"], evidence_set.CD_SAMPLE_RATE
        )
        line = f"  {track['number']}: {duration}, {track['audio_digest']}"
        if track["error_frames"]:
            line = (
                f"{line}, {_count(track['error_frames'], 'frame')} not read "
                "successfully"
            )
        print(line)
    print(f"Preserved {_count(result.files, 'file')}, {_count(result.bytes, 'byte')}")


# Lone surrogates: how Python represents file name bytes that are not valid UTF-8.
_SURROGATE = re.compile(f"[{chr(0xD800)}-{chr(0xDFFF)}]")


def _print_json(document: dict[str, Any]) -> None:
    """Print a `--json` document as UTF-8, whatever the locale.

    Lone surrogates are escaped as `\\uXXXX`, which `json.loads` turns back into the
    original string, so the output stays valid UTF-8.
    """
    text = json.dumps(document, indent=2, ensure_ascii=False)
    # Surrogates only occur inside JSON strings, where an escape is valid.
    text = _SURROGATE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)
    sys.stdout.flush()
    sys.stdout.buffer.write(f"{text}\n".encode())
    sys.stdout.buffer.flush()


def _print_import(result: ImportResult) -> None:
    exclusions = result.import_record["exclusions"]
    print(f"Accepted Evidence Set {_printable(str(result.evidence_set))}")
    print(f"Preserved {_count(result.files, 'file')}, {_count(result.bytes, 'byte')}")
    print(f"Excluded {_count(len(exclusions), 'item')}")
    for exclusion in exclusions:
        reason = exclusion["reason"].replace("_", " ")
        if "pattern" in exclusion:
            reason = f"{reason} {exclusion['pattern']}"
        print(f"  {_printable(exclusion['path'])}: {_printable(reason)}")


def _verify(args: argparse.Namespace) -> int:
    try:
        report = verifier.verify(args.evidence_set)
    except verifier.NotAnEvidenceSetError as error:
        print(f"copyofa: {error}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        _print_json(report)
    else:
        _print_verification(report)
    return EXIT_OK if verifier.is_intact(report) else EXIT_PROBLEM


def _print_verification(report: dict[str, Any]) -> None:
    baseline = report["integrity_baseline"]
    print(f"Evidence Set {_printable(report['evidence_set'])}")
    print(f"Integrity Baseline: {'usable' if baseline['usable'] else 'unusable'}")
    for problem in baseline["problems"]:
        print(f"  {_printable(problem)}")
    _print_items("Records", report["tag_files"])
    _print_items("Payload", report["payload"])
    print(f"Unexpected files: {len(report['unexpected_files'])}")
    for path in report["unexpected_files"]:
        print(f"  {_printable(path)}")
    if report["unexamined_directories"]:
        print("Directories not searched for unexpected files:")
        for item in report["unexamined_directories"]:
            print(f"  {_printable(item['path'])} ({_printable(item['reason'])})")
    print(f"Result: {'intact' if verifier.is_intact(report) else 'problems found'}")


def _print_items(title: str, items: list[dict[str, str]]) -> None:
    counts = Counter(item["outcome"] for item in items)
    summary = ", ".join(
        f"{counts[outcome]} {outcome.replace('_', ' ')}"
        for outcome in verifier.OUTCOMES
        if counts[outcome]
    )
    print(f"{title}: {summary or 'none'}")
    for item in items:
        if item["outcome"] == verifier.MATCHING:
            continue
        line = f"  {item['outcome'].replace('_', ' ')}: {item['path']}"
        if item["outcome"] != verifier.CHANGED:
            line = f"{line} ({item['reason']})"
        print(_printable(line))


def _inspect(args: argparse.Namespace) -> int:
    def progress(entry: dict[str, Any]) -> None:
        outcome = entry["outcome"].replace("_", " ")
        name = f"track {entry['number']}" if "number" in entry else entry["path"]
        print(f"Inspected {_printable(name)}: {outcome}", file=sys.stderr)

    try:
        report = inspector.inspect(args.evidence_set, progress=progress)
    except verifier.NotAnEvidenceSetError as error:
        print(f"copyofa: {error}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        _print_json(report)
    else:
        _print_inspection(report)
    return EXIT_PROBLEM if inspector.found_problems(report) else EXIT_OK


def _print_inspection(report: dict[str, Any]) -> None:
    baseline = report["integrity_baseline"]
    print(f"Evidence Set {_printable(report['evidence_set'])}")
    print(f"Integrity Baseline: {'usable' if baseline['usable'] else 'unusable'}")
    for problem in baseline["problems"]:
        print(f"  {_printable(problem)}")
    counts = report["counts"]
    summary = ", ".join(
        f"{counts[outcome]} {outcome.replace('_', ' ')}"
        for outcome in inspector.OUTCOMES
        if counts[outcome]
    )
    print(f"Files: {summary or 'none'}")
    entries = report["files"]
    for entry in entries:
        if entry["outcome"] == inspector.INTERPRETED:
            print(_printable(f"  {entry['path']}: {_describe_audio(entry)}"))
    for entry in entries:
        if entry["outcome"] != inspector.INTERPRETED:
            outcome = entry["outcome"].replace("_", " ")
            print(_printable(f"  {outcome}: {entry['path']} ({entry['reason']})"))
    if "disc" in report:
        _print_disc(report["disc"])
    result = "problems found" if inspector.found_problems(report) else "no problems"
    print(f"Result: {result}")


def _print_disc(disc: dict[str, Any]) -> None:
    if "reason" in disc:
        print(_printable(f"Disc: not inspected ({disc['reason']})"))
        return
    tracks = disc["tracks"]
    counts = Counter(track["outcome"] for track in tracks)
    summary = ", ".join(
        f"{counts[outcome]} {outcome.replace('_', ' ')}"
        for outcome in inspector.OUTCOMES
        if counts[outcome]
    )
    print(f"Disc: {_count(len(tracks), 'track')}, {summary}")
    for track in tracks:
        if track["outcome"] != inspector.INTERPRETED:
            continue
        agreement = (
            "matches the recorded one"
            if track["audio_digest"] == track["recorded_audio_digest"]
            else "differs from the recorded one"
        )
        duration = viewer.format_duration(track["frames"], evidence_set.CD_SAMPLE_RATE)
        print(
            f"  track {track['number']}: {duration}, {track['audio_digest']}, "
            f"Audio Digest {agreement}"
        )
    for track in tracks:
        if track["outcome"] != inspector.INTERPRETED:
            outcome = track["outcome"].replace("_", " ")
            print(
                _printable(f"  {outcome}: track {track['number']} ({track['reason']})")
            )


def _describe_audio(entry: dict[str, Any]) -> str:
    """Summarize an interpreted file, such as `flac, 44100 Hz, 16-bit, 2 channels`."""
    parts = [entry["format"], f"{entry['sample_rate']} Hz"]
    if "bits_per_sample" in entry:
        parts.append(f"{entry['bits_per_sample']}-bit")
    parts.append(_count(entry["channels"], "channel"))
    parts.append(viewer.format_duration(entry["frames"], entry["sample_rate"]))
    if entry.get("flac_md5_signature") == inspector.MD5_DIFFERS:
        parts.append("decoded audio differs from its FLAC MD5 signature")
    return ", ".join(parts)


def _compare(args: argparse.Namespace) -> int:
    def progress(entry: dict[str, Any]) -> None:
        outcome = entry["outcome"].replace("_", " ")
        print(f"Inspected {_printable(entry['path'])}: {outcome}", file=sys.stderr)

    try:
        report = comparator.compare(
            args.track_a,
            args.track_b,
            progress=progress,
            omit_locations=args.omit_locations,
        )
    except verifier.NotAnEvidenceSetError as error:
        print(f"copyofa: {error}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        _print_json(report)
    else:
        _print_comparison(report)
    return EXIT_PROBLEM if comparator.found_problems(report) else EXIT_OK


def _print_comparison(report: dict[str, Any]) -> None:
    for name in ("a", "b"):
        entry = report["inputs"][name]
        if entry["outcome"] == inspector.INTERPRETED:
            detail = _describe_audio(entry)
        else:
            detail = f"{entry['outcome'].replace('_', ' ')}: {entry['reason']}"
        location = (
            entry["path"]
            if "evidence_set" not in entry
            else f"{entry['evidence_set']}/{entry['path']}"
        )
        print(_printable(f"Track {name.upper()}: {location} ({detail})"))
    measurements = report.get("measurements")
    if measurements is None:
        print("Not compared: an input was not interpreted")
        return
    if measurements.get("identical_audio"):
        print("Identical audio: the Audio Digests are equal")
    absent = measurements.get("absent", {})
    if "offset" in measurements:
        offset = measurements["offset"]
        rate = report["method"]["common_sample_rate"]
        print(
            f"Offset: {offset['frames']:+} frames ({offset['seconds']:+.3f} s) "
            f"at {rate} Hz"
        )
        overlap = measurements["overlap"]
        print(
            f"Overlap: {overlap['a']['fraction']:.1%} of track A, "
            f"{overlap['b']['fraction']:.1%} of track B"
        )
    else:
        print(f"Offset: absent ({absent['offset']})")
        print(f"Overlap: absent ({absent['overlap']})")
    downmix = measurements["downmix"]
    for label, field, digits, unit in (
        ("Correlation", "correlation", 3, ""),
        ("Gain", "gain_db", 2, " dB"),
        ("Residual", "residual_db", 1, " dB"),
    ):
        if field in downmix:
            # Adding 0.0 turns a value that rounds to -0.0 into 0.0.
            value = round(downmix[field], digits) + 0.0
            sign = "+" if field == "gain_db" else ""
            print(f"{label}: {value:{sign}.{digits}f}{unit}")
        else:
            print(f"{label}: absent ({downmix['absent'][field]})")


def _validate(args: argparse.Namespace) -> int:
    try:
        validation = validator.validate(args.report)
    except validator.UnreadableReportError as error:
        print(f"copyofa: {_printable(str(error))}", file=sys.stderr)
        return EXIT_PROBLEM
    result = validation.result
    if args.json:
        _print_json(result)
    else:
        _print_validation(result)
    return EXIT_OK if result["outcome"] == validator.VALID else EXIT_PROBLEM


def _print_validation(result: dict[str, Any]) -> None:
    print(f"Result: {result['outcome']}")
    print(f"Report: {_printable(result['report'])}")
    print(f"SHA-256: {result['sha256']}")
    if "report_kind" in result:
        print(f"Report kind: {_printable(result['report_kind'])}")
    if "format_version" in result:
        print(f"Format version: {result['format_version']}")
    for problem in result["problems"]:
        location = problem["location"] or "(document)"
        print(_printable(f"  {location}: {problem['message']}"))
    print("Limitations:")
    for limitation in result["limitations"]:
        print(f"  {limitation}")


def _view(args: argparse.Namespace) -> int:
    try:
        validation = validator.validate(args.report)
    except validator.UnreadableReportError as error:
        print(f"copyofa: {_printable(str(error))}", file=sys.stderr)
        return EXIT_PROBLEM
    result = validation.result
    report = _printable(args.report)
    if result["outcome"] != validator.VALID:
        kind = "valid" if result["outcome"] == validator.INVALID else "supported"
        print(f"copyofa: {report} is not a {kind} Report", file=sys.stderr)
        for problem in result["problems"]:
            location = problem["location"] or "(document)"
            print(_printable(f"  {location}: {problem['message']}"), file=sys.stderr)
        return EXIT_PROBLEM
    if result["report_kind"] not in viewer.SUPPORTED_KINDS:
        print(
            f"copyofa: {report} is not a comparison Report; view supports "
            "comparison Reports only",
            file=sys.stderr,
        )
        return EXIT_PROBLEM
    page = viewer.render(validation.document, result["sha256"])
    sys.stdout.flush()
    sys.stdout.buffer.write(page.encode())
    sys.stdout.buffer.flush()
    return EXIT_OK


def _count(number: int, noun: str) -> str:
    """Format a count with its noun, such as `1 file` or `2 files`."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _printable(text: str) -> str:
    """Escape characters, such as a line feed in a file name, that break a line."""
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)
