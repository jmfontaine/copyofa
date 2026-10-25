from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from conftest import requires_permissions, snapshot

import copyofa
from copyofa import verifier

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Outcome, Run

FILES = {
    "01.flac": b"fLaC one" * 100,
    "02.flac": b"fLaC two",
    "03.flac": b"fLaC three",
    "04.flac": b"fLaC four",
    "05.flac": b"fLaC five",
    "cover.jpg": b"\xff\xd8 cover",
    "100% pure": b"percent",
    "line\n feed": b"line feed",
}
PAYLOAD = sorted(f"data/Album/{name}" for name in FILES)
TAG_FILES = [
    "bagit.txt",
    "bag-info.txt",
    "manifest-sha256.txt",
    "copyofa/import-record.json",
]


@pytest.fixture
def bag(run: Run, tmp_path: Path) -> Path:
    source = tmp_path / "Downloads" / "Album"
    source.mkdir(parents=True)
    for name, data in FILES.items():
        (source / name).write_bytes(data)
    destination = tmp_path / "Archive" / "Album"
    destination.parent.mkdir()
    outcome = run("import", source, "--to", destination)
    assert outcome.code == 0, outcome.err
    return destination


def verify(run: Run, bag: Path) -> tuple[Outcome, dict]:
    outcome = run("verify", bag, "--json")
    return outcome, json.loads(outcome.out)


def outcomes(report: dict) -> dict[str, str]:
    return {item["path"]: item["outcome"] for item in report["payload"]}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rewrite(bag: Path, name: str, change: Callable[[str], str]) -> None:
    """Change a manifest, then update the tag manifest to match it."""
    path = bag / name
    path.write_text(change(path.read_text()))
    if name != "tagmanifest-sha256.txt":
        tag_manifest = bag / "tagmanifest-sha256.txt"
        digest = sha256(path.read_bytes())
        tag_manifest.write_text(
            re.sub(
                rf"^[0-9a-f]{{64}}  {re.escape(name)}$",
                f"{digest}  {name}",
                tag_manifest.read_text(),
                flags=re.MULTILINE,
            )
        )


def test_verify_finds_set_intact_after_relocation(
    run: Run, tmp_path: Path, bag: Path
) -> None:
    moved = tmp_path / "Other" / "Moved"
    moved.parent.mkdir()
    shutil.move(bag, moved)
    (moved / "data" / ".DS_Store").write_bytes(b"Finder")
    (moved / "data" / "Album" / ".DS_Store").write_bytes(b"Finder")
    (moved / "data" / "Album" / "._01.flac").write_bytes(b"AppleDouble")
    (moved / "data" / "Album" / "Icon\r").write_bytes(b"icon")
    (moved / "copyofa" / "recovery").mkdir()
    (moved / "copyofa" / "recovery" / "Album.par2").write_bytes(b"PAR2")

    outcome, report = verify(run, moved)

    assert outcome.code == 0, outcome.err
    assert outcomes(report) == dict.fromkeys(PAYLOAD, "matching")
    assert report["unexpected_files"] == []
    assert report["evidence_set"] == str(moved)

    text = run("verify", moved)
    assert text.code == 0
    assert text.out.endswith("Result: intact\n")


@requires_permissions
def test_verify_reports_each_payload_problem(run: Run, bag: Path) -> None:
    album = bag / "data" / "Album"
    with (album / "01.flac").open("ab") as file:
        file.write(b"damage")
    (album / "02.flac").unlink()
    (album / "03.flac").chmod(0)
    (album / "04.flac").unlink()
    (album / "04.flac").mkdir()
    (album / "05.flac").unlink()
    (album / "05.flac").symlink_to("cover.jpg")
    (bag / "data" / "extra.txt").write_bytes(b"extra")
    (album / "new").mkdir()
    (album / "new" / "track.flac").write_bytes(b"new")
    (bag / "copyofa" / "recovery").mkdir()
    (bag / "copyofa" / "recovery" / "Album.par2").write_bytes(b"PAR2")
    try:
        outcome, report = verify(run, bag)
        text = run("verify", bag)
    finally:
        (album / "03.flac").chmod(0o644)

    assert outcome.code == 1
    assert outcomes(report) == {
        **dict.fromkeys(PAYLOAD, "matching"),
        "data/Album/01.flac": "changed",
        "data/Album/02.flac": "missing",
        "data/Album/03.flac": "unavailable",
        "data/Album/04.flac": "unavailable",
        "data/Album/05.flac": "unavailable",
    }
    assert report["unexpected_files"] == [
        "data/Album/new/track.flac",
        "data/extra.txt",
    ]
    assert report["counts"] == {
        "matching": 3,
        "changed": 1,
        "missing": 1,
        "unavailable": 3,
        "not_checked": 0,
        "unexpected": 2,
    }
    for item in report["payload"]:
        assert ("reason" in item) == (item["outcome"] != "matching")
        assert ("observed_digest" in item) == (
            item["outcome"] in {"matching", "changed"}
        )
    changed = report["payload"][PAYLOAD.index("data/Album/01.flac")]
    assert changed["observed_digest"] == sha256(FILES["01.flac"] + b"damage")
    assert changed["expected_digest"] == sha256(FILES["01.flac"])
    assert "Permission denied" in outcomes_reasons(report)["data/Album/03.flac"]

    assert text.code == 1
    assert "  changed: data/Album/01.flac\n" in text.out
    assert "  missing: data/Album/02.flac (the file does not exist)\n" in text.out
    assert "  data/extra.txt\n" in text.out
    assert text.out.endswith("Result: problems found\n")


def outcomes_reasons(report: dict) -> dict[str, str]:
    return {item["path"]: item.get("reason", "") for item in report["payload"]}


def edit_manifest_digest(bag: Path) -> None:
    path = bag / "manifest-sha256.txt"
    text = path.read_text()
    path.write_text(("0" if text[0] != "0" else "1") + text[1:])


def add_line(name: str, path: str) -> Callable[[Path], None]:
    def damage(bag: Path) -> None:
        rewrite(bag, name, lambda text: f"{text}{'0' * 64}  {path}\n")

    return damage


def drop_manifest_entry(bag: Path) -> None:
    rewrite(
        bag,
        "tagmanifest-sha256.txt",
        lambda text: re.sub(
            r"^.*  manifest-sha256\.txt\n", "", text, flags=re.MULTILINE
        ),
    )


DAMAGES: dict[str, tuple[Callable[[Path], None], str]] = {
    "manifest edited": (
        edit_manifest_digest,
        "manifest-sha256.txt fails its check: changed",
    ),
    "manifest deleted": (
        lambda bag: (bag / "manifest-sha256.txt").unlink(),
        "manifest-sha256.txt is missing",
    ),
    "tag manifest deleted": (
        lambda bag: (bag / "tagmanifest-sha256.txt").unlink(),
        "tagmanifest-sha256.txt is missing",
    ),
    "tag manifest without manifest": (
        drop_manifest_entry,
        "tagmanifest-sha256.txt does not list manifest-sha256.txt",
    ),
    "payload entry outside the bag": (
        add_line("manifest-sha256.txt", "../outside"),
        "manifest-sha256.txt lists '../outside'",
    ),
    "payload entry absolute": (
        add_line("manifest-sha256.txt", "/etc/hosts"),
        "manifest-sha256.txt lists '/etc/hosts'",
    ),
    "payload entry outside data": (
        add_line("manifest-sha256.txt", "copyofa/import-record.json"),
        "manifest-sha256.txt lists 'copyofa/import-record.json'",
    ),
    "payload entry with dot": (
        add_line("manifest-sha256.txt", "data/./Album/01.flac"),
        "manifest-sha256.txt lists 'data/./Album/01.flac'",
    ),
    "tag entry outside the bag": (
        add_line("tagmanifest-sha256.txt", "../outside"),
        "tagmanifest-sha256.txt lists '../outside'",
    ),
    "tag entry absolute": (
        add_line("tagmanifest-sha256.txt", "/etc/hosts"),
        "tagmanifest-sha256.txt lists '/etc/hosts'",
    ),
    "manifest unparsable": (
        lambda bag: rewrite(bag, "manifest-sha256.txt", lambda t: t + "garbage\n"),
        "manifest-sha256.txt cannot be parsed",
    ),
}


@pytest.mark.parametrize("case", DAMAGES)
def test_verify_reports_damaged_records_without_trusting_them(
    run: Run, bag: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    damage, problem = DAMAGES[case]
    (bag.parent / "outside").write_bytes(b"outside the bag")
    damage(bag)
    examined = []
    original = verifier._examine

    def spy(root: Path, path: str) -> tuple[str | None, str | None, str | None]:
        examined.append(path)
        return original(root, path)

    monkeypatch.setattr(verifier, "_examine", spy)

    outcome, report = verify(run, bag)

    assert outcome.code == 1
    baseline = report["integrity_baseline"]
    assert baseline["usable"] is False
    assert any(item.startswith(problem) for item in baseline["problems"]), baseline
    assert "matching" not in outcomes(report).values()
    assert report["unexpected_files"] == []
    assert not [path for path in examined if path.startswith(("data/", "/", "../"))]
    manifest = bag / "manifest-sha256.txt"
    if case == "manifest deleted":
        assert report["payload"] == []
        assert baseline["manifest_sha256"] is None
    else:
        assert baseline["manifest_sha256"] == sha256(manifest.read_bytes())
    if case in {"manifest deleted", "manifest unparsable"}:
        assert report["payload"] == []
    else:
        assert {item["outcome"] for item in report["payload"]} == {"not_checked"}
        assert set(PAYLOAD) <= set(outcomes(report))
        for item in report["payload"]:
            assert item["reason"] == "the Integrity Baseline is unusable"


def test_verify_checks_payload_when_only_import_record_is_edited(
    run: Run, bag: Path
) -> None:
    record = bag / "copyofa" / "import-record.json"
    record.write_text(record.read_text().replace("copyofa.import", "copyofa.edited"))

    outcome, report = verify(run, bag)

    assert outcome.code == 1
    assert report["integrity_baseline"]["usable"] is True
    tag_outcomes = {item["path"]: item["outcome"] for item in report["tag_files"]}
    assert tag_outcomes == {
        **dict.fromkeys(TAG_FILES, "matching"),
        "copyofa/import-record.json": "changed",
    }
    assert outcomes(report) == dict.fromkeys(PAYLOAD, "matching")
    assert "  changed: copyofa/import-record.json\n" in run("verify", bag).out


def test_verify_report_content(run: Run, bag: Path) -> None:
    before = snapshot(bag)
    started = datetime.now(UTC).replace(microsecond=0)

    outcome, report = verify(run, bag)
    run("verify", bag)

    assert outcome.code == 0
    assert snapshot(bag) == before
    checked_at = datetime.strptime(report.pop("checked_at"), "%Y-%m-%dT%H:%M:%S%z")
    assert started <= checked_at <= datetime.now(UTC) + timedelta(seconds=1)
    album = bag / "data" / "Album"
    assert report == {
        "report_kind": "copyofa.verification",
        "format_version": 1,
        "copyofa_version": copyofa.__version__,
        "evidence_set": str(bag),
        "scope": "full_content",
        "integrity_baseline": {
            "manifest_sha256": sha256((bag / "manifest-sha256.txt").read_bytes()),
            "usable": True,
            "problems": [],
        },
        "tag_files": [
            {
                "path": path,
                "outcome": "matching",
                "expected_digest": sha256((bag / path).read_bytes()),
                "observed_digest": sha256((bag / path).read_bytes()),
            }
            for path in TAG_FILES
        ],
        "payload": [
            {
                "path": f"data/Album/{name}",
                "outcome": "matching",
                "expected_digest": sha256(FILES[name]),
                "observed_digest": sha256((album / name).read_bytes()),
            }
            for name in sorted(FILES)
        ],
        "unexpected_files": [],
        "unexamined_directories": [],
        "counts": {
            "matching": len(FILES),
            "changed": 0,
            "missing": 0,
            "unavailable": 0,
            "not_checked": 0,
            "unexpected": 0,
        },
    }


@pytest.mark.parametrize("target", ["not a bag", "nonexistent", "a file"])
def test_verify_exits_2_when_target_is_not_an_evidence_set(
    run: Run, tmp_path: Path, target: str
) -> None:
    path = tmp_path / target
    if target == "not a bag":
        path.mkdir()
        (path / "manifest-sha256.txt").write_bytes(b"")
    elif target == "a file":
        path.write_bytes(b"x")

    outcome = run("verify", path, "--json")

    assert outcome.code == 2
    assert outcome.out == ""
    assert str(path) in outcome.err


def test_verify_exits_2_on_invalid_arguments(run: Run) -> None:
    outcome = run("verify")

    assert outcome.code == 2
    assert outcome.out == ""


def test_verify_canceled_prints_nothing(
    run: Run, bag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(path: Path) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(verifier, "_digest", interrupted)

    outcome = run("verify", bag, "--json")

    assert outcome.code == 130
    assert outcome.out == ""


@requires_permissions
def test_verify_reports_a_directory_it_cannot_search(run: Run, bag: Path) -> None:
    album = bag / "data" / "Album"
    album.chmod(0)
    try:
        outcome, report = verify(run, bag)
    finally:
        album.chmod(0o755)

    assert outcome.code == 1
    assert report["unexamined_directories"] == [
        {"path": "data/Album", "reason": "Permission denied"}
    ]
    assert set(outcomes(report).values()) == {"unavailable"}


def test_verify_does_not_follow_a_symlinked_payload_directory(
    run: Run, tmp_path: Path, bag: Path
) -> None:
    elsewhere = tmp_path / "Elsewhere"
    (bag / "data").rename(elsewhere)
    (elsewhere / "outside.txt").write_bytes(b"outside the set")
    (bag / "data").symlink_to(elsewhere)

    outcome, report = verify(run, bag)

    assert outcome.code == 1
    assert set(outcomes(report).values()) == {"unavailable"}
    assert report["unexpected_files"] == []
    assert report["unexamined_directories"] == [
        {"path": "data", "reason": "a symbolic link, which is not followed"}
    ]


def test_verify_searches_directories_named_like_metadata_files(
    run: Run, bag: Path
) -> None:
    (bag / "data" / "._extras").mkdir()
    (bag / "data" / "._extras" / "extra.flac").write_bytes(b"extra")
    (bag / "data" / "._extras" / "._extra.flac").write_bytes(b"AppleDouble")

    outcome, report = verify(run, bag)

    assert outcome.code == 1
    assert report["unexpected_files"] == ["data/._extras/extra.flac"]


@pytest.mark.parametrize("name", ["manifest-sha256.txt", "tagmanifest-sha256.txt"])
def test_verify_reports_a_named_pipe_in_place_of_a_manifest(
    run: Run, bag: Path, name: str
) -> None:
    (bag / name).unlink()
    os.mkfifo(bag / name)

    outcome, report = verify(run, bag)

    assert outcome.code == 1
    assert f"{name} is not a regular file." in report["integrity_baseline"]["problems"]
    assert "matching" not in outcomes(report).values()


def test_verify_checks_payload_against_the_manifest_bytes_it_authenticated(
    run: Run, bag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = bag / "manifest-sha256.txt"
    track = bag / "data" / "Album" / "01.flac"
    original = verifier._examine

    def swap_manifest(root: Path, path: str) -> tuple[str | None, ...]:
        if path == "copyofa/import-record.json":
            track.write_bytes(b"damaged")
            manifest.write_text(
                manifest.read_text().replace(
                    sha256(FILES["01.flac"]), sha256(b"damaged")
                )
            )
        return original(root, path)

    monkeypatch.setattr(verifier, "_examine", swap_manifest)

    outcome, report = verify(run, bag)

    assert outcome.code == 1
    assert outcomes(report)["data/Album/01.flac"] == "changed"


@requires_permissions
@pytest.mark.parametrize("locked", ["set", "parent"])
def test_verify_reports_a_set_it_cannot_reach(run: Run, bag: Path, locked: str) -> None:
    directory = bag if locked == "set" else bag.parent
    directory.chmod(0)
    try:
        outcome, report = verify(run, bag)
    finally:
        directory.chmod(0o755)

    assert outcome.code == 1
    baseline = report["integrity_baseline"]
    assert baseline["usable"] is False
    assert baseline["manifest_sha256"] is None
    assert (
        "tagmanifest-sha256.txt cannot be read: Permission denied."
        in baseline["problems"]
    )
    assert report["payload"] == []
