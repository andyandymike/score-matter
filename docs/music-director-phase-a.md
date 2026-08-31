# Host-agent Director and bounded Phase A

!!! warning "Optional research lane"
    This page documents contract and capability research. It is not the BGM
    generation quick path and never gates ordinary authoring. Use
    `score-matter generate` when the goal is to hear a candidate.

ScoreMatter includes a dependency-light, model-agnostic planning kernel. Its
primary authoring path captures the bare response bytes produced by the user's
current host agent, then imports them through an evidence-bound submission;
ScoreMatter does not start or manage that host. An optional
`local_jsonl_command` adapter remains available for offline diagnostic work.
Neither path currently establishes Director capability.

## What the lane does

```text
visible context + provider descriptor
  -> Director packet binds a fresh evidence root and out-of-root claim path
  -> exact packet submitted to the current host agent
  -> host returns only bare response bytes
  -> capture base64-wraps those exact bytes without parsing
  -> ingest acquires the no-replace claim before parsing
  -> exact host submission and decoded raw response retained
  -> strict schema and authority validation
  -> deterministic Gap / Direction / Brief-draft / Plan-draft compilation
  -> advisory immutable evidence for independent human review

optional local diagnostic:
  canonical JSON request -> one ordinary local command process
  -> immutable raw response -> the same validation and compilation boundary
```

The host-ingest record binds the exact Director packet intentionally submitted
to the host, its normalized absolute evidence and claim paths, the byte-exact
submission wrapper, and the decoded bare response. That packet is not called
the complete model-visible request unless the host exports evidence for its
system instructions, conversation state, routing, and tools. Model revision,
call count, tokens, cost, tool use, network posture, remote retention, and other
facts are recorded only as host-reported, operator-declared, or unavailable;
unavailable facts are never replaced with guessed values or zeros.

For the optional JSONL path, ScoreMatter serializes only the visible context,
provider capability descriptor, fixed policy, response schema identity,
settings, and run seed into the request; it does not serialize the hidden
adjudication sheet into that request. The current adapter cannot prove that the
invoked wrapper, its descendants, or the model runtime did not obtain hidden
material through filesystem or other out-of-band access.

For both paths, the compiler may bind identities, copy explicit facts, project
positive and anti-targets, enforce the disabled-critic profile, and reject
unsupported routing. It does not contain scenario-specific mood lookups or
silently replace malformed agent output with a template.

The Phase A runner supplies fail-if-called generator, critic, and
reference-audio service boundaries. Calls through those boundaries become
retained `authority_escalation` evidence. The Director kernel has no authorized
path to generate audio, read reference bytes, create a Plan review, approve its
own drafts, call a Provider, or write consumer-game evidence. The import-only
host path invokes none of those services, but that observation is not proof of
what an opaque host did internally. Likewise, the application boundary is not
a claim that an unrestricted local process is OS-confined.

## Host-response ingest

`host_agent_response_ingest` is the default authoring posture. The user asks
the already active host agent to answer the frozen response contract with bare
response bytes, captures those bytes exactly, then ingests the resulting
submission. Request, capture, and ingest start no model process and need no
local text-model installation. Ingest validates and may materialize
non-executable advisory drafts, but it cannot approve those drafts or turn them
into Provider authority.

First export the exact packet that will be submitted to the host:

```powershell
.venv\Scripts\score-matter director host request `
  --run-id semantic-atlas-calibration-v0 `
  --context planning-private/<calibration>/context.json `
  --provider-descriptor planning-private/<calibration>/provider-descriptor.json `
  --evidence-root .local/director-host/semantic-atlas-calibration-v0 `
  --claim-path .local/director-host-claims/semantic-atlas-calibration-v0.json `
  --output planning-private/<calibration>/host-request.json
```

The command writes one immutable `score-director-host-request/v1` document and
prints `model_calls=0 pass_eligible=false`. It resolves and binds the evidence
root and claim path as normalized absolute paths; the claim path must be outside
the evidence root. The request file, evidence root, claim path, and later
capture output must all be fresh.

Give that exact request to the current host agent. The host returns only the
bare `score-director-agent-response/v1` bytes; it does not manufacture the
submission envelope, hashes, timestamps, usage claims, or evidence paths. Save
the response exactly as returned, without parsing, reformatting, repairing, or
extracting JSON. Then capture it:

```powershell
.venv\Scripts\score-matter director host capture `
  --request planning-private/<calibration>/host-request.json `
  --response planning-private/<calibration>/host-response.raw.json `
  --submission-id semantic-atlas-calibration-v0-submission `
  --host-product codex `
  --output planning-private/<calibration>/host-submission.json
```

Capture reads the regular non-symlink response file as bounded bytes, computes
its digest and byte count, and base64-wraps it in one immutable
`score-director-host-submission/v1`. It deliberately does not parse the response,
so malformed JSON is still sealed and can become a retained
`submission_rejected` outcome. Unavailable host identity, usage, settings, and
tool facts remain explicit `null` or `unavailable` values rather than guesses.

Then ingest the existing response without making another model call:

```powershell
.venv\Scripts\score-matter director host ingest `
  --request planning-private/<calibration>/host-request.json `
  --submission planning-private/<calibration>/host-submission.json `
  --output .local/director-host/semantic-atlas-calibration-v0
```

`--output` must resolve to the exact evidence root bound by the request. Before
parsing either the submission or decoded response, ingest creates the bound
`score-director-host-ingest-claim/v1` outside that root with no-replace
semantics. It then retains `host-submission.json` and, whenever the capture can
be decoded, the byte-exact `raw-response.json`. A valid response without an
adjudication sheet produces `diagnostic_contract_validated`.

A condition-hidden evaluator may instead add an adjudication only after the
host response is frozen:

```powershell
.venv\Scripts\score-matter director host ingest `
  --request planning-private/<experiment>/host-request.json `
  --submission planning-private/<experiment>/host-submission.json `
  --adjudication planning-private/<experiment>/adjudication.json `
  --output .local/director-host/<experiment>
```

That path produces `diagnostic_adjudication_matched` or
`diagnostic_adjudication_failed`; malformed or mismatched input produces
`submission_rejected`. The output directory must not already exist. Every ingest
attempt consumes the request once the claim is acquired, including malformed,
mismatched, rejected, or failed outcomes. Do not delete the claim/evidence or
repair and retry the same request. A successor attempt requires a new run ID,
request, evidence root, and claim path while retaining the original outcome.
These are diagnostic receipt conclusions, not Phase A report conclusions. The
CLI's `model_calls=0` describes only the ScoreMatter ingest kernel and says
nothing about opaque host internals.

Asking the host agent is a user-controlled action outside ScoreMatter. Importing
the returned bytes does not retroactively authorize their production, expand
the host session's data boundary, or establish privacy, service identity,
reproducibility, hidden-fixture secrecy, token use, cost, or capability. A
consumer context may be submitted only when that disclosure was already
intentional and authorized for the active host trust boundary.

The previously discussed expressive-semantic-atlas prompt and its critique are
a non-scoring calibration item. The same conversation exposed both the question
and expected analysis, so that response cannot replace a frozen fixture,
influence hidden adjudication after freeze, or contribute to the formal 14 + 2
Phase A denominator. Use a distinct calibration ID and omit `--adjudication`
for that already contaminated exchange. Host ingest neither runs P01-P08 nor
creates their missing contexts, hidden sheets, plan, or authorization.

## Optional local preflight and execution

An operator using `local_jsonl_command` first prepares ignored, machine-local
files:

```text
planning-private/<experiment>/
  evaluation-plan.json
  phase-authorization.json
  provider-descriptor.json
  command-descriptor.json
  inventory/
    contexts/p01.json ... s02.json
    adjudications/p01.json ... s02.json
```

The exact public-kernel identity for the current checkout can be inspected
without a model call:

```powershell
.venv\Scripts\score-matter director kernel-digest
```

For the optional local execution path, the machine-readable plan freezes the
exact fourteen contexts, fourteen hidden adjudications, two exact repeats,
runtime-recomputed Director kernel digest, policy, model identity, settings,
budgets, route policy, fail-if-called services, and the exact `evidence_root`.
It also freezes an
`execution_claim_path` outside that evidence root. The command descriptor binds
absolute non-symlink paths for the executable, model/runtime artifacts, and
working directory, plus their digests, a complete working-directory manifest,
and process-observation metadata.
Any existing file named as a command argument must also appear in that bound
artifact inventory. The descriptor is forbidden from relabelling this adapter
as OS-enforced; its observation digest is not isolation proof.

Preflight performs no model call:

```powershell
.venv\Scripts\score-matter director phase-a preflight `
  --spec spec/003-music-director-agent-capability-experiment.md `
  --plan planning-private/<experiment>/evaluation-plan.json `
  --authorization planning-private/<experiment>/phase-authorization.json `
  --provider-descriptor planning-private/<experiment>/provider-descriptor.json `
  --command-descriptor planning-private/<experiment>/command-descriptor.json `
  --inventory-root planning-private/<experiment>/inventory
```

A local model run additionally requires a digest-matching `allow` record whose
trust level is `local_acknowledgement`. ScoreMatter deliberately provides no
command that manufactures that authorization. After explicit authorization,
the same frozen inputs can be run only at the plan-bound fresh ignored evidence
directory:

```powershell
.venv\Scripts\score-matter director phase-a run `
  --spec spec/003-music-director-agent-capability-experiment.md `
  --plan planning-private/<experiment>/evaluation-plan.json `
  --authorization planning-private/<experiment>/phase-authorization.json `
  --provider-descriptor planning-private/<experiment>/provider-descriptor.json `
  --command-descriptor planning-private/<experiment>/command-descriptor.json `
  --inventory-root planning-private/<experiment>/inventory `
  --output .local/director/<experiment>
```

For a fresh run, ScoreMatter first creates the frozen out-of-root execution
claim with no-replace semantics, then writes evidence only under the frozen
`evidence_root`. `--resume` recognizes only that same root and reuses only
complete, canonical, digest-matching run results. A partially written run is
not retried in place, and no failed result is dropped from the denominator.
Deleting either the execution claim or retained evidence breaks the audit chain;
cleanup is evidence destruction, not a reset that preserves the experiment's
claim.

## Evidence and acceptance boundary

Each formal run retains its request, raw exchange, validated agent payload when
available, derived planning artifacts, trace, and run result. The phase report
contains exactly sixteen retained outcomes and uses an all-AND gate. It records
the plan's actual budget limits, observed adapter invocations, reported token
use, timeouts, elapsed time, external cost, forbidden service calls,
hallucination findings, route checks, repeat stability, and the exact
out-of-root execution-claim digest. A host-ingest calibration is not silently
promoted into this denominator.

A scripted fixture backend is available only for deterministic Phase A runner
tests. `host_agent_response_ingest` is a separate diagnostic receipt lane
because ScoreMatter cannot observe the host's complete prompt, runtime, tools,
inference count, or hidden-fixture access. It never emits a Phase A report or
`planning_blocked`; its only conclusions are the four diagnostic receipt values
listed above. `local_jsonl_command` is diagnostic because ordinary process
observation is not OS isolation. The scripted and local-command Phase A runner
postures have `pass_eligible=false` and can conclude at most
`planning_blocked`, even when every deterministic check is green. None of the
three postures establishes model capability.

A future capability-eligible local experiment needs a separately implemented
and verified `os_isolated` backend. A future capability-eligible external-host
or API experiment needs a separate ADR and equivalent privacy, service-identity,
hidden-fixture, reproducibility, cost, and authorization controls; host ingest
does not inherit eligibility from local isolation work. Even an eligible report
could support only the narrow director-planning conclusion. It would not
establish BGM quality, musical taste, generator fitness, rights, release
readiness, or game suitability. Human listening remains authoritative for
audio.

The JSONL adapter starts one ordinary local process without a shell, sends one
request through stdin, and observes its exit, stdout, stderr, timeout, and
resource declarations. It strips proxy variables and forces common
offline-library flags. Those observations do not prove that the process made
only one model inference, avoided descendants, lacked network access, stayed
within a filesystem allowlist, or avoided hidden files. Ordinary `Popen` and
environment flags are not an OS firewall. Until a separate `os_isolated`
backend enforces and verifies those properties, command runs remain diagnostic
and capability-pass-ineligible.

See [ADR 0004](adr/0004-bounded-music-director-phase-a.md) for the optional local
diagnostic lane and [ADR 0005](adr/0005-host-agent-response-ingest.md) for the
host-agent-first authoring posture.
