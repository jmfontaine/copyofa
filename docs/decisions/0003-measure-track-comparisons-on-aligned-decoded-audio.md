# Measure track comparisons on aligned decoded audio

- **Date:** 2026-10-25
- **Status:** Accepted; decisions 2 (Alignment) and 3 (Overlap) superseded by
  [ADR 0006](0006-locate-matching-portions-between-tracks.md)
- **Related artifacts:**
  [Issue #74: Compare two tracks across formats](https://github.com/jmfontaine/copyofa/issues/74);
  [ADR 0002](0002-define-audio-digest-from-canonical-pcm.md); Product Map capability
  [Compare and Discover Relationships](../product-map.md#compare-and-discover-relationships)
  and scenario [S3](../product-map.md#s3-compare-two-tracks)

## Context

Collectors compare tracks across formats: the same song as 24-bit, 96 kHz FLAC and as
44.1 kHz MP3. The Audio Digest of ADR 0002 settles only identical lossless audio, so a
comparison has to measure the decoded audio. The two tracks may differ in sample rate,
channel count, leading silence, level and encoding.

Following the Manifesto, a comparison Report holds measurements, not
interpretations: it never says "same master" or "match". Its numbers are cited and
compared across Reports, so the method behind them has to be fixed and stated.

A probe on the maintainer's albums tried the method below. FLAC against MP3 of the
same songs gave correlations of 0.93 to 0.97 and offsets under 0.11 s. Two unrelated
songs gave 0.02. Each pair took about 2 s.

## Decision

`copyofa compare <track-a> <track-b>` measures how track B relates to track A. Both
tracks are decoded as `inspect` decodes them (libsndfile), as floating-point samples
where 1.0 is full scale.

1. **Common rate.** When the sample rates differ, the track at the higher rate is
   resampled to the lower one with libsoxr (python-soxr) at its `VHQ` quality.
   Every measurement is at that common rate and covers only its band.
2. **Alignment.** Each track is mixed down to mono, the mean of its channels. One
   global offset aligns them: the lag with the largest magnitude of the FFT
   cross-correlation of the two downmixes, over every lag at which they overlap. A
   positive offset means track B starts that many frames later than track A: frame
   *n* of A lines up with frame *n* + offset of B. The magnitude is used, not the
   signed maximum, so that a copy with its polarity inverted still aligns and shows as
   a negative correlation.
3. **Overlap.** The measurements cover the frames where the aligned tracks overlap,
   given as frames at the common rate and as a fraction of each track.
4. **Measurements.** Each is given on the downmix, and for each channel when both
   tracks have the same channel count. Channels are paired by position. Over the
   overlap, with *a* and *b* the samples of A and B:
   - **Correlation:** the Pearson correlation coefficient of *a* and *b*.
   - **Gain:** the least-squares gain *g* that maps B onto A, that is *a* ≈ *g*·*b*:
     *g* = Σ*ab* / Σ*b*², given as 20·log10|*g*| dB. Track B at half the amplitude
     of A gives +6.02 dB. A negative *g*, which an inverted polarity gives, has the
     sign of the correlation.
   - **Residual:** the level of *a* − *g*·*b* relative to A,
     10·log10(Σ(*a* − *g*·*b*)² / Σ*a*²) dB, over the whole overlap and over each
     one-second window of it, starting at its first frame; the last window may be
     shorter.
5. **Identical audio.** When both tracks have an Audio Digest and the digests are
   equal, the Report states that the audio is identical. The offset is then 0
   without a search, unless the tracks have no frames, and the residual is absent
   with that reason.
6. **Undefined values.** A value that the audio leaves undefined is absent, with a
   sentence saying why, never NaN or infinity: no offset when a track has no frames
   or, for audio that is not identical, when a downmix is zero throughout; no
   correlation when a track is constant over the overlap; no gain when B is zero over
   it or *g* is zero; and no residual when A is zero, the gain is undefined, or
   *a* − *g*·*b* is exactly zero.

## Rationale and alternatives

- **Resample down, not up.** The lower rate's band is all both tracks hold; resampling
  up adds no information.
- **libsoxr at `VHQ`.** A widely used resampler, with wheels for every supported
  Python, so the method runs anywhere CopyOfA does. Its very high quality preset keeps
  its own error far below anything the residual of a real comparison shows, and costs
  about half a second for a six-minute 96 kHz stereo track. A fixed, named preset
  makes the Report reproducible.
- **One alignment on the downmix.** One offset for all channels keeps the channels
  in step, and the downmix holds both channels' content, which a single channel may
  lack.
- **Plain cross-correlation, not normalized per lag.** Each lag's value grows with
  its overlap, which favors the long overlaps whole tracks have. A per-lag Pearson
  correlation costs much more and can prefer a short, accidental overlap.
- **Magnitude, not signed maximum.** With the signed maximum, an inverted copy aligns
  at an arbitrary lag, and every measurement after it is meaningless.
- **Gain mapping B onto A.** With *g* fitted as *a* ≈ *g*·*b*, the residual relative to
  A is the smallest left after any gain, 1 − *r*² when both are zero-mean. An
  unrelated B gives a gain far below 0 dB and a residual near 0 dB, as the probe
  showed.
- **One-second windows.** They show where along the track the residual changes,
  without a parameter to choose.

Alternatives considered:

- **Audio fingerprints, such as Chromaprint.** Rejected: they recognize the same
  recording perceptually and give a match score, which is an interpretation, not a
  measurement.
- **Aligning by onsets or by several segments.** Not adopted now: finding edits,
  drift and speed changes is out of scope for v0.3.0. One global offset is the
  smallest method that handles the leading-silence and encoder-delay differences
  seen in practice.
- **Comparing MP3 as encoded frames.** Rejected: it says nothing about two
  different encodings, which is the case that matters.

## Consequences

- MP3 measurements depend on the decoder, as MP3 properties already do; the Report
  names the decoder and its version.
- Edited, sped-up or drifting copies are not located: they lower the correlation
  and raise the residual, and the Report says so.
- Both tracks are held in memory while they are compared, and the alignment FFT runs
  in double precision over both tracks' length. Two 4½-minute 96 kHz stereo tracks
  peak at about 3 GB of resident memory. Very long tracks may need a lighter
  alignment.
- A later method gets a new `alignment` value or a new Report format version, so
  Reports made with this one keep their meaning.
- Revisit this decision when a release needs to find edits or compare editions, or
  when a supported format cannot be decoded to floating-point samples.
