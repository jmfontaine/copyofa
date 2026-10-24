# CopyOfA Product Map

This map describes the intended product; it does not claim that any capability has been
delivered or validated.

## Purpose

CopyOfA helps serious music collectors preserve recorded audio, understand what it
contains, compare their copies, and share findings that others can evaluate. It follows
the Manifesto’s **Acquire → Preserve → Analyze → Compare → Share** lifecycle. Collectors
can also begin with existing files or a shared Report; acquisition is not a prerequisite
for every workflow.

This map records intended capabilities and the Now / Next / Later roadmap. GitHub
release Milestones and their Issues establish committed work; detailed implementation
contracts belong in Issues or optional Briefs. The [Manifesto](manifesto.md) is the
authority for purpose, principles, and boundaries.

## Capability Areas

### Acquire Audio and Record Its Origins

Acquire digital audio from supported physical media and import audio files already
owned. Preserve the source information, acquisition observations, supporting records,
and limitations needed to understand where the audio came from. Accept useful incomplete
provenance without inventing missing history or requiring a collection-system account.

A selected delivery can include audio, original archives, and companion files whose
contents CopyOfA does not interpret. Record the accepted selection, original delivery
layout, and exclusions. Collectors may instead analyze externally maintained audio
directly; the result explains whether CopyOfA preserved the input.

This area serves the Manifesto’s audio-and-provenance scope and practical-accuracy
principle.

### Preserve Evidence Throughout Its Lifetime

Keep acquired or imported evidence usable for later investigation without reacquiring
the original media. Establish what was accepted, verify its integrity over time, and
preserve its meaning when storage locations or analytical methods change. Stored
integrity, acquisition accuracy, and completeness are separate claims.

Support optional recovery information and repair within declared limits. Restored
content is accepted against the existing Integrity Baseline; recovery cannot redefine
damaged content as correct. Export preserved audio for use in external tools while
keeping the Preserved Evidence intact and identifying transformations or omissions.

This area serves the Manifesto’s preservation-lifecycle and durable-results principles.

### Understand Audio

Describe the structure and properties of selected audio and produce useful measurements
for identified tracks, ranges, or ordered Audio Sequences. Help collectors investigate
silence, unexpected content, and possible anomalies while stating what was examined and
what remains unknown.

Keep File Identity separate from Audio Identity. Relate each measurement to its inputs,
interpretation, method, and scope so it can be understood and, where practical,
reproduced. Measurements provide evidence for interpretations; they do not establish
source attribution or mastering history by themselves.

This area serves the Manifesto’s evidence/identity/conclusion distinction and
reproducibility principle.

### Compare and Discover Relationships

Compare selected tracks or editions, identifying complete audio matches, matching
portions, and measured differences. Describe alignment, coverage, excluded material, and
uncertainty without implying that a partial match establishes equality of complete
inputs.

Discover related audio within a collector-selected search scope. Search may use Evidence
Sets, externally maintained audio, or existing Reports with sufficient compatible data.
Distinguish established relationships from candidates that need further comparison.
Edition-level findings explain their basis through track correspondences and coverage; a
single shared track does not establish edition equivalence.

This area serves the Manifesto’s goals of understanding versions, edits, and unexpected
relationships across collections and discographies.

### Share and Evaluate Findings

Store authoritative machine-readable Reports and generate human-readable views of the
same recorded findings. A portable view can be read without installing CopyOfA or
obtaining the audio. CopyOfA provides its supported Report operations. External software
may independently consume the documented structured representation without installing
CopyOfA; performing new evidence-dependent analysis requires the relevant evidence and
analysis tools. Checks explain which audio or other material they require.

Allow recipients to inspect methods, evidence references, provenance, and limitations;
validate a Report; compare it with their own copy; or reproduce measurements when the
prerequisites are available. These checks establish different things. Reports and
identifiers remain useful across installations without depending on a central service.

This area serves the Manifesto’s sharing, interoperability, and durable-results
principles.

## Collector Scenarios

### S1. Preserve a CD

A collector has a newly acquired or aging CD and wants continued access to its audio.
CopyOfA acquires what its supported method can capture, preserves relevant records, and
explains problems or omissions. Useful partial evidence may be retained. The collector
can later verify, analyze, or export the preserved audio, including individual tracks
where their boundaries are known, for external tagging and playback. Completion does not
conceal uncertainty about capture accuracy or coverage.

### S2. Use Audio Files Already Owned

A collector has a purchase, existing rip, or digitized analog recording, possibly with
archives, companion files, or incomplete history. CopyOfA preserves a selected delivery
or analyzes supported audio directly, retaining the distinction between these modes. It
describes examined content without treating uninterpreted material as absent.
Completeness refers to the accepted selection; determining whether a publisher supplied
everything requires an independent expected inventory. Importing audio does not
establish the accuracy of its earlier acquisition.

### S3. Compare Two Tracks

A collector selects two tracks to determine whether their audio matches or contains
subtle differences. A Comparison Report identifies complete matches, aligned or partial
matches, and supported measured differences with their affected ranges. Changes to a
file’s container or tags can be distinguished from changes to its audio. Measured
differences do not by themselves establish audibility or a particular mastering history;
unsupported or inconclusive comparisons remain explicit.

### S4. Compare Two Editions

A collector owns two editions or pressings and wants to understand their audio
relationship. A Comparison Report explains supporting track comparisons, matching
regions, differences, coverage, and uncertainty. Track boundaries, durations, offsets,
or edits may differ. The collector can assess the evidence without mistaking aligned
overlap for whole-input equality or a suspected shared master for an observed fact.

### S5. Share and Evaluate a Finding

A collector shares a Report and its portable human-readable view without exchanging
audio. Another collector can read the finding and understand its basis. With CopyOfA,
they can inspect or validate the machine-readable Report and perform further checks when
they have the necessary evidence. Checking the Report, comparing another copy, and
reproducing measurements remain distinct outcomes. Missing audio limits verification
without making the recorded finding unreadable.

#### Variant — Supply Evidence to an External Recording Catalog

A collector uses CopyOfA’s documented structured data and Reports as source material for
an external recording catalog or research service. The external system can associate
findings with its own catalog entities, retain distinct source occurrences even when
their audio matches, and trace measurements and comparisons to their identified inputs,
provenance, methods, and limitations. It can consume recorded findings without parsing
human-readable presentations or depending on CopyOfA’s private application state.
Catalog classification, aggregation, editorial conclusions, and publication remain
outside CopyOfA.

[NIN Deviations](https://nindeviations.com/about) is a concrete example: CopyOfA
supplies the audio evidence for recording tracking and comparison; an external layer
maps that evidence into the catalog and website. An Audio Identity is not the identifier
of a NIN Deviations Recording. Matching audio does not merge distinct source
occurrences, and differing audio does not automatically establish different catalog
Recordings.

### S6. Check an Archive Later

After time passes or storage moves, a collector checks an Evidence Set against its
established Integrity Baseline. CopyOfA identifies material that matches, has changed,
is missing, is unavailable, or was not checked. Supported recovery can attempt repair
within its stated limits; an intact copy restored externally can also be verified.
Replacements must match the existing Integrity Baseline before acceptance. Original
acquisition accuracy remains a separate question.

### S7. Find Related Audio

A collector starts with a track or edition and searches selected material for matches or
related editions, including relationships within one edition. Findings distinguish
complete matches, excerpts, edited portions, and candidate similarities according to the
method’s capabilities. They identify the searched inputs, supporting track
relationships, coverage, and unresolved questions. One shared track does not make two
editions equivalent, and insufficient Report data may require access to audio.

## Core Concepts

These distinctions describe the product's meaning; they do not prescribe a database or
service architecture. Use capitalized concept names when referring to these meanings.

| Concept | Meaning |
| --- | --- |
| Source Description | Observed, supplied, or inferred information about the audio’s claimed origin. |
| Acquisition/Import Record | The context, observations, and limitations of one event bringing audio into the workflow. Separate acquisitions retain separate records. |
| Preserved Evidence | Original imported files or declared acquisition output, with supporting records, retained separately from later transformations and findings. |
| Evidence Set | An explicitly selected unit of Preserved Evidence and provenance, with an Integrity Inventory and Integrity Baseline, that is accepted, verified, and moved independently. |
| Audio Sequence | Ordered decoded sample frames with declared sample rate, channel interpretation, and extent, including selected ranges and assembly. |
| File Identity and Audio Identity | Respectively identify exact stored bytes and an explicitly interpreted Audio Sequence. Neither establishes source attribution or acquisition accuracy. |
| Report | The authoritative structured result, including input references, method, findings, and limitations, from which human-readable views are generated. |
| Comparison Report | A Report identifying the compared inputs and their corresponding Evidence Sets when preserved, and recording the scope, method, relationships or differences, and limitations. It follows the shared Report rules. |
| Integrity Inventory and Integrity Baseline | Respectively record what belongs to an Evidence Set and retain the expected values and supporting records used for later integrity checks. |
| Derivative | A converted or processed representation that identifies its source and transformations without replacing Preserved Evidence. |

Two Evidence Sets can refer to the same claimed source while retaining distinct
Acquisition/Import Records, provenance, and limitations. Assurance dimensions and
findings may coexist; these concepts do not prescribe mutually exclusive status values.

## Shared Product Expectations

Normal workflows need practical defaults, actionable feedback, progress, safe
cancellation, and structured outcomes for automation. Partial work and uncertainty
remain visible. Accepted evidence stays usable as operations fail or new results are
produced.

Results distinguish stored integrity, acquisition accuracy, coverage, and confidence in
an interpretation. Corrected provenance or findings do not silently rewrite earlier
Reports. Sharing permits deliberate omission of private information while keeping the
exported data and presentation consistent. Received Reports are treated as untrusted
data.

macOS is the primary support target. Other platforms should remain feasible where
contributors can develop and test them. AI may assist operation and interpretation, but
acquisition, integrity, identity, analysis, comparison, and Report handling work
independently of AI. AI interpretations remain attributed and grounded in recorded
evidence.

## External Boundaries

Collection ownership, cataloging, playback, tagging, audio editing, mastering, and
analog digitization remain external. Optional catalog references describe sources
without defining Audio Identity or requiring a particular service. Selected companion
files can be preserved without turning CopyOfA into a packaging catalog.

CopyOfA manages its evidence, integrity records, and supported recovery information.
Storage provisioning, replication, and broader backup orchestration remain external.
Archives and Reports remain usable after relocation and without a private application
database. Their documented representations support independent use and a possible
separate comparison service; CopyOfA does not become a central music database.

## Roadmap

Plan CopyOfA as a clean reboot from the Manifesto. Retire the previous implementation
while retaining Git history; its code does not define the new architecture or release
sequence. Establishing file workflows before integrating CD acquisition is a
recommendation to assess when planning the first release.

### Now

No committed release. No GitHub release Milestone has been created.

### Next

No release outcomes have been selected. Choose the first useful collector outcome, its
supported boundary, and an effort appetite before committing work.

### Later

- **Preserve and Verify a Selected File Delivery** — Acquire Audio and Record Its
  Origins; Preserve Evidence Throughout Its Lifetime. S2 and S6.
- **Inspect Audio and Share Its Analysis** — Understand Audio; Share and Evaluate
  Findings. S2 and S5.
- **Compare Selected Tracks or Editions** — Compare and Discover Relationships; Share
  and Evaluate Findings. S3–S5.
- **Preserve a Supported CD and Use Its Audio Later** — Acquire Audio and Record Its
  Origins; Preserve Evidence Throughout Its Lifetime. S1, connected to S2–S6. Lossless
  export is also useful for preserved file inputs and can be delivered earlier.
- **Find Related Audio Among Selected Material** — Compare and Discover Relationships.
  S7.
- **Repair Limited Archive Damage Using Optional Recovery Information** — Preserve
  Evidence Throughout Its Lifetime. S6.

These are intended outcomes without release assignments. Their order here does not
prescribe a release sequence.

Preserving one selected file delivery and verifying it after relocation remains a
candidate for the first release. It offers a useful end-to-end outcome using files the
collector already owns. It has not been selected.

Move the selected outcome into Now when its GitHub release Milestone establishes
commitment. Keep Next limited to the following one or two outcomes when planned, and
review the roadmap after each release.
