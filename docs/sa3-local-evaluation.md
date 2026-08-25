# Stable Audio 3 local evaluation

Status: machine-local evaluation only  
Last verified: 2026-08-25  
ScoreMatter provider status: not implemented

ScoreMatter's tracked M0 core still makes zero real-model calls. Separately, a
CPU/LiteRT installation of Stable Audio 3 Small Music (`sm-music`) is the
current real-model evaluation candidate. It can create WAV candidates for
listening and later manual ingestion, but it is not a built-in provider, a
default model, or evidence of musical, rights, or release approval.

The selection boundary is recorded in
[ADR 0002](adr/0002-stable-audio-3-small-local-evaluation.md).

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
| Optimized-weight snapshot | `2204d5086475bd5b7e6e2bd720772dd8e8160513` |
| Hugging Face cache | `models/huggingface-cache` |
| Runtime | Python 3.12.10; LiteRT `ai-edge-litert` 2.2.0 |
| Installed bundle | `sm-music`, SAME-S codec, T5Gemma text encoder |
| TFLite payload | 4 files; 2,836,149,512 bytes (about 2.641 GiB) |

These values describe this checkout; they are not a promise that an upstream
branch, package index, or model repository will remain unchanged.

The locally resolved files were hashed on 2026-08-25:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tokenizer.model` | 4,241,003 | `61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2` |
| `sa3-sm-music/dit_fp32.tflite` | 1,838,758,544 | `d388700a2ca439c11e9a53506e964e93231386a2beb8173c6eec6d95f676ce09` |
| `same-s/dec_fp32.tflite` | 218,377,156 | `cd87fa6686b24a56dc3497e05fbb26a34cf9604afe49c6631e829c9e70fccf21` |
| `same-s/enc_fp32.tflite` | 215,195,204 | `35ce38ea9f56e116036c683e37bf96c954d4fe0a435606ded0f62595b91f52a3` |
| `t5gemma/encoder_fp16.tflite` | 563,818,608 | `8530d0b3e6b9b9dcf1239145c2a853fb749708eaddbb472ff8f0802b50059372` |

The SAME-S encoder is installed for audio-to-audio/inpainting; the initial
text-to-audio lane uses the tokenizer, T5Gemma encoder, Small Music DiT, and
SAME-S decoder.

## Terms preflight

Before downloading or running the model, the operator must review the exact
terms that apply to the intended action, including the
[Stability AI Community License](https://stability.ai/community-license-agreement),
[Acceptable Use Policy](https://stability.ai/use-policy), and the bundled
[Gemma terms](https://huggingface.co/stabilityai/stable-audio-3-optimized/blob/2204d5086475bd5b7e6e2bd720772dd8e8160513/LICENSE_GEMMA.md).
The optimized model repository also carries its own
[license file](https://huggingface.co/stabilityai/stable-audio-3-optimized/blob/2204d5086475bd5b7e6e2bd720772dd8e8160513/LICENSE.md).

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

The download may require the operator to authenticate and accept upstream
gated-model terms. After installation, record the resolved Hugging Face
snapshot rather than treating the moving `main` ref as frozen. The currently
verified snapshot is listed above.

Verify the isolated CLI without generating audio:

```powershell
cmd /c models\stable-audio-3\optimized\tflite\sa3.bat --help
```

## Generate an evaluation candidate

Always provide an absolute output path under the repository-root `.local/`.
Otherwise the upstream CLI places a relative output inside its own source
checkout, mixing disposable audio with the persistent runtime.

```powershell
$scoreRoot = (Get-Location).Path
$candidateDir = Join-Path $scoreRoot ".local\sa3-evaluation"
New-Item -ItemType Directory -Force $candidateDir | Out-Null
$candidate = Join-Path $candidateDir "candidate-seed-19.wav"

Push-Location models/stable-audio-3/optimized/tflite
.\sa3.ps1 `
  --prompt "dark restrained psychological horror underscore, audible midrange, no vocals" `
  --negative-prompt "piercing whistle, harsh resonance, vocals, speech" `
  --dit sm-music --decoder same-s --precision fp32 `
  --seconds 60 --steps 8 --seed 19 --cfg 3.0 --out $candidate
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

## What the exploratory smoke established

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

## Bring a candidate into ScoreMatter

Until an SA3 process adapter exists, the only honest bridge is the built-in
`manual` provider:

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

The external generation record referenced above must independently retain the
exact positive and negative prompts, CFG/APG, seed, duration, step and thread
counts, precision, component revisions and hashes, host/runtime facts, elapsed
time, output SHA-256, byte count, and upstream stdout/stderr. Manual ingestion
does not capture or prove that lineage; its receipt has no effective SA3 seed
and keeps rights unapproved.

## Judgement Horror handoff boundary

The current truthful dogfood path is:

```text
Judgement Horror inquiry constraints
  -> external SA3 CLI candidate in ScoreMatter .local/
  -> ScoreMatter manual source record + ingest
  -> ScoreMatter replay byte verification
  -> separate listening, loop, mix, creative, and rights review
```

It is not `Judgement Horror -> ScoreMatter SA3 provider`, because no such
provider exists. Keep the candidate in ScoreMatter's ignored evaluation lane
until the consumer project has an exact ignored staging path and export
exclusion. Do not copy it into game assets merely because manual replay passes.

There is also an unresolved contract mismatch: ScoreMatter Brief v1 requires
specific BPM, key, and meter values, while a horror cue may intentionally be
beatless or leave those fields unknown. Do not invent musical facts to satisfy
the current schema. Resolve that M1 schema gap before claiming that the
Judgement Horror brief was losslessly compiled.

## Work still required for a real provider

- a versioned out-of-process SA3 adapter and frozen provider descriptor;
- timeout, cancellation, failure-receipt, environment, revision, and hardware
  evidence;
- prompt/options mapping from reviewed ScoreMatter contracts;
- raw-float peak capture and an explicit non-destructive post-processing chain;
- automated media checks plus human audibility, harshness, vocal-leakage, loop,
  mix, creative, and rights gates;
- an evaluation package whose evidence survives cleanup;
- consumer-project packaging and playback acceptance, owned by that project.

Until those items are implemented and reviewed, SA3 remains an external local
evaluation runtime, not ScoreMatter production capacity.
