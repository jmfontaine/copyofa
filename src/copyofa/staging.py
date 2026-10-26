"""Create a destination through a staging directory, and write a bag's tag files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import copyofa
from copyofa import evidence_set
from copyofa.errors import CopyOfAError

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from datetime import datetime

STAGING_SUFFIX = ".copyofa-staging"

_COMMANDS = "import, acquire or export"
"""The commands that create a staging directory, as a refusal names them."""

T = TypeVar("T")


class StagingError(CopyOfAError):
    """A destination that was refused, or a result that could not be accepted."""


@dataclass(frozen=True)
class Destination:
    """A destination to create, checked, with the staging directory beside it."""

    given: str
    """The destination as given on the command line."""
    target: Path
    """The destination's absolute path, its parent resolved."""
    staging: Path
    """Where the result is written before it is renamed to target."""


def require_utf8(
    text: str, what: str, requirement: str = "BagIt manifests require"
) -> None:
    """Refuse text, such as a path with bytes that are not UTF-8, it cannot encode."""
    try:
        text.encode()
    except UnicodeEncodeError:
        raise StagingError(
            f"Refused: {what} is not valid UTF-8, which {requirement}."
        ) from None


def check_destination(given: str) -> Destination:
    """Check a destination to create; return it with its staging directory.

    Refuses a destination that exists, whose parent does not, whose path is not
    valid UTF-8, or beside which a staging directory was left.
    """
    path = Path(given).absolute()
    if path.name in {"", ".", ".."} or os.path.lexists(path):
        raise StagingError(f"Refused: destination {given} already exists.")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise StagingError(
            f"Refused: the parent of destination {given} does not exist."
        )
    target = parent / path.name
    require_utf8(str(target), f"destination {given}")
    staging = parent / f"{path.name}{STAGING_SUFFIX}"
    if os.path.lexists(staging):
        raise StagingError(
            f"Refused: a staging directory left by an earlier {_COMMANDS} exists at "
            f"{staging}. Check it, then remove it."
        )
    return Destination(given, target, staging)


def identity(path: Path) -> tuple[int, int]:
    """Identify a file or directory on its volume, whatever path names it."""
    info = path.stat()
    return info.st_dev, info.st_ino


def ancestors(path: Path) -> set[tuple[int, int]]:
    """Identify every directory that holds path."""
    return {identity(parent) for parent in path.parents}


def accept(
    destination: Destination, command: str, build: Callable[[Path], T]
) -> tuple[T, tuple[str, ...]]:
    """Create the staging directory, let build fill it, then rename it to the target.

    Returns what build returns, with the warnings that did not fail the command.
    When build raises, or the command fails or is canceled before the result is
    accepted, removes what it created, never a staging directory it did not create.
    """
    target, staging = destination.target, destination.staging
    try:
        parent_fd = os.open(target.parent, os.O_RDONLY)
    except OSError as error:
        raise StagingError(
            f"Refused: cannot open the parent of destination {destination.given}: "
            f"{error.strerror}."
        ) from None
    created: Path | None = None
    warnings: list[str] = []
    try:
        with interrupt_deferred():
            try:
                staging.mkdir()
            except FileExistsError:
                raise StagingError(
                    f"Refused: a staging directory already exists at {staging}."
                ) from None
            created = staging
        result = build(staging)
        if os.path.lexists(target):
            raise StagingError(f"Failed: {target} appeared during the {command}.")
        with interrupt_deferred():
            staging.rename(target)
            created = target
        try:
            os.fsync(parent_fd)
        except OSError as error:
            # The result is complete and accepted; only the rename's durability is
            # in doubt, which deleting it would not improve.
            warnings.append(
                f"could not sync {target.parent} after creating {target}: "
                f"{error.strerror}. {target.name} is complete."
            )
    except BaseException:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
        raise
    finally:
        os.close(parent_fd)
    return result, tuple(warnings)


@contextmanager
def interrupt_deferred() -> Generator[None]:
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


def build_bag(
    root: Path,
    payload: Sequence[tuple[str, str, int]],
    record_path: str,
    record: dict[str, Any],
    bagged_at: datetime,
) -> int:
    """Write the tag files of a bag whose payload is already under root.

    payload lists each stored file as (path in the bag, SHA-256, size), in manifest
    order; record is written at record_path. Returns the payload size.
    """
    total = sum(size for _, _, size in payload)
    tag_files = {
        evidence_set.BAGIT_TXT: evidence_set.BAGIT_TXT_CONTENT,
        evidence_set.BAG_INFO_TXT: (
            f"Bagging-Date: {bagged_at.date().isoformat()}\n"
            f"Payload-Oxum: {total}.{len(payload)}\n"
            f"Bag-Software-Agent: copyofa {copyofa.__version__}\n"
        ),
        evidence_set.MANIFEST: "".join(
            evidence_set.manifest_line(digest, path) for path, digest, _ in payload
        ),
        record_path: json.dumps(record, indent=2, ensure_ascii=False) + "\n",
    }
    tag_manifest = []
    for name, text in tag_files.items():
        data = text.encode()
        write_file(root / name, data)
        digest = hashlib.sha256(data).hexdigest()
        tag_manifest.append(evidence_set.manifest_line(digest, name))
    write_file(root / evidence_set.TAG_MANIFEST, "".join(tag_manifest).encode())
    return total


def digest_file(path: Path) -> str:
    """Return the SHA-256 of a file's content."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_file(path: Path, data: bytes) -> None:
    """Create a file with data, and sync it; refuse to replace one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def sync_file(path: Path) -> None:
    """Sync a file another library wrote, so it is durable before it is accepted."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
