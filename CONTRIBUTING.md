# Contributing to ScoreMatter

Thank you for helping shape ScoreMatter.

## Current phase

The project is stabilizing the narrow M0 bootstrap described in
`docs/m0-contract.md`. Changes inside that contract may be proposed directly.
Please open an issue before expanding providers, model downloads, audio formats,
network access, approval authority, packaging, or game integration.

## Contribution expectations

- Keep changes narrow and explain the game-authoring use case.
- Prefer exact receipts, hashes, fixtures, and negative tests over broad claims.
- Do not add network services, telemetry, automatic downloads, or runtime model
  dependencies without a public design decision.
- Do not commit private material from `spec/`, `planning-private/`, or
  `.local/`, or machine-local provider material from `models/`.
- Do not add audio, prompts, datasets, model files, weights, or generated assets
  without explicit source, author, license/terms, redistribution rights, and
  permitted-use evidence.
- Do not infer output rights from the repository license or a model-card claim.
- Preserve raw artifact immutability and hash-bound lineage.
- Keep provider-specific dependencies outside the dependency-light core.
- Keep Windows path behavior and Linux CI behavior equivalent.

The current external Stable Audio 3 evaluation candidate is documented in
[ADR 0002](docs/adr/0002-stable-audio-3-small-local-evaluation.md). It is not a
precedent for adding model dependencies, downloads, generated audio, or provider
claims to a contribution.

## Reports and proposals

A useful proposal describes:

1. The game-BGM authoring problem.
2. The exact Brief/Plan/Provider contract change.
3. Required versus preferred controls.
4. Hardware, runtime, storage, and network constraints.
5. Model, asset, dependency, and license implications.
6. The objective tests and human evidence needed.
7. Claims the result still cannot support.

## Public documentation

Private working notes are not project documentation. Once a decision is stable,
rewrite the relevant conclusion under `docs/` without copying private
discussion, prompts, terms evidence, or unpublished material verbatim.

## Verification

From an editable installation:

```powershell
python -m unittest discover -s tests -v
python tools/audit_public_tree.py
python -m score_matter --help
```
