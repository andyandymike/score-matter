# Security Policy

## Supported versions

ScoreMatter has not released a supported version yet.

## Reporting a vulnerability

Please do not disclose security-sensitive details in a public issue. Use the
repository host's private vulnerability reporting feature when available, or
contact the maintainer through the account that publishes this repository.

Useful reports include the affected revision, platform, reproduction steps,
impact, and suggested mitigation. Never include real credentials, private
prompts, licensed reference audio, generated production audio, terms evidence,
or model files in a report.

## Security boundaries

ScoreMatter is local-first, but ordinary child processes do not prove network
or filesystem isolation. The current M0 built-ins are dependency-light test and
ingest paths; real providers require a separate isolation design and evidence.

Treat all imported JSON, audio, provider output, manifests, filenames, archives,
model files, and metadata as untrusted. Path traversal, symlinks, oversized
input, decompression bombs, unsafe decoders, prompt leakage, credential leakage,
and stale/recomputed approval chains are security concerns.

Network access, automatic downloads, telemetry, provider credentials, model
execution, archive extraction, digital signing, and consumer-repository writes
remain outside the current M0 bootstrap trust boundary.
