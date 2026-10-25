# Store Evidence Sets as BagIt bags

- **Date:** 2026-10-24
- **Status:** Accepted
- **Related artifacts:**
  [Brief: Preserve and Verify a Selected File Delivery](../briefs/0001-preserve-and-verify-file-delivery.md);
  Product Map capability
  [Preserve Evidence Throughout Its Lifetime](../product-map.md#preserve-evidence-throughout-its-lifetime)

## Context

An Evidence Set must stay verifiable for decades: after it moves, after CopyOfA
changes, and ideally without CopyOfA at all. Its on-disk format is the hardest choice
to reverse, because every archive a collector creates carries it. The format also has
to leave room for optional recovery information, such as PAR2, added later to sets
that already exist, without touching their Preserved Evidence. Re-reading media to
fix a format mistake is not acceptable.

## Decision

Each Evidence Set is a BagIt 1.0 bag
([RFC 8493](https://www.rfc-editor.org/rfc/rfc8493)):

- `data/` holds the Preserved Evidence and nothing else.
- `manifest-sha256.txt` is the Integrity Inventory of the payload. Its lines put two
  spaces between digest and path, the format `shasum -c` reads.
- `tagmanifest-sha256.txt` lists every other tag file CopyOfA writes, so damage to the
  Integrity Baseline records is detectable.
- `bag-info.txt` carries `Bagging-Date` and `Payload-Oxum`, reserved by the
  specification, and `Bag-Software-Agent`, an unreserved element that `bagit.py` also
  writes.
- CopyOfA's own records live in the `copyofa/` tag directory. `copyofa/recovery/` is
  reserved for recovery information.

## Rationale and alternatives

- **Independent verification.** Existing tools validate a bag without CopyOfA, such
  as the Library of Congress `bagit.py --validate`; file names without percent-encoding
  also check with `shasum -a 256 -c manifest-sha256.txt` run from the bag root.
- **Settled edge cases.** The specification defines relative `/`-separated paths,
  encoding of CR, LF, and `%` in file names, algorithm-tagged manifests, and the
  difference between a complete and a valid bag.
- **Room for recovery information.** Tag files may have any name outside `data/` that
  the specification does not reserve, so
  recovery files join an existing bag by rewriting only the tag manifest. A probe with
  par2cmdline 1.4.0 and `bagit.py` confirmed it: PAR2 files created later in
  `copyofa/recovery/`, with the bag root as base path, left `manifest-sha256.txt`
  byte-identical, kept the bag valid, and repaired a damaged and a deleted payload
  file after the bag moved to another path.
- **SHA-256.** RFC 8493 recommends SHA-512 as the default for new bags. SHA-256 is
  ample against accidental corruption, which is the threat here, and `shasum -a 256`
  or `sha256sum` ships with macOS and Linux. A bag can gain a `manifest-sha512.txt` in
  place later without breaking existing readers.

Alternatives considered:

- **BagIt plus a CopyOfA JSON inventory with per-file sizes.** Rejected: it stores the
  Integrity Inventory twice, and the two copies must agree, to recover sizes that only
  speed up detecting truncation. The digest alone decides whether a file changed.
- **A CopyOfA layout** (`evidence/`, a versioned `inventory.json`, a checksum file).
  Rejected: about the same amount of code, but completeness, path encoding, and
  protection of the records would be ours to define and document, and no existing
  tool would recognize the set.

## Consequences

- Per-file sizes are not recorded; `Payload-Oxum` gives the payload's total size and
  file count only.
- Nothing may be added to `data/` after acceptance without changing the Integrity
  Baseline. Recovery information, Derivatives, and later records go in tag directories
  or separate bags.
- Verification ignores files outside `data/` that the tag manifest does not list, so
  sets created by later versions stay verifiable by earlier ones.
- Verification ignores operating system metadata files under `data/`, such as
  `.DS_Store`, which Finder writes while a collector browses a set, and import never
  preserves them. `bagit.py` would report such a bag invalid; CopyOfA reports it
  intact when every preserved file matches, because those files are not evidence.
- Checking a set with an independent tool depends on that tool following RFC 8493
  section 2.1.3. bagit-python does not decode `%25`
  ([bagit-python#157](https://github.com/LibraryOfCongress/bagit-python/issues/157)),
  so it reports a set with `%` in a file name incomplete. CopyOfA keeps the standard
  encoding rather than follow a tool's bug.
- Repair must run on a staging copy and be accepted against `manifest-sha256.txt`.
  par2cmdline's default repair leaves the damaged original as `<name>.1` beside the
  repaired file, which invalidates the bag, and its `-p` option deletes the PAR2 files
  after a successful repair.
- Revisit this decision if BagIt prevents a required capability, or if file name
  normalization on a supported storage target breaks verification after relocation.
