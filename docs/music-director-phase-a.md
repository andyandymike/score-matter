# Bounded music-director Phase A

ScoreMatter now includes a dependency-light planning kernel for preparing a
future local music-director experiment. Its current command adapter is a
process-observed diagnostic boundary, not an OS sandbox. No local text model
has been selected or executed, and no planning capability has been established.

## What the lane does

```text
visible context + provider descriptor
  -> one canonical JSON request observed at the adapter boundary
  -> one frozen local command process started by ScoreMatter
  -> immutable raw response
  -> strict schema and authority validation
  -> deterministic Gap / Direction / Brief-draft / Plan-draft compilation
  -> separately stored hidden adjudication used by the host evaluator
  -> immutable run result
  -> complete 14-primary + 2-repeat report
```

ScoreMatter serializes only the visible context, provider capability descriptor,
fixed policy, response schema identity, settings, and run seed into the JSONL
request; it does not serialize the hidden adjudication sheet into that request.
The current adapter cannot prove that the invoked wrapper, its descendants, or
the model runtime did not obtain hidden material through filesystem or other
out-of-band access. The compiler may bind identities, copy explicit facts,
project positive and anti-targets, enforce the disabled-critic profile, and
reject unsupported routing. It does not contain scenario-specific mood lookups
or silently replace malformed model output with a template.

The host runner supplies fail-if-called generator, critic, and reference-audio
service boundaries. Calls through those boundaries become retained
`authority_escalation` evidence. The Director kernel has no authorized path to
generate audio, read reference bytes, create a Plan review, approve its own
drafts, call a Provider, or write consumer-game evidence. That application
boundary is not a claim that an unrestricted external process is OS-confined.

## Preflight and execution

An operator first prepares ignored, machine-local files:

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

The machine-readable plan freezes the exact fourteen contexts, fourteen hidden
adjudications, two exact repeats, runtime-recomputed Director kernel digest,
policy, model identity, settings, budgets, route policy, fail-if-called
services, and the exact `evidence_root`. It also freezes an
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

A real run additionally requires a digest-matching `allow` record whose trust
level is `local_acknowledgement`. ScoreMatter deliberately provides no command
that manufactures that authorization. After explicit authorization, the same
frozen inputs can be run only at the plan-bound fresh ignored evidence
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

Each run retains the model-visible request, raw exchange, validated agent
payload when available, derived planning artifacts, trace, and run result. The
phase report contains exactly sixteen retained outcomes and uses an all-AND
gate. It records the plan's actual budget limits, observed adapter invocations,
child-reported token use, timeouts, elapsed time, external cost, forbidden
service calls, hallucination findings, route checks, repeat stability, and the
exact out-of-root execution-claim digest.

A scripted fixture backend is available only for deterministic tests. The
current `local_jsonl_command` backend is likewise diagnostic: for both backends,
`pass_eligible` is always false and the strongest report conclusion is
`planning_blocked`, even when every fixture check is green. Neither establishes
model capability. A future capability-eligible experiment needs a separately
implemented and verified `os_isolated` backend. Even such a report could support
only the narrow director-planning conclusion; it would not establish BGM
quality, musical taste, generator fitness, rights, release readiness, or game
suitability. Human listening remains authoritative for audio.

The JSONL adapter starts one ordinary local process without a shell, sends one
request through stdin, and observes its exit, stdout, stderr, timeout, and
resource declarations. It strips proxy variables and forces common
offline-library flags. Those observations do not prove that the process made
only one model inference, avoided descendants, lacked network access, stayed
within a filesystem allowlist, or avoided hidden files. Ordinary `Popen` and
environment flags are not an OS firewall. Until a separate `os_isolated`
backend enforces and verifies those properties, command runs remain diagnostic
and capability-pass-ineligible.

See [ADR 0004](adr/0004-bounded-music-director-phase-a.md) for the accepted
architecture and non-decisions.
