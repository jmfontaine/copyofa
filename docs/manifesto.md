# CopyOfA Manifesto

## Vision

CopyOfA is a preservation and forensic toolkit for music collectors that acquires and
maintains trustworthy evidence of recorded audio, then lets collectors analyze, compare,
and share what that evidence reveals.

<!-- rumdl-disable-next-line MD036 -->
**Acquire → Preserve → Analyze → Compare → Share**

So collectors can discover what is actually in their collections.

## Target Users

CopyOfA is built first for serious music collectors who care about preserving and
understanding the exact audio contained in the releases they own. Within that audience,
common profiles include:

- **Preservation-minded collectors:** want reliable archival copies of audio from aging,
  fragile, or obsolete media and confidence that those archives remain healthy over
  time.
- **Discography researchers:** want to compare releases and understand differences in
  masters, versions, edits, and other audio content.
- **Power users and contributors:** want structured reports, automation, scripting, and
  data that can support broader comparison and research workflows.

## What CopyOfA Enables

- Preserve audio from aging, fragile, or obsolete media before degradation, damage, or
  hardware obsolescence makes it difficult or impossible to recover, and maintain
  archive integrity over time.
- Compare releases to identify masters, edits, mispressings, and other meaningful audio
  differences.
- Recognize when different releases contain identical or substantially equivalent
  audio.
- Discover anomalies and unexpected relationships across a collection or discography,
  including mislabeled tracks, hidden audio, unusual versions, and audio shared across
  releases.
- Share portable analysis reports so collectors can compare findings and independently
  evaluate the evidence behind them.

## Principles

- **Audio and provenance are the scope.** CopyOfA works with digital audio acquired from
  physical media or files. Digitized analog audio may also be analyzed, but CopyOfA does
  not perform the digitization. For analog sources, the digitization chain is part of
  the provenance and should support a flexible, largely free-form description, with
  structured fields where they add clear value.
- **Provenance should identify the source.** CopyOfA should record the information
  needed to understand what the audio came from and how it was acquired, such as catalog
  or pressing identifiers, matrix/runout information, media type, disc number, and
  acquisition details. Collectible, visual, and packaging attributes unrelated to source
  identification are out of scope.
- **Accuracy must remain usable.** CopyOfA should favor accuracy without requiring
  restrictive hardware, software, or procedures that make the tool impractical for
  collectors.
- **Evidence, identity, and conclusions are distinct.** CopyOfA should preserve the
  acquired evidence and its provenance separately from any canonical representation or
  identity and from conclusions derived by analysis. Canonicalization must not erase
  acquisition-specific evidence. Where technically meaningful, equivalent source audio
  should resolve to the same canonical identity and materially equivalent analysis
  results; for digitized analog sources, equivalence should not imply sample-for-sample
  identity.
- **Results should be reproducible and durable.** CopyOfA should record enough
  information about the source, acquisition or digitization process, analysis methods,
  and relevant tool versions for results to be understood and, where practical,
  reproduced. Preserved evidence should remain usable for future analysis as methods
  improve without requiring the original media to be reacquired.
- **Measurements and interpretations should remain distinguishable.** Conclusions should
  be traceable to underlying evidence, and uncertainty should be communicated explicitly
  rather than presenting unsupported inference as fact.
- **Preservation is a lifecycle.** It includes durable storage, ongoing integrity
  verification, and, where practical, optional recovery information that can repair
  limited corruption without reacquiring the original media. Archives may be stored
  locally or remotely without requiring a particular storage provider or topology.
- **Sharing and interoperability matter.** CopyOfA should expose its data, reports,
  terminology, and operations in structured forms that humans and software agents can
  use. Reports should be easy to share and compare peer-to-peer, and the design should
  not prevent a separate centralized comparison or research service later.
- **Collection management remains external.** Users should be able to associate archives
  and reports with identifiers from whatever cataloging or inventory system they use,
  without CopyOfA requiring or replacing any particular system.
- **macOS is the primary supported platform.** Design and implementation should avoid
  unnecessarily preventing Windows or Linux support, but support for those platforms
  depends on contributors who can develop and test them.
- **AI is assistive, not evidentiary.** AI-assisted workflows may help users configure
  hardware, operate the tool, explore collections, and interpret reports, but core
  archival and analytical results should not depend on AI. AI may interpret evidence; it
  should not manufacture or replace it.

## Non-goals

CopyOfA is not intended to be:

- A general-purpose music library, player, or streaming service.
- A collection manager, Discogs replacement, or packaging/collectibles catalog.
- An audio editor, mastering tool, or analog digitization workstation.
- A centralized music database, although its reports and structured data may support a
  separate centralized comparison or research service.
- A general-purpose backup, storage, or infrastructure orchestration system. CopyOfA may
  manage archive integrity and recovery data, but broader replication, storage
  lifecycle, and infrastructure management are outside its scope.
