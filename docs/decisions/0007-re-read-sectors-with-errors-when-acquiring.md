# Re-read sectors with errors when acquiring a CD

- **Date:** 2026-10-26
- **Status:** Accepted
- **Supersedes:** in decision 1 of
  [ADR 0005](0005-acquire-audio-cds-with-redumper.md), redumper's default retry count;
  its other decisions stand
- **Related artifacts:** Product Map capability
  [Acquire Audio and Record Its Origins](../product-map.md#acquire-audio-and-record-its-origins)
  and scenario [S1](../product-map.md#s1-preserve-a-cd)

## Context

ADR 0005 runs `redumper disc` once with redumper's defaults. By default, redumper
"records errors but performs no sector retries"
([redumper's README](https://github.com/superg/redumper#readme)): a sector the drive
failed to read, or read with a C2 error, stays in error. redumper b768 then refuses to
split a pressed CD with such a sector inside a track ("data errors detected, unable to
continue"), so acquire fails and keeps nothing (see
[Evidence Set format](../formats/evidence-set.md#how-an-acquired-set-is-accepted)).

A pressed CD with light scratches failed acquire this way. Errors like these often
come from dust or a scratch the drive reads through on another attempt, which is what
redumper's `--retries` does: it re-reads each sector in error up to that many times,
and its refine stage touches no other sector.

## Decision

1. **Acquire gives redumper a retry count.** `copyofa acquire` runs `redumper disc`
   with `--retries=20` by default, the count of the Redump project's
   [guidance for audio CD submissions](http://forum.redump.org/topic/47761/updated-guidance-for-audio-cd-submissions).
   `copyofa acquire --retries <count>` sets another whole number from 0; 0 is
   redumper's own default.
2. **The record states it.** The argument is one of the `reader.arguments` the
   Acquisition Record already lists, so its format does not change.
3. **The record counts the errors not corrected.** redumper logs the errors of its
   first read as `media errors`, and, when it re-read sectors, what the re-reads
   corrected as `correction statistics`. The record's SCSI and C2 counts in
   `read_errors` are the first less the second, so a disc whose errors the re-reads
   corrected is usually accepted with exit 0; its Q count stays the first, since the
   second also counts sectors whose subchannel the first never counted. Without
   re-reads, redumper logs no correction statistics and the counts are as before.
4. **Remaining errors are handled as before.** A disc whose errors remain after the
   re-reads fails or is accepted exactly as ADR 0005 and the Evidence Set format
   describe.

## Rationale and alternatives

- **Re-reading by default** because the common damaged disc, a lightly scratched one,
  then succeeds without the collector knowing redumper's options, and a disc read
  without error takes no longer: only sectors in error are read again.
- **20** because it is the Redump project's count for audio CDs; a collector can raise
  it for a disc that still fails, or try another drive.

Alternatives considered:

- **Keeping redumper's default and adding the option only.** Rejected: a lightly
  scratched disc would still fail by default, with a message that does not say what
  to do.
- **Splitting with `--force-split` when errors remain.** Deferred to the Later outcome
  Acquire More Kinds of Disc: it needs deciding what a track holds where the drive
  read nothing.
- **Running `redumper refine` as a further step after a failure.** Rejected: ADR 0005
  keeps acquire to one `redumper disc` run, and `--retries` gives that run the same
  re-reads.

## Consequences

- Acquiring a damaged disc takes longer: up to 20 more reads of each sector in error.
- The stand-in `redumper` of the tests logs correction statistics when told what it
  corrected, so tests cover the counts; a damaged disc is acquired by hand to confirm
  the re-reads themselves.
- The counts come from two log blocks that cover slightly different sectors: the dump
  stage also counts C2 errors in the lead-out it reads past the disc's end, and the
  drive's lead-in read can replace sectors in error before the re-reads. Such errors
  stay counted though the image no longer holds them, as they were before this
  decision.
- redumper keeps its counts in 32-bit unsigned integers. When a re-read turns a
  skipped sector into one with C2 errors, the C2 count it logs as corrected wraps
  below zero; acquire subtracts in the same arithmetic, so the record still gives the
  C2 samples left.
