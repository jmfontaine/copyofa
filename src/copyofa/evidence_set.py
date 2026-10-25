"""The on-disk layout of an Evidence Set, a BagIt 1.0 bag (see ADR 0001)."""

from __future__ import annotations

import re

BAGIT_TXT = "bagit.txt"
BAG_INFO_TXT = "bag-info.txt"
MANIFEST = "manifest-sha256.txt"
TAG_MANIFEST = "tagmanifest-sha256.txt"
PAYLOAD_DIR = "data"
IMPORT_RECORD = "copyofa/import-record.json"

BAGIT_TXT_CONTENT = "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"

_OS_METADATA_NAMES = frozenset({".DS_Store", "Icon\r", "Thumbs.db", "desktop.ini"})


def is_os_metadata(name: str) -> bool:
    """Tell whether a file name is an operating system metadata file.

    Operating systems create and rewrite these while a collector browses folders:
    `.DS_Store`, AppleDouble files (`._*`), `Icon` followed by a carriage return,
    `Thumbs.db`, and `desktop.ini`.
    """
    return name in _OS_METADATA_NAMES or name.startswith("._")


_ENCODE = re.compile(r"[%\r\n]")
_ENCODINGS = {"%": "%25", "\r": "%0D", "\n": "%0A"}


def encode_manifest_path(path: str) -> str:
    """Percent-encode the characters RFC 8493 requires in a manifest path."""
    return _ENCODE.sub(lambda match: _ENCODINGS[match.group()], path)


def manifest_line(digest: str, path: str) -> str:
    """Format a manifest line the way `shasum -c` reads it: two spaces apart."""
    return f"{digest}  {encode_manifest_path(path)}\n"


class ManifestError(ValueError):
    """A manifest that cannot be parsed."""


_LINE = re.compile(r"([0-9a-fA-F]{64})  (.+)")
_DECODE = re.compile(r"%(25|0[AaDd])?")
_DECODINGS = {"25": "%", "0a": "\n", "0d": "\r"}


def decode_manifest_path(path: str) -> str:
    """Undo encode_manifest_path; raise ManifestError on a `%` not encoded."""

    def decode(match: re.Match[str]) -> str:
        code = match.group(1)
        if code is None:
            raise ManifestError(f"the path {path!r} holds a % that is not encoded")
        return _DECODINGS[code.lower()]

    return _DECODE.sub(decode, path)


def parse_manifest(data: bytes) -> list[tuple[str, str]]:
    """Parse a manifest into (lowercase digest, decoded path) pairs, in order.

    Raises ManifestError when the manifest is not UTF-8, a line is not a SHA-256
    digest and a path two spaces apart, or a path is listed twice.
    """
    try:
        text = data.decode()
    except UnicodeDecodeError:
        raise ManifestError("it is not valid UTF-8") from None
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    entries = []
    seen = set()
    for number, line in enumerate(lines, start=1):
        match = _LINE.fullmatch(line.removesuffix("\r"))
        if match is None:
            raise ManifestError(f"line {number} is not a SHA-256 digest and a path")
        path = decode_manifest_path(match.group(2))
        if path in seen:
            raise ManifestError(f"line {number} lists {path!r} a second time")
        seen.add(path)
        entries.append((match.group(1).lower(), path))
    return entries


def is_bag_path(path: str) -> bool:
    """Tell whether a manifest path is normalized, relative, and inside the bag."""
    return "\0" not in path and all(
        part not in {"", ".", ".."} for part in path.split("/")
    )


def is_payload_path(path: str) -> bool:
    """Tell whether a manifest path names a file under data/."""
    return is_bag_path(path) and path.startswith(f"{PAYLOAD_DIR}/")
