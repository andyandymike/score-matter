# ADR 0002: use Stable Audio 3 Small Music for bounded local evaluation

Status: accepted for machine-local evaluation; provider adoption not accepted  
Date: 2026-08-25

## Context

M0 deliberately proves ScoreMatter's evidence kernel without a real music
model. The next research step needs an affordable local generator that can be
tested on the reference Windows laptop without weakening that boundary.

An exploratory ACE-Step 1.5 setup did not produce a usable local path on the
reference RTX 2060 6 GiB machine and was removed. Stable Audio 3's optimized
Small Music TFLite path did run on CPU, generated audible 44.1 kHz stereo WAVs,
and used tolerable time and memory for offline evaluation.

The exploratory audio and analysis were later removed from `.local/`. The
operational observations therefore guide this decision but do not constitute a
retained acceptance package.

## Decision

- Use Stable Audio 3 Small Music (`sm-music`) as the current real-model local
  evaluation candidate.
- Freeze the reference source checkout at
  `a0b57f5483c4588f827f3552b7d5c6ca2a9687be` and record the resolved optimized
  weight snapshot, currently
  `2204d5086475bd5b7e6e2bd720772dd8e8160513`.
- Keep provider source, its virtual environment, model weights, and download
  cache under ignored, persistent `models/`.
- Keep generated WAVs, analysis, run evidence, and receipts under ignored
  `.local/`. Cleaning `.local/` must not remove `models/`; cleaning it still
  destroys any evidence not retained elsewhere.
- Keep all SA3 dependencies out of ScoreMatter's core environment and package
  metadata.
- Require explicit operator review of the exact model, component, acceptable
  use, and input/output terms before download or use. Do not make ScoreMatter
  accept terms or attest to rights.
- Require an absolute `.local/` output path when invoking the upstream CLI so
  generated audio does not land in the persistent provider checkout.
- Use the built-in manual provider as the only current bridge from an external
  SA3 WAV into ScoreMatter's evidence store.
- Continue treating every output as an untrusted candidate. A fixed seed and
  recorded revision improve identification but do not claim cross-platform or
  cross-version byte reproducibility.
- Add a separate public decision and implementation evidence before registering
  SA3 as a built-in provider or permitting ScoreMatter to invoke or download it.

The machine-local procedure and current measurements are documented in the
[SA3 local evaluation guide](../sa3-local-evaluation.md).

## Explicit non-decisions

This ADR does not:

- add, bundle, manage, download, or invoke a model from the tracked core;
- register a fourth built-in provider;
- accept an M1 provider protocol or production default;
- claim the removed smoke artifacts are replayable evidence;
- approve a prompt, seed, mix, loop, loudness, vocal state, or creative result;
- approve model, reference-input, output, commercial, redistribution, or
  release rights;
- authorize copying generated audio into Judgement Horror or any other game;
- add GPU inference, training, fine-tuning, LoRA, continuation, or inpainting to
  the ScoreMatter contract.

## Consequences

The project now has one concrete, low-cost external runtime for the next
evaluation cycle without changing the M0 dependency or authority boundary.
Local storage is larger, and upstream code, weights, component terms, and
runtime dependencies must be tracked separately from the MIT repository.

The manual-ingest bridge is intentionally awkward: it prevents exploratory
generation from silently becoming a provider or approved game asset. Formal
integration will require a versioned process protocol, provider descriptor,
failure and environment evidence, exact media contracts, and both automated and
human QA.

## Verification for this decision

On the 2026-08-25 reference checkout:

- the source and optimized-weight revisions above were resolved locally;
- four installed TFLite files totalled 2,836,149,512 bytes, and their component
  hashes plus the tokenizer hash were recorded in the evaluation guide;
- Python 3.12.10 with LiteRT 2.2.0 loaded the isolated CLI;
- `sa3.bat --help` completed from the persistent installation;
- the ScoreMatter core remained free of SA3 dependencies;
- `models/` remained ignored and absent from the tracked tree;
- `.local/` was absent after the requested cleanup while the model installation
  remained present.

These checks prove installation separation, not generation quality or rights.

## Revisit conditions

Revisit this ADR when:

- a retained, predeclared evaluation package supports or rejects SA3 adoption;
- a provider process protocol is proposed;
- the source, weight snapshot, dependency set, or applicable terms change;
- a different local or remote provider shows a materially better cost/quality
  tradeoff;
- the consuming game defines concrete cue, loop, loudness, and mix acceptance
  criteria;
- model storage or cleanup policy changes.
