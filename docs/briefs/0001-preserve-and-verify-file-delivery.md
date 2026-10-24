# Brief: Preserve and Verify a Selected File Delivery

## Goal and context

A collector can preserve files they already own, such as a download purchase, as an
Evidence Set, move it to another drive, and later learn whether every preserved file is
still intact.

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
   `/Volumes/Archive/Album` as an accepted Evidence Set. The result gives the number of
   files and bytes preserved and lists what was excluded, with reasons.
4. Months later, after moving the set to another drive and browsing it in Finder, they
   run `copyofa verify /Volumes/Other/Album`. Every file is reported as matching.
5. A file gets damaged and another deleted. `verify` reports one file changed and one
   missing, names them, and exits non-zero; `--json` gives the same result as a
   verification Report.

## In scope

- `copyofa import <source>... --to <destination>`: preserve selected files and
  directories as a new Evidence Set.
- `copyofa verify <evidence-set>`: check an Evidence Set against its Integrity
  Baseline.
- Collector-supplied provenance: one free-form note and repeatable external references.
- Exclusion of files by pattern, and accounting for everything not preserved.
- Human-readable output by default; `--json` for structured output on both commands.
- Documentation of the Evidence Set layout and the verification Report format.

## Out of scope

- Reading inside archives. A ZIP is preserved as one opaque file.
- Decoding audio, Audio Identity, and any audio measurement.
- A portable human-readable view of a Report.
- Export, Derivatives, and recovery information or repair.
- CD acquisition.
- Changing an accepted Evidence Set: adding files, correcting provenance, merging sets,
  or deleting operating system metadata files from it.
- Verifying bags that `copyofa import` did not create.
- Relocation to storage that rewrites file names, such as Unicode normalization on
  some network shares. Supported relocation is between macOS local volumes.
- Interactive prompts.

## Requirements

### Import

- **Destination.** `--to` names a directory that must not exist yet, whose parent must
  exist. The destination must not lie inside any source. The Evidence Set appears
  there only once it is accepted.
- **Payload layout.** Each source goes under `data/` by its base name, as `cp -R` would
  place it: `~/Downloads/Album` becomes `data/Album/…`, a file `notes.txt` becomes
  `data/notes.txt`. Sources that do not exist, share a base name, are the same path, or
  lie inside one another are refused.
- **Selection.** Every regular file under a selected directory is preserved, hidden
  files included, except:
  - files and directories matching an `--exclude <pattern>`, against their name or
    their path under `data/` (shell-style patterns); a matching directory is excluded
    whole, without being listed, and recorded as one exclusion;
  - operating system metadata files, as defined in Design decisions;
  - symbolic links, which are not followed, and special files such as sockets;
  - empty directories, which BagIt cannot represent.

  Each of these is recorded as an exclusion with its reason.
- **Nothing to preserve.** A selection that leaves no file to preserve is refused.
- **Unreadable input.** A file that cannot be read, or a directory that cannot be
  listed, fails the import, and the error names it. The collector can exclude it and
  import again. Unreadable input is never silently skipped.
- **Check before acceptance.** CopyOfA computes each file's SHA-256 while reading the
  source, then re-reads the stored copy and compares. A mismatch fails the import. So
  does a source file whose size or modification time changes while it is being
  copied.
- **Staging.** Files are written to a staging directory beside the destination, on the
  same volume, and renamed to the destination only after every check passes.
  Ctrl-C removes the staging directory. A staging directory left behind by a crash
  makes the next import to the same destination refuse, naming the leftover; CopyOfA
  never deletes it on its own.
- **Refusals come first.** Every refusal above that does not depend on reading file
  contents happens before anything is copied.
- **Sources are read-only.** Import never modifies, moves, or deletes source files.
- **Import Record.** `copyofa/import-record.json`, versioned, records: the CopyOfA
  version; the import time in UTC; each source as given and as resolved; the note and
  external references exactly as supplied, omitted when not supplied; and the
  exclusions with their reasons. It records no acquisition time; import time never
  stands in for it.
- **Progress.** Import reports each file as it is preserved on stderr.

### Verify

- **Records first.** Verify checks every tag file listed in `tagmanifest-sha256.txt`,
  then reads `manifest-sha256.txt`. The Integrity Baseline is unusable when:
  - either manifest is missing, unreadable, or cannot be parsed;
  - the tag manifest does not list `manifest-sha256.txt`, or `manifest-sha256.txt`
    fails its check;
  - any entry in either manifest is not a normalized relative path inside the bag (an
    absolute path, or one with `.` or `..` components), or a payload manifest entry
    is not under `data/`. Verify never opens such a path.
- **Unusable baseline.** Each entry of `manifest-sha256.txt`, when the file can still
  be parsed, is reported as not checked with the reason, and never as matching. When it
  cannot be read or parsed, no payload item is reported. Unexpected files are not
  looked for.
- **Payload outcomes.** With a usable baseline, each file listed in
  `manifest-sha256.txt` gets exactly one outcome, as defined in Design decisions:
  matching, changed, missing, unavailable, or not checked.
- **Unexpected files.** Files under `data/` that the manifest does not list are
  reported as unexpected, except operating system metadata files, which are ignored
  and not reported. Unexpected files do not change the outcome of listed files.
- **Forward compatibility.** Files outside `data/` that the tag manifest does not list
  are ignored, so recovery information added by a later version does not fail
  verification.
- **Read-only.** Verify writes nothing into the Evidence Set.
- **Cancellation.** Ctrl-C stops verification without producing a Report.

### Output and exit codes

- Both commands print a short human-readable result by default; `--json` prints a
  single JSON document on stdout instead. Progress and errors go to stderr.
- Exit 0: import accepted, or verify found every listed item matching, no unexpected
  files, and all records intact.
- Exit 1: import refused or failed, or verify found anything else. Verify still prints
  its result, or its Report with `--json`.
- Exit 2: invalid arguments, or the verify target is not an Evidence Set (no
  `bagit.txt`).
- Exit 130: canceled with Ctrl-C.
- Stdout is empty whenever no result is produced: a refused or failed import, exit 2,
  and exit 130.

## Design decisions

- **Layout.** BagIt 1.0, as
  [ADR 0001](../decisions/0001-store-evidence-sets-as-bagit-bags.md) defines:
  `bagit.txt`, `bag-info.txt` (`Bagging-Date`, `Payload-Oxum`, `Bag-Software-Agent`),
  `manifest-sha256.txt`, `tagmanifest-sha256.txt`, `data/`, and the `copyofa/` tag
  directory holding `import-record.json`. Manifest lines put two spaces between digest
  and path, the format `shasum -c` reads. `copyofa/recovery/` is reserved by
  documentation; import does not create it.
- **Operating system metadata files.** `.DS_Store`, AppleDouble files (`._*`), `Icon`
  followed by a carriage return, `Thumbs.db`, and `desktop.ini`. Operating systems
  create and rewrite them while a collector browses folders, so import excludes them
  and verify ignores them; otherwise browsing a set in Finder would make it fail
  verification.
- **Outcome definitions.** Matching: the file was read completely and its digest
  equals the manifest's. Changed: the file was read and its digest differs. Missing:
  the file does not exist while the Evidence Set itself is reachable. Unavailable: the
  path exists but could not be read completely, such as a permission or I/O error, or
  is not a regular file (a directory, symbolic link, or special file; symbolic links
  are not followed). Not checked: the check was not attempted, with the reason.
- **Verification Report format.** A JSON document with `report_kind`
  `copyofa.verification` and a `format_version`. It records: the CopyOfA version; the
  check time in UTC; the Integrity Baseline it used, identified by the SHA-256 of
  `manifest-sha256.txt`, or its absence when that file cannot be read; whether the
  baseline is usable; the scope, which is full content in this release; the outcome of
  each tag file check; each payload item with its outcome, expected digest, observed
  digest when one was computed, and the reason for any outcome other than matching;
  the unexpected files; and a count per outcome. The `--json` output of verify is the
  Report; saving it is a shell redirect.
- **Import result.** The `--json` output of import contains the Evidence Set path, the
  Import Record, and the counts of preserved files, bytes, and exclusions. It is not a
  Report.
- **Documentation.** `docs/formats/evidence-set.md` describes the layout, the Import
  Record, the operating system metadata files, and how to check a set without
  CopyOfA. `docs/formats/verification-report.md` describes the Report. The README
  shows both commands.

## Blocking questions

None.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise.

- **AC1 — Bag created.** `copyofa import` produces a destination containing the
  layout in Design decisions, with every payload file byte-identical to its source,
  including files whose names need percent-encoding in a manifest (`%`, CR, LF). The
  independent `bagit.py --validate <destination>` (run once by hand, with
  `uvx --from bagit bagit.py`) reports the bag valid.
- **AC2 — Import Record.** The record holds the fields in Requirements. A note and
  references appear exactly as supplied; without them, those fields are absent rather
  than empty or invented.
- **AC3 — Selection accounted for.** Every regular file under the selected sources is
  either listed in `manifest-sha256.txt` or listed as an exclusion with its reason, and
  so is every pattern match, operating system metadata file, symbolic link, special
  file, and empty directory. `Payload-Oxum` matches the preserved files.
- **AC4 — Unreadable input.** With a source file made unreadable, or a source
  subdirectory that cannot be listed, import exits 1, names it, and creates no
  destination. Excluding it makes the import succeed.
- **AC5 — Stored copies checked.** When a stored copy is corrupted after writing (a
  test fault injection), or a source file grows during its copy, import exits 1 and
  creates no destination.
- **AC6 — Safe import.** Each of these refusals exits 1 before anything is copied: an
  existing destination, a missing destination parent, a destination inside a source,
  a source that does not exist, sources sharing a base name, nested or repeated
  sources, a selection with nothing to preserve, and a leftover staging directory,
  which the error names. Source files keep
  their content and modification times. Ctrl-C leaves no staging directory and no
  destination and exits 130.
- **AC7 — Intact after relocation.** After the Evidence Set is moved to a different
  parent directory and a `.DS_Store` is added under `data/`, `copyofa verify` reports
  every item matching, reports no unexpected file, and exits 0.
- **AC8 — Problems reported.** With one payload file modified, one deleted, one made
  unreadable, one replaced by a directory, and one extra file added under `data/`,
  verify reports changed, missing, unavailable, unavailable, and unexpected
  respectively, reports every other file matching, and exits 1. An unlisted file added
  in `copyofa/recovery/` changes nothing.
- **AC9 — Damaged records.** Verify reports the record failure, reports no item
  matching, and exits 1 in each case:
  - `manifest-sha256.txt` edited: its entries are reported not checked.
  - `manifest-sha256.txt` deleted: no payload item is reported, and the Report has no
    baseline identifier.
  - `tagmanifest-sha256.txt` deleted, or missing its `manifest-sha256.txt` entry: the
    payload entries are reported not checked.
  - A manifest entry pointing outside the bag (`../x`, `/etc/hosts`) or, in the payload
    manifest, outside `data/`: the path is not opened, and the payload entries are
    reported not checked.

  With only `copyofa/import-record.json` edited, verify reports that record failure,
  still checks the payload, and exits 1.
- **AC10 — Report content.** `verify --json` prints a Report with the content in
  Design decisions, and the Evidence Set's files are unchanged afterward.
- **AC11 — Command conventions.** Both commands follow the output and exit-code rules
  above, including empty stdout when no result is produced. Import reports progress
  per file on stderr. Ctrl-C during verify exits 130 with nothing on stdout.
- **AC12 — Formats documented.** The two format documents exist and match the
  implementation. Following `docs/formats/evidence-set.md`, a reader checks a set
  without CopyOfA with `shasum -a 256 -c manifest-sha256.txt` (verified by hand once).

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
- **Accuracy must remain usable:** browsing an archive in Finder does not make it fail
  verification.
- **Collection management remains external:** external references link to any
  catalog without requiring one.

## Appetite and scope cuts

Appetite: a few days of work.

If the work outgrows it, cut in this order, keeping import, verify, and the
verification Report:

1. Progress output on stderr.
2. `--json` on import.
3. External references (`--ref`); the note remains.
