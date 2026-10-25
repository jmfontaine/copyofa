# Evidence Set format

An Evidence Set is a [BagIt 1.0](https://www.rfc-editor.org/rfc/rfc8493) bag, as
[ADR 0001](../decisions/0001-store-evidence-sets-as-bagit-bags.md) decides.
`copyofa import` creates it; this document describes what it contains and how to check
it without CopyOfA.

## Layout

```text
Album/
├── bagit.txt
├── bag-info.txt
├── manifest-sha256.txt
├── tagmanifest-sha256.txt
├── copyofa/
│   └── import-record.json
└── data/
    ├── Album/
    │   ├── 01.flac
    │   └── scans.zip
    └── notes.txt
```

- `data/` holds the Preserved Evidence and nothing else. Each source given to
  `copyofa import` goes under `data/` by its base name, as `cp -R` would place it: a
  directory `~/Downloads/Album` becomes `data/Album/…`, a file `notes.txt` becomes
  `data/notes.txt`. File contents are stored byte for byte.
- `bagit.txt` is the bag declaration, always the same two lines:

  ```text
  BagIt-Version: 1.0
  Tag-File-Character-Encoding: UTF-8
  ```

- `bag-info.txt` holds three elements:
  - `Bagging-Date`: the import date in UTC, as `YYYY-MM-DD`.
  - `Payload-Oxum`: the payload's total size in bytes and its number of files,
    separated by a dot, such as `1048576.12`.
  - `Bag-Software-Agent`: `copyofa` and the version that created the set.
- `manifest-sha256.txt` is the Integrity Inventory: one line per payload file, with its
  SHA-256 digest in lowercase hexadecimal, two spaces, and its path from the bag root,
  such as `data/Album/01.flac`. Each line ends with a line feed.
- `tagmanifest-sha256.txt` has the same format and lists every other file CopyOfA
  writes: `bagit.txt`, `bag-info.txt`, `manifest-sha256.txt`, and
  `copyofa/import-record.json`. With `manifest-sha256.txt`, it forms the Integrity
  Baseline.
- `copyofa/` is CopyOfA's tag directory. It holds the Import Record.
  `copyofa/recovery/` is reserved for recovery information, such as PAR2 files, that a
  later version may add; import does not create it.

Paths in both manifests use `/` as separator. As BagIt requires, three characters are
percent-encoded in a path: `%` as `%25`, a carriage return as `%0D`, and a line feed as
`%0A`. Every other character, including spaces and non-ASCII letters, appears as is, in
UTF-8.

## Import Record

`copyofa/import-record.json` is a UTF-8 JSON object:

| Field | Content |
| --- | --- |
| `record_kind` | Always `copyofa.import`. |
| `format_version` | The version of this record's format, `1`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that imported the set. |
| `imported_at` | The import time in UTC, such as `2026-10-24T18:30:00Z`. It is not an acquisition time. |
| `sources` | One object per source, in the order given: `given`, the path as typed on the command line; `resolved`, its absolute path with every parent directory's symbolic links resolved; `stored_as`, its path in the bag, such as `data/Album`. |
| `note` | The `--note` text, exactly as supplied. Absent when no note was given. |
| `external_references` | The `--ref` values, exactly as supplied and in the order given. Absent when none was given. |
| `exclusions` | Everything under the sources that was not preserved, one object each, possibly an empty list. |

The record holds no acquisition time and no other provenance: CopyOfA records what the
collector supplied and invents nothing.

Each exclusion has a `path`, where the item would have been in the bag, such as
`data/Album/.DS_Store`, and a `reason`:

| `reason` | Excluded item |
| --- | --- |
| `exclude_pattern` | A file or directory matching an `--exclude` pattern, which the `pattern` field gives. A directory is excluded whole, without being listed, and recorded once. |
| `operating_system_metadata` | An operating system metadata file (see below). |
| `symbolic_link` | A symbolic link. Import does not follow links. |
| `special_file` | A file that is neither regular nor a directory, such as a socket or a named pipe. |
| `empty_directory` | A directory with no entries, which BagIt cannot represent. |

An `--exclude` pattern is a shell-style pattern, as Python's `fnmatch` reads it, matched
case-sensitively against the item's name and against its path under `data/`, such as
`Album/scans/back.png`. `*` also matches `/` in a path.

## Import result

`copyofa import --json` prints, instead of its short human-readable result, a JSON
object with `evidence_set`, the absolute path of the new set; `import_record`, the
Import Record as written; and `counts`, with the numbers of preserved `files`,
payload `bytes`, and `exclusions`. It is not a Report. Like every `--json` output of
CopyOfA, it is UTF-8, whatever the locale. A file name that is not valid UTF-8, which
a Linux file system can hold, keeps each invalid byte as a `\udcXX` escape, so the
output stays valid UTF-8 and Python's `json` turns it back into the original name.

## Operating system metadata files

Operating systems create and rewrite some files while a collector browses folders, so
they are not evidence. Import never preserves them, and `copyofa verify` ignores them
under `data/`, so browsing a set in Finder does not make it fail verification:

- `.DS_Store`
- AppleDouble files, whose names start with `._`
- `Icon` followed by a carriage return, which holds a custom folder icon
- `Thumbs.db`
- `desktop.ini`

## How an Evidence Set is accepted

Before copying anything, import refuses, exiting 1 and creating nothing, when:

- a source does not exist, has no base name (`/`), or is neither a regular file nor a
  directory;
- a source is itself a symbolic link. Import never follows links, so name the link's
  target instead;
- two sources are the same file or directory, or one lies inside the other;
- two sources share a base name. Base names are compared case-insensitively and after
  Unicode normalization, as a case-insensitive volume, the default on macOS, compares
  them: `Album` and `album` are refused together even on a case-sensitive volume,
  because the set must stay valid once moved to a macOS volume;
- the destination exists, its parent does not exist or cannot be opened, or it lies
  inside a source;
- a staging directory left by an earlier import exists (see below);
- the path of a source or of the destination, or a name in a directory import lists
  (not one inside an excluded directory), is not valid UTF-8, which BagIt manifests
  require;
- the selection leaves no file to preserve.

It also fails before copying anything when a selected directory cannot be listed or a
selected file cannot be opened; the error names it, and excluding it lets the rest be
imported.

Import then reads each source file once, computing its SHA-256 while copying it into a
staging directory, `<destination>.copyofa-staging`, beside the destination. It then
re-reads the stored copy and compares digests, and fails if they differ or if the
source file's size or modification time changed during the copy. Only when every file
and tag file is written does it rename the staging directory to the destination. A
set at the destination is therefore complete. If syncing the destination's parent
directory fails after that rename, the set is kept and import warns on stderr. A
staging directory left behind by a crash is never reused or deleted by CopyOfA: the
next import to that destination refuses and names it.

## Checking a set without CopyOfA

From the bag root, `shasum`, which ships with macOS, checks both manifests:

```bash
cd /Volumes/Archive/Album
shasum -a 256 -c tagmanifest-sha256.txt
shasum -a 256 -c manifest-sha256.txt
```

Each prints `OK` per file and exits 0 when every listed file matches. On Linux,
`sha256sum -c` reads the same files. Three limits apply:

- A line whose path contains `%25`, `%0D`, or `%0A` names a file whose name holds `%`,
  a carriage return, or a line feed. `shasum` does not decode them and reports that
  file as missing; check it by hand under its decoded name.
- `shasum` checks only the files listed. It does not report files added under `data/`.
- The Library of Congress validator, `bagit.py --validate <set>` (for example through
  `uvx --from bagit bagit.py`), also checks that no file under `data/` is unlisted. It
  reports a set invalid once Finder has added a `.DS_Store` to it, and bagit.py 1.9.0
  does not decode `%25`
  ([bagit-python#157](https://github.com/LibraryOfCongress/bagit-python/issues/157)),
  so it also reports a set with `%` in a file name invalid.
  CopyOfA's own check, `copyofa verify`, ignores operating system metadata files and
  decodes every path; [Verification Report format](verification-report.md) describes
  it.
