# ADR 0003: run a bounded Stable Audio 3 Medium capability pilot

Status: Phase 1A executed; blind listening pending; provider adoption not accepted
Date: 2026-08-28

## Context

ADR 0002 recorded a bounded Stable Audio 3 Small Music CPU/TFLite smoke. Its
audio and local analysis were later removed, and it never became a provider or
formal M1 experiment.

The live ignored installation has since changed: the Small Music/SAME-S bundle
is absent, while Stable Audio 3 Medium with SAME-L fp32 components is present.
The moving optimized-weight repository ref also changed. Treating the old ADR
as proof for the new files would hide model drift.

Before spending a full formal M1 budget, the project needs a smaller,
pre-registered pilot that can falsify specific hypotheses about wordless vocal
texture, ensemble capacity, uncommon instrument identity, prompt controls,
editing, artifacts, and game-BGM fitness.

## Decision

- Permit a private, machine-local capability pilot against exact Medium/SAME-L
  component hashes.
- Keep the exact prompts, seeds, terms snapshots, component manifest, attempt
  manifest, generated audio, analysis, and reviews in ignored `spec/`,
  `models/`, and `.local/` paths.
- Add the dependency-light public `tools/sa3_boundary_pilot.py` orchestrator.
  It validates a private plan, verifies exact component and terms snapshot
  hashes, proves offline missing-file failure, runs the already-installed
  upstream CLI as a subprocess, records immutable attempt evidence, performs
  bounded PCM analysis, and can build derived blind listening copies.
- Do not register Stable Audio 3 in the built-in provider registry. The
  tracked M0 providers remain `manual`, `mock`, and `replay`.
- Do not add SA3, LiteRT, NumPy, audio-analysis, GPU, or Hugging Face packages
  to ScoreMatter's core dependencies. The orchestrator uses the ignored
  provider environment only for the frozen external invocation and tokenizer
  count.
- Require offline environment flags and fail when a component is absent. The
  pilot may not download, upgrade, substitute, quantize, or attach a LoRA while
  executing.
- Preserve raw WAVs. RMS/sample-peak-matched listening files, repeat previews,
  padded continuation inputs, and edited files are separately hash-bound
  derivatives.
- Treat humming and choir as exploratory wordless vocal textures. Do not infer
  intelligible lyric or speech support.
- Treat one-seed breadth results as `observed_once` at most. Control claims
  require the pre-registered matched multi-seed confirmation rule.
- End the pilot with an advance, narrow, stop, blocked, or aborted
  recommendation. No outcome automatically adopts a provider or enters a
  consumer game.

The private experiment specification and plan are intentionally absent from
the public tree. Public contributors can inspect and test the generic
orchestrator without receiving private prompts, generated audio, model files,
or gated terms evidence.

## Explicit non-decisions

This ADR does not:

- supersede ADR 0002's historical Small Music evidence;
- accept Medium as a built-in or default provider;
- complete formal M1 or authorize M2;
- approve lyrics, synchronized stems, native continuation, seamless loops,
  exact BPM/key/meter/timeline control, or broad uncommon-instrument coverage;
- approve any generated output creatively, legally, commercially, for release,
  or for Judgement Horror;
- permit automatic downloads, network inference, telemetry, training,
  fine-tuning, LoRA, model redistribution, or model files in the tracked tree;
- make automatic signal or semantic analysis authoritative over human
  listening; or
- claim byte-identical regeneration across processes, machines, dependency
  versions, or platforms.

## Consequences

ScoreMatter gains a reproducible way to test one already-installed external
runtime without contaminating the core or making a provider claim. The public
repository grows one local experiment tool and deterministic tests; the heavy
runtime, prompts, terms evidence, and audio remain private and ignored.

The pilot remains intentionally inconvenient: execution needs a frozen private
plan, exact hashes, retained terms evidence, sufficient disk, offline proof,
and explicit phase authority. This cost prevents exploratory audio from being
mistaken for accepted product capacity.

The current listening preparation uses linear PCM16 RMS matching with a sample
peak ceiling. It explicitly does not claim LUFS or true-peak normalization.
Unavailable analysis fields are recorded rather than fabricated.

The authorized reference-host Phase 1A run later closed all 18 attempts with
complete hard-media outcomes. The blind package and append-only execution
summary exist only under ignored `.local/`. No audible capability state is
assigned until the human review is attested. Phase 1B remains unauthorized.

The first calibration exposed a Windows measurement defect: the initial peak
working-set sampler observed only the virtual-environment launcher. That value
is retained and explicitly invalidated by an append-only correction. The
corrected implementation samples the aggregate working set of the complete
process tree and has a controlled allocation regression test.

## Verification

The tracked implementation is accepted only when:

- plan validation rejects unknown fields, unsafe paths, duplicate/case-colliding
  attempt IDs, invalid CFG/negative-prompt combinations, and a non-frozen
  execution plan;
- PCM analysis, exact-duration checks, tail padding, RMS matching, and repeat
  previews have deterministic positive and negative tests;
- Windows resource evidence follows virtual-environment launcher children, and
  editing analysis separates inside/outside PCM changes plus both boundaries;
- blind preparation rejects a partial or still-open Phase 1A inventory and
  binds anonymous raw copies, matched copies, condition-hidden first-stage
  review, deferred loop review, and reveal mapping to one commitment;
- the public-tree audit proves that `spec/`, `models/`, `.local/`, model files,
  prompts, terms snapshots, and audio are not tracked;
- the ordinary model-free M0 suite and strict documentation build still pass;
  and
- the first real calibration retains its command, stdout/stderr, component and
  terms bindings, wall time, raw WAV, media analysis, and a non-approving
  generation record; any invalid resource field is retained and corrected
  append-only rather than silently overwritten.

The implementation bullets verify the generic lane. The final bullet verifies only
the named Medium calibration on the reference host.

## Revisit conditions

Revisit this decision when:

- the private pilot completes or stops;
- a formal 30-60 second, four-brief, multi-seed M1 plan is proposed;
- the source, model files, terms, runtime, or reference host changes;
- the pilot suggests Small Music or another model should replace Medium for
  screening;
- a real out-of-process provider protocol is proposed; or
- an exact candidate is proposed for consumer-game evaluation.
