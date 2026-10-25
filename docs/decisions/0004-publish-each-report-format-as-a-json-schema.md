# Publish each Report format as a JSON Schema

- **Date:** 2026-10-25
- **Status:** Accepted
- **Related artifacts:**
  [Brief 0003: Share a Comparison Report](../briefs/0003-share-a-comparison-report.md);
  Product Map capability
  [Share and Evaluate Findings](../product-map.md#share-and-evaluate-findings) and
  scenario [S5](../product-map.md#s5-share-and-evaluate-a-finding)

## Context

CopyOfA prints three kinds of Report, each documented in prose under `docs/formats/`
and identified by its `report_kind` and `format_version`. A recipient who receives a
Report, and external software such as a recording catalog, need to check that it is
well formed before trusting its structure, and the Product Map asks that they can do
so without installing CopyOfA. Prose alone gives them nothing to run, and CopyOfA has
no check of its own: nothing today catches a Report whose structure drifts from its
document.

Received Reports are untrusted data, so whatever checks them must not execute or fetch
anything the document names.

## Decision

1. **A JSON Schema per Report kind and format version.** Each format version of each
   Report kind gets one schema, written as JSON Schema draft 2020-12, in
   `src/copyofa/schemas/<kind>-report-<version>.schema.json`, such as
   `comparison-report-2.schema.json`. The `report_kind` and `format_version` of a
   Report name its schema. Each schema is self-contained, with no reference to another
   file, and its `$id` is its URL on the `main` branch of the repository on
   raw.githubusercontent.com. The files ship in the package and are linked from their
   format documents.
2. **Strict.** Every object allows only the fields its format document lists
   (`additionalProperties: false`), required fields are required, closed sets of
   values are enumerations, and digests and timestamps have patterns. Numeric ranges
   are constrained only where CopyOfA guarantees them: counts and frames, and the
   correlation, which compare clamps to −1 to 1 because rounding can carry the
   computed value just past that limit. Values with no such guarantee, such as a gain
   or a residual in dB, are not bounded.
3. **Prose for meaning, schema for structure.** The format document stays the
   authority for what each field means; the schema states which fields exist and
   their types. A disagreement between them is a bug, fixed in both. A released
   schema changes only to fix such a bug; any other change to a format's fields is a
   new format version with its own schema, so every Report CopyOfA has printed keeps a
   schema that validates it.
4. **Validated with jsonschema.** `copyofa validate` checks a Report with
   [jsonschema](https://github.com/python-jsonschema/jsonschema) (python-jsonschema)
   4.18 or later, using its draft 2020-12 validator on the schema loaded from the
   package. It becomes CopyOfA's fourth runtime dependency. Before the schema, CopyOfA
   parses the file as strict JSON itself: UTF-8 only, no `NaN` or `Infinity`, no
   repeated member name.
5. **Tested against real output.** Every Report the test suite produces validates
   against its schema, so the schemas cannot drift from the implementation unnoticed.

## Rationale and alternatives

- **JSON Schema** is the standard way to describe a JSON document, with validators in
  most languages, so a catalog can check Reports in its own stack. Draft 2020-12 is
  its current version.
- **One file per version** keeps old Reports checkable forever and makes the schema a
  recipient needs obvious from the Report itself. Version 1 and 2 of the comparison
  Report differ by one field, so the duplication is small.
- **Self-contained files** let a validator check a Report with no network access and
  no reference resolution, which also leaves no fetch for a hostile document to
  trigger.
- **jsonschema** is the reference Python implementation, maintained, and complete for
  draft 2020-12. Version 4.18 is the first to resolve schemas with `referencing`
  instead of the deprecated `RefResolver`. A probe installed it and validated a
  draft 2020-12 schema on Python 3.11 and 3.15, both at 4.18.0 and at the latest
  release, 4.26.0, with the latest versions of its dependencies, as CI's lowest-direct
  job installs them.
- **Strict JSON parsing first** because Python's `json` accepts `NaN`, `Infinity` and
  repeated member names, which other parsers reject or read differently, so one file
  could mean different things to different readers.

Alternatives considered:

- **Checks written in Python.** Rejected: they give external software nothing to run,
  and a published schema would then be a second description that could drift.
- **fastjsonschema.** Rejected: no dependencies, but it supports drafts up to 07 only,
  and it validates by generating and executing Python code.
- **Generating the schemas from Python models, such as pydantic.** Rejected: a large
  dependency, and Reports are built as plain dictionaries today. The schema files are
  the published contract, so they are written and reviewed as such.
- **JSON Type Definition (RFC 8927).** Rejected: simpler, but with far fewer validators
  than JSON Schema.

## Consequences

- jsonschema brings `attrs`, `jsonschema-specifications`, `referencing` and `rpds-py`,
  whose Rust extension has wheels for every supported Python, 3.11 to 3.15. CopyOfA
  uses no deprecated jsonschema interface, such as its `__version__` attribute, since
  CI makes deprecation warnings fatal.
- Any change to a Report's fields comes with a new format version, a new schema file,
  and a test that the new Reports validate; the old schema file stays.
- A valid Report is well formed, nothing more. Validation does not establish that its
  findings are true, who produced it, or anything about the audio it describes.
- The `$id` URLs rely on the files staying at their path on `main`. Revisit this
  decision if the schemas move, or when a Report format needs a check that JSON Schema
  cannot express.
