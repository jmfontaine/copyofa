# Brief: Preserve and Verify a Selected File Delivery

## Goal and context

A collector can preserve files they already own, such as a download purchase, as an
Evidence Set, move it anywhere, and later learn whether every preserved file is still
intact.

- **Milestone:** [v0.1.0](https://github.com/jmfontaine/copyofa/milestone/1)
- **Product Map capabilities:**
  [Acquire Audio and Record Its Origins](../product-map.md#acquire-audio-and-record-its-origins);
  [Preserve Evidence Throughout Its Lifetime](../product-map.md#preserve-evidence-throughout-its-lifetime)
- **Decision:**
  [ADR 0001: Store Evidence Sets as BagIt bags](../decisions/0001-store-evidence-sets-as-bagit-bags.md)

This is CopyOfA's first release. It sets the Evidence Set format, the first Report,
and the command conventions that later releases build on, without decoding audio.

## Primary scenario

Refines [S2](../product-map.md#s2-use-audio-files-already-owned) (preserve a selected
delivery) and [S6](../product-map.md#s6-check-an-archive-later) (check it later).

1. A collector downloads an album: FLAC files, a cover image, and a ZIP of scans.
2. They run `copyofa import ~/Downloads/Album --to /Volumes/Archive/Album --note
   "Bandcamp purchase" --ref discogs=r123456`.
3. CopyOfA copies the files, checks every stored copy, and only then creates
   `/Volumes/Archive/Album` as an accepted Evidence Set. The output lists what was
   preserved and what was excluded, with reasons.
4. Months later, after moving the set to another drive, they run
   `copyofa verify /Volumes/Other/Album`. Every file is reported as matching.
5. A file gets damaged and another deleted. `verify` reports one file changed and one
   missing, names them, and exits non-zero; `--json` gives the same result as a
   Verification Report.

## In scope

- `copyofa import <source>... --to <destination>`: preserve selected files and
  directories as a new Evidence Set.
- `copyofa verify <evidence-set>`: check an Evidence Set against its Integrity
  Baseline.
- Collector-supplied provenance: one free-form note and repeatable external references.
- Exclusion of files by pattern, and accounting for everything not preserved.
- Human-readable output by default; `--json` for structured output on both commands.
- Documentation of the Evidence Set layout and the Verification Report format.

## Out of scope

- Reading inside archives. A ZIP is preserved as one opaque file.
- Decoding audio, Audio Identity, and any audio measurement.
- A portable human-readable view of a Report.
- Export, Derivatives, and recovery information or repair.
- CD acquisition.
- Changing an accepted Evidence Set: adding files, correcting provenance, or merging
  sets.
- Verifying bags that `copyofa import` did not create.
- Relocation to storage that rewrites file names, such as Unicode normalization on
  some network shares. Supported relocation is between macOS local volumes.
- Interactive prompts.

## Requirements

### Import

- **Destination.** `--to` names a directory that must not exist yet. The Evidence Set
  appears there only once it is accepted.
- **Payload layout.** Each source goes under `data/` by its base name, as `cp -R` would
  place it: `~/Downloads/Album` becomes `data/Album/…`, a file `notes.txt` becomes
  `data/notes.txt`. Two sources with the same base name are refused before anything is
  copied.
- **Selection.** Every regular file under a selected directory is preserved, hidden
  files included, unless an `--exclude <pattern>` matches its file name or its path
  under `data/` (shell-style patterns). The following are never preserved and are
  recorded as exclusions with a reason: pattern matches, symbolic links (not
  followed), special files such as sockets, and empty directories, which BagIt cannot
  represent.
- **Unreadable files.** A file that cannot be read fails the import, and the error
  names it. The collector can exclude it and import again. An unreadable file is never
  silently skipped.
- **Check before acceptance.** CopyOfA computes each file's SHA-256 while reading the
  source, then re-reads the stored copy and compares. A mismatch fails the import. So
  does a source file whose size or modification time changes while it is being
  copied.
- **Staging.** Files are written to a staging directory beside the destination, on the
  same volume, and renamed to the destination only after every check passes.
  Ctrl-C removes the staging directory. A staging directory left behind by a crash
  makes the next import to the same destination refuse, naming the leftover; CopyOfA
  never deletes it on its own.
- **Sources are read-only.** Import never modifies, moves, or deletes source files.
- **Import Record.** `copyofa/import-record.json`, versioned, records: the CopyOfA
  version; the import time in UTC; each source as given and as resolved; the note and
  external references exactly as supplied, omitted when not supplied; and the
  exclusions with their reasons. It records no acquisition time; import time never
  stands in for it.
- **Progress.** Import reports each file as it is preserved on stderr.

### Verify

- **Records first.** Verify checks every tag file listed in `tagmanifest-sha256.txt`.
  If `manifest-sha256.txt` fails that check, or either manifest is missing or
  unreadable, the Integrity Baseline is unusable: every payload item is reported as
  not checked, never as matching.
- **Payload outcomes.** Each file listed in `manifest-sha256.txt` gets exactly one
  outcome, as defined in Design decisions: matching, changed, missing, unavailable, or
  not checked.
- **Unexpected files.** Files under `data/` that the manifest does not list are
  reported as unexpected. They do not change the outcome of listed files.
- **Forward compatibility.** Files outside `data/` that the tag manifest does not list
  are ignored, so recovery information added by a later version does not fail
  verification.
- **Read-only.** Verify writes nothing into the Evidence Set.
- **Cancellation.** Ctrl-C stops verification without producing a Report.

### Output and exit codes

- Both commands print a short human-readable result by default; `--json` prints a
  single JSON document on stdout instead. Progress and errors go to stderr.
- Exit 0: import accepted, or verify found every item matching, no unexpected files,
  and all records intact. Exit 1: import failed, or verify found any other outcome.
  Exit 2: usage error, or the verify target is not an Evidence Set (no `bagit.txt`).
  Exit 130: canceled with Ctrl-C.

## Design decisions

- **Layout.** BagIt 1.0, as
  [ADR 0001](../decisions/0001-store-evidence-sets-as-bagit-bags.md) defines:
  `bagit.txt`, `bag-info.txt` (`Bagging-Date`, `Payload-Oxum`, `Bag-Software-Agent`),
  `manifest-sha256.txt`, `tagmanifest-sha256.txt`, `data/`, and the `copyofa/` tag
  directory. `copyofa/recovery/` stays reserved and empty in this release.
- **Outcome definitions.** Matching: the file was read completely and its digest
  equals the manifest's. Changed: the file was read and its digest differs. Missing:
  the file does not exist while the Evidence Set itself is reachable. Unavailable: the
  file exists but could not be read completely, such as a permission or I/O error.
  Not checked: the check was not attempted, with the reason.
- **Verification Report.** A JSON document with `report_kind`
  `copyofa.verification` and a `format_version`. It records: the CopyOfA version; the
  check time in UTC; the Integrity Baseline it used, identified by the SHA-256 of
  `manifest-sha256.txt`; the scope, which is full content in this release; the outcome
  of each tag file check; each payload item with its outcome, expected digest,
  observed digest when one was computed, and the reason for any outcome other than
  matching; the unexpected files; and a count per outcome. The `--json` output of
  verify is the Report; saving it is a shell redirect.
- **Import result.** The `--json` output of import contains the Evidence Set path, the
  Import Record, and the counts of preserved files, bytes, and exclusions. It is not a
  Report.
- **Documentation.** `docs/formats/evidence-set.md` describes the layout, the Import
  Record, and how to check a set without CopyOfA. `docs/formats/verification-report.md`
  describes the Report. The README shows both commands.

## Blocking questions

None.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise.

- **AC1 — Bag created.** `copyofa import` produces a destination containing the
  layout in Design decisions, with every payload file byte-identical to its source.
  The independent `bagit.py --validate <destination>` (run once by hand, with
  `uvx --from bagit bagit.py`) reports the bag valid.
- **AC2 — Import Record.** The record holds the fields in Requirements. A note and
  references appear exactly as supplied; without them, those fields are absent rather
  than empty or invented.
- **AC3 — Selection accounted for.** Every regular file under the selected sources is
  either listed in `manifest-sha256.txt` or listed as an exclusion with its reason, and
  so is every symbolic link, special file, and empty directory. `Payload-Oxum` matches
  the preserved files.
- **AC4 — Unreadable file.** With a source file made unreadable, import exits 1,
  names the file, and creates no destination. Excluding that file makes the import
  succeed.
- **AC5 — Stored copies checked.** When a stored copy is corrupted after writing (a
  test fault injection), or a source file grows during its copy, import exits 1 and
  creates no destination.
- **AC6 — Safe import.** Import refuses an existing destination and colliding source
  base names before copying anything. Source files keep their content and
  modification times. Ctrl-C leaves no staging directory and no destination and exits
  130. A leftover staging directory makes the next import to that destination refuse
  and name it.
- **AC7 — Intact after relocation.** After the Evidence Set is moved to a different
  parent directory, `copyofa verify` reports every item matching and exits 0.
- **AC8 — Problems reported.** With one payload file modified, one deleted, one made
  unreadable, and one extra file added under `data/`, verify reports changed, missing,
  unavailable, and unexpected respectively, reports every other file matching, and
  exits 1. An unlisted file added in `copyofa/recovery/` changes nothing.
- **AC9 — Damaged records.** With `manifest-sha256.txt` edited or deleted, or
  `tagmanifest-sha256.txt` deleted, verify reports the record failure, reports every
  payload item not checked, and exits 1. With only `copyofa/import-record.json`
  edited, verify reports that record failure, still checks the payload, and exits 1.
- **AC10 — Verification Report.** `verify --json` prints a Report with the content in
  Design decisions, and the Evidence Set's files are unchanged afterward.
- **AC11 — Command conventions.** Both commands follow the output and exit-code rules
  above; import reports progress per file on stderr.
- **AC12 — Formats documented.** The two format documents exist and match the
  implementation. Following `docs/formats/evidence-set.md`, a reader checks a set
  without CopyOfA (verified by hand once).

## Manifesto alignment

- **Preservation is a lifecycle:** this release delivers its first two steps, accepting
  evidence and verifying it later.
- **Evidence, identity, and conclusions are distinct:** files are preserved byte for
  byte, opaque to CopyOfA, and the Import Record holds provenance separately.
- **Provenance should identify the source:** a note and external references capture
  what the collector knows, and nothing is invented.
- **Results should be reproducible and durable:** a standard, documented format checks
  without CopyOfA and survives relocation.
- **Measurements and interpretations should remain distinguishable:** verification
  states stored integrity only, with explicit outcomes for what it could not check.
- **Collection management remains external:** external references link to any
  catalog without requiring one.

## Appetite and scope cuts

Appetite: a few days of work.

If the work outgrows it, cut in this order, keeping import, verify, and the
Verification Report:

1. Progress output on stderr.
2. `--json` on import.
3. External references (`--ref`); the note remains.
