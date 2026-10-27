"""Write the tracks of an acquired set as FLAC files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile

from copyofa import evidence_set, inspector, staging, verifier
from copyofa.errors import CopyOfAError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import numpy.typing as npt

LEFT_OUT = (
    (
        "The first track's pregap, the audio before the first track's range, which "
        "the image holds and no track file does."
    ),
    (
        "The lead-in and the lead-out, which the image holds before the first track "
        "and after the last."
    ),
)
"""What export does not write, one sentence each."""


class ExportError(CopyOfAError):
    """An export that was refused or failed."""


@dataclass(frozen=True)
class ExportedFile:
    """A FLAC file export wrote, and the track it holds."""

    path: str
    """Its name in the directory, such as `01.flac`."""
    track: int
    audio_digest: str


@dataclass(frozen=True)
class ExportResult:
    """What export wrote, and from which set."""

    directory: Path
    evidence_set: Path
    manifest_sha256: str
    files: tuple[ExportedFile, ...]
    warnings: tuple[str, ...]
    """Problems that did not fail the export, one sentence each."""

    def to_json(self) -> dict[str, Any]:
        """Describe the export as `export --json` prints it."""
        return {
            "directory": str(self.directory),
            "evidence_set": str(self.evidence_set),
            "manifest_sha256": self.manifest_sha256,
            "files": [
                {
                    "path": exported.path,
                    "track": exported.track,
                    "audio_digest": exported.audio_digest,
                }
                for exported in self.files
            ],
            "left_out": list(LEFT_OUT),
        }


def export(
    target: str,
    destination: str,
    progress: Callable[[str], None] | None = None,
) -> ExportResult:
    """Write each track of the acquired set at target as a FLAC file in destination.

    Checks the set as inspect does, writes in a staging directory beside destination,
    decodes each file to check its Audio Digest against the recorded one, then
    renames the staging directory to destination. Calls progress with a sentence as
    each track is written. Raises verifier.NotAnEvidenceSetError when target is not
    an Evidence Set, and CopyOfAError when the export is refused or fails.
    """
    root = verifier.locate(target)
    checked = staging.check_destination(destination)
    if staging.identity(root) in staging.ancestors(checked.target):
        raise ExportError(
            f"Refused: destination {destination} lies inside the Evidence Set {target}."
        )
    baseline = verifier.read_baseline(root)
    if not baseline.usable or baseline.manifest_sha256 is None:
        raise ExportError(
            f"Refused: the Integrity Baseline of {target} is unusable: "
            + " ".join(baseline.problems)
        )
    try:
        disc = inspector.read_acquired_disc(root, baseline)
    except inspector.UnusableRecordError as error:
        raise ExportError(f"Refused: {error}.") from None
    if disc is None:
        raise ExportError(
            f"Refused: {target} is not an acquired set: {evidence_set.TAG_MANIFEST} "
            f"does not list {evidence_set.ACQUISITION_RECORD}."
        )
    manifest_sha256 = baseline.manifest_sha256

    def build(directory: Path) -> tuple[ExportedFile, ...]:
        files = []
        # Read and checked once, for every track.
        with inspector.open_accepted(root, disc.image, disc.image_digest) as image:
            for track in disc.tracks:
                name = f"{track.number:02}.flac"
                _write_track(image, track, directory / name)
                staging.sync_file(directory / name)
                files.append(ExportedFile(name, track.number, track.audio_digest))
                if progress is not None:
                    progress(f"Exported track {track.number} to {name}")
        return tuple(files)

    files, warnings = staging.accept(checked, "export", build)
    return ExportResult(checked.target, root, manifest_sha256, files, warnings)


def _write_track(
    image: inspector.AcceptedFile, track: inspector.RecordedTrack, path: Path
) -> None:
    """Decode a track from the opened image into a FLAC file, then check the file."""
    scale = np.float32(1 << (evidence_set.CD_BITS_PER_SAMPLE - 1))

    def cannot_write(error: soundfile.LibsndfileError) -> ExportError:
        return ExportError(f"Failed: cannot write {path.name}: {error.error_string}.")

    try:
        with soundfile.SoundFile(
            path,
            "x",
            evidence_set.CD_SAMPLE_RATE,
            evidence_set.CD_CHANNELS,
            f"PCM_{evidence_set.CD_BITS_PER_SAMPLE}",
            format="FLAC",
        ) as sound:

            def write(block: npt.NDArray[np.float32]) -> None:
                # Exact: the decoder gives each 16-bit sample divided by 32768.
                try:
                    sound.write(np.rint(block * scale).astype(np.int16))
                except soundfile.LibsndfileError as error:
                    # Raised as ExportError, so decoding does not report it as a
                    # problem of the image.
                    raise cannot_write(error) from None

            findings = inspector.decode_track(image, track, write)
    except soundfile.LibsndfileError as error:
        raise cannot_write(error) from None
    outcome = findings["outcome"]
    if outcome == inspector.NOT_INSPECTED:
        raise ExportError(f"Refused: {findings['reason']}.")
    if outcome != inspector.INTERPRETED:
        raise ExportError(f"Failed: track {track.number}: {findings['reason']}.")
    if findings["audio_digest"] != track.audio_digest:
        raise ExportError(
            f"Failed: track {track.number} of the image differs from its recorded "
            "Audio Digest."
        )
    # Decoded only: the file was just written, so it has no digest to check.
    written = inspector.inspect_file(path.parent, path.name, None)
    if written.get("audio_digest") != track.audio_digest:
        raise ExportError(
            f"Failed: {path.name} does not decode to the recorded Audio Digest of "
            f"track {track.number}."
        )
