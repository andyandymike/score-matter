# ADR 0001: keep generation and evidence in an offline authoring boundary

Status: accepted for M0 bootstrap
Date: 2026-08-24

## Context

Game BGM generation may eventually require large model stacks, provider terms,
reference audio, nondeterministic execution, and subjective review. None of
those concerns should become a hidden dependency of a shipped game or gain
release authority merely because a provider returned audio.

The first implementation also needs useful verification before a real model is
selected.

## Decision

- Build ScoreMatter as an independent local authoring repository and CLI.
- Keep the core Python environment free of model frameworks and codecs.
- Place each future real provider behind a versioned process protocol and
  separate environment.
- Make every provider input a strict request bound to a Brief, reviewed Plan,
  Provider Descriptor, and exact input digests.
- Store raw and derived artifacts immutably with explicit lineage.
- Treat provider metadata and generated audio as untrusted candidate evidence.
- Make mock, manual, and replay paths sufficient to verify the initial contract
  without a model, GPU, credential, or network call.
- Keep generated evidence under ignored local storage.
- Export only ordinary audio and manifests in a later package gate.
- Leave playback, crossfades, state transitions, import settings, mixing, and
  player-path acceptance in the consuming game.
- Keep SonicMatter separate: it remains the Foley project; ScoreMatter owns BGM
  authoring evidence.

## Explicit non-decisions

This ADR does not select, install, download, execute, train, fine-tune, host, or
redistribute a music model. It does not approve ACE-Step, Stable Audio, or any
other provider.

It does not define musical QA, seamless-loop acceptance, synchronized stems,
creative approval, rights approval, signatures, release packaging, or a Godot
runtime API.

The repository MIT license applies only to project-authored source and public
documentation. It does not grant rights to models, data, audio inputs, outputs,
or consumer assets.

## Verification

M0 bootstrap must prove:

- the core installs and tests without model dependencies;
- all authority-bearing JSON is strict and RFC 8785/JCS canonical;
- stale bindings and unsafe paths fail closed;
- mock output is deterministic for a frozen request;
- manual input remains source-bound and rights-unapproved;
- replay verifies exact bytes without pretending to regenerate them;
- private working material, local evidence, weights, and unapproved audio are
  absent from the tracked tree;
- Windows and Linux execute the same public contract.

## Consequences

The first release line is intentionally an evidence kernel rather than an AI
music product. This delays impressive demos but prevents model choice,
dependency conflicts, provider claims, and generated audio from becoming
architectural authority.

A future Codex skill may guide the workflow and call the CLI, but it is not the
source of truth and cannot bypass human gates.

## Rollback and revisit conditions

Rollback removes the Python core and local artifacts without changing any game
runtime because no runtime dependency exists.

Revisit through a new public ADR before:

- adding a real local or remote provider;
- permitting network or automatic download behavior;
- uploading reference audio;
- adding creative/rights/signing authority;
- generating a release package;
- modifying a consumer game;
- introducing a runtime music system.
