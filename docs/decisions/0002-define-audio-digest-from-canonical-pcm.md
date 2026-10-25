# Define Audio Digest from canonical PCM

- **Date:** 2026-10-25
- **Status:** Accepted
- **Related artifacts:**
  [Brief: Describe the Audio in an Evidence Set](../briefs/0002-describe-audio-in-evidence-set.md);
  Product Map capabilities
  [Understand Audio](../product-map.md#understand-audio) and
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)

## Context

File Digest, the SHA-256 of a file's bytes, changes when only a tag, the cover art, or
the compression level of a FLAC file changes. Collectors need to recognize the same
audio despite those changes, and later releases build on that: comparison, discovery,
and catalogs such as NIN Deviations that cite CopyOfA's findings. The Product Map
defines Audio Digest as what recognizes an explicitly interpreted Audio Sequence:
decoded sample frames with a declared sample rate, channel interpretation, and extent.
Equal digests mean identical audio; a digest says nothing about what the audio is.

A digest that Reports publish is hard to change, because shared Reports and external
catalogs keep the old values. It has to be reproducible on another computer, with
another decoder, and without CopyOfA.

That holds only when decoding is exact. Lossless formats such as FLAC and PCM WAV
decode to the same integers in every correct decoder. Lossy formats do not: a test MP3
decoded by libsndfile (mpg123) and by ffmpeg gave the same 88,200 frames but different
sample values, and mpg123 itself selects CPU-specific code.

## Decision

The Audio Digest of an integer PCM Audio Sequence is the string

```text
pcm1:<sample rate>:<channels>:<bits per sample>:<sha256>
```

such as `pcm1:44100:2:16:8b348bf5…` with all 64 hexadecimal digits, where `<sha256>`
is the SHA-256 of the canonical PCM byte stream:

- every sample frame of the sequence, in order, with the channels of each frame
  interleaved in the order the source stores them;
- each sample a signed two's-complement integer at the sequence's bits per sample,
  little-endian, in the fewest whole bytes that hold it (2 bytes for 16 bits, 3 for 24);
- nothing else: no header, no metadata, no padding.

The sample rate, channel count, and bits per sample are the interpretation; they are
part of the digest, so the same bytes declared at another rate give another digest.
`pcm1` names this definition. A later definition gets a new prefix, and values with
different prefixes are never compared as equal or different.

CopyOfA gives an Audio Digest only to audio it decodes exactly: FLAC and integer PCM
WAV in v0.2.0. Lossy audio, such as MP3, gets none, and the Report says so.

## Rationale and alternatives

- **Reproducible without CopyOfA.** The canonical byte stream is what
  `flac -d --force-raw-format --endian=little --sign=signed -c <file>` and
  `ffmpeg -i <file> -f s16le -` (or `s24le`) write, so piping either into
  `shasum -a 256` reproduces the hash. A probe confirmed it for 8-, 16- and 24-bit FLAC
  with flac and ffmpeg.
- **Same layout as the FLAC MD5 signature.** FLAC stores an MD5 of exactly this byte
  stream in its STREAMINFO block, so one read yields both the digest and a check of the
  encoder's own signature.
- **SHA-256**, as for File Digest: one algorithm across CopyOfA, available as
  `shasum -a 256` on macOS and Linux.
- **The interpretation in the value.** One string compares with one equality test and
  can be cited by itself, without a separate set of fields that must travel with it.
- **"Digest", not "identity" or "fingerprint".** The value recognizes identical audio;
  it does not say what the audio is, which "identity" suggests. In audio, a fingerprint
  is perceptual and matches the same recording across lossy encodings; this value
  changes with a single sample, so "fingerprint" would promise matches it never makes.
  "Digest" is also the word the verification Report already uses for SHA-256 values.

Alternatives considered:

- **Hash the samples only, with the interpretation in separate fields.** Rejected:
  two sequences at different sample rates would share a digest, and every consumer
  would have to remember to compare the extra fields too.
- **Hash a header plus the samples.** Rejected: no standard tool produces that byte
  stream, so the digest could not be checked without CopyOfA.
- **Normalize to one representation, such as 32-bit integers or floats.** Rejected: a
  16-bit sequence and the same samples padded to 24 bits are different Audio
  Sequences. Relating them is a comparison finding, not a digest.
- **Give MP3 a digest bound to the decoder that produced it.** Rejected: it would
  match only digests from the same decoder build, so a shared Report would show
  "different audio" for the same file decoded elsewhere.
- **Hash the MP3's encoded audio frames, without its tags.** Not adopted now: it is
  exact and decoder-independent, but it recognizes an encoded stream, not an Audio
  Sequence, and the Product Map has no concept for it yet.

## Consequences

- Retagging, re-embedding art, or recompressing a FLAC file keeps its Audio Digest;
  converting it to WAV keeps it too. Changing the sample rate or bit depth changes it.
- Two editions with the same samples share an Audio Digest. That establishes neither
  common source nor acquisition accuracy; Reports say what a digest does not establish.
- A digest covers the whole Audio Sequence a file decodes to. Digests of ranges or
  assembled sequences need their own definition when a release needs them.
- MP3 files are described, with decoder-dependent measurements, but cannot be matched
  by Audio Digest. Comparing them needs the measurement-based comparison of a later
  release.
- 32-bit float PCM gets no digest under `pcm1`; adding it needs a new definition.
- Revisit this decision if a supported lossless format cannot produce this byte stream,
  or if a consumer needs digests of ranges or of lossy streams.
