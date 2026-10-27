# Validation result format

`copyofa validate <report> --json` prints a validation result: a JSON document
recording whether one file is a well-formed Report, and if not, why. It is the result
of [ADR 0004](../decisions/0004-publish-each-report-format-as-a-json-schema.md)'s
check: the file is parsed as strict JSON, then checked against the JSON Schema
published for its Report kind and format version. Like every `--json` output of
CopyOfA, it is UTF-8, whatever the locale. Save it with a shell redirect:

```bash
copyofa validate htf.json --json > htf-validation.json
```

A valid Report is well formed and nothing more. Validation establishes neither that the
findings are true, nor who produced the Report, nor anything about the audio it
describes, and the result says so in its `limitations`. Validate reads the file and
writes nothing. It never runs code from the Report or fetches anything it names.

## How validate checks a file

1. **Strict JSON first.** The file must be UTF-8 and one JSON document. It is invalid
   when it is empty, is not JSON, holds `NaN`, `Infinity` or a number too large for a
   float, repeats a member name in an object, or nests arrays or objects deeper than the
   parser allows. Python's parser would accept some of these, and other parsers read
   them differently, so one file could mean different things to different readers. A
   JSON string may hold a `\udcXX` escape, as a Report records a path that is not valid
   UTF-8. Each of these gives one problem, with the location `""`.
2. **Then the schema.** The document's `report_kind` and `format_version` select the
   schema. A document that is not an object, lacks either field, or whose `report_kind`
   is not a string or `format_version` not a positive integer, is invalid. Otherwise
   the document is checked against the schema, and each problem the schema finds is
   reported with its location.
3. **Unknown is not invalid.** A `report_kind` this CopyOfA does not know, or a
   `format_version` it has no schema for, is `unsupported`: a newer CopyOfA may know it.

The schemas are in
[`src/copyofa/schemas/`](../../src/copyofa/schemas), one per Report kind and format
version, and are linked from the format of each Report:
[verification](verification-report.md), [inspection](inspection-report.md) and
[comparison](comparison-report.md).

## Outcomes

| Outcome | Meaning |
| --- | --- |
| `valid` | The file is strict JSON and matches the schema of its Report kind and format version. |
| `invalid` | The file is not strict JSON, is not an object with a usable `report_kind` and `format_version`, or does not match its schema. `problems` says why. |
| `unsupported` | The Report kind or format version is not one this CopyOfA has a schema for. `problems` holds one problem saying which. |

A file that cannot be read, such as a missing file, a directory or a named pipe, has no
outcome: there is no result, only an error on stderr.

## Fields

| Field | Content |
| --- | --- |
| `outcome` | `valid`, `invalid` or `unsupported`. |
| `report` | The file's path as given, made absolute but not normalized: `..` segments and symbolic links are kept. |
| `sha256` | The SHA-256 of the exact bytes that were read, in lowercase hexadecimal. It identifies the Report whatever its outcome. |
| `report_kind` | The document's `report_kind`; absent unless the document is an object with a string `report_kind`. |
| `format_version` | The document's `format_version`; absent unless the document is an object with a positive integer `format_version`. |
| `problems` | One item for each problem found, in the order of their locations; empty when the outcome is `valid`. |
| `copyofa_version` | The version of CopyOfA that validated the file. |
| `limitations` | Sentences stating what a valid Report does not establish. |

Each item of `problems` holds:

- `location`: where the problem is, as a JSON Pointer
  ([RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)): `/payload/0/outcome` is the
  `outcome` of the first item of `payload`. It is `""`, the whole document, for a
  problem of the file as a whole or of an object that lacks a field or holds an unknown
  one.
- `message`: a sentence saying what is wrong. A message that quotes part of the
  document is cut short when it is long.

## Example

An edited verification Report with a `scope` that the format does not define, and
without its `checked_at`:

```json
{
  "outcome": "invalid",
  "report": "/Users/jm/Reports/album-verification.json",
  "sha256": "8f3e…",
  "report_kind": "copyofa.verification",
  "format_version": 1,
  "problems": [
    {
      "location": "",
      "message": "'checked_at' is a required property."
    },
    {
      "location": "/scope",
      "message": "'partial' is not one of ['full_content']."
    }
  ],
  "copyofa_version": "0.4.0",
  "limitations": [
    "A valid Report is well formed: it has the fields its format defines, …",
    "Validation does not establish that the findings in the Report are true.",
    "Validation does not establish who produced the Report.",
    "Validation does not establish anything about the audio the Report describes."
  ]
}
```

The example is shortened: the SHA-256 holds all 64 hexadecimal digits, and the first
limitation its whole sentence. The wording of a message that comes from the schema
validator may change between releases.

Without `--json`, validate prints the same facts as short lines: the outcome, the
file's SHA-256, the Report kind and format version when known, one line for each
problem with its location, and the limitations.

## Exit codes

`copyofa validate` exits 0 when the Report is `valid`, and 1 when it is `invalid` or
`unsupported`, and still prints its result. It exits 1, printing nothing on stdout and
the reason on stderr, when the file cannot be read: it does not exist, is a directory
or another file that is not a regular file, or cannot be read. It exits 2,
printing nothing on stdout, when the arguments are invalid, and 130 when canceled with
Ctrl-C. It also exits 1, with `copyofa: stdout closed` on stderr, when stdout is closed
before or while it prints its result.

## Validate without CopyOfA

Each schema is a JSON Schema of draft 2020-12 with no reference to another file, so any
validator of that draft checks a Report with no network access. For example, with
[check-jsonschema](https://check-jsonschema.readthedocs.io/):

```bash
check-jsonschema --schemafile comparison-report-2.schema.json htf.json
```

or with [Ajv](https://ajv.js.org/) and its `ajv/dist/2020` class in JavaScript. Choose
the schema file from the Report's `report_kind` and `format_version`: a Report of kind
`copyofa.comparison` and format version 2 is checked by
`comparison-report-2.schema.json`. Each schema's `$id` is its URL on the `main` branch
of the repository.

A generic validator checks only what the schema states. It does not reject a file that
repeats a member name or holds `NaN`, which many JSON parsers accept; CopyOfA parses
strictly first, so that one file cannot mean different things to different readers.
