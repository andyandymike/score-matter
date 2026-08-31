# Getting started

ScoreMatter's default path makes one local BGM candidate and gives you the WAV
immediately. It does not require a Brief, Plan, review form, blind comparison,
or local text model.

```text
Describe the scene -> Agent chooses a music direction -> one SA3 call -> listen
```

## Requirements

- Python 3.10 or newer
- Git
- A machine-local Stable Audio 3 Medium/SAME-L TFLite runtime for real
  generation
- On the verified Windows reference machine, roughly 9.34 GiB for model files
  and enough free RAM for a large CPU inference process

The Python package does not download model files. Follow the
[SA3 local guide](sa3-local-evaluation.md) when preparing or auditing a local
runtime, including its separate model terms.

## Install from source

=== "Windows PowerShell"

    ```powershell
    git clone https://github.com/andyandymike/score-matter.git
    cd score-matter
    python -m venv .venv
    .venv\Scripts\python -m pip install --disable-pip-version-check -e .
    .venv\Scripts\score-matter --help
    ```

=== "macOS / Linux"

    ```bash
    git clone https://github.com/andyandymike/score-matter.git
    cd score-matter
    python -m venv .venv
    .venv/bin/python -m pip install --disable-pip-version-check -e .
    .venv/bin/score-matter --help
    ```

## Generate one BGM draft

Ask the host agent to turn the scene, gameplay, dialogue, and mix needs into one
focused music prompt. Then invoke the local generator once:

=== "Windows PowerShell"

    ```powershell
    .venv\Scripts\score-matter generate `
      --prompt "Instrumental background music for a quiet star-map navigation screen: spacious curiosity, ordered vastness, warm restrained analog pad, muted electric keys, soft low synth pulse, clearly audible midrange on ordinary speakers, controlled upper mids, rounded transients, no vocals, no choir, no trailer impacts." `
      --seconds 20 `
      --seed 2719 `
      --out ".local\authoring\star-map-v1.wav"
    ```

=== "macOS / Linux"

    ```bash
    .venv/bin/score-matter generate \
      --prompt "Instrumental background music for a quiet star-map navigation screen: spacious curiosity, ordered vastness, warm restrained analog pad, muted electric keys, soft low synth pulse, clearly audible midrange on ordinary speakers, controlled upper mids, rounded transients, no vocals, no choir, no trailer impacts." \
      --seconds 20 \
      --seed 2719 \
      --out ".local/authoring/star-map-v1.wav"
    ```

The command prints `SCORE_GENERATE_START` before inference and
`SCORE_GENERATE_OK` with the absolute path when the candidate is ready. It
starts one process, creates one WAV, and makes no automatic retry.

If `--out` is omitted, ScoreMatter chooses a unique ignored path under
`.local/authoring/`. If `--seed` is omitted, it chooses and reports a random
seed. It will not overwrite an existing WAV.

The default runtime root is `models/stable-audio-3/optimized/tflite`. Use
`--runtime-root` or `SCORE_MATTER_SA3_ROOT` only for another local
installation. Missing files cause a fast local error; generation never
downloads them.

## Listen, then revise

The WAV is a draft, not an approval. Listen in the actual playback context when
possible, then tell the agent what changed perceptually:

- “The melody competes with dialogue.”
- “It is too quiet on laptop speakers.”
- “The upper mids become sharp around the middle.”
- “Keep the instrumentation, but make the emotion less tragic.”

The next turn should normally produce one revised prompt and one revised WAV.
Loop editing, loudness work, game import, or deeper analysis should happen only
when the project actually needs them.

!!! note "CFG and negative prompts"
    The fast default uses CFG `1.0` and expresses exclusions inside the main
    prompt. The upstream runtime ignores a separate negative prompt at CFG
    `1.0`, so ScoreMatter rejects that combination instead of silently doing
    something different. Advanced users may set both an explicit non-default
    `--cfg` and `--negative-prompt`.

## Developer and research tools

The deterministic mock, manual-ingest, replay, SA3 boundary-pilot, and Director
Phase A commands remain available for explicit infrastructure, provenance, or
capability research. None is required to hear the first BGM draft.

Run the no-model repository checks with:

```text
python -m unittest discover -s tests -v
python tools/audit_public_tree.py
score-matter --help
```

Read the [M0 contract](m0-contract.md) for the optional evidence kernel and the
[Director Phase A guide](music-director-phase-a.md) for the optional planning-
contract research lane.
