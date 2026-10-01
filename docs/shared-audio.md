# Shared local audio authoring

`score-matter audio` provides shared editing and an optional adapter for an
already configured local SA3 inpainting runtime. Existing `generate` remains a
separate entry point.
Both products use Matter Audio Core **0.6.0** for sessions, PCM protection, jobs,
comparisons, loops, scene timelines, cue packages and measured local search.

## Install from a clean checkout

`score-matter audio` supports Windows and Linux only. The separate generation
and evidence commands retain their own platform and runtime requirements.

Use Python 3.10+ and Git. Run from this repository's root. The build step accesses
GitHub and the Python package index for source and tooling; it downloads no audio
model. Create and activate an environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

On Linux, activate with `source .venv/bin/activate` instead. Then run the
same commands on either platform:

```sh
python -m pip wheel --wheel-dir .local/audio-wheels -r requirements-audio.txt
python -m pip install --no-index --find-links .local/audio-wheels "score-matter[audio]==0.1.0.dev0"
python -m pip check
python -m score_matter audio capabilities --json
python -X utf8 tools/check_shared_audio.py
```

`requirements-audio.txt` builds the core from immutable commit
`7834d03ad5447dd383b3f011e20d381ac0aa0f03`. It does not assume the core is on PyPI.
The second step installs only the collected wheels. Retain that directory for
offline installation on compatible Python/platform environments. Transitive
third-party dependencies are resolved during the build; this is not a lockfile
for every platform or a byte-reproducible wheel build. An absent core or a version
other than 0.6.0 returns a structured installation error.

The wheel installation includes ScoreMatter's `audio` extra and refreshes its
installed dependency metadata. Base-only installation with `python -m pip install .`
keeps audio optional. For an existing editable checkout, after collecting the
wheels, use `python -m pip install --find-links .local/audio-wheels -e ".[audio]"`
instead to keep local source edits live while refreshing metadata.

The verification script requires every adapter test to pass without skips. It
uses fresh installed CLIs with synthetic PCM to check
normalization, loops, scene rendering, revision-bound cue exports and local
search, including original and exported bytes. It calls no model and plays no
audio. Windows and Linux run this as a required CI job.

## Start from an audio snapshot

```sh
python -m score_matter audio --workspace .local/audio-workspace assets import existing.wav --request-id import-001 --json
python -m score_matter audio --workspace .local/audio-workspace inspect ASSET_ID --json
python -m score_matter audio --workspace .local/audio-workspace action execute --request gain.json --json
```

Use the actual returned ID for `ASSET_ID` and request inputs. `gain.json` contains:

```json
{"schema":"matter-action/v1","request_id":"gain-001","operation":"gain/v1","inputs":["ASSET_ID"],"parameters":{"db":-3}}
```

Import preserves an immutable snapshot and records unknown external rights;
it does not grant distribution rights or establish listening approval.

## Shared operations and continued work

`capabilities --json` returns exact schemas:

| Workflow | Commands and operations |
| --- | --- |
| PCM editing | `inspect`, `gain/v1`, `trim/v1`, `fade/v1`, `mix/v1`, `splice/v1` |
| Continued work | `session`, `feedback`, `context`, `constraints` |
| Managed execution | `job`, `batch`, explicit cancellation and recovery |
| Comparison and delivery | `audition`, `export`, `cue-set` |
| Production authoring | `normalize/v1`, `loop/v1`, `scene/v1`, `analyze`, `library` |

Use `action resolve` before editing and `action show REQUEST_ID` to query a
request. Reuse its ID for a retry; a pending request requires inspection or
recovery before resubmission. Read context before editing a selected asset.
Session mutations use the observed `expected_revision`; restoring appends a
revision. Feedback keeps its actual source and evaluated revision.

Managed jobs bind current selection and lock policy. Direct actions can bind a
protection session and revision. Final PCM is verified before publication. To
change one mixed layer, re-render the original immutable recipe with that layer
changed, preserving the relevant protection policy.

Cue exports bind exact WAV bytes and optional saved selections. Comparison-page
preview gain never changes delivery. Normalization uses RMS/peak, not LUFS;
overlap loops shorten the selected window; feature distance does not provide
semantic audio understanding. See the pinned
[core production guide](https://github.com/andyandymike/matter-audio-core/blob/7834d03ad5447dd383b3f011e20d381ac0aa0f03/docs/production.md)
for examples. These core operations call no audio model. Opening a comparison
page does not start playback. Listening and game integration remain separate.

## Upgrade an existing workspace

Stop clients and retain a backup before upgrading. Core 0.6.0 uses SQLite schema
4, the same schema as 0.5. For an older workspace:

```sh
python -m score_matter audio --workspace .local/audio-workspace session migrate --json
```

Migration preserves audio and historical revisions and calls no model. Install
the same reviewed core version in every client using that workspace.


## Local SA3 inpainting

The audio requirements install no model weights. Set `SCORE_MATTER_SA3_ROOT` to
the existing runtime directory containing `scripts/sa3_tflite.py`, its `.venv`
and model components. Use this explicit setting when a wheel installation cannot
locate the checkout's default `models/stable-audio-3/optimized/tflite` directory:

```powershell
$env:SCORE_MATTER_SA3_ROOT = "C:\audio-models\sa3-tflite"
python -m score_matter audio capabilities --json
```

Shared PCM operations remain available when this optional runtime is absent.

The optional authoring entry point registers `score.sa3_inpaint/v1` from
`src/score_matter/sa3_edit.py`. It uses the existing configured local SA3 Medium /
SAME-L fp32 / LiteRT runtime, including its encoder. Capabilities report unavailable
when the installation or supported driver is missing. No weights are downloaded.

Use `audio capabilities` for the strict schema. Input is 1-120 seconds of
44.1 kHz stereo PCM16. Required parameters are prompt, seed and start/end frames;
transition_frames, steps, threads, cfg and timeout_seconds are optional. Default
settings are 8 steps, 8 threads, cfg 1 and a 600-second deadline. A negative prompt
requires cfg other than 1. Local component SHA-256 snapshots bind the resolved
backend; the configured runtime is trusted local code, not a hermetic sandbox.

Prefer a managed job so current selection, PCM locks, cancellation and attempt
evidence are durable. The model receives the whole source with an explicit latent
mask; final assembly writes only the requested PCM window. A partial final second
is explicitly cropped from the model proposal. Findings keep context_read,
requested_edit, model_mask, allowed_write, transition and observed_changes separate.
Output 0 is the assembled final audio; the model_proposal output is evidence, not
the chosen protected result. Human listening remains a separate acceptance step.

Cancellation stops the owned process tree before acknowledgement. Call counts,
wall time and failures remain attached to each attempt, even if audio publication
fails. A launched cancelled attempt counts as a local model call; an uncertain
launch is null, not zero. There are no automatic inference retries or paid API
calls in this path. Legacy `generate` remains a separate API.
