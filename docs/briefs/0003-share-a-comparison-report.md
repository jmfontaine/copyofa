# Brief: Share a Comparison Report

## Goal and context

A collector shares a comparison with another collector, who reads it without CopyOfA
and checks the Report with CopyOfA or any JSON Schema validator. The shared Report
can leave out where the collector stores their Evidence Sets, and its human-readable
view shows exactly what the Report holds.

- **Milestone:** [v0.4.0](https://github.com/jmfontaine/copyofa/milestone/4)
- **Product Map capability:**
  [Share and Evaluate Findings](../product-map.md#share-and-evaluate-findings)
- **Decision:**
  [ADR 0004: Publish each Report format as a JSON Schema](../decisions/0004-publish-each-report-format-as-a-json-schema.md)

v0.3.0 made the first finding worth sharing, the comparison Report. Until now a
Report could only be read as JSON, its structure was described only in prose, and it
recorded the absolute path of each Evidence Set, which names the collector's disks and
often their user account.

## Primary scenario

Refines [S5](../product-map.md#s5-share-and-evaluate-a-finding), starting with the
comparison Report of [S3](../product-map.md#s3-compare-two-tracks):

1. A collector compares a FLAC track with an MP3 of the same song:
   `copyofa compare <track-a> <track-b> --omit-locations --json > htf.json`. The Report
   holds no path of either Evidence Set, and says that it leaves them out.
2. They run `copyofa view htf.json > htf.html` and send both files.
3. The recipient opens `htf.html` in a browser, without CopyOfA and offline. It shows
   the inputs, the method, every measurement, each absent value with its reason, and
   the limitations, and gives the SHA-256 of the Report it was generated from.
4. With CopyOfA, the recipient runs `copyofa validate htf.json`: the file is a valid
   comparison Report of format version 2, and its SHA-256 matches the view's. The
   result states what validation does not establish: that the measurements are true,
   that CopyOfA produced the Report, or that the audio is unchanged.
5. An external catalog validates the same file against the published schema with its
   own JSON Schema validator, without CopyOfA.
6. A Report edited by hand, with a value of the wrong type or an unknown field, is
   reported invalid with the location of each problem, and `view` refuses it.

## In scope

- A JSON Schema for each Report format CopyOfA has produced: verification and
  inspection Reports at format version 1, comparison Reports at format versions 1
  and 2. They ship in the package and are linked from each format document.
- `copyofa validate <report>` with `--json`, for every Report kind.
- `copyofa view <report>`, which prints a self-contained HTML page for a comparison
  Report.
- `copyofa compare --omit-locations`, and comparison Report format version 2, which
  records what a Report leaves out.

## Out of scope

- A view of inspection and verification Reports; `view` refuses them.
- Checks beyond the schema, such as whether counts agree with entries or whether an
  offset fits the overlap.
- Comparing a received Report with the recipient's own copy, or reproducing its
  measurements. These are separate checks of S5.
- Signing Reports, or any check of who produced one.
- Leaving out anything but the Evidence Set locations, such as file names inside a set
  or the comparison time, and leaving out locations from inspection and verification
  Reports.
- Removing locations from an existing Report: a collector runs compare again.
- Charts in the view, styling for print or dark mode, and languages other than English.
- Writing a Report or a view into an Evidence Set; both go to stdout.

## Requirements

### Report schemas

- **One schema per Report kind and format version**, written as JSON Schema draft
  2020-12, as ADR 0004 decides: `verification-report-1`, `inspection-report-1`,
  `comparison-report-1` and `comparison-report-2`, each a `.schema.json` file in
  `src/copyofa/schemas/`. A schema is strict: every object allows only the fields its
  format document lists, and fields with a closed set of values, such as `outcome`,
  are enumerations.
- **The schemas agree with what CopyOfA prints.** Every Report the test suite produces,
  for every outcome, validates against its schema.

### Validation

- **Input.** `copyofa validate <report>` reads one file. A received Report is untrusted:
  validation never runs code from it, fetches anything, or stops with a traceback.
- **Well-formed JSON first.** A file that is not UTF-8, is not JSON, holds `NaN` or
  `Infinity`, repeats a member name in an object, or nests deeper than the parser
  allows is invalid, with a reason. A JSON string may hold a `\udcXX` escape, as a
  Report records a path that is not valid UTF-8.
- **Then the schema.** The document's `report_kind` and `format_version` select the
  schema. A document that is not an object, lacks either field, or whose
  `report_kind` is not a string or `format_version` not a positive integer, is
  invalid. An unknown kind, or a format version this CopyOfA has no schema for, is
  unsupported: a newer CopyOfA may know it.
- **Outcomes.** `valid`, `invalid` or `unsupported`. Each problem of an invalid Report
  has its location, as a JSON Pointer, and a message.
- **Limitations.** The result states that a valid Report is well formed and nothing
  more: validation establishes neither its findings, nor who produced it, nor anything
  about the audio it describes.

### View

- **Comparison Reports only.** `copyofa view <report>` validates the file first. It
  refuses a Report that is not valid, and a valid Report of another kind.
- **The whole Report.** The page shows every field of the Report. That includes the
  Report's `copyofa_version` and `compared_at`; each input's Evidence Set location or
  that it was left out, its Integrity Baseline (`manifest_sha256`, usability and
  problems), path, outcome and reason, properties, expected and observed File Digest,
  Audio Digest and inspect's findings; the method; each measurement for the downmix
  and each channel; each residual window; each absent value with its reason; and each
  limitation, word for word. With the locations left out, `manifest_sha256` still
  identifies each Evidence Set's Integrity Baseline. The page adds labels and units,
  never an interpretation.
- **Tied to its Report.** The page gives the SHA-256 of the exact bytes it was
  generated from, the Report's kind and format version, and the CopyOfA version that
  generated the page.
- **Self-contained and inert.** One HTML file, UTF-8, with its styles inline: no
  script, no external resource, and a Content Security Policy that forbids both. Every
  text from the Report is escaped, and a `\udcXX` escape in a path is shown as that
  text.

### Leaving out Evidence Set locations

- **`compare --omit-locations`** prints a Report without the `evidence_set` field of
  either input; the human result shows each track's path inside its set instead of
  its full path.
- **Comparison Report format version 2** is version 1 with one field added: `omitted`,
  the JSON Pointers of the values the Report leaves out, such as
  `/inputs/a/evidence_set`, and empty when it leaves out nothing. Compare prints
  version 2 from this release on, with or without the option. Validate and view also
  accept version 1.

### Output and exit codes

Validate and view follow the command conventions in AGENTS.md:

- Validate prints a short result: the outcome, the file's SHA-256, the kind and format
  version when known, each problem, and the limitations. `--json` prints the
  validation result instead, documented in `docs/formats/validation-result.md`. Its
  fields: the outcome, the Report's path as given made absolute, its SHA-256, kind and
  format version when known, the problems, the CopyOfA version, and the limitations.
- View prints the page on stdout and nothing else there.
- Exit 0 when the Report is valid (validate) or the page was printed (view); 1 when the
  Report is invalid or unsupported or view refuses it; 2 for invalid arguments; 130
  when canceled. A file that cannot be read, such as a missing file or a directory, is
  neither valid nor invalid: both commands exit 1 with the reason on stderr and nothing
  on stdout. View writes problems and errors to stderr.
- Neither command writes a file.

## Design decisions

- **Schemas and validator:** decided by ADR 0004, including the new runtime dependency
  on [jsonschema](https://github.com/python-jsonschema/jsonschema).
- **Leaving out at the source.** Compare leaves the locations out when it produces the
  Report, rather than a later command rewriting a saved one. The shared Report is then
  an original, not an edited copy, and the view, generated from it, cannot disagree
  with it. The cost is running compare again, a few seconds per pair.
- **Recorded, not silent.** A left-out value is absent and listed in `omitted`, so a
  reader can tell "left out" from "never recorded", and the schema can require
  `evidence_set` exactly when `omitted` does not list it.
- **HTML for the view.** It opens in any browser on any platform, holds the residual
  windows as tables, and needs no new dependency: the page is built with the standard
  library's escaping.
- **Unsupported is not invalid.** A newer format version is the expected way formats
  change; calling it invalid would tell a recipient their Report is wrong when their
  CopyOfA is old.

## Blocking questions

None.

## Acceptance criteria

Each criterion is verified by an automated test unless stated otherwise.

- **AC1 — Schemas published.** The four schema files are valid JSON Schema draft
  2020-12 and are linked from their format documents; CI's distribution check
  (`scripts/check_distributions.py`) confirms they ship in the wheel and the sdist.
  Every verification, inspection and comparison Report the test suite produces
  validates against its schema, including Reports with not inspected, not interpreted
  and failed files, an unusable baseline, and absent measurements.
- **AC2 — Valid Reports.** `copyofa validate` reports `valid` and exits 0 for a
  verification, an inspection, and a comparison Report printed by CopyOfA, and for a
  comparison Report of format version 1; the result names the kind and format version.
- **AC3 — Invalid Reports.** Each of these is reported `invalid` with a reason, exits 1
  and prints no traceback: a missing required field, a value of the wrong type, an
  unknown field, a value outside an enumeration, a malformed digest, a document that
  is not an object, one without `report_kind`, a `format_version` of `"2"` or `0`, an
  empty file, text that is not JSON, bytes that are not UTF-8, `NaN`, a repeated
  member name, and arrays nested 100,000 deep. A problem found by the schema gives its
  JSON Pointer.
- **AC4 — Unsupported Reports.** An unknown `report_kind` and a `format_version` of 99
  are reported `unsupported` and exit 1.
- **AC5 — Without CopyOfA (by hand, once).** A comparison Report and an inspection
  Report printed by CopyOfA validate against their published schemas with
  [Ajv](https://ajv.js.org/), a JavaScript implementation, and a Report edited to hold
  an unknown field fails.
- **AC6 — Locations left out.** With `--omit-locations`, the Report holds neither
  input's `evidence_set`, its `omitted` lists both pointers, neither set's path appears
  anywhere in stdout, with or without `--json`, and the Report validates. Without the
  option, the Report is format version 2 with an empty `omitted`. A version 2 Report
  missing `evidence_set` without listing it in `omitted` is invalid.
- **AC7 — View.** For comparison Reports with measurements, with an input not
  interpreted, with absent values, and with locations left out, the page holds each
  value the View requirement lists, the SHA-256 that `shasum -a 256` gives for the
  file, and each limitation. It holds no `<script` element and no URL other than in
  text from the Report, and declares the Content Security Policy. A track path
  containing `<script>` and one holding `\udc80` appear escaped as text.
- **AC8 — View refusals.** An invalid or unsupported Report, a valid inspection Report,
  and a file that cannot be read each make view exit 1 with nothing on stdout and the
  reason on stderr.
- **AC9 — Command conventions.** Validate prints its result, or its validation result
  with `--json`. A missing file and a directory make validate exit 1 with nothing on
  stdout and the reason on stderr. Both commands exit 2 for invalid arguments and 130
  when canceled with nothing on stdout, and neither changes the file it reads.
- **AC10 — Documented.** `docs/formats/validation-result.md` documents the validation
  result. `docs/formats/comparison-report.md` documents format version 2, how version
  1 differs, the option, and the view. The README shows the three commands. The
  Architecture section of AGENTS.md records the schemas, the new dependency, and the
  new format document.
- **AC11 — Real comparison (by hand, once).** The view of a comparison of two of the
  maintainer's tracks, made with `--omit-locations`, opens in Safari and in Firefox
  with no request in the network panel, and reads correctly.

## Manifesto alignment

- **Sharing and interoperability matter:** the Report's structure is published in a
  standard, machine-readable form that other software validates without CopyOfA, and
  the view needs only a browser.
- **Evidence, identity, and conclusions are distinct:** validation says only that a
  Report is well formed, and says so; the view shows the recorded measurements
  without adding a conclusion.
- **Results should be reproducible and durable:** each format version keeps its own
  schema, so a Report made today still validates after the format changes.
- **Measurements and interpretations should remain distinguishable:** left-out values
  are recorded as left out, and unsupported Reports are not called invalid.

## Appetite and scope cuts

Appetite: a few hours.

If the work outgrows it, cut in this order, keeping a validated comparison Report and
its view. Taking the first cut also narrows the v0.4.0 entry in the Product Map and the
milestone description, which promise a schema for every Report kind; update them at
the release review.

1. Schemas and validation for verification and inspection Reports.
2. The residual windows in the view; they stay in the Report.
3. `--omit-locations` and comparison Report format version 2.
