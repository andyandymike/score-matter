# Stable Audio 3 local runtime and research

Status: direct machine-local authoring implemented; research lanes optional
Last verified: 2026-08-31
ScoreMatter fast-generation status: implemented
ScoreMatter evidence-provider status: not registered
External capability-pilot orchestrator: implemented
Private Phase 1A execution: 18/18 complete; blind human review pending

ScoreMatter's default authoring command now invokes a machine-local CPU/LiteRT
installation of Stable Audio 3 Medium with the SAME-L codec. It launches one
offline process, creates one candidate, performs a cheap WAV-format check, and
returns the path for immediate listening. It does not register SA3 inside the
older evidence-provider bundle, download or bundle a model, or establish
musical, rights, adoption, or release approval.

The frozen pilot, blind-review builder, manual ingest, and Director experiments
described later on this page are optional research or audit tools. They are not
steps in ordinary BGM generation.

The historical Small Music smoke is recorded in
[ADR 0002](adr/0002-stable-audio-3-small-local-evaluation.md). The Medium pilot
decision is recorded separately in
[ADR 0003](adr/0003-stable-audio-3-medium-capability-pilot.md).

## Default fast-authoring command

With this page's ignored runtime installed, generate one draft directly from
the repository root:

```powershell
.venv\Scripts\score-matter generate `
  --prompt "Instrumental game BGM, restrained psychological tension, clearly audible midrange on ordinary speakers, controlled upper mids, rounded transients, space for dialogue, no vocals or sharp metallic highs." `
  --seconds 20 `
  --seed 19 `
  --out ".local\authoring\candidate-seed-19.wav"
```

The default is Medium + SAME-L + fp32, eight steps, eight CPU threads, CFG
`1.0`, and no separate negative prompt. It makes exactly one attempt and never
retries silently. Omit `--out` for a unique path under `.local/authoring/`.
Omit `--seed` for a random seed that is reported after generation.

The command records only a small ignored recall record under ScoreMatter's
`.local/authoring/records/`; exporting a WAV elsewhere does not add a JSON file
beside it. It does not hash the multi-gigabyte weights on every run, build an
evaluation inventory, score the result, normalize it, make a loop, or import it
into a game.

## Local directory boundary

The two ignored roots have different lifetimes:

```text
models/   persistent machine-local provider source, environment, weights, cache
.local/   generated candidates, receipts, analysis, and other evaluation evidence
```

- Removing `.local/` does **not** remove the installed model, but it permanently
  removes any candidate or receipt that was stored only there.
- Removing `models/` removes the local provider runtime and weights.
- Neither directory may be committed. The tracked-tree audit denies both roots;
  model files placed somewhere else do not inherit that protection.

On the current reference machine the installation is:

| Component | Frozen local value |
| --- | --- |
| Source checkout | `models/stable-audio-3` at `a0b57f5483c4588f827f3552b7d5c6ca2a9687be` |
| Moving optimized-weight ref observed | `eb343c94397c3de81f98f6e0eb75f08f183c020b`; informational only |
| Hugging Face cache | `models/huggingface-cache` |
| Runtime | Python 3.12.10; LiteRT `ai-edge-litert` 2.2.0 |
| Installed bundle | `medium`, SAME-L encoder/decoder, T5Gemma text encoder |
| TFLite plus tokenizer payload | 5 files; 10,032,146,459 bytes (about 9.34 GiB) |
| Not installed | `sm-music`, `sm-sfx`, alternate precisions, LoRA adapters |

These values describe this checkout; they are not a promise that an upstream
branch, package index, or model repository will remain unchanged.

The locally resolved pilot files were hashed on 2026-08-28:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tokenizer.model` | 4,241,003 | `61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2` |
| `sa3-m/dit_fp32.tflite` | 5,816,313,104 | `b811dc7d0135ca48afbc7a7bb7d19bdaaad13cbcb592418b8aa169e0c149daba` |
| `same-l/dec_fp32.tflite` | 1,823,900,848 | `3af34d35939ce6fc74d9f7b9d9bd6b99bc9568b614bcfe57da4a781bf40c8c6c` |
| `same-l/enc_fp32.tflite` | 1,823,872,896 | `f8b5e95a7073e3b59e4a1c2b07836d86d514cc7eaaff05b3c7cbdd1620f141d5` |
| `t5gemma/encoder_fp16.tflite` | 563,818,608 | `8530d0b3e6b9b9dcf1239145c2a853fb749708eaddbb472ff8f0802b50059372` |

Text-to-audio uses the tokenizer, T5Gemma encoder, Medium DiT, and SAME-L
decoder. Audio-to-audio and inpainting additionally use the SAME-L encoder.
The model and cache paths are hardlinked on the current machine, so summing
both logical trees would overstate physical storage.

### Historical Small Music record

The 2026-08-25 Small Music/SAME-S installation totalled 2,836,149,512 bytes.
Its optimized snapshot was
`2204d5086475bd5b7e6e2bd720772dd8e8160513`. The Small DiT hash was
`d388700a2ca439c11e9a53506e964e93231386a2beb8173c6eec6d95f676ce09`;
the SAME-S decoder and encoder hashes were
`cd87fa6686b24a56dc3497e05fbb26a34cf9604afe49c6631e829c9e70fccf21`
and `35ce38ea9f56e116036c683e37bf96c954d4fe0a435606ded0f62595b91f52a3`.
Those files are not currently installed. Historical smoke measurements below
must not be presented as current Medium performance.

## Terms preflight

Before downloading or running the model, the operator must review and retain
the exact terms that apply to the intended action, including the
[Stability AI Community License](https://stability.ai/community-license-agreement),
[Acceptable Use Policy](https://stability.ai/use-policy), and the bundled
[Gemma terms](https://ai.google.dev/gemma/terms). The gated
[Medium model card](https://huggingface.co/stabilityai/stable-audio-3-medium)
states that the model uses the Stability AI Community License and redistributes
T5Gemma under the Gemma terms. The frozen source checkout carries an MIT code
license; that code license does not license the model files.

Repository MIT licensing does not cover the provider, weights, inputs, or
outputs. Access to a download and a successful generation are not commercial,
redistribution, non-infringement, or release clearance. Terms acceptance is an
operator action; ScoreMatter does not automate or attest to it.

## Recreate the local installation

This is an explicit, reviewable Windows PowerShell path. Do not replace it with
a remote script piped directly into the shell.

```powershell
New-Item -ItemType Directory -Force models | Out-Null
git clone https://github.com/Stability-AI/stable-audio-3.git models/stable-audio-3
git -C models/stable-audio-3 checkout --detach a0b57f5483c4588f827f3552b7d5c6ca2a9687be

$env:HF_HOME = Join-Path (Get-Location) "models\huggingface-cache"
Push-Location models/stable-audio-3/optimized/tflite
.\install.bat --download sm-music
Pop-Location
```

The command above recreates the historical Small Music route, not the current
Medium pilot. Any new download may require authentication and acceptance of
upstream gated-model terms. Record exact downloaded file hashes and the
resolved Hugging Face revision rather than treating moving `main` as frozen.
Do not use lazy download during an experiment.

Verify the isolated CLI without generating audio:

```powershell
cmd /c models\stable-audio-3\optimized\tflite\sa3.bat --help
```

## Run a frozen private capability pilot

`tools/sa3_boundary_pilot.py` contains no prompts or model dependencies. It
requires an ignored private plan that contains exact prompts, attempts,
component hashes, terms-snapshot hashes, offline settings, and review
parameters.

Validate and preflight the plan without generating audio:

```powershell
.venv\Scripts\python tools\sa3_boundary_pilot.py validate `
  --plan spec\001-m1-capability-boundary-experiment.plan.json
.venv\Scripts\python tools\sa3_boundary_pilot.py preflight `
  --plan spec\001-m1-capability-boundary-experiment.plan.json
```

Run only the separately authorized calibration attempt:

```powershell
.venv\Scripts\python tools\sa3_boundary_pilot.py run `
  --plan spec\001-m1-capability-boundary-experiment.plan.json `
  --attempt cal-001
```

After the calibration satisfies the frozen media and 300-second wall-time
gate, run only the authorized Phase 1A inventory. `--resume` skips immutable
final attempts but does not replace or retry them:

```powershell
.venv\Scripts\python tools\sa3_boundary_pilot.py run-phase `
  --plan spec\001-m1-capability-boundary-experiment.plan.json `
  --phase phase1a --resume
```

The frozen pilot does not authorize Phase 1B. The orchestrator rejects that
phase, including a direct attempt invocation, until a later reviewed plan and
explicit authority exist.

The orchestrator writes the command, stdout/stderr, timings, component and
terms bindings, raw WAV, media analysis, status, and generation record under
`.local/experiments/<experiment-id>/`. It fails closed on a non-frozen plan,
hash drift, unreviewed local-evaluation terms, low disk, an unsafe output path,
or a missing preflight. Offline Hugging Face flags turn a missing component
into a failure rather than a download.

The optional review command creates hash-bound blind copies using the frozen
linear PCM16 RMS/sample-peak transform. That is not LUFS or true-peak
normalization, and the raw WAV remains unchanged.

Close editing evidence and build the complete Phase 1A review inventory with:

```powershell
"E01", "E02", "E03" | ForEach-Object {
  .venv\Scripts\python tools\sa3_boundary_pilot.py analyze-edit `
    --plan spec\001-m1-capability-boundary-experiment.plan.json `
    --attempt $_
}

$reviewArgs = @(
  "prepare-review", "--plan",
  "spec\001-m1-capability-boundary-experiment.plan.json"
)
"B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B09",
"B10", "B11", "B12", "N01", "N02", "N03", "E01", "E02", "E03" |
  ForEach-Object { $reviewArgs += @("--attempt", $_) }
& .venv\Scripts\python.exe tools\sa3_boundary_pilot.py @reviewArgs

.venv\Scripts\python tools\sa3_boundary_pilot.py stage-review `
  --plan spec\001-m1-capability-boundary-experiment.plan.json

.venv\Scripts\python tools\sa3_boundary_pilot.py summarize-phase1a `
  --plan spec\001-m1-capability-boundary-experiment.plan.json
```

The review builder fails if the phase is still open, an attempt is omitted, a
candidate hash no longer matches, or an editing probe lacks its parent/child
analysis. Outputs are immutable; the commands are not an overwrite mechanism.

### Current bounded result

The 2026-08-29 reference-host run closed all 18 Phase 1A outcomes without a
process, dependency, timeout, or hard-media failure. This is execution evidence,
not a musical pass:

| Observation | Result |
| --- | ---: |
| Phase 1A attempt denominator | 18 complete, 0 non-complete |
| Total Phase 1A wall time | 1,207.74 seconds (20.13 minutes) |
| Per-attempt wall time | 53.28 seconds minimum; 55.90 median; 157.20 maximum |
| Sampled process-tree working set | 12.47 GiB median; 21.41 GiB maximum |
| Experiment evidence after blind-copy preparation | 223.07 MiB; below the frozen 512 MiB budget |
| Human review | pending |

The first calibration's original Windows memory field captured only the
virtual-environment launcher and is marked `invalid_do_not_use` by an immutable
correction. A byte-identical B01 repeat using the same frozen prompt, seed, and
model files recorded the corrected whole-process-tree value. This repeat is
useful local evidence, not a promise of cross-machine determinism.

Four Phase 1A files contained a small number of full-scale PCM16 samples: B01
(39), N01 (62), N02 (168), and N03 (82). They passed the hard media contract but
retain a clipping-risk advisory. Automatic format checks do not approve their
sound.

Editing produced complete files, but it did not preserve the nominally
unchanged PCM region bit-for-bit. E02 changed about 92.6% of outside-region
samples with an outside difference RMS near -47.45 dBFS; E03 changed about
98.5% with an outside difference RMS near -49.95 dBFS. These low-level changes
and the recorded boundary jumps still require parent/child listening.

The private blind package contains all 18 anonymous raw and RMS-matched copies,
a reveal commitment, and an unfilled human-review draft. First-stage listening
uses `review/sound-quality-manifest.json`, which contains no attempt, family,
seed, prompt, or loop-condition marker. A separate manifest exposes the one
eight-repeat raw preview only after sound-quality scoring. The original manifest
that exposed this loop-condition marker is retained and marked unsuitable for
first-stage review rather than overwritten. No capability state is assigned
while listening is pending.

## Advanced: invoke the upstream CLI directly

Ordinary authoring should use `score-matter generate`. Direct upstream access
is retained for experiments with runtime options that the fast path does not
expose. Always provide an absolute output path under the repository-root
`.local/`; otherwise the upstream CLI places relative output inside its own
source checkout, mixing disposable audio with the persistent runtime.

```powershell
$scoreRoot = (Get-Location).Path
$candidateDir = Join-Path $scoreRoot ".local\sa3-evaluation"
New-Item -ItemType Directory -Force $candidateDir | Out-Null
$candidate = Join-Path $candidateDir "candidate-seed-19.wav"

Push-Location models/stable-audio-3/optimized/tflite
.\sa3.ps1 `
  --prompt "dark restrained psychological horror underscore, audible midrange, no vocals" `
  --negative-prompt "piercing whistle, harsh resonance, vocals, speech" `
  --dit medium --decoder same-l --precision fp32 `
  --seconds 20 --steps 8 --seed 19 --cfg 3.0 --out $candidate
Pop-Location
```

The upstream CLI ignores `--negative-prompt` when CFG is `1.0`; whenever a
negative prompt is recorded, set and record an explicit non-default `--cfg` as
shown above.

The native result is 44.1 kHz stereo PCM WAV. A seed helps identify a run; it
does not promise byte-identical output across provider revisions, dependency
versions, machines, or platforms.

Treat the raw file as quarantined candidate evidence. The tested upstream
decoder can produce float peaks outside `[-1, 1]`, while its PCM writer clips
when converting to 16-bit samples. A future adapter must record the pre-write
peak and any declared constant-gain derivative. It must not silently normalize,
compress, limit, or overwrite the raw artifact.

## What the historical Small Music smoke established

The following observations came from a bounded local exploration on an Intel
Core i7-10875H machine with about 23.5 GiB available RAM. The RTX 2060 6 GiB
was present but the TFLite path used CPU inference.

| Observation | Result |
| --- | --- |
| First 30-second run, including download | about 75.9 seconds wall time |
| Three cached 60-second runs | 55.8-62.4 seconds wall time |
| Peak Python working set | about 6.0 GiB |
| Peak Python private bytes | about 4.7 GiB |
| Lowest observed system-available memory | about 17 GiB |

The generated files and analysis were later deliberately removed from
`.local/`, so these figures are historical observations, not replayable
acceptance evidence. The smoke established only that the selected CPU path can
generate audible candidates on this machine at tolerable cost.

Listening also exposed two prompt/output risks:

- prompts can concentrate too much energy in sub-bass, making a nominally valid
  file difficult to hear on ordinary playback;
- some seeds can develop narrow, harsh resonances in the upper midrange.

Those risks must remain listening and analysis gates. A successful process,
valid WAV, or pleasing single excerpt does not prove good BGM, a clean loop,
vocal absence, mix compatibility, creative approval, or release readiness.

## Optional: ingest a candidate into the evidence kernel

The fast path already generates through ScoreMatter. If a separate experiment
needs content-addressed storage and a replay receipt, the older built-in
`manual` provider can additionally ingest that WAV:

1. Generate the WAV into `.local/sa3-evaluation/`.
2. Construct and review a manual-provider bundle whose output contract matches
   the actual 44.1 kHz stereo PCM WAV and full frame count.
3. Create a source record with `source-kind` set to `unknown`, `intended-use`
   set to `local_preview` or `internal_eval`, and a truthful rights-evidence
   reference. The v1 schema has no `ai_generated` source kind.
4. Run `manual ingest`; retain its immutable artifact and receipt under
   `.local/`.
5. Complete listening, loop, mix, creative, and rights review before copying
   anything into a game project.

The tiny bundle created by `score-matter demo init` expects fixture-sized audio
and is not a valid bundle for a 45- or 60-second SA3 file. Do not edit its WAV
constraints after review or reuse stale digests. The manual path records exact
bytes and declarations; it does not convert an AI output into an approved
asset.

A correctly prepared bundle can use the following final two commands:

```powershell
$bundle = ".local\jh-inquiry-manual-bundle" # reviewed bundle; not demo init output

.venv\Scripts\score-matter manual source-record `
  $candidate .local/sa3-evaluation/manual-source.json `
  --source-id sa3-external-seed-19 `
  --supplied-by local-operator `
  --source-kind unknown `
  --intended-use internal_eval `
  --rights-evidence-reference external-generation-record:sa3-seed-19

.venv\Scripts\score-matter manual ingest `
  --bundle $bundle `
  --audio $candidate `
  --source-record .local/sa3-evaluation/manual-source.json `
  --store .local
```

For a formal research claim, the external generation record referenced above
must independently retain the
exact positive and negative prompts, CFG/APG, seed, duration, step and thread
counts, precision, component revisions and hashes, host/runtime facts, elapsed
time, output SHA-256, byte count, and upstream stdout/stderr. Manual ingestion
does not capture or prove that lineage; its receipt has no effective SA3 seed
and keeps rights unapproved.

## Judgement Horror handoff boundary

The default dogfood path is now:

```text
Judgement Horror scene specification and runtime constraints
  -> host Agent makes one music-direction judgment
  -> score-matter generate creates one ignored local WAV
  -> immediate human listening and natural-language feedback
  -> optional project-owned loop, mix, import, and playback work
```

This uses the lightweight authoring adapter, not the registered evidence-
provider bundle. Keep exploratory candidates in ScoreMatter's ignored local
lane until the consumer project chooses an exact staging/import path and export
policy. Do not copy a candidate into release assets merely because its process
and WAV checks pass.

The optional evidence kernel still has an unresolved contract mismatch:
ScoreMatter Brief v1 requires
specific BPM, key, and meter values, while a horror cue may intentionally be
beatless or leave those fields unknown. That does not block fast generation.
Do not invent musical facts merely to ingest the result into the optional
contract path.

## Work still required for a registered evidence provider

- a versioned out-of-process SA3 adapter and frozen provider descriptor;
- timeout, cancellation, failure-receipt, environment, revision, and hardware
  evidence;
- prompt/options mapping from reviewed ScoreMatter contracts;
- raw-float peak capture and an explicit non-destructive post-processing chain;
- automated media checks plus human audibility, harshness, vocal-leakage, loop,
  mix, creative, and rights gates;
- an evaluation package whose evidence survives cleanup;
- consumer-project packaging and playback acceptance, owned by that project.

Those items are not prerequisites for ordinary local generation. They are
required only before claiming that SA3 participates in the stricter provider,
evidence, or release pipeline.
