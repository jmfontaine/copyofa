# Verification Report format

`copyofa verify <evidence-set> --json` prints a verification Report: a UTF-8 JSON
document recording what one check of an [Evidence Set](evidence-set.md) against its
Integrity Baseline found. Save it with a shell redirect:

```bash
copyofa verify /Volumes/Archive/Album --json > album-verification.json
```

A Report states stored integrity only: whether each preserved file still has the
digest recorded when it was accepted. It says nothing about the audio.

## How verify checks a set

1. **Records first.** Verify checks every tag file that `tagmanifest-sha256.txt` lists,
   then reads `manifest-sha256.txt`. The Integrity Baseline is unusable when:
   - either manifest is missing, unreadable, or cannot be parsed;
   - `tagmanifest-sha256.txt` does not list `manifest-sha256.txt`, or
     `manifest-sha256.txt` fails its check;
   - an entry in either manifest is not a normalized relative path inside the set (an
     absolute path, an empty component, or a `.` or `..` component), or a
     `manifest-sha256.txt` entry is not under `data/`. Verify never opens such a path.
2. **Payload.** With a usable baseline, each file `manifest-sha256.txt` lists is read
   completely and gets one outcome. With an unusable baseline, each entry is reported
   as not checked when the manifest can still be parsed, and no payload item is
   reported when it cannot.
3. **Unexpected files.** With a usable baseline, verify lists the files under `data/`
   that the manifest does not list. It ignores the
   [operating system metadata files](evidence-set.md#operating-system-metadata-files)
   that Finder and other systems write while a collector browses the set.

Files outside `data/` that `tagmanifest-sha256.txt` does not list, such as recovery
information a later version adds in `copyofa/recovery/`, are ignored. Verify follows no
symbolic link inside the set and writes nothing into it.

## Outcomes

Each listed file, payload or tag file, gets exactly one outcome:

| Outcome | Meaning |
| --- | --- |
| `matching` | The file was read completely and its SHA-256 equals the manifest's. |
| `changed` | The file was read completely and its SHA-256 differs. |
| `missing` | The file does not exist, while the Evidence Set itself is reachable. |
| `unavailable` | The path exists but could not be read completely, such as a permission or I/O error, or is not a regular file: a directory, a symbolic link, a special file, or a path through a symbolic link. |
| `not_checked` | The check was not attempted; the reason says why. |

## Fields

| Field | Content |
| --- | --- |
| `report_kind` | Always `copyofa.verification`. |
| `format_version` | The version of this format, `1`. A later change to the fields increments it. |
| `copyofa_version` | The version of CopyOfA that ran the check. |
| `checked_at` | The check time in UTC, such as `2026-10-24T18:30:00Z`. |
| `evidence_set` | The absolute path of the Evidence Set as given, which changes when the set moves. |
| `scope` | What was checked: `full_content`, every byte of every listed file. |
| `integrity_baseline` | The baseline used (see below). |
| `tag_files` | One item per entry of `tagmanifest-sha256.txt`, in its order; empty when that manifest is missing or cannot be parsed. |
| `payload` | One item per entry of `manifest-sha256.txt`, in its order; empty when that manifest is missing or cannot be parsed. |
| `unexpected_files` | The paths of unlisted files under `data/`, such as `data/extra.txt`, sorted. Empty when the baseline is unusable, because they are not looked for. |
| `unexamined_directories` | `data/` or the directories under it that could not be searched for unexpected files, because they could not be listed or `data/` is a symbolic link or not a directory, each with a `path` and a `reason`. |
| `counts` | The number of payload items per outcome (`matching`, `changed`, `missing`, `unavailable`, `not_checked`), and `unexpected`, the number of unexpected files. |

`integrity_baseline` holds:

- `manifest_sha256`: the SHA-256 of `manifest-sha256.txt` as read, which identifies the
  baseline; `null` when that file cannot be read.
- `usable`: `true` when the payload could be checked against the baseline.
- `problems`: why the baseline is unusable, one sentence each; empty when it is usable.

Each item of `tag_files` and `payload` holds:

- `path`: the path from the set's root, decoded, such as `data/Album/01.flac`.
- `outcome`: one of the outcomes above.
- `expected_digest`: the SHA-256 the manifest records.
- `observed_digest`: the SHA-256 computed now; present only when the file was read
  completely.
- `reason`: why the outcome is not `matching`; absent when it is.

## Example

```json
{
  "report_kind": "copyofa.verification",
  "format_version": 1,
  "copyofa_version": "0.1.0",
  "checked_at": "2026-10-24T18:30:00Z",
  "evidence_set": "/Volumes/Other/Album",
  "scope": "full_content",
  "integrity_baseline": {
    "manifest_sha256": "5f3c…",
    "usable": true,
    "problems": []
  },
  "tag_files": [
    {
      "path": "bagit.txt",
      "outcome": "matching",
      "expected_digest": "e91f…",
      "observed_digest": "e91f…"
    }
  ],
  "payload": [
    {
      "path": "data/Album/01.flac",
      "outcome": "changed",
      "expected_digest": "920c…",
      "observed_digest": "41b7…",
      "reason": "its digest differs from the manifest's"
    },
    {
      "path": "data/Album/cover.jpg",
      "outcome": "missing",
      "expected_digest": "3fa4…",
      "reason": "the file does not exist"
    }
  ],
  "unexpected_files": [],
  "unexamined_directories": [],
  "counts": {
    "matching": 0,
    "changed": 1,
    "missing": 1,
    "unavailable": 0,
    "not_checked": 0,
    "unexpected": 0
  }
}
```

The example is shortened: a Report holds all 64 hexadecimal digits of each digest,
and one item per tag file and payload file.

## Exit codes

`copyofa verify` exits 0 when every listed tag file and payload file is matching, no
unexpected file was found, and every directory under `data/` could be listed. It exits
1 otherwise, and still prints its result or Report. It exits 2, printing nothing on
stdout, when the target is not an Evidence Set (it does not exist, is not a directory,
or has no `bagit.txt`) or the arguments are invalid, and 130 when canceled with Ctrl-C.
A set it cannot reach, such as one behind a directory without search permission, gets
a Report whose records cannot be read, and exit 1.
