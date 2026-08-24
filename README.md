# ScoreMatter

Auditable, local-first AI-assisted BGM authoring for games.

[![CI](https://github.com/andyandymike/score-matter/actions/workflows/ci.yml/badge.svg)](https://github.com/andyandymike/score-matter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

ScoreMatter is an experimental authoring tool that places replaceable music
providers behind typed requests, immutable artifacts, reproducible evidence,
and explicit human review boundaries. A shipped game consumes ordinary audio
and manifests; it does not require ScoreMatter, Python, a model, a network
connection, or a GPU.

## Status

The M0 bootstrap evidence kernel is implemented. It remains experimental,
pre-release software; the CI badge is the current cross-platform proof source.

The current public slice validates strict JSON contracts, computes RFC 8785/JCS
digests, probes built-in providers, creates deterministic synthetic WAV
fixtures, ingests bounded manual WAV input, stores immutable content-addressed
artifacts, and replays their integrity evidence.

It does **not** currently provide:

- a real music model or model download;
- audio-quality, loop, vocal, key, BPM, or loudness approval;
- creative or rights approval;
- release packaging or Godot integration;
- a claim that generated music is useful, original, seamless, or publishable.

Read [the M0 public contract](docs/m0-contract.md) before relying on the tool.
The authoring/runtime boundary is recorded in
[ADR 0001](docs/adr/0001-offline-authoring-boundary.md).

## Quick start

Python 3.10 or newer is required. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --disable-pip-version-check -e .
.venv\Scripts\score-matter --help
```

Create and execute a tiny deterministic mock bundle:

```powershell
.venv\Scripts\score-matter demo init .local/demo --provider mock
.venv\Scripts\score-matter mock execute --bundle .local/demo --store .local
```

The execute command prints the exact run-receipt path. Replay it without
regenerating audio:

```powershell
.venv\Scripts\score-matter replay verify `
  .local/runs/<run-id>/run-receipt.json --store .local
```

Run the repository verification:

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python tools/audit_public_tree.py
```

All generated runs, receipts, mock audio, imported audio, and private working
material stay under ignored local paths.

## Design boundary

```text
Brief -> reviewed Plan -> resolved Request -> Provider
      -> quarantined immutable Artifact -> Run receipt -> replay verification
```

- Provider output is always a candidate.
- A request/receipt records what ScoreMatter requested and observed; it does
  not prove opaque provider internals.
- Model, code, training-data, reference-audio, and output rights are separate.
- ScoreMatter does not own game playback, music state transitions, or mixing.
- SonicMatter remains a separate Foley project.

## Repository layout

- `src/score_matter/` — the dependency-light M0 core and CLI.
- `src/score_matter/schemas/` — strict versioned JSON Schemas.
- `docs/` — stable public contracts and architecture decisions.
- `tests/` — deterministic positive and negative evidence.
- `tools/audit_public_tree.py` — tracked-tree privacy and artifact audit.
- `spec/` — private working material, intentionally excluded from Git.
- `.local/` — generated local evidence and audio, intentionally excluded.

## Contributing

This is a small personal open-source project. Narrow, evidence-backed changes
inside the current M0 contract are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md)
before proposing a provider, model, audio asset, dependency, or release claim.

## License

Project-authored source code and public documentation are licensed under the
[MIT License](LICENSE). Dependencies, model code, model weights, datasets,
reference audio, and generated outputs retain separate terms and never inherit
MIT merely by passing through ScoreMatter.
