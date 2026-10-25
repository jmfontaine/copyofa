from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import requires_permissions, snapshot

import copyofa
from copyofa import importer

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Run

BAG_FILES = {
    "bagit.txt",
    "bag-info.txt",
    "manifest-sha256.txt",
    "tagmanifest-sha256.txt",
    "data",
    "copyofa",
}
TAG_FILES = {
    "bagit.txt",
    "bag-info.txt",
    "manifest-sha256.txt",
    "copyofa/import-record.json",
}
OS_METADATA = [".DS_Store", "._01.flac", "Icon\r", "Thumbs.db", "desktop.ini"]


@pytest.fixture
def album(tmp_path: Path) -> Path:
    root = tmp_path / "Downloads" / "Album"
    (root / "scans").mkdir(parents=True)
    (root / "01.flac").write_bytes(b"fLaC" + bytes(range(256)) * 64)
    (root / "cover.jpg").write_bytes(b"\xff\xd8 cover")
    (root / "scans.zip").write_bytes(b"PK\x03\x04 scans")
    (root / ".hidden").write_bytes(b"hidden but preserved")
    (root / "100% pure").write_bytes(b"percent")
    (root / "line\n feed").write_bytes(b"line feed")
    (root / "carriage\r return").write_bytes(b"carriage return")
    (root / "scans" / "back.png").write_bytes(b"\x89PNG back")
    return root


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    path = tmp_path / "Archive"
    path.mkdir()
    return path


def decode(path: str) -> str:
    codes = {"%0D": "\r", "%0A": "\n", "%25": "%"}
    return re.sub("%0D|%0A|%25", lambda match: codes[match.group()], path)


def read_manifest(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)\n", line)
        assert match, f"malformed manifest line {line!r}"
        entries[decode(match.group(2))] = match.group(1)
    return entries


def payload_files(bag: Path) -> set[str]:
    return {
        str(path.relative_to(bag))
        for path in (bag / "data").rglob("*")
        if path.is_file()
    }


def record_of(bag: Path) -> dict:
    return json.loads((bag / "copyofa" / "import-record.json").read_text())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def staging_of(destination: Path) -> Path:
    return destination.with_name(destination.name + importer.STAGING_SUFFIX)


def test_import_creates_bag_with_identical_payload(
    run: Run, tmp_path: Path, album: Path, archive: Path
) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_bytes(b"liner notes")
    destination = archive / "Album"

    outcome = run("import", album, notes, "--to", destination)

    assert outcome.code == 0, outcome.err
    assert {path.name for path in destination.iterdir()} == BAG_FILES
    assert [p.name for p in (destination / "copyofa").iterdir()] == [
        "import-record.json"
    ]
    assert (destination / "bagit.txt").read_bytes() == (
        b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
    )

    manifest = read_manifest(destination / "manifest-sha256.txt")
    assert set(manifest) == payload_files(destination)
    sources = {f"data/Album/{p.relative_to(album)}": p for p in album.rglob("*")}
    sources["data/notes.txt"] = notes
    assert set(manifest) == {path for path, p in sources.items() if p.is_file()}
    for path, digest in manifest.items():
        stored = (destination / path).read_bytes()
        assert stored == sources[path].read_bytes()
        assert sha256(stored) == digest

    raw_manifest = (destination / "manifest-sha256.txt").read_text()
    assert "  data/Album/100%25 pure\n" in raw_manifest
    assert "  data/Album/line%0A feed\n" in raw_manifest
    assert "  data/Album/carriage%0D return\n" in raw_manifest

    tag_manifest = read_manifest(destination / "tagmanifest-sha256.txt")
    assert set(tag_manifest) == TAG_FILES
    for path, digest in tag_manifest.items():
        assert sha256((destination / path).read_bytes()) == digest

    info = (destination / "bag-info.txt").read_text().splitlines()
    total = sum(sources[path].stat().st_size for path in manifest)
    assert info == [
        f"Bagging-Date: {record_of(destination)['imported_at'][:10]}",
        f"Payload-Oxum: {total}.{len(manifest)}",
        f"Bag-Software-Agent: copyofa {copyofa.__version__}",
    ]
    assert outcome.out.startswith(f"Accepted Evidence Set {destination}\n")
    assert f"Preserved {len(manifest)} files, {total} bytes\n" in outcome.out


def test_import_reports_progress_per_file_on_stderr(
    run: Run, album: Path, archive: Path
) -> None:
    destination = archive / "Album"

    outcome = run("import", album, "--to", destination)

    assert outcome.code == 0
    preserved = [
        line for line in outcome.err.splitlines() if line.startswith("Preserved ")
    ]
    assert len(preserved) == len(read_manifest(destination / "manifest-sha256.txt"))
    assert "Preserved data/Album/01.flac (16388 bytes)" in preserved
    assert "Preserved data/Album/line\\n feed (9 bytes)" in preserved


def test_import_record_holds_provenance_exactly_as_supplied(
    run: Run, album: Path, archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(album.parent)
    destination = archive / "Album"
    note = "Bandcamp purchase\nfor the 24-bit café edition  "
    started = datetime.now(UTC).replace(microsecond=0)

    outcome = run(
        "import",
        "Album",
        "--to",
        destination,
        "--note",
        note,
        "--ref",
        "discogs=r123456",
        "--ref",
        "musicbrainz=b2c3",
        "--ref",
        "discogs=r123456",
    )

    assert outcome.code == 0, outcome.err
    record = record_of(destination)
    imported_at = datetime.strptime(record.pop("imported_at"), "%Y-%m-%dT%H:%M:%S%z")
    assert started <= imported_at <= datetime.now(UTC) + timedelta(seconds=1)
    assert record == {
        "record_kind": "copyofa.import",
        "format_version": 1,
        "copyofa_version": copyofa.__version__,
        "sources": [
            {"given": "Album", "resolved": str(album), "stored_as": "data/Album"}
        ],
        "note": note,
        "external_references": [
            "discogs=r123456",
            "musicbrainz=b2c3",
            "discogs=r123456",
        ],
        "exclusions": [],
    }


def test_import_record_omits_provenance_not_supplied(
    run: Run, album: Path, archive: Path
) -> None:
    destination = archive / "Album"

    assert run("import", album, "--to", destination).code == 0

    record = record_of(destination)
    assert "note" not in record
    assert "external_references" not in record


def test_import_accounts_for_every_file_not_preserved(
    run: Run, album: Path, archive: Path
) -> None:
    for name in OS_METADATA:
        (album / name).write_bytes(b"metadata")
    (album / "scans" / ".DS_Store").write_bytes(b"metadata")
    (album / "link").symlink_to("01.flac")
    (album / "dangling").symlink_to("nowhere")
    os.mkfifo(album / "pipe")
    (album / "empty").mkdir()
    (album / "work" / "deep").mkdir(parents=True)
    (album / "work" / "deep" / "draft.flac").write_bytes(b"draft")
    (album / "work" / "todo.txt").write_bytes(b"todo")
    (album / "upload.tmp").write_bytes(b"partial")
    destination = archive / "Album"

    outcome = run(
        "import",
        album,
        "--to",
        destination,
        "--exclude",
        "work",
        "--exclude",
        "*.tmp",
        "--exclude",
        "Album/scans/*.png",
    )

    assert outcome.code == 0, outcome.err
    exclusions = record_of(destination)["exclusions"]
    assert sorted(exclusions, key=lambda item: item["path"]) == sorted(
        [
            *(
                {"path": f"data/Album/{name}", "reason": "operating_system_metadata"}
                for name in OS_METADATA
            ),
            {
                "path": "data/Album/scans/.DS_Store",
                "reason": "operating_system_metadata",
            },
            {"path": "data/Album/link", "reason": "symbolic_link"},
            {"path": "data/Album/dangling", "reason": "symbolic_link"},
            {"path": "data/Album/pipe", "reason": "special_file"},
            {"path": "data/Album/empty", "reason": "empty_directory"},
            {"path": "data/Album/work", "reason": "exclude_pattern", "pattern": "work"},
            {
                "path": "data/Album/upload.tmp",
                "reason": "exclude_pattern",
                "pattern": "*.tmp",
            },
            {
                "path": "data/Album/scans/back.png",
                "reason": "exclude_pattern",
                "pattern": "Album/scans/*.png",
            },
        ],
        key=lambda item: item["path"],
    )

    manifest = read_manifest(destination / "manifest-sha256.txt")
    excluded = [item["path"] for item in exclusions]
    for path in album.rglob("*"):
        if path.is_file() and not path.is_symlink():
            stored = f"data/Album/{path.relative_to(album)}"
            assert (stored in manifest) != any(
                stored == item or stored.startswith(f"{item}/") for item in excluded
            ), stored
    assert "data/Album/.hidden" in manifest

    sizes = sum((destination / path).stat().st_size for path in manifest)
    assert (
        f"Payload-Oxum: {sizes}.{len(manifest)}\n"
        in (destination / "bag-info.txt").read_text()
    )
    assert "  data/Album/work: exclude pattern work\n" in outcome.out


@requires_permissions
@pytest.mark.parametrize("name", ["cover.jpg", "scans"])
def test_import_fails_on_unreadable_input_until_excluded(
    run: Run, album: Path, archive: Path, name: str
) -> None:
    unreadable = album / name
    unreadable.chmod(0)
    destination = archive / "Album"
    try:
        refused = run("import", album, "--to", destination)

        assert refused.code == 1
        assert refused.out == ""
        assert str(unreadable) in refused.err
        assert "Preserved" not in refused.err
        assert list(archive.iterdir()) == []

        accepted = run("import", album, "--to", destination, "--exclude", name)

        assert accepted.code == 0, accepted.err
        assert record_of(destination)["exclusions"] == [
            {"path": f"data/Album/{name}", "reason": "exclude_pattern", "pattern": name}
        ]
    finally:
        unreadable.chmod(0o755)


def corrupting_transfer(
    original: Callable[[int, int, Path], tuple[str, int]],
) -> Callable[[int, int, Path], tuple[str, int]]:
    def transfer(source_fd: int, target_fd: int, source: Path) -> tuple[str, int]:
        result = original(source_fd, target_fd, source)
        os.pwrite(target_fd, b"X", 0)
        return result

    return transfer


def growing_transfer(
    original: Callable[[int, int, Path], tuple[str, int]],
) -> Callable[[int, int, Path], tuple[str, int]]:
    def transfer(source_fd: int, target_fd: int, source: Path) -> tuple[str, int]:
        result = original(source_fd, target_fd, source)
        with source.open("ab") as file:
            file.write(b"more")
        return result

    return transfer


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        (corrupting_transfer, "does not match its source"),
        (growing_transfer, "changed while it was being copied"),
    ],
)
def test_import_fails_when_a_stored_copy_cannot_be_trusted(
    run: Run,
    album: Path,
    archive: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: Callable[..., Callable[[int, int, Path], tuple[str, int]]],
    message: str,
) -> None:
    monkeypatch.setattr(importer, "_transfer", fault(importer._transfer))
    destination = archive / "Album"

    outcome = run("import", album, "--to", destination, "--json")

    assert outcome.code == 1
    assert outcome.out == ""
    assert message in outcome.err
    assert list(archive.iterdir()) == []


def make_refusal(
    tmp_path: Path, album: Path, archive: Path, case: str
) -> list[Path | str]:
    destination = archive / "Album"
    if case == "existing destination":
        destination.mkdir()
        return [album, "--to", destination]
    if case == "missing destination parent":
        return [album, "--to", tmp_path / "Missing" / "Album"]
    if case == "destination inside a source":
        return [album, "--to", album / "scans" / "Bag"]
    if case == "nonexistent source":
        return [album, tmp_path / "Nope", "--to", destination]
    if case == "symbolic link source":
        (tmp_path / "Link").symlink_to(album)
        return [tmp_path / "Link", "--to", destination]
    if case == "shared base names":
        (tmp_path / "Other" / "album").mkdir(parents=True)
        (tmp_path / "Other" / "album" / "x").write_bytes(b"x")
        return [album, tmp_path / "Other" / "album", "--to", destination]
    if case == "nested sources":
        return [album, album / "scans" / "back.png", "--to", destination]
    if case == "repeated sources":
        return [album, album.parent / ".." / "Downloads" / "Album", "--to", destination]
    if case == "nothing to preserve":
        (tmp_path / "Empty" / "sub").mkdir(parents=True)
        (tmp_path / "Empty" / ".DS_Store").write_bytes(b"metadata")
        return [tmp_path / "Empty", "--to", destination]
    if case == "leftover staging directory":
        staging_of(destination).mkdir()
        (staging_of(destination) / "partial").write_bytes(b"partial")
        return [album, "--to", destination]
    raise AssertionError(case)


REFUSALS = {
    "existing destination": "already exists",
    "missing destination parent": "does not exist",
    "destination inside a source": "lies inside source",
    "nonexistent source": "Nope does not exist",
    "symbolic link source": "is a symbolic link",
    "shared base names": "share the base name",
    "nested sources": "lie one inside the other",
    "repeated sources": "are the same file or directory",
    "nothing to preserve": "no file to preserve",
    "leftover staging directory": "Album.copyofa-staging",
}


@pytest.mark.parametrize("output", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize("case", REFUSALS)
def test_import_refuses_before_copying_anything(
    run: Run, tmp_path: Path, album: Path, archive: Path, case: str, output: list
) -> None:
    args = make_refusal(tmp_path, album, archive, case)
    before = snapshot(tmp_path)

    outcome = run("import", *args, *output)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.startswith("copyofa: Refused: ")
    assert REFUSALS[case] in outcome.err
    assert snapshot(tmp_path) == before


def test_import_cleans_up_when_canceled(
    run: Run,
    album: Path,
    archive: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = importer._transfer
    calls = []

    def interrupted(source_fd: int, target_fd: int, source: Path) -> tuple[str, int]:
        calls.append(source)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return original(source_fd, target_fd, source)

    monkeypatch.setattr(importer, "_transfer", interrupted)
    destination = archive / "Album"
    before = snapshot(album)

    outcome = run("import", album, "--to", destination, "--json")

    assert outcome.code == 130
    assert outcome.out == ""
    assert len(calls) == 2
    assert list(archive.iterdir()) == []
    assert snapshot(album) == before


def test_import_removes_destination_when_canceled_after_rename(
    run: Run, album: Path, archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsync = os.fsync

    def interrupted_on_directories(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise KeyboardInterrupt
        fsync(fd)

    monkeypatch.setattr(os, "fsync", interrupted_on_directories)

    outcome = run("import", album, "--to", archive / "Album")

    assert outcome.code == 130
    assert outcome.out == ""
    assert list(archive.iterdir()) == []


@pytest.mark.parametrize("operation", ["mkdir", "rename"])
def test_import_cleans_up_when_ctrl_c_arrives_right_after_creating(
    run: Run,
    album: Path,
    archive: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    original = getattr(Path, operation)

    def interrupted(self: Path, *args: object, **kwargs: object) -> object:
        result = original(self, *args, **kwargs)
        if self.name.endswith(importer.STAGING_SUFFIX):
            signal.raise_signal(signal.SIGINT)
        return result

    monkeypatch.setattr(Path, operation, interrupted)

    outcome = run("import", album, "--to", archive / "Album")

    assert outcome.code == 130
    assert outcome.out == ""
    assert list(archive.iterdir()) == []


def test_import_prints_json_result(run: Run, album: Path, archive: Path) -> None:
    (album / ".DS_Store").write_bytes(b"metadata")
    destination = archive / "Album"

    outcome = run("import", album, "--to", destination, "--json", "--note", "n")

    assert outcome.code == 0
    result = json.loads(outcome.out)
    manifest = read_manifest(destination / "manifest-sha256.txt")
    assert result == {
        "evidence_set": str(destination),
        "import_record": record_of(destination),
        "counts": {
            "files": len(manifest),
            "bytes": sum((destination / path).stat().st_size for path in manifest),
            "exclusions": 1,
        },
    }


@pytest.mark.parametrize(
    "args",
    [
        ["import", "Album"],
        ["import", "--to", "Bag"],
        ["import", "Album", "--to", "Bag", "--note", "a", "--note", "b"],
        [],
    ],
    ids=["no destination", "no source", "repeated note", "no command"],
)
def test_invalid_arguments_exit_2_without_output(
    run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Album").mkdir()
    (tmp_path / "Album" / "x").write_bytes(b"x")

    outcome = run(*args)

    assert outcome.code == 2
    assert outcome.out == ""
    assert not (tmp_path / "Bag").exists()
