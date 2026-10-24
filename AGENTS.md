# Instructions for coding agents

## Product

CopyOfA is being rebuilt from a clean slate. Read these before proposing or doing work:

- [docs/manifesto.md](docs/manifesto.md) is the authority for purpose, principles and
  boundaries.
- [docs/product-map.md](docs/product-map.md) holds the capabilities, collector
  scenarios, core concepts and the Now / Next / Later roadmap. Use its capitalized
  concept names (Evidence Set, Audio Identity, Report, …) with the meanings it gives.

The previous implementation is retired; its last version is commit `0d04a38`. Consult
its history for lessons learned, not as the architecture to follow. There is no
toolchain yet.

## Language

Write US English in everything: code, comments, documentation, messages, tests and
commit messages (`-ize`, `-or`, `-er`, `canceled`, `catalog`). Optical media are
"discs"; "disk" stays correct for other storage and in macOS names such as `diskutil`.

The project is "CopyOfA" in prose and `copyofa` in identifiers: the repository,
packages, commands, configuration directories, `COPYOFA_*` environment variables, and
the tool name recorded in data. Type names use `CopyOfA` (`CopyOfAError`).

## Conventions

Workarounds that are knowingly less than ideal carry a `KLUDGE:` comment that states
what is wrong and what removes it. Grep for `KLUDGE` before changing such code, and do
not add one without a removal condition.
