# ScoreMatter

Auditable AI-assisted BGM authoring for games, with local evidence and offline
game delivery.

[![CI](https://github.com/andyandymike/score-matter/actions/workflows/ci.yml/badge.svg)](https://github.com/andyandymike/score-matter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

ScoreMatter is an experimental authoring tool that places replaceable music
providers behind typed requests, immutable artifacts, reproducible evidence,
and explicit human review boundaries. A shipped game consumes ordinary audio
and manifests; it does not require ScoreMatter, Python, a model, a network
connection, or a GPU.

ScoreMatter is model-agnostic. Its primary Director path captures the bare
planning-response bytes produced by the user's current host agent, while local
text models remain optional adapters. ScoreMatter preserves, validates,
compiles, and records the untrusted response; it does not require a reasoning
model in the repository core or in the shipped game.

## Status

The M0 bootstrap evidence kernel is implemented. It remains experimental,
pre-release software; the CI badge is the current cross-platform proof source.

The current public slice validates strict JSON contracts, computes RFC 8785/JCS
digests, probes built-in providers, creates deterministic synthetic WAV
fixtures, ingests bounded manual WAV input, stores immutable content-addressed
artifacts, and replays their integrity evidence.

Separately, the current reference machine has an ignored, machine-local Stable
Audio 3 Medium/SAME-L CPU/TFLite installation. Earlier Small Music smoke runs
showed only local operability and their artifacts were removed. A generic
tracked pilot orchestrator can now execute an explicitly frozen private plan
against exact installed files without registering SA3 as a provider or adding
model dependencies to the core. The bounded Phase 1A run completed 18 of 18
attempts on the reference machine; blind human listening and every capability,
adoption, rights, release, and consumer-game decision remain pending. See the
[SA3 local evaluation guide](docs/sa3-local-evaluation.md), historical
[ADR 0002](docs/adr/0002-stable-audio-3-small-local-evaluation.md), and current
[ADR 0003](docs/adr/0003-stable-audio-3-medium-capability-pilot.md).

A separate bounded music-director kernel now provides strict planning
contracts, immutable traces, deterministic compilation and adjudication, and
fail-if-called audio/critic boundaries. The primary authoring posture is
`host_agent_response_ingest`: ScoreMatter freezes the exact submitted Director
packet together with a fresh evidence root and an out-of-root no-replace claim
path, while the host returns only bare response bytes. A separate capture step
base64-wraps those bytes without parsing them, so even malformed JSON can be
retained. Ingest claims the request before parsing, preserves both the exact
host submission and decoded raw response, then validates and compiles when
possible. A failed ingest still consumes that request; it is evidence, not a
redraw opportunity. The optional `local_jsonl_command` posture starts one
ordinary local process for diagnostic work. Both postures are always
capability-pass-ineligible. Host ingest writes only a diagnostic ingest receipt;
it never emits a formal Phase A report or `planning_blocked`, and it does not run
or replace formal P01-P08. The current local Phase A runner can conclude at most
`planning_blocked`. Host ingest cannot prove the host's full model-visible
context, model routing, tool use, call count, token use, cost, or hidden-fixture
isolation; ordinary process invocation cannot prove OS network, filesystem,
descendant-process, internal-inference, or hidden-file isolation.
No formal Director evaluation plan is currently frozen or authorized, and no
formal Phase A run has occurred. Validated drafts are advisory implementation
evidence—not a claim that the agent can direct useful music. See the
[Phase A guide](docs/music-director-phase-a.md) and
[ADR 0004](docs/adr/0004-bounded-music-director-phase-a.md) together with
[ADR 0005](docs/adr/0005-host-agent-response-ingest.md).

It does **not** currently provide:

- a tracked, bundled, managed, downloaded, or invoked real-model provider;
- a capability-approved Director execution or response-ingest posture;
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

Generated runs, receipts, candidate audio, and private working material stay
under ignored local paths. Optional machine-local model runtimes and weights
belong under the separate ignored `models/` root; deleting `.local/` removes
evidence but must not remove an installed model.

## Design boundary

```text
Project context -> bound host request -> host Agent -> bare response bytes
                -> byte-exact capture -> no-replace ingest claim
                -> retained submission/raw response
                -> ScoreMatter validation/evidence -> Brief/Plan drafts
                -> independent human selection and review
                -> resolved Request -> Provider
                -> quarantined immutable Artifact
                -> Run receipt -> replay verification
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
- `tools/sa3_boundary_pilot.py` — generic external-pilot orchestration; exact
  plans, prompts, model files, terms evidence, and results stay private.
- `src/score_matter/director/` — bounded planning contracts, model-agnostic
  host-response ingest, optional adapter boundary, deterministic
  compiler/adjudicator, immutable evidence, and Phase A runner.
- `spec/` — private working material, intentionally excluded from Git.
- `models/` — persistent machine-local provider source, environments, weights,
  and caches, intentionally excluded.
- `.local/` — generated candidates, receipts, and evaluation evidence,
  intentionally excluded; cleanup loses evidence stored only there.

## Contributing

This is a small personal open-source project. Narrow, evidence-backed changes
inside the current M0 contract are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md)
before proposing a provider, model, audio asset, dependency, or release claim.

## License

Project-authored source code and public documentation are licensed under the
[MIT License](LICENSE). Dependencies, model code, model weights, datasets,
reference audio, and generated outputs retain separate terms and never inherit
MIT merely by passing through ScoreMatter.
