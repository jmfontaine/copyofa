"""Preserve selected files and directories as a new Evidence Set."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import signal
import stat
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import copyofa
from copyofa import evidence_set
from copyofa.errors import CopyOfAError

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence

IMPORT_RECORD_KIND = "copyofa.import"
IMPORT_RECORD_FORMAT_VERSION = 1
STAGING_SUFFIX = ".copyofa-staging"

_CHUNK_SIZE = 1024 * 1024


class EvidenceImportError(CopyOfAError):
    """An import that was refused or failed; no Evidence Set was created."""


@dataclass(frozen=True)
class ImportResult:
    evidence_set: Path
    import_record: dict[str, Any]
    files: int
    bytes: int
    # Problems that did not fail the import, reported on stderr.
    warnings: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "evidence_set": str(self.evidence_set),
            "import_record": self.import_record,
            "counts": {
                "files": self.files,
                "bytes": self.bytes,
                "exclusions": len(self.import_record["exclusions"]),
            },
        }


@dataclass(frozen=True)
class _Source:
    given: str
    resolved: Path
    is_dir: bool


@dataclass
class _Selection:
    # (source path, path under data/) of each file to preserve, in manifest order.
    files: list[tuple[Path, str]] = field(default_factory=list)
    exclusions: list[dict[str, str]] = field(default_factory=list)

    def exclude(self, path: str, reason: str, **details: str) -> None:
        self.exclusions.append({"path": f"data/{path}", "reason": reason, **details})


def import_evidence(
    sources: Sequence[str],
    destination: str,
    *,
    excludes: Sequence[str] = (),
    note: str | None = None,
    references: Sequence[str] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> ImportResult:
    """Copy the sources into a new Evidence Set at destination.

    Every refusal that does not depend on reading file contents happens before
    anything is copied. Files are copied into a staging directory beside the
    destination, checked, and renamed to the destination only once every check
    passes. Raises EvidenceImportError, after removing the staging directory, when the
    import is refused or fails.
    """
    imported_at = datetime.now(UTC)
    if note is not None:
        _require_utf8(note, "the --note text", "the Import Record requires")
    for reference in references or ():
        _require_utf8(reference, "a --ref value", "the Import Record requires")
    resolved_sources = [_resolve_source(given) for given in sources]
    _refuse_overlapping_sources(resolved_sources)
    target, staging = _check_destination(destination, resolved_sources)
    selection = _select(resolved_sources, excludes)
    if not selection.files:
        raise EvidenceImportError("Refused: the selection leaves no file to preserve.")

    record: dict[str, Any] = {
        "record_kind": IMPORT_RECORD_KIND,
        "format_version": IMPORT_RECORD_FORMAT_VERSION,
        "copyofa_version": copyofa.__version__,
        "imported_at": imported_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {
                "given": source.given,
                "resolved": str(source.resolved),
                "stored_as": f"{evidence_set.PAYLOAD_DIR}/{source.resolved.name}",
            }
            for source in resolved_sources
        ],
    }
    if note is not None:
        record["note"] = note
    if references is not None:
        record["external_references"] = list(references)
    record["exclusions"] = selection.exclusions

    try:
        parent_fd = os.open(target.parent, os.O_RDONLY)
    except OSError as error:
        raise EvidenceImportError(
            f"Refused: cannot open the parent of destination {destination}: "
            f"{error.strerror}."
        ) from None
    # What this import created and removes when it fails or is canceled; never
    # a staging directory it did not create.
    created: Path | None = None
    warnings: list[str] = []
    try:
        with _interrupt_deferred():
            try:
                staging.mkdir()
            except FileExistsError:
                raise EvidenceImportError(
                    f"Refused: a staging directory already exists at {staging}."
                ) from None
            created = staging
        total = _build_bag(staging, selection, record, imported_at, progress)
        if os.path.lexists(target):
            raise EvidenceImportError(f"Failed: {target} appeared during the import.")
        with _interrupt_deferred():
            staging.rename(target)
            created = target
        try:
            os.fsync(parent_fd)
        except OSError as error:
            # The set is complete and accepted; only the rename's durability is
            # in doubt, which deleting the set would not improve.
            warnings.append(
                f"could not sync {target.parent} after creating {target}: "
                f"{error.strerror}. The Evidence Set is complete."
            )
    except BaseException:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
        raise
    finally:
        os.close(parent_fd)
    return ImportResult(target, record, len(selection.files), total, tuple(warnings))


@contextmanager
def _interrupt_deferred() -> Generator[None]:
    """Hold Ctrl-C until the block ends, so an ownership change completes."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    received: list[int] = []
    previous = signal.signal(
        signal.SIGINT, lambda number, _frame: received.append(number)
    )
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        if received:
            signal.raise_signal(signal.SIGINT)


def _resolve_source(given: str) -> _Source:
    path = _resolve(given)
    name = path.name
    if not name:
        raise EvidenceImportError(f"Refused: source {given} has no base name.")
    _require_utf8(str(path), f"source {given}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise EvidenceImportError(f"Refused: source {given} does not exist.") from None
    except OSError as error:
        raise EvidenceImportError(
            f"Refused: cannot examine source {given}: {error.strerror}."
        ) from None
    if stat.S_ISLNK(mode):
        raise EvidenceImportError(
            f"Refused: source {given} is a symbolic link, which import does not "
            "follow; name its target instead."
        )
    if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        raise EvidenceImportError(
            f"Refused: source {given} is neither a regular file nor a directory."
        )
    return _Source(given, path, stat.S_ISDIR(mode))


def _resolve(given: str) -> Path:
    """Make a path absolute and resolve its parents, without following it."""
    path = Path(given).absolute()
    if path.name in {"", ".", ".."}:
        return path.resolve()
    return path.parent.resolve() / path.name


def _identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino


def _ancestors(path: Path) -> set[tuple[int, int]]:
    return {_identity(parent) for parent in path.parents}


def _refuse_overlapping_sources(sources: Sequence[_Source]) -> None:
    identities = [_identity(source.resolved) for source in sources]
    ancestors = [_ancestors(source.resolved) for source in sources]
    for i, first in enumerate(sources):
        for j in range(i + 1, len(sources)):
            second = sources[j]
            if identities[i] == identities[j]:
                raise EvidenceImportError(
                    f"Refused: sources {first.given} and {second.given} are the "
                    "same file or directory."
                )
            if identities[i] in ancestors[j] or identities[j] in ancestors[i]:
                raise EvidenceImportError(
                    f"Refused: sources {first.given} and {second.given} lie one "
                    "inside the other."
                )
    seen: dict[str, _Source] = {}
    for source in sources:
        # Compared as a case-insensitive volume would, the default on macOS.
        key = unicodedata.normalize("NFC", source.resolved.name).casefold()
        if key in seen:
            raise EvidenceImportError(
                f"Refused: sources {seen[key].given} and {source.given} share the "
                f"base name {source.resolved.name}."
            )
        seen[key] = source


def _check_destination(
    destination: str, sources: Sequence[_Source]
) -> tuple[Path, Path]:
    path = Path(destination).absolute()
    if path.name in {"", ".", ".."}:
        raise EvidenceImportError(f"Refused: destination {destination} already exists.")
    if os.path.lexists(path):
        raise EvidenceImportError(f"Refused: destination {destination} already exists.")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise EvidenceImportError(
            f"Refused: the parent of destination {destination} does not exist."
        )
    target = parent / path.name
    _require_utf8(str(target), f"destination {destination}")
    inside = _ancestors(target)
    for source in sources:
        if source.is_dir and _identity(source.resolved) in inside:
            raise EvidenceImportError(
                f"Refused: destination {destination} lies inside source {source.given}."
            )
    staging = parent / f"{path.name}{STAGING_SUFFIX}"
    if os.path.lexists(staging):
        raise EvidenceImportError(
            f"Refused: a staging directory left by an earlier import exists at "
            f"{staging}. Check it, then remove it."
        )
    return target, staging


def _select(sources: Sequence[_Source], excludes: Sequence[str]) -> _Selection:
    """List what to preserve and what to exclude, reading no file contents."""
    selection = _Selection()
    pending = [(source.resolved, source.resolved.name) for source in reversed(sources)]
    while pending:
        path, relative = pending.pop()
        name = path.name
        pattern = next(
            (
                pattern
                for pattern in excludes
                if fnmatch.fnmatchcase(name, pattern)
                or fnmatch.fnmatchcase(relative, pattern)
            ),
            None,
        )
        if pattern is not None:
            selection.exclude(relative, "exclude_pattern", pattern=pattern)
            continue
        try:
            mode = path.lstat().st_mode
        except OSError as error:
            raise EvidenceImportError(
                f"Failed: cannot examine {path}: {error.strerror}. Exclude it to "
                "import the rest."
            ) from None
        if stat.S_ISLNK(mode):
            selection.exclude(relative, "symbolic_link")
        elif stat.S_ISDIR(mode):
            try:
                names = sorted(child.name for child in path.iterdir())
            except OSError as error:
                raise EvidenceImportError(
                    f"Failed: cannot list directory {path}: {error.strerror}. "
                    "Exclude it to import the rest."
                ) from None
            if not names:
                selection.exclude(relative, "empty_directory")
            for child in reversed(names):
                _require_utf8(child, f"the name of an entry in {path}")
                pending.append((path / child, f"{relative}/{child}"))
        elif not stat.S_ISREG(mode):
            selection.exclude(relative, "special_file")
        elif evidence_set.is_os_metadata(name):
            selection.exclude(relative, "operating_system_metadata")
        else:
            _check_readable(path)
            selection.files.append((path, relative))
    return selection


def _require_utf8(
    text: str, what: str, requirement: str = "BagIt manifests require"
) -> None:
    try:
        text.encode()
    except UnicodeEncodeError:
        raise EvidenceImportError(
            f"Refused: {what} is not valid UTF-8, which {requirement}."
        ) from None


def _build_bag(
    root: Path,
    selection: _Selection,
    record: dict[str, Any],
    imported_at: datetime,
    progress: Callable[[str, int], None] | None,
) -> int:
    """Write and check the payload and tag files; return the payload size."""
    manifest: list[str] = []
    total = 0
    for source, relative in selection.files:
        stored = f"{evidence_set.PAYLOAD_DIR}/{relative}"
        target = root / stored
        digest, size = _store(source, target)
        if _digest_file(target) != digest:
            raise EvidenceImportError(
                f"Failed: the stored copy of {source} does not match its source."
            )
        manifest.append(evidence_set.manifest_line(digest, stored))
        total += size
        if progress is not None:
            progress(stored, size)

    tag_files = {
        evidence_set.BAGIT_TXT: evidence_set.BAGIT_TXT_CONTENT,
        evidence_set.BAG_INFO_TXT: (
            f"Bagging-Date: {imported_at.date().isoformat()}\n"
            f"Payload-Oxum: {total}.{len(selection.files)}\n"
            f"Bag-Software-Agent: copyofa {copyofa.__version__}\n"
        ),
        evidence_set.MANIFEST: "".join(manifest),
        evidence_set.IMPORT_RECORD: json.dumps(record, indent=2, ensure_ascii=False)
        + "\n",
    }
    tag_manifest = []
    for name, text in tag_files.items():
        data = text.encode()
        _write_file(root / name, data)
        digest = hashlib.sha256(data).hexdigest()
        tag_manifest.append(evidence_set.manifest_line(digest, name))
    _write_file(root / evidence_set.TAG_MANIFEST, "".join(tag_manifest).encode())
    return total


def _store(source: Path, target: Path) -> tuple[str, int]:
    """Copy source to target; return the SHA-256 and size of what was read."""
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise _unreadable(source, error) from None
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceImportError(f"Failed: {source} changed during the import.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            digest, size = _transfer(source_fd, target_fd, source)
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
        after = os.fstat(source_fd)
    finally:
        os.close(source_fd)
    if size != before.st_size or (after.st_size, after.st_mtime_ns) != (
        before.st_size,
        before.st_mtime_ns,
    ):
        raise EvidenceImportError(
            f"Failed: {source} changed while it was being copied."
        )
    return digest, size


def _transfer(source_fd: int, target_fd: int, source: Path) -> tuple[str, int]:
    """Copy every byte from source_fd to target_fd, hashing what is read."""
    digest = hashlib.sha256()
    size = 0
    while True:
        try:
            chunk = os.read(source_fd, _CHUNK_SIZE)
        except OSError as error:
            raise _unreadable(source, error) from None
        if not chunk:
            return digest.hexdigest(), size
        digest.update(chunk)
        size += len(chunk)
        view = memoryview(chunk)
        while view:
            view = view[os.write(target_fd, view) :]


def _check_readable(source: Path) -> None:
    """Fail before copying anything when a selected file cannot be opened."""
    try:
        os.close(os.open(source, os.O_RDONLY | os.O_NOFOLLOW))
    except OSError as error:
        raise _unreadable(source, error) from None


def _unreadable(source: Path, error: OSError) -> EvidenceImportError:
    return EvidenceImportError(
        f"Failed: cannot read {source}: {error.strerror}. Exclude it to import "
        "the rest."
    )


def _digest_file(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
