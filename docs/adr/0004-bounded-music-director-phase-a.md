# ADR 0004: add a bounded music-director Phase A diagnostic lane

Status: implementation authorized; Phase A execution not authorized  
Date: 2026-08-30

## Context

ScoreMatter already separates provider execution, immutable candidate evidence,
technical checks, human review, rights review, packaging, and consumer-game
verification. A music-director experiment now needs to test a different
question: whether a local reasoning model can turn project context into useful
gaps, alternatives, and non-executable Brief and Plan drafts without acquiring
any provider or approval authority.

The director must eventually add evidence beyond a deterministic prompt
template. Phase A's target ceiling permits at most one local model inference per
scenario run, so a conventional multi-turn tool loop would exceed that boundary.
The first implementation can observe one request and one local command process,
but that process observation does not prove the number of internal inferences
or descendant processes. The initial posture must therefore remain diagnostic
and must not claim a general autonomous music agent or model capability.

The exact local text model, inference engine, model and tokenizer bytes, system
policy, settings, scenario inventory, hidden adjudication, and machine-readable
evaluation plan have not yet been selected and frozen. No Phase A model
execution has been authorized.

## Decision

- Add the director as an independent authoring-evidence lane. It is not a
  Provider, is not registered in the provider registry, and does not produce
  audio or provider execution receipts.
- Define the initial director protocol as a single-request bounded planner. One
  frozen request may ask a local command wrapper to classify gaps and conflicts,
  choose a terminal state, propose materially different musical directions,
  recommend a supported route, and draft semantic inputs for existing contracts.
- Treat `local_jsonl_command` as a process-observed diagnostic adapter. It
  starts one ordinary process, but ordinary `Popen` does not prove OS network,
  filesystem, or descendant-process isolation; it also does not prove one
  internal model inference or that hidden fixtures were not read out of band.
  The backend is always `pass_eligible=false` and its strongest conclusion is
  `planning_blocked`. A capability-eligible run requires a separate, verified
  `os_isolated` backend in a future decision.
- Keep deterministic code responsible for strict parsing, schema validation,
  digest binding, explicit fact copying, ID construction, unit conversion,
  budget enforcement, safe materialization, and immutable evidence. It must not
  contain scenario-ID or mood-to-music lookup tables that substitute for model
  reasoning.
- Implement a dependency-light public kernel for director contracts, guards,
  compilation, model-adapter boundaries, execution traces, and deterministic
  validation.
- Recompute and bind a kernel digest covering the Director source, shared
  canonicalization/contract/path boundary, and every Brief/Plan/Provider and
  Director schema used by Phase A. A kernel change invalidates a frozen plan.
- Freeze the exact `evidence_root` in the evaluation plan and freeze an
  `execution_claim_path` outside that root. A fresh run must acquire the claim
  with no-replace semantics before writing evidence; resume accepts only the
  frozen root. Deleting either the claim or evidence breaks the audit chain and
  is not an evidence-preserving reset.
- Keep exact scenario cards, hidden adjudication, model files, model runtime,
  system policy snapshots, frozen experiment plans, raw model transcripts,
  and run evidence in ignored private paths such as `spec/`,
  `planning-private/`, `models/`, and `.local/`.
- Permit fake, scripted, malformed, timeout, and fail-if-called adapters only
  for deterministic implementation tests. They may prove contract and boundary
  behavior, but they cannot establish director capability or satisfy the Phase
  A planning gate. The process-observed `local_jsonl_command` backend shares
  that capability-pass-ineligible conclusion even when it invokes real model
  code.
- In Phase A, generator, advisory critic, and reference-audio reader boundaries
  are fail-if-called. Their invocation counts must remain zero and be retained
  in each run's evidence.
- Produce only non-executable `score-brief/v1` and `score-plan/v1` drafts for
  eligible complete scenarios. Phase A does not create a resolved request,
  invoke `load_execution_bundle`, execute a Provider, or fabricate a
  `score-plan-review/v1` record.
- Keep `score-brief/v1` and `score-plan/v1` unchanged. Director-specific
  provenance, gaps, alternatives, recommendations, traces, experiment control,
  and adjudication belong in separate versioned director artifacts.
- Treat model absence, model-identity drift, policy drift, malformed output,
  unsupported routing, timeout, budget exhaustion, and deterministic rejection
  as retained outcomes. There is no silent template fallback or replacement
  run.

## Explicit non-decisions

This ADR does not:

- select, install, download, execute, or approve a local text model or inference
  engine;
- freeze or authorize a machine-readable Phase A evaluation plan;
- authorize any of the fourteen primary scenario runs or two repeat runs;
- authorize generator, critic, reference-audio, network, external API, or
  consumer-project access;
- adopt the director as a Provider or allow it to bypass provider capability
  resolution;
- make the director, a second model, or deterministic code a Plan reviewer,
  creative reviewer, rights reviewer, package approver, or consumer verifier;
- claim that a scripted fixture, schema-valid output, or passing unit test is a
  successful music-director result;
- approve any Brief, Plan, prompt, audio, route, rights position, package,
  release, or Judgement Horror integration; or
- authorize a multi-turn ReAct-style agent loop under the current Phase A call
  budget.

## Consequences

The public repository can expose and test a reusable director evidence kernel
without adding a text-model framework, weights, private prompts, or experiment
answers to the tracked tree. The existing provider and M0 evidence paths remain
unchanged.

The first director is deliberately narrower than a general interactive agent.
The kernel can frame and validate one bounded planning exchange from frozen
typed input, but the current adapter cannot establish that the external runtime
performed exactly one inference or remained isolated. Clarification answers,
feedback revision, critic replay, audio comparison, and multi-turn tool use
remain later and separately authorized work.

Implementation completion and Phase A capability remain separate conclusions.
A future capability-eligible Phase A result requires an exact frozen local
model and plan, private condition-hidden fixtures, complete denominator
retention, deterministic checks, digest-bound human adjudication, and a
separately verified `os_isolated` backend. Until those exist and execution is
explicitly authorized, the strongest conclusion is that the diagnostic
implementation is ready for future experiment preparation.

## Verification

The implementation associated with this decision is acceptable only when:

- director schemas reject unknown fields and stale parent, policy, model, plan,
  context, and output digests;
- complete, clarification-required, abstained, safety-rejected, malformed,
  timeout, and unavailable outcomes have deterministic tests;
- tests prove that blocked or conflicting inputs cannot materialize Brief or
  Plan drafts;
- tests prove that generator, critic, and reference-audio reader spies fail if
  called and remain at zero in valid Phase A traces;
- tests prove that fake, scripted, and `local_jsonl_command` adapters cannot
  emit a capability-pass conclusion;
- the compiler contains no scenario-specific or mood-to-music mapping and does
  not rewrite model-produced semantic choices;
- Phase A writes no Plan review, approval-bearing record, resolved request,
  provider receipt, audio, or consumer evidence;
- the existing `score-brief/v1`, `score-plan/v1`, provider registry, execution
  bundle, M0 tests, public-tree audit, and strict documentation build continue
  to pass; and
- any future real run fails closed until an exact frozen model record, policy,
  evaluation plan, fixture inventory, adjudication inventory, budgets, and
  explicit phase authorization all match their recorded digests.

These checks establish the bounded implementation boundary only. They do not
establish planning value, music quality, provider fitness, or game suitability.

## Revisit conditions

Revisit this decision before:

- freezing or executing the first Phase A plan;
- introducing or claiming a capability-eligible `os_isolated` backend;
- selecting a different local-model or external-API posture;
- increasing the model-call budget or adding a multi-turn tool loop;
- allowing the director to read reference audio or call a generator or critic;
- changing `score-brief/v1` or `score-plan/v1` for director-specific data;
- promoting any director draft into a reviewed executable Plan; or
- adding feedback revision, project sonic memory, audio comparison, packaging,
  or consumer-game integration.
