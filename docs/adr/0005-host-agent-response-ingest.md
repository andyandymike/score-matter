# ADR 0005: use host-agent response ingest as the primary Director posture

Status: implementation authorized; formal capability execution not authorized
Date: 2026-08-31

## Context

ADR 0004 established a bounded, process-observed local JSONL diagnostic lane.
That lane is useful for offline and reproducible experiments, but it does not
mean ScoreMatter must install, own, or invoke a local reasoning model. In normal
authoring, the user already works with a capable host agent that can understand
project context and draft musical directions. Adding a second local text model
by default would duplicate that reasoning layer and make the repository own
model installation, runtime, and hardware concerns that are not required for
its core purpose.

ScoreMatter's durable responsibility is different: define strict planning
contracts, treat agent output as untrusted, preserve exact evidence, compile
only permitted deterministic artifacts, and keep Provider and approval
authority outside the Director. The architecture therefore needs a primary
path for importing a response produced by the current host agent, while keeping
the local JSONL path as an optional diagnostic adapter.

An imported host response has important evidence limits. ScoreMatter can bind
the Director packet intentionally submitted by the user, a unique evidence root,
an out-of-root no-replace claim path, the exact submission bytes, and the bare
response bytes returned by the host. It normally cannot observe the host's
complete system prompt, conversation state, routing, model weights, internal
calls, tools, tokens, cost, network use, or remote retention. It also cannot
prove that an opaque host had no out-of-band access to hidden fixtures. Import
must preserve those unknowns rather than turning them into false zero or exact
values.

The expressive-semantic-atlas prompt previously discussed in the same
conversation is useful as a calibration example, but the host has already seen
both the prompt and expected critique. It is therefore not condition-hidden and
cannot count toward formal capability evidence.

## Decision

- Make `host_agent_response_ingest` the primary Director authoring posture.
  The user asks the already active host agent to return only the bare structured
  response bytes; ScoreMatter captures and imports those existing bytes and
  starts no model process.
- Keep ScoreMatter model-agnostic. A local text model, inference engine, or
  model framework is not a core dependency and is not required for ordinary
  Director authoring.
- Keep ADR 0004 and `local_jsonl_command` as an optional offline diagnostic
  lane. That adapter's existing process-observed limitations remain unchanged.
- Bind the exact Director packet intentionally submitted to the host and the
  exact returned response. The request also binds a fresh normalized absolute
  evidence root and a normalized absolute no-replace claim path outside that
  root. Do not describe the packet as the complete model-visible request unless
  the host exports sufficient evidence for its system instructions,
  conversation state, routing, and tools.
- Represent that boundary with `score-director-host-request/v1`, capture the
  answer and explicit disclosure limits in
  `score-director-host-submission/v1`, acquire
  `score-director-host-ingest-claim/v1` before parsing, and retain validation
  and optional hidden adjudication in
  `score-director-host-ingest-receipt/v1`.
- Require the host to return only bare response bytes. The host does not create
  the submission envelope, evidence paths, digests, timestamps, usage claims,
  or authority-bearing artifacts.
- Make capture byte-exact and parse-free. It records the bare response digest
  and byte count and base64-wraps the exact bytes, including malformed JSON,
  before any response validation occurs.
- At ingest, acquire the out-of-root claim with no-replace semantics before
  parsing the submission or decoded response. Retain both the exact
  `host-submission` artifact and decoded `raw-response` artifact when the
  capture is decodable. A malformed, mismatched, rejected, or failed outcome
  still consumes the request and forbids redraw under that identity.
- Treat imported responses as untrusted. Strict parsing, schema validation,
  explicit-fact preservation, authority checks, deterministic compilation, and
  immutable evidence remain ScoreMatter responsibilities.
- Record host/runtime facts only with their evidence quality. Values may be
  host-reported, operator-declared, or unavailable. Model revision, call count,
  token use, cost, tool use, and elapsed time MUST NOT be guessed; unavailable
  values MUST NOT be represented as measured zero.
- Keep imported Brief and Plan material non-executable and advisory. The host
  agent cannot review or approve its own drafts, call a Provider through this
  path, create human attestations, or write consumer-game evidence.
- Make host ingest capability-pass-ineligible. A valid import can establish
  only that exact bytes were ingested, validated, and deterministically
  compiled under the recorded boundary. It emits only
  `diagnostic_contract_validated`, `diagnostic_adjudication_matched`,
  `diagnostic_adjudication_failed`, or `submission_rejected` in its ingest
  receipt. It never emits a formal Phase A report, `planning_blocked`, or
  `director_planning_gate_passed`.
- Keep `local_jsonl_command` capability-pass-ineligible for its independent
  reasons. Ordinary process observation does not establish OS network,
  filesystem, descendant-process, internal-inference, or hidden-file isolation.
- Require a separate decision before any capability-eligible external-host or
  API experiment. Such a decision must address privacy, service and model
  identity, credentials, terms, cost, reproducibility, complete prompt capture,
  hidden-fixture protection, and explicit authorization. It cannot inherit
  eligibility from a future local `os_isolated` backend.
- Reuse only the active host session's already accepted data boundary. Import
  does not infer permission to disclose additional private consumer context,
  upload files, or broaden retention. Consumer-project exports remain separately
  reviewed and digest-bound.
- Classify the previously discussed expressive-semantic-atlas exchange as a
  non-scoring calibration item. It cannot replace a frozen scenario, influence
  hidden adjudication after freeze, or enter the formal 14-primary + 2-repeat
  denominator. Host ingest does not create or execute P01-P08; those exact
  contexts, hidden sheets, plan, and authorization remain separate and absent.

## Explicit non-decisions

This ADR does not:

- authorize another host-agent request, local model call, external API call, or
  formal Phase A execution;
- select, install, download, execute, or approve any reasoning model;
- claim that a host product exposes its complete model-visible context or exact
  model/runtime identity;
- make a host response, valid JSON, or compiled draft creative or capability
  evidence;
- weaken the condition-hidden fixtures, complete-denominator retention,
  no-redraw policy, or independent human adjudication required by Phase A;
- treat host ingest as execution of P01-P08 or use a host calibration to fill
  any formal Phase A inventory slot;
- authorize generation, critic execution, reference-audio access, provider
  adoption, rights approval, package approval, publication, Judgement Horror
  changes, or release; or
- make local execution obsolete. It remains an optional path when its privacy,
  reproducibility, or offline properties are useful.

## Consequences

The common authoring workflow can use the user's current capable agent without
adding model weights, a text-model framework, or a duplicate inference runtime
to ScoreMatter. The public core remains focused on contracts, compilation,
evidence, and authority boundaries.

Host responses are convenient but weakly observable. Reports must distinguish
successful response ingestion from Director capability. Formal evaluation may
later choose a verified local execution posture or a separately governed
external-host posture, but neither is a product prerequisite.

The existing Phase A schemas and runner were designed around a managed command
backend and exact numeric usage fields. Host ingest is instead represented by
the host request, byte-exact host submission, out-of-root ingest claim, and host
ingest receipt schemas. It must not be forced into a command descriptor or
populated with invented model, usage, or isolation facts. This remains a
distinct boundary even when both paths reuse the same response validator and
compiler.

## Verification

The implementation associated with this decision is acceptable only when:

- host ingest performs no model, Provider, critic, generator, or reference-audio
  call;
- request generation binds a fresh evidence root and an out-of-root claim path;
- the host returns only bare response bytes, which capture base64-wraps with an
  exact digest and byte count before parsing;
- malformed JSON can be captured and retained as a rejected outcome;
- ingest acquires the no-replace claim before parsing, retains the exact host
  submission and decoded raw response, and consumes the request on failure;
- malformed, schema-invalid, authority-escalating, and stale-parent responses
  fail closed without template repair;
- unavailable host/runtime facts remain explicitly unavailable rather than
  becoming guessed values or zeros;
- imported drafts remain non-executable and cannot create Plan review or other
  approval-bearing artifacts;
- host ingest and `local_jsonl_command` both remain capability-pass-ineligible;
- host ingest emits only its diagnostic receipt conclusions and cannot create a
  Phase A report or `planning_blocked`;
- calibration evidence cannot enter a formal frozen denominator;
- host ingest cannot create, substitute for, or execute P01-P08 fixtures;
- the existing Brief/Plan contracts, provider path, Phase A local diagnostic
  tests, public-tree audit, and strict documentation build remain valid; and
- documentation never implies that host ingest establishes BGM quality,
  musical taste, generator fitness, privacy, rights, release readiness, or game
  suitability.

These checks establish an authoring and evidence boundary only. Human review
remains required for planning decisions, and human listening remains
authoritative for audio.

## Revisit conditions

Revisit this decision before:

- making host ingest capability-pass-eligible;
- allowing ScoreMatter to invoke, authenticate to, or upload context to a host
  service;
- using host responses as a formal `D` arm without separately frozen eligibility
  and hidden-fixture controls;
- allowing capture or ingest to repair malformed host bytes, redraw a failed
  request, or reuse an existing claim/evidence identity;
- changing the host-data disclosure boundary or accepting private consumer
  context without a reviewed export;
- allowing a host agent to call a Provider, generator, critic, or reference
  reader through the Director lane; or
- promoting an imported draft into a reviewed executable Plan without the
  existing independent authority chain.
