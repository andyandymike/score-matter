# ScoreMatter M0 bootstrap contract

Status: experimental public contract
Version: 0.1
Runtime impact: none
Model requirement: none

## Purpose

M0 bootstrap proves a narrow offline evidence path before ScoreMatter invokes a
real music model:

```text
strict Brief + reviewed Plan + resolved Request
  -> built-in Provider
  -> immutable content-addressed WAV artifact
  -> artifact manifest + run receipt
  -> replay integrity verification
```

This contract tests schemas, hashes, boundaries, and evidence. It does not test
AI music.

## Included

- Strict duplicate-key-aware JSON loading.
- JSON Schema Draft 2020-12 validation with unknown fields rejected.
- RFC 8785/JCS canonical bytes and SHA-256 digests.
- Versioned Brief, Plan, Plan Review, Provider Descriptor, Resolved Request,
  provider-options, manual-source, Artifact Manifest, and Run Receipt schemas.
- Built-in `mock`, `manual`, and `replay` provider boundaries.
- Deterministic tiny stereo PCM WAV generation for synthetic fixtures.
- Bounded manual PCM WAV ingestion with exact source-byte binding.
- Immutable content-addressed artifact and manifest storage.
- Exact artifact replay verification without audio regeneration.
- Windows-safe relative-path validation.
- Tracked-tree privacy/model/audio audit.

## Explicitly excluded

- A music-generation model, model manager, weight download, GPU path, or cloud
  provider.
- General audio decoding or transcoding; M0 accepts only bounded PCM WAV.
- Musical, loop, key, BPM, meter, vocal, loudness, clipping, or perceptual QA.
- Blind listening, creative approval, rights approval, signing, or release
  authority.
- Evaluation/release packages or Godot integration.
- Any claim that an imported or generated artifact is publishable.

## Authority and trust boundaries

- Input JSON, filenames, imported audio, and provider output are untrusted.
- A valid schema proves structure only.
- A matching digest proves byte identity relative to recorded evidence only.
- The mock provider proves deterministic fixture generation, not music quality.
- The manual provider records source bytes and a source declaration; it does not
  approve rights.
- Replay proves that recorded artifact bytes still match; it does not regenerate
  a provider result.
- Run receipts record ScoreMatter observations. They do not attest to opaque
  provider internals.
- Every output remains local evidence and a candidate.

## Contract rules

Authority-bearing JSON:

- uses an exact `schema` identifier;
- rejects duplicate keys, non-finite numbers, unknown fields, and unknown schema
  identifiers;
- canonicalizes with RFC 8785/JCS as UTF-8 without a BOM;
- uses `sha256:<64-lowercase-hex>` digests;
- records only normalized relative paths in portable manifests.

The initial execution bundle contains:

```text
brief.json
plan.json
plan-review.json
resolved-request.json
```

The executor validates every document and cross-checks:

- Plan -> Brief digest;
- Plan Review -> Brief and Plan digests;
- Plan Review decision is `allow`;
- Resolved Request -> Brief, Plan, Plan Review, and current built-in Provider
  Descriptor digests;
- nested provider options against the adapter-owned options schema.

Any changed byte or stale binding fails before provider execution.

## Built-in providers

### Mock

`mock` creates a tiny deterministic signed-16-bit PCM WAV from explicit
frequency, amplitude, output format, sample count, channel count, sample rate,
and seed. Repeated execution is checked for identical bytes within one fixed
implementation environment. Cross-platform bit-exact regeneration is not
guaranteed. Each execution still gets a distinct run receipt unless a test
clock/identity is injected.

The provider explicitly declares text-to-music and native-loop capabilities
unsupported. Its output is synthetic test evidence, not BGM.

### Manual

`manual` ingests an existing bounded PCM WAV only when:

- the source record binds the exact audio SHA-256;
- the source record carries an explicit provenance declaration and rights
  evidence reference;
- decoded WAV facts match the Resolved Request output contract.

Ingestion never upgrades `rights_reviewed: false`.

### Replay

`replay` validates a frozen source run receipt, every artifact manifest, every
relative path, byte count, and SHA-256. It produces a new replay receipt that
references the source run. The source run remains the artifact authority;
replay execution metadata remains separate evidence.

## Local storage

The default local store is `.local/`:

```text
.local/
  artifacts/sha256/<prefix>/<digest>/payload.wav
  manifests/sha256/<prefix>/<digest>.json
  runs/<execution-id>/run-receipt.json
  staging/
```

`.local/` is ignored and denied by the tracked-tree audit. Artifact publication
is atomic no-replace where supported by the M0 store implementation. Existing
content is verified rather than overwritten.

## CLI boundary

```text
score-matter validate <document>
score-matter digest <document>
score-matter provider probe <mock|manual|replay>
score-matter demo init <new-directory> --provider <mock|manual>
score-matter mock execute --bundle <directory> --store <directory>
score-matter manual source-record <wav> <new-json> <source arguments>
score-matter manual ingest --bundle <directory> --audio <wav>
                          --source-record <json> --store <directory>
score-matter replay verify <run-receipt> --store <directory>
```

Commands emit a stable `SCORE_*_OK` sentinel on success and a structured
`SCORE_ERROR` line on expected boundary failure.

## Verification required

- Valid documents pass and canonical key ordering produces the same digest.
- Duplicate keys, non-finite values, unknown fields, and unknown schemas fail.
- Stale Brief/Plan/Review/Provider bindings fail before execution.
- Traversal, absolute, reserved Windows, backslash, and unsafe relative paths
  fail.
- Two mock executions of the same request in one test environment produce
  identical WAV SHA-256 values and different execution receipts.
- Manual ingestion rejects a source-hash or media-contract mismatch.
- Replay rejects missing, changed, oversized, or path-escaped artifacts.
- Content-addressed storage never silently replaces different bytes.
- The tracked tree contains no private planning/evidence, model weights, or
  unapproved audio.
- Tests pass on Windows and Linux with no model, GPU, or provider credential.

## Current proof boundary

Passing M0 bootstrap tests may establish only that the named contract,
canonicalization, storage, built-in fixture/ingest, and replay checks work for
their tested inputs. It does not establish M0 completion, real-model
compatibility, audio quality, creative approval, rights approval, signing,
packaging, or game integration.
