from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest
import soundfile
from conftest import closed_stdout, edit_record, signal, synthetic_disc, write_audio

from copyofa import exporter, inspector, staging

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import Run, StandIn

    MakeSet = Callable[[Callable[[Path], None]], Path]

# FLAC metadata block types that hold tags or artwork.
VORBIS_COMMENT = 4
PICTURE = 6


def metadata_blocks(path: Path) -> list[tuple[int, bytes]]:
    """List the type and content of a FLAC file's metadata blocks, in order."""
    data = path.read_bytes()
    assert data[:4] == b"fLaC"
    blocks = []
    position = 4
    while True:
        header = data[position]
        length = int.from_bytes(data[position + 1 : position + 4], "big")
        blocks.append((header & 0x7F, data[position + 4 : position + 4 + length]))
        position += 4 + length
        if header & 0x80:
            return blocks


def tags(path: Path) -> list[bytes]:
    """List the comments of a FLAC file's Vorbis comment block, and its pictures."""
    found = []
    for kind, content in metadata_blocks(path):
        if kind == PICTURE:
            found.append(content)
        elif kind == VORBIS_COMMENT:
            # The encoder's vendor string, which is not a tag, then the comments.
            vendor = int.from_bytes(content[:4], "little")
            position = 8 + vendor
            for _ in range(int.from_bytes(content[4 + vendor : position], "little")):
                length = int.from_bytes(content[position : position + 4], "little")
                found.append(content[position + 4 : position + 4 + length])
                position += 4 + length
    return found


def manifest_sha256(evidence_set: Path) -> str:
    return hashlib.sha256(
        (evidence_set / "manifest-sha256.txt").read_bytes()
    ).hexdigest()


def left_behind(destination: Path) -> list[Path]:
    """List what an export to destination left in its parent."""
    return [
        path
        for path in destination.parent.iterdir()
        if path.name.startswith(destination.name)
    ]


def test_export_writes_one_flac_file_per_track(
    run: Run, redumper: StandIn, acquired_set: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination, "--json")

    assert outcome.code == 0, outcome.err
    disc = synthetic_disc(redumper.config)
    record = json.loads((acquired_set / "copyofa/acquisition-record.json").read_bytes())
    names = [f"0{number}.flac" for number in range(1, len(disc.tracks) + 1)]
    assert sorted(path.name for path in destination.iterdir()) == names
    for name, data, recorded in zip(names, disc.tracks, record["tracks"], strict=True):
        path = destination / name
        with soundfile.SoundFile(path) as sound:
            assert (sound.format, sound.subtype) == ("FLAC", "PCM_16")
            assert (sound.samplerate, sound.channels) == (44100, 2)
            samples = sound.read(dtype="int16")
        assert samples.tobytes() == data
        assert tags(path) == []
        assert recorded["audio_digest"].endswith(hashlib.sha256(data).hexdigest())
    assert json.loads(outcome.out) == {
        "directory": str(destination),
        "evidence_set": str(acquired_set),
        "manifest_sha256": manifest_sha256(acquired_set),
        "files": [
            {
                "path": name,
                "track": recorded["number"],
                "audio_digest": recorded["audio_digest"],
            }
            for name, recorded in zip(names, record["tracks"], strict=True)
        ],
        "left_out": list(exporter.LEFT_OUT),
    }
    assert left_behind(destination) == [destination]


def test_export_human_result(run: Run, acquired_set: Path, tmp_path: Path) -> None:
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 0, outcome.err
    record = json.loads((acquired_set / "copyofa/acquisition-record.json").read_bytes())
    assert outcome.out.splitlines() == [
        f"Exported {len(record['tracks'])} tracks to {destination}",
        *(
            f"  0{track['number']}.flac: track {track['number']}, "
            f"{track['audio_digest']}"
            for track in record["tracks"]
        ),
        f"From Evidence Set {acquired_set}",
        f"Manifest SHA-256: {manifest_sha256(acquired_set)}",
        "Left out:",
        *(f"  {sentence}" for sentence in exporter.LEFT_OUT),
    ]
    assert "Exported track 1 to 01.flac" in outcome.err


def imported(make_set: MakeSet) -> Path:
    return make_set(
        lambda source: write_audio(source / "a.flac", signal(100, 2, 16), 16, "FLAC")
    )


def change_image(evidence_set: Path) -> None:
    image = evidence_set / "data/disc.scram.flac"
    data = bytearray(image.read_bytes())
    data[-1] ^= 0xFF
    image.write_bytes(bytes(data))


REFUSALS: dict[str, tuple[Callable[[Path, Path], None], str]] = {
    "a changed image": (
        lambda evidence_set, _: change_image(evidence_set),
        (
            "Refused: the disc image data/disc.scram.flac was not inspected: its "
            "digest differs from the manifest's."
        ),
    ),
    "a record that does not match the tag manifest": (
        lambda evidence_set, _: edit_record(
            evidence_set, lambda record: record.update(note="edited"), reseal=False
        ),
        "Refused: the Acquisition Record's digest differs from the tag manifest's.",
    ),
    "an unusable baseline": (
        lambda evidence_set, _: (evidence_set / "manifest-sha256.txt").unlink(),
        (
            "Refused: the Integrity Baseline of {set} is unusable: "
            "manifest-sha256.txt is missing."
        ),
    ),
    "an existing destination": (
        lambda _, destination: destination.mkdir(),
        "Refused: destination {destination} already exists.",
    ),
    "a destination inside the set": (
        lambda evidence_set, destination: None,
        "Refused: destination {inside} lies inside the Evidence Set {set}.",
    ),
}


@pytest.mark.parametrize("name", REFUSALS)
@pytest.mark.parametrize("json_option", [(), ("--json",)], ids=["text", "json"])
def test_export_refuses_and_leaves_nothing(
    run: Run,
    acquired_set: Path,
    tmp_path: Path,
    name: str,
    json_option: tuple[str, ...],
) -> None:
    change, message = REFUSALS[name]
    destination = tmp_path / "Tracks"
    inside = acquired_set / "data/Tracks"
    change(acquired_set, destination)
    if name == "a destination inside the set":
        destination = inside
    before = set(destination.parent.iterdir())

    outcome = run("export", acquired_set, "--to", destination, *json_option)

    assert outcome.code == 1
    assert outcome.out == ""
    expected = message.format(set=acquired_set, destination=destination, inside=inside)
    assert f"copyofa: {expected}\n" in outcome.err
    assert set(destination.parent.iterdir()) == before


def test_export_refuses_a_destination_inside_the_set_named_another_way(
    run: Run, acquired_set: Path
) -> None:
    alias = acquired_set.with_name(acquired_set.name.swapcase())
    if not alias.exists():
        pytest.skip("the volume compares names case-sensitively")
    destination = alias / "data/Tracks"

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 1
    assert (
        f"copyofa: Refused: destination {destination} lies inside the Evidence Set "
        f"{acquired_set}.\n"
    ) in outcome.err
    assert not destination.exists()


@pytest.mark.parametrize("json_option", [(), ("--json",)], ids=["text", "json"])
def test_export_refuses_a_set_that_is_not_an_acquired_set(
    run: Run, make_set: MakeSet, tmp_path: Path, json_option: tuple[str, ...]
) -> None:
    evidence_set = imported(make_set)
    destination = tmp_path / "Tracks"

    outcome = run("export", evidence_set, "--to", destination, *json_option)

    assert outcome.code == 1
    assert outcome.out == ""
    assert (
        f"copyofa: Refused: {evidence_set} is not an acquired set: "
        "tagmanifest-sha256.txt does not list copyofa/acquisition-record.json.\n"
    ) in outcome.err
    assert left_behind(destination) == []


def test_export_refuses_a_left_staging_directory(
    run: Run, acquired_set: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "Tracks"
    left = destination.with_name("Tracks" + staging.STAGING_SUFFIX)
    left.mkdir()
    (left / "kept").write_bytes(b"x")

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 1
    assert outcome.out == ""
    assert left_behind(destination) == [left]
    assert (left / "kept").read_bytes() == b"x"


def test_export_fails_when_the_image_gives_another_audio_digest(
    run: Run, acquired_set: Path, tmp_path: Path
) -> None:
    def change(record: dict) -> None:
        record["tracks"][1]["audio_digest"] = "pcm1:44100:2:16:" + "0" * 64

    edit_record(acquired_set, change, reseal=True)
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 1
    assert outcome.out == ""
    assert (
        "copyofa: Failed: track 2 of the image differs from its recorded Audio "
        "Digest.\n"
    ) in outcome.err
    assert left_behind(destination) == []


def test_export_fails_when_a_range_ends_after_the_image(
    run: Run, acquired_set: Path, tmp_path: Path
) -> None:
    edit_record(
        acquired_set,
        lambda record: record["tracks"][-1].update(
            frame_count=record["tracks"][-1]["frame_count"] + 10**6
        ),
        reseal=True,
    )
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 1
    assert outcome.out == ""
    assert "copyofa: Failed: track 3: the range ends after the image's " in outcome.err
    assert left_behind(destination) == []


def test_export_fails_when_a_written_file_decodes_to_another_digest(
    run: Run,
    acquired_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect_file = inspector.inspect_file

    def misread(*args: Any, **kwargs: Any) -> dict[str, Any]:
        findings = inspect_file(*args, **kwargs)
        return {**findings, "audio_digest": "pcm1:44100:2:16:" + "0" * 64}

    monkeypatch.setattr(inspector, "inspect_file", misread)
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 1
    assert outcome.out == ""
    assert (
        "copyofa: Failed: 01.flac does not decode to the recorded Audio Digest of "
        "track 1.\n"
    ) in outcome.err
    assert left_behind(destination) == []


@pytest.mark.parametrize("step", ["open", "write"])
def test_export_fails_when_a_file_cannot_be_written(
    run: Run,
    acquired_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    original = soundfile.SoundFile.__init__

    def failing(*args: Any, **kwargs: Any) -> None:
        raise soundfile.LibsndfileError(2, "")

    def failing_on_create(self: soundfile.SoundFile, *args: Any, **kwargs: Any) -> None:
        if "x" in args[1:2]:
            failing()
        original(self, *args, **kwargs)

    if step == "open":
        monkeypatch.setattr(soundfile.SoundFile, "__init__", failing_on_create)
    else:
        monkeypatch.setattr(soundfile.SoundFile, "write", failing)
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination)

    assert outcome.code == 1
    assert outcome.out == ""
    message = soundfile.LibsndfileError(2).error_string
    assert f"copyofa: Failed: cannot write 01.flac: {message}.\n" in outcome.err
    assert left_behind(destination) == []


@pytest.mark.parametrize(
    "arguments",
    [("{missing}", "--to", "{destination}"), ("{set}",)],
    ids=["not an Evidence Set", "no destination"],
)
def test_export_exits_2_for_invalid_arguments(
    run: Run, acquired_set: Path, tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    destination = tmp_path / "Tracks"

    outcome = run(
        "export",
        *(
            argument.format(
                set=acquired_set,
                missing=tmp_path / "missing",
                destination=destination,
            )
            for argument in arguments
        ),
    )

    assert outcome.code == 2
    assert outcome.out == ""
    assert left_behind(destination) == []


def test_export_refuses_a_repeated_destination(
    run: Run, acquired_set: Path, tmp_path: Path
) -> None:
    outcome = run(
        "export", acquired_set, "--to", tmp_path / "A", "--to", tmp_path / "B"
    )

    assert outcome.code == 2
    assert outcome.out == ""
    assert "--to may be given only once" in outcome.err
    assert left_behind(tmp_path / "A") == []
    assert left_behind(tmp_path / "B") == []


@pytest.mark.parametrize("options", [(), ("--json",)])
def test_export_keeps_the_directory_when_stdout_is_closed(
    run: Run, acquired_set: Path, tmp_path: Path, options: tuple[str, ...]
) -> None:
    destination = tmp_path / "Tracks"

    with closed_stdout():
        outcome = run("export", acquired_set, "--to", destination, *options)

    assert outcome.code == 1
    assert outcome.out == ""
    assert outcome.err.endswith(
        f"\ncopyofa: stdout closed; {destination} was created\n"
    )
    assert "Traceback" not in outcome.err
    assert sorted(path.name for path in destination.iterdir()) == [
        "01.flac",
        "02.flac",
        "03.flac",
    ]


def test_export_canceled_leaves_nothing(
    run: Run,
    acquired_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decode_track = inspector.decode_track
    calls = []

    def interrupted(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(args)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return decode_track(*args, **kwargs)

    monkeypatch.setattr(inspector, "decode_track", interrupted)
    destination = tmp_path / "Tracks"

    outcome = run("export", acquired_set, "--to", destination, "--json")

    assert outcome.code == 130
    assert outcome.out == ""
    assert left_behind(destination) == []
    assert len(calls) == 2


def test_export_writes_nothing_into_the_set(
    run: Run, acquired_set: Path, tmp_path: Path
) -> None:
    before = {
        path: path.read_bytes() for path in acquired_set.rglob("*") if path.is_file()
    }

    outcome = run("export", acquired_set, "--to", tmp_path / "Tracks")

    assert outcome.code == 0, outcome.err
    assert {
        path: path.read_bytes() for path in acquired_set.rglob("*") if path.is_file()
    } == before
