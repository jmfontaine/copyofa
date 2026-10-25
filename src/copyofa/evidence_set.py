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
