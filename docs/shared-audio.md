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
uses fresh installed CLIs with synthetic PCM to check candidate registration,
musical coordinates and immutable plans, explicit revision-checked session
selection, normalization, loops, scene rendering, revision-bound cue exports and local
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

## Register an existing generated candidate

Register a WAV from `generate` after generation has completed. This step uses
existing files and calls no model:

```sh
python -m score_matter audio --workspace .local/audio-workspace candidate register --audio candidate.wav --generation-record candidate.generation.json --intent intent.json --request-id register-001 --json
```

`--generation-record` and `--intent` are optional. Use the actual generation
record path returned by `generate`; registration does not search for a sidecar.
An example `intent.json` is:

```json
{"schema":"score-music-intent/v1","source":"user","purpose":"Quiet exploration music","preserve":["Restrained dynamics"],"change":["Leave room for dialogue"]}
```

The intent requires `schema`, `source` (`user`, `agent`, `project` or `unknown`)
and `purpose`; `preserve`, `change` and `notes` are optional. Keep the actual
source of the intent. This records desired authoring choices, not human listening
feedback, musical consistency or approval. Exact schemas, file arguments and
validation limits are exposed in `capabilities --json` under
`product_capabilities.candidate_registration`.

Registration validates the existing PCM16 WAV. If a generation record is
supplied, its SHA-256 and media facts must match that WAV. The record's historical
output path is not opened, so an unchanged WAV and record can be moved together.
This check binds the record to audio bytes; it does not authenticate historical
claims, verify model weights or establish rights. Without a record, origin stays
unknown. For older WAVs with no metadata, use `assets import`; registration with
neither optional file delegates to that same import operation.

The `matter-result/v1` result contains the registered audio at
`outputs[0].asset_id`. The supplied original JSON bytes become immutable
`generation_record` and `music_intent` attachments in the same publication as the
unchanged WAV. Attachment digests are recorded on the audio and each attachment
references that audio. You can use the returned audio ID in existing actions,
sessions and cue variants.

### Select the candidate explicitly

Registration does not create a session, change an existing selection or add
feedback. Create a session separately with `create-session.json`:

```json
{"schema":"matter-session-create/v1","request_id":"create-music-001","session_id":"exploration","name":"Exploration music"}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace session create --request create-session.json --json
python -m score_matter audio --workspace .local/audio-workspace context show exploration --json
```

The new empty session is at revision 1. Put the actual registered audio ID in
`select-candidate.json`:

```json
{"schema":"matter-session-select/v1","request_id":"select-music-001","session_id":"exploration","expected_revision":1,"asset_id":"ASSET_ID"}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace session select --request select-candidate.json --json
```

Selection advances the revision. Replaying the same request returns its saved
receipt. A new selection request using the old revision fails with
`revision_conflict` and leaves the current selection intact. For an existing
session, read its context first and use the observed revision; explicitly decide
whether to replace its selected candidate.

### Retry or inspect registration

Registration request IDs are distinct from the later session request IDs. When
either metadata file is supplied, reuse the same registration ID with identical
input bytes to retrieve the saved result, even after moving those files; changed
bytes conflict. With neither metadata file, the generic import fallback also
binds the source path, so keep that path unchanged for same-ID retries.
Even JSON whitespace is part of the saved
attachment identity. Invalid metadata or a record mismatch is rejected before
claiming the request, so it can be corrected and retried. After successful
publication, query the saved result even if the original files have been removed:

```sh
python -m score_matter audio --workspace .local/audio-workspace action show register-001 --json
```

An interrupted publication can leave the core request in `recovery_pending`.
Registration does not automatically reclaim that request, select a different ID
or regenerate audio. Inspect the saved request and workspace before taking a
recovery action; retrying the pending request alone does not complete it.

## Mark musical regions on an exact asset

Music annotations attach supplied timing and named regions to one immutable audio
asset. They do not detect beats, stretch audio, generate music or record listening
feedback. Start with an existing registered or imported WAV and manually establish
its timing. Keep the actual `source`: `user`, `agent`, `project` or `unknown`.

Save `annotation.json`, replacing `ASSET_ID` with the original audio ID. This
illustrative 120 BPM grid needs at least eight seconds of audio; replace the grid
and regions with marks appropriate to your file:

```json
{
  "schema": "score-music-annotate/v1",
  "request_id": "music-marks-001",
  "asset_id": "ASSET_ID",
  "source": "user",
  "timing": {
    "mode": "fixed",
    "bpm": "120",
    "bpm_unit": {"numerator": 1, "denominator": 4},
    "meter": {"beats": 4, "unit": 4},
    "origin_frame": 0
  },
  "regions": [
    {"id": "intro", "start": {"bar": 1, "beat": "1"}, "end": {"bar": 2, "beat": "1"}},
    {"id": "loop", "start": {"bar": 2, "beat": "1"}, "end": {"bar": 4, "beat": "1"}},
    {"id": "outro", "start": {"bar": 4, "beat": "1"}, "end": {"bar": 5, "beat": "1"}}
  ]
}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace music annotate --request annotation.json --json
python -m score_matter audio --workspace .local/audio-workspace music show ANNOTATION_ID --json
```

Use `annotation.asset_id` (also `outputs[0].asset_id`) as `ANNOTATION_ID`.
This is a JSON annotation asset, not playable audio. The saved document includes
the exact source asset ID, digest and media facts, the supplied coordinates, and
their resolved frame ranges. It is immutable: changed marks require a new request
ID and produce a new annotation. Annotating the same WAV under a different audio
asset ID is a separate binding. Edited outputs never inherit these marks
automatically; explicitly annotate each new audio asset.

### Coordinate rules

- Bars and beats start at 1. A beat is measured in the meter's denominator unit;
  in 6/8, beats run from `"1"` up to but excluding `"7"`. Write the next bar's
  first beat instead of beat 7. Decimal subdivisions such as `"2.5"` are allowed.
- `bpm_unit` is a fraction of a whole note. Use `1/4` for quarter-note BPM,
  `1/8` for eighth-note BPM, or `3/8` for dotted-quarter BPM in 6/8. `origin_frame`
  is the location of bar 1, beat 1; it can follow an unmetered lead-in.
- BPM, beat subdivisions and seconds use nonnegative decimal **strings**, with
  at most nine fractional digits. BPM must be greater than zero and at most 1000.
  Integer fields, including meter units, reject floating-point values and booleans.
- Each endpoint can instead be `{"frame": 8000}` or `{"seconds": "1.25"}`.
  For free or uncertain timing, use `{"mode":"free"}` or `{"mode":"unknown"}`
  and only frame/second endpoints. A variable tempo map is not supported.
- All conversions use exact fractions from the absolute origin and round only
  once with `rational-half-up/v1`: nonnegative half frames round upwards.
  Results report `exact_frame`, actual `frame`, `error_frames` and
  `error_seconds`; fractions are strings, so large intermediate integers do not
  lose JSON precision. There is no repeated per-beat rounding drift.
- Regions are half-open: start is included, end excluded. An end at the audio's
  frame-count boundary is valid. The exact coordinate must fit before rounding,
  and the resulting range must remain nonempty. Neither the grid nor names prove
  that the file actually follows that tempo or musical structure.

### Plan, inspect and explicitly execute

`music plan` saves an immutable plan; it does not render audio. For example,
`loop-plan.json` selects the marked loop with no overlap:

```json
{"schema":"score-music-plan/v1","request_id":"music-loop-plan-001","annotation_id":"ANNOTATION_ID","region_ids":["loop"],"target":{"kind":"loop","crossfade_frames":0}}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace music plan --request loop-plan.json --json
python -m score_matter audio --workspace .local/audio-workspace music show PLAN_ID --json
python -m score_matter audio --workspace .local/audio-workspace music execute PLAN_ID --json
```

Use the returned `plan.asset_id` as `PLAN_ID`. The plan stores its exact annotation
and audio references, resolved ranges and errors, a complete Core request, and
the Core resolution digest. `target: {"kind":"trim"}` extracts one named range;
trim and loop plans each take exactly one region. Loop overlap is explicit;
`crossfade_frames` must be zero or at least two frames and at most half the range.
The plan reports the final `period_frames`, exact `period_seconds`, source offset
and removed frames. An overlap shortens the loop, so its period is not necessarily
the original number of bars. Neither zero overlap nor crossfading guarantees a
musically seamless result.

Execution delegates the frozen request to Core's existing trim/loop/splice operations
with the saved resolution digest. It returns playable audio in `outputs`, keeps
the plan and annotation references, and preserves Core failure status. Select
the output into a session separately using the current observed revision.
Capabilities expose the full annotation and plan request schemas under
`product_capabilities.music`.

### Replace one named region with another

A splice plan replaces one region of a base asset with one complete region
from another annotation. Both can also refer to different regions of the same
audio asset. For example, save `splice-plan.json` to replace the base `bridge`
with the replacement `bridge`:

```json
{
  "schema": "score-music-plan/v1",
  "request_id": "music-splice-plan-001",
  "annotation_id": "BASE_ANNOTATION_ID",
  "region_ids": ["bridge"],
  "target": {
    "kind": "splice",
    "replacement": {
      "annotation_id": "REPLACEMENT_ANNOTATION_ID",
      "region_id": "bridge"
    },
    "transition_frames": 0
  }
}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace music plan --request splice-plan.json --json
python -m score_matter audio --workspace .local/audio-workspace music show PLAN_ID --json
python -m score_matter audio --workspace .local/audio-workspace music execute PLAN_ID --json
```

Create both annotations first and substitute their actual IDs. A plan accepts
exactly one base region and one replacement region. The two complete regions
must resolve to **exactly equal frame counts**, and the audio must share sample
rate and channel count. Equal bar counts alone are insufficient: different BPMs
can produce different durations. A longer or shorter replacement is rejected;
there is no implicit cropping, padding, resampling or time stretching. Free and
unknown timing still work through explicit frame/second marks.

The plan freezes both annotation/audio identities and digests, the complete
named replacement window and its coordinate errors, and a Core `splice/v1`
request with the base and replacement as its two audio inputs. `music show` and
`music execute` reload and verify both bindings. The execution response retains
`music_annotation` for the base and adds `music_replacement_annotation`; the
immutable plan contains the full relationship. Existing trim/loop/constraints
plan identities and saved plans remain compatible.

`transition_frames` is required and applies equally at both ends **inside** the
base write window. Zero performs a direct replacement; each nonzero transition
must fit without overlapping the other. A one-frame transition preserves its
outer base sample, following Core's existing splice rule. The output preserves
the base's total frame count and all PCM outside the target window. Transition
and change measurements do not prove that the edit is musically seamless.

An optional `target.protection` binds the base session's Core policy; it does
not reinterpret the replacement as the protected selection. Protected overlaps
are rejected before rendering. Explicitly select any accepted result afterward;
neither source annotation is automatically transferred to the new audio. This
operation calls no model and makes no claim about matching harmony or rhythm.

### Arrange named regions into a complete track

Use `music arrange` for a new sequence such as intro, theme A twice, theme B,
then outro. Each segment names an existing annotation and one complete region;
`repeat` is always an explicit positive integer. Save this as `arrange.json`,
substituting the actual annotation IDs and region names:

```json
{
  "schema": "score-music-arrange/v1",
  "request_id": "music-arrange-001",
  "segments": [
    {
      "id": "intro",
      "annotation_id": "INTRO_ANNOTATION_ID",
      "region_id": "intro",
      "repeat": 1
    },
    {
      "id": "theme-a",
      "annotation_id": "THEME_A_ANNOTATION_ID",
      "region_id": "theme",
      "repeat": 2
    },
    {
      "id": "theme-b",
      "annotation_id": "THEME_B_ANNOTATION_ID",
      "region_id": "theme",
      "repeat": 1
    },
    {
      "id": "outro",
      "annotation_id": "OUTRO_ANNOTATION_ID",
      "region_id": "outro",
      "repeat": 1
    }
  ]
}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace music arrange --request arrange.json --json
python -m score_matter audio --workspace .local/audio-workspace music show PLAN_ID --json
python -m score_matter audio --workspace .local/audio-workspace music execute PLAN_ID --json
```

Arrangement creates an immutable `music_arrangement` metadata asset, returned
as `plan` and `outputs[0]`. Its `score-music-arrangement-plan/v1` document freezes
every segment's exact annotation/audio identities, digests and complete source
range. `timeline` records each occurrence's new start/end frames and zero-based
`repeat_index`, referring back to the frozen segment table. Inputs are deduplicated
by asset ID in first-appearance order; distinct assets remain distinct even when
their audio bytes match.

The v1 plan compiles to Core `scene/v1` and its duration is the sum of all repeated
region lengths. Every input must have the same sample rate and channel count.
Source regions may have different lengths, tempi or free/unknown timing: the
operation copies their resolved PCM sequentially. It adds no gaps, overlaps,
transitions, cropping, padding, resampling, time stretching or beat alignment,
and does not infer a global BPM. Joins may be audible; exact copying does not
establish musical or listening acceptance.

Limits apply together: 128 segments with unique IDs, 1–64 repeats each, at most
1,024 occurrences, 16 distinct audio assets and 144 parent references. Core also
limits the combined **complete input WAV files** to 64 MiB and the output WAV to
64 MiB. A conservative size check covers the complete publication receipt,
including its duplicated metadata, under the 1 MiB JSON limit. Some combinations
below the count limits can therefore still exceed the metadata budget. All these
checks happen before claiming the arrangement request or rendering audio.

`music execute` verifies the saved sequence and source bindings before delegating
to Core. Its response preserves Core's outputs/status and adds `music_plan` and
the distinct `music_annotations` references. The result is an unselected candidate
on a **new timeline**. Arrangement rejects `protection` and session fields; it
does not change source sessions, locks or feedback. Source annotations and PCM
locks are not transferred. Annotate the result and create its session or protection
explicitly. Selecting it into a source session with existing locks can be rejected
by Core's lineage checks; create a new session when working with this new timeline.

#### Add explicit transitions

Use `score-music-arrange/v2` when a particular join needs a linear crossfade.
The existing v1 request, saved plans and execution identities keep their original
hard-join behavior. In v2, `transitions` is required, and an empty array still
means hard joins. Each entry identifies the occurrence **before** a join using
its segment ID and zero-based repeat index:

```json
{
  "schema": "score-music-arrange/v2",
  "request_id": "music-transition-001",
  "segments": [
    {
      "id": "theme-a",
      "annotation_id": "THEME_A_ANNOTATION_ID",
      "region_id": "theme",
      "repeat": 2
    },
    {
      "id": "theme-b",
      "annotation_id": "THEME_B_ANNOTATION_ID",
      "region_id": "theme",
      "repeat": 1
    }
  ],
  "transitions": [
    {
      "after_segment_id": "theme-a",
      "after_repeat_index": 0,
      "crossfade_frames": 128
    },
    {
      "after_segment_id": "theme-a",
      "after_repeat_index": 1,
      "crossfade_frames": 256
    }
  ]
}
```

Save the request and use the same `music arrange`, `music show` and
`music execute` commands above. This example crossfades the two A occurrences,
then the second A into B. The chosen regions must be long enough for those
windows. Each transition is at least two integer frames; the final occurrence,
missing occurrences and duplicate boundary entries are rejected. For every
occurrence, its incoming and outgoing overlaps together must fit its complete
source length. Three-way mixing is not allowed. No transition is inferred for
an omitted join, and no fade is added at the beginning or end of the track.

The v2 plan records each overlap's output start/end frames, each occurrence's
`fade_in_frames`, `fade_out_frames`, `body_start_frame` and `body_end_frame`, and
`shortened_by_frames`. Its total duration is the original sum minus the overlap
lengths: this example shortens the track by 384 frames. Envelopes use Core's
linear Q24 rule and `scene/v1` mixing with clipping rejection. The plan still
makes no beat-alignment, harmony, tempo or seamlessness claim.

Compatible consecutive repeats are compiled into the same Core event where
their source, fades and spacing agree. A transition pattern requiring more than
128 event definitions is rejected before publication, even if it fits the
1,024-occurrence limit. The other input, output and complete-receipt size limits
continue to apply. Both v1 and v2 produce candidates on a new timeline and leave
source sessions and locks unchanged.

#### Continue editing an executed arrangement

`music annotate-arrangement` creates explicitly requested section marks on an
**already completed** v1 or v2 arrangement. It does not execute a saved plan.
After inspecting and executing the plan above, save this request as
`arranged-marks.json` with its actual plan ID:

```json
{
  "schema": "score-music-annotate-arrangement/v1",
  "request_id": "arranged-marks-001",
  "plan_id": "ARRANGEMENT_PLAN_ID",
  "source": "agent",
  "regions": [
    {
      "id": "opening-a",
      "segment_id": "theme-a",
      "repeat_index": 0,
      "range": "full"
    },
    {
      "id": "second-a-body",
      "segment_id": "theme-a",
      "repeat_index": 1,
      "range": "body"
    }
  ]
}
```

```sh
python -m score_matter audio --workspace .local/audio-workspace music annotate-arrangement --request arranged-marks.json --json
python -m score_matter audio --workspace .local/audio-workspace music show ANNOTATION_ID --json
```

`full` marks the occurrence's whole output range, including any mixed transition
audio. `body` removes the complete incoming and outgoing overlap windows; an
empty body is rejected. A v1 occurrence has no overlaps, so its full and body
ranges coincide. Each request names 1–128 distinct occurrences with distinct
region IDs; choose full or body once per occurrence. Marks use exact integer
output frames and `unknown` timing. They do not inherit source tempo grids.

The new `music_annotation` asset binds the exact plan, matching completed action
receipt and actual output WAV. Its document also records the selected source
occurrences and their source/output ranges. Showing or reusing it verifies this
relationship, including its ancestors, again. A missing or failed action cannot
be annotated; a pending claim remains `recovery_pending`. Creation never selects
the output or adds feedback or locks. The supplied `source` describes who supplied
these marks and is not listening approval.

Use the returned annotation ID with the existing `music plan` commands to trim,
loop or replace a named region, or use it in another arrangement. Inspect that
plan, execute it explicitly, then create/select a session and export using the
existing shared commands. Protection requires a separate explicit request on the
new timeline. Derived annotations support at most 32 ancestry levels, and their
complete publication receipts must fit the same 1 MiB budget; invalid or excessive
ancestry is rejected before creating another annotation.

### Add protection without removing existing locks

A constraints plan requires the session to select the annotation's exact source
asset. Read context first. For a session named `exploration` currently at revision
2, a plan to protect the intro is:

```json
{"schema":"score-music-plan/v1","request_id":"music-lock-plan-001","annotation_id":"ANNOTATION_ID","region_ids":["intro"],"target":{"kind":"constraints","session_id":"exploration","expected_revision":2}}
```

Plan and execute this with the same commands above. Planning unions the named
ranges with the existing mapped locks at that revision, merging overlapping or
adjacent ranges. The final union must fit Core's 16-region limit. The plan freezes
the complete resulting constraints request; execution does not recalculate it
against a newer selection. An outdated revision fails before any new lock change.
Removing locks remains an explicit Core constraints operation.

Subsequent trim/loop/splice plans can include a Core protection reference in `target`,
for example `"protection":{"session_id":"exploration","revision":3}` after
the lock mutation advances that session. Core rejects operations that discard or
modify protected PCM; extracting only the loop would therefore fail if it removes
the protected intro. These references use Core's constraint-set validation, not
a blanket requirement that the referenced revision remain the latest selection.

### Plan identity and retries

The Core execution request ID is derived from the plan request and the exact
annotation/audio references. Two annotation identities cannot silently share
one execution identity merely because their frame ranges match. Annotation and
plan publication use the existing complete-publication transaction; execution
uses the existing Core action transaction or session mutation. There is no atomic
transaction spanning all three steps.

Replaying the same annotate, plan, arrange or annotate-arrangement request returns its original saved result;
changing its inputs under that ID conflicts. Repeating `music execute PLAN_ID`
returns its completed receipt even after later session changes. The plan's
`core_request.request_id` can also be queried with `action show` for trim/loop/splice/scene,
or `session request` for constraints. An unfinished action claim remains
`recovery_pending`; execution never invents a replacement ID or regenerates audio.
The saved plan continues to link the annotation to the Core request even when
that request is queried directly through the Core commands. If executing the
frozen trim/loop/splice/scene request directly, also pass its saved digest with Core's
`--expected-resolution-digest`; `music execute` supplies this check for you.

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
