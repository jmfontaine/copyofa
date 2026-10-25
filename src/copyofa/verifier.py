"""Check an Evidence Set against its Integrity Baseline."""

from __future__ import annotations

import hashlib
import os
import stat
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import copyofa
from copyofa import evidence_set
from copyofa.errors import CopyOfAError

REPORT_KIND = "copyofa.verification"
REPORT_FORMAT_VERSION = 1
SCOPE = "full_content"

MATCHING = "matching"
CHANGED = "changed"
MISSING = "missing"
UNAVAILABLE = "unavailable"
NOT_CHECKED = "not_checked"
OUTCOMES = (MATCHING, CHANGED, MISSING, UNAVAILABLE, NOT_CHECKED)

_UNUSABLE = "the Integrity Baseline is unusable"
_UNSAFE = "the path is not a normalized relative path inside the Evidence Set"


class NotAnEvidenceSetError(CopyOfAError):
    """The verify target is not an Evidence Set."""


@dataclass(frozen=True)
class _Read:
    """The bytes of a record file, or why they could not be read."""

    data: bytes | None
    problem: str | None


def verify(target: str) -> dict[str, Any]:
    """Check the Evidence Set at target and return its verification Report.

    Reads every file it checks and writes nothing.
    """
    # Absolute and without `.` or `..` segments, symbolic links kept as given.
    root = Path(os.path.abspath(target))  # noqa: PTH100
    try:
        mode: int | None = root.stat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        raise NotAnEvidenceSetError(f"{target} does not exist.") from None
    except OSError:
        # Unreachable, such as behind a directory without search permission: it
        # may be an Evidence Set, so the checks below report what cannot be read.
        mode = None
    if mode is not None and not stat.S_ISDIR(mode):
        raise NotAnEvidenceSetError(f"{target} is not a directory.")
    try:
        (root / evidence_set.BAGIT_TXT).lstat()
    except FileNotFoundError:
        raise NotAnEvidenceSetError(
            f"{target} is not an Evidence Set: it has no {evidence_set.BAGIT_TXT}."
        ) from None
    except OSError:
        pass
    checked_at = datetime.now(UTC)
    problems: list[str] = []

    # Read once: the bytes checked against the tag manifest are the bytes parsed.
    manifest = _read_record(root, evidence_set.MANIFEST)
    tag_files = _check_tag_files(root, manifest, problems)

    baseline_id = None
    entries = None
    if manifest.data is None:
        problems.append(f"{evidence_set.MANIFEST} {manifest.problem}.")
    else:
        baseline_id = hashlib.sha256(manifest.data).hexdigest()
        entries = _parse(manifest.data, evidence_set.MANIFEST, problems)
    if entries is not None:
        for _, path in entries:
            if not evidence_set.is_payload_path(path):
                problems.append(
                    f"{evidence_set.MANIFEST} lists {path!r}, which is not a "
                    f"normalized relative path under {evidence_set.PAYLOAD_DIR}/."
                )

    usable = not problems
    payload: list[dict[str, str]] = []
    for digest, path in entries or []:
        if usable:
            payload.append(_check_file(root, path, digest))
        else:
            payload.append(_not_checked(path, digest, _UNUSABLE))

    unexpected: list[str] = []
    unexamined: list[dict[str, str]] = []
    if usable:
        listed = {path for _, path in entries or []}
        _find_unexpected(root, listed, unexpected, unexamined)
        unexpected.sort()

    counts = Counter(item["outcome"] for item in payload)
    return {
        "report_kind": REPORT_KIND,
        "format_version": REPORT_FORMAT_VERSION,
        "copyofa_version": copyofa.__version__,
        "checked_at": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_set": str(root),
        "scope": SCOPE,
        "integrity_baseline": {
            # Absent, not null, when manifest-sha256.txt cannot be read.
            **({} if baseline_id is None else {"manifest_sha256": baseline_id}),
            "usable": usable,
            "problems": problems,
        },
        "tag_files": tag_files,
        "payload": payload,
        "unexpected_files": unexpected,
        "unexamined_directories": unexamined,
        "counts": {
            **{outcome: counts[outcome] for outcome in OUTCOMES},
            "unexpected": len(unexpected),
        },
    }


def is_intact(report: dict[str, Any]) -> bool:
    """Tell whether a Report found every record and payload file intact."""
    return (
        report["integrity_baseline"]["usable"]
        and all(item["outcome"] == MATCHING for item in report["tag_files"])
        and all(item["outcome"] == MATCHING for item in report["payload"])
        and not report["unexpected_files"]
        and not report["unexamined_directories"]
    )


def _check_tag_files(
    root: Path, manifest: _Read, problems: list[str]
) -> list[dict[str, str]]:
    tag_manifest = _read_record(root, evidence_set.TAG_MANIFEST)
    if tag_manifest.data is None:
        problems.append(f"{evidence_set.TAG_MANIFEST} {tag_manifest.problem}.")
        return []
    entries = _parse(tag_manifest.data, evidence_set.TAG_MANIFEST, problems)
    if entries is None:
        return []
    results = []
    for digest, path in entries:
        if not evidence_set.is_bag_path(path):
            problems.append(
                f"{evidence_set.TAG_MANIFEST} lists {path!r}, which is not a "
                "normalized relative path inside the Evidence Set."
            )
            results.append(_not_checked(path, digest, _UNSAFE))
        elif path == evidence_set.MANIFEST and manifest.data is not None:
            observed = hashlib.sha256(manifest.data).hexdigest()
            results.append(_item(path, digest, None, observed, None))
        else:
            results.append(_check_file(root, path, digest))
    checked = next(
        (item for item in results if item["path"] == evidence_set.MANIFEST), None
    )
    if checked is None:
        problems.append(
            f"{evidence_set.TAG_MANIFEST} does not list {evidence_set.MANIFEST}."
        )
    elif checked["outcome"] != MATCHING and manifest.data is not None:
        # When it could not be read, verify reports that cause once.
        problems.append(
            f"{evidence_set.MANIFEST} fails its check: {checked['outcome']}."
        )
    return results


def _read_record(root: Path, name: str) -> _Read:
    path = root / name
    try:
        # Non-blocking, so a named pipe in place of a record cannot hang verify.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return _Read(None, "is missing")
    except OSError as error:
        return _Read(None, f"cannot be read: {error.strerror}")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return _Read(None, "is not a regular file")
        with os.fdopen(os.dup(fd), "rb") as file:
            return _Read(file.read(), None)
    except OSError as error:
        return _Read(None, f"cannot be read: {error.strerror}")
    finally:
        os.close(fd)


def _parse(data: bytes, name: str, problems: list[str]) -> list[tuple[str, str]] | None:
    try:
        return evidence_set.parse_manifest(data)
    except evidence_set.ManifestError as error:
        problems.append(f"{name} cannot be parsed: {error}.")
        return None


def _not_checked(path: str, digest: str, reason: str) -> dict[str, str]:
    return {
        "path": path,
        "outcome": NOT_CHECKED,
        "expected_digest": digest,
        "reason": reason,
    }


def _check_file(root: Path, path: str, expected: str) -> dict[str, str]:
    """Check one listed file, following no symbolic link inside the set."""
    return _item(path, expected, *_examine(root, path))


def _item(
    path: str,
    expected: str,
    outcome: str | None,
    observed: str | None,
    reason: str | None,
) -> dict[str, str]:
    """Build a Report item; no outcome means the file was read completely."""
    if outcome is None:
        outcome = MATCHING if observed == expected else CHANGED
    if outcome == CHANGED:
        reason = "its digest differs from the manifest's"
    result = {"path": path, "outcome": outcome, "expected_digest": expected}
    if observed is not None:
        result["observed_digest"] = observed
    if reason is not None:
        result["reason"] = reason
    return result


def _examine(root: Path, path: str) -> tuple[str | None, str | None, str | None]:
    """Return (outcome, observed digest, reason); no outcome when it was read."""
    current = root
    parts = path.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            if not root.is_dir():
                return UNAVAILABLE, None, "the Evidence Set is no longer reachable"
            return MISSING, None, "the file does not exist"
        except OSError as error:
            return UNAVAILABLE, None, f"cannot be examined: {error.strerror}"
        last = index == len(parts) - 1
        if stat.S_ISLNK(mode):
            return UNAVAILABLE, None, "a symbolic link, which is not followed"
        if not last and not stat.S_ISDIR(mode):
            return MISSING, None, "the file does not exist"
    if stat.S_ISDIR(mode):
        return UNAVAILABLE, None, "a directory, not a regular file"
    if not stat.S_ISREG(mode):
        return UNAVAILABLE, None, "a special file, not a regular file"
    try:
        return None, _digest(current), None
    except OSError as error:
        return UNAVAILABLE, None, f"cannot be read: {error.strerror}"


def _digest(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _find_unexpected(
    root: Path,
    listed: set[str],
    unexpected: list[str],
    unexamined: list[dict[str, str]],
) -> None:
    """List files under data/ that the manifest does not list."""
    try:
        reason = _not_a_directory((root / evidence_set.PAYLOAD_DIR).lstat().st_mode)
    except FileNotFoundError:
        return
    except OSError as error:
        reason = error.strerror or ""
    if reason is not None:
        unexamined.append({"path": evidence_set.PAYLOAD_DIR, "reason": reason})
        return
    pending = [evidence_set.PAYLOAD_DIR]
    while pending:
        relative = pending.pop()
        try:
            names = sorted(child.name for child in (root / relative).iterdir())
        except FileNotFoundError:
            continue
        except OSError as error:
            unexamined.append({"path": relative, "reason": error.strerror or ""})
            continue
        for name in names:
            path = f"{relative}/{name}"
            try:
                mode = (root / path).lstat().st_mode
            except FileNotFoundError:
                continue
            except OSError as error:
                unexamined.append({"path": path, "reason": error.strerror or ""})
                continue
            if stat.S_ISDIR(mode):
                pending.append(path)
            elif path not in listed and not evidence_set.is_os_metadata(name):
                unexpected.append(path)


def _not_a_directory(mode: int) -> str | None:
    """Say why a path with this mode cannot be searched, or None if it can."""
    if stat.S_ISLNK(mode):
        return "a symbolic link, which is not followed"
    if not stat.S_ISDIR(mode):
        return "not a directory"
    return None
