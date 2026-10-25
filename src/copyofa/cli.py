"""Command-line interface for CopyOfA."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import TYPE_CHECKING, Any

import copyofa
from copyofa import verifier
from copyofa.errors import CopyOfAError
from copyofa.importer import import_evidence

if TYPE_CHECKING:
    from collections.abc import Sequence

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
        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    else:
        _print_import(result)
    return EXIT_OK


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
        print(json.dumps(report, indent=2))
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


def _count(number: int, noun: str) -> str:
    """Format a count with its noun, such as `1 file` or `2 files`."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _printable(text: str) -> str:
    """Escape characters, such as a line feed in a file name, that break a line."""
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)
