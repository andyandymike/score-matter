# ScoreMatter

Fast, local-first BGM generation for games.

[![CI](https://github.com/andyandymike/score-matter/actions/workflows/ci.yml/badge.svg)](https://github.com/andyandymike/score-matter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

ScoreMatter is a generation agent: describe what a scene needs, let the host
agent turn that project context into a focused music direction, generate one
local Stable Audio 3 candidate, and listen immediately. Your next natural-
language instruction shapes the next attempt.

```text
Project context -> Agent judgment -> one SA3 generation -> one WAV
        ^                                                |
        +--------------- listening feedback -------------+
```

Fast authoring is the default. Blind comparisons, capability experiments,
immutable evidence, and replay tooling remain available for explicit research
or audit work, but they never gate the first audible candidate.

## Status

The top-level `generate` command invokes the machine-local Stable Audio 3
Medium/SAME-L TFLite runtime exactly once. The default is a 20-second,
44.1 kHz stereo PCM16 candidate using eight sampling steps and eight CPU
threads. It runs offline, performs no hidden retry, and returns the WAV as soon
as a cheap media-format check passes.

The runtime and its roughly 9.34 GiB of model payload are intentionally not
bundled or downloaded by the command. On the verified reference machine, a
20-second candidate typically takes around one to two minutes and uses
substantial system memory. See the
[local SA3 guide](docs/sa3-local-evaluation.md) for the current installation
boundary.

Every generated WAV is still a candidate. Successful generation does not
prove that the music sounds good, loops cleanly, fits a game mix, contains no
unwanted vocal-like sound, is original, is rights-cleared, or is ready to
ship. Listening decides what happens next.

## Quick start

Python 3.10 or newer is required. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --disable-pip-version-check -e .
.venv\Scripts\score-matter --help
```

With the ignored SA3 runtime installed under
`models/stable-audio-3/optimized/tflite`, generate one candidate:

```powershell
.venv\Scripts\score-matter generate `
  --prompt "Instrumental game BGM for a quiet star-map screen: spacious curiosity, warm restrained synths, clearly audible midrange on ordinary speakers, controlled upper mids, rounded transients, no vocals or heroic trailer hits." `
  --seconds 20 `
  --seed 2719 `
  --out ".local\authoring\star-map-v1.wav"
```

Omit `--out` to create a unique candidate path under `.local/authoring/`.
Omit `--seed` to choose a random seed that is printed with the result. The
command writes one small ignored record under ScoreMatter's
`.local/authoring/records/` for recall, but that record does not create another
workflow step or accompany a WAV exported elsewhere.

The normal iteration is deliberately short:

1. Listen to the returned WAV.
2. Say what should change: for example, “too quiet,” “upper mids are harsh,”
   “less tragic,” or “leave more room for dialogue.”
3. Generate one revised candidate.

There is no automatic candidate pool, scoring phase, Plan approval, model
rehash, normalization, loop construction, or game import in this path.

## Local files and model safety

Generated candidates and local records stay under ignored `.local/` paths.
The persistent machine-local runtime and weights stay under ignored `models/`.
Deleting `.local/` removes disposable output but must not remove the installed
model; deleting `models/` does remove the runtime and weights.

The command generates beside the destination under a unique temporary name,
then publishes the checked WAV without replacing an existing file. Failed
attempts do not leave a file that looks finished. It also forces the model
libraries offline and fails quickly when required local components are absent.
Set `SCORE_MATTER_SA3_ROOT` or pass `--runtime-root` only when the runtime lives
somewhere else. Defaults stay anchored to this ScoreMatter checkout even when
the command is launched from a consumer project.

## Optional research and evidence tools

The repository still contains the earlier dependency-light evidence kernel:
strict contracts, deterministic mock audio, bounded manual ingest,
content-addressed artifacts, and replay verification. It also retains the SA3
boundary-pilot and music-director Phase A tooling as optional research lanes.
They are not the ScoreMatter product loop and ordinary BGM generation does not
require them.

Run the repository verification with:

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python tools\audit_public_tree.py
```

For exact historical boundaries, see the [M0 public contract](docs/m0-contract.md),
[SA3 local guide](docs/sa3-local-evaluation.md), and
[Director Phase A research guide](docs/music-director-phase-a.md).

## Repository layout

- `src/score_matter/authoring.py` — single-attempt local SA3 generation.
- `src/score_matter/` — CLI plus optional contracts and evidence tooling.
- `docs/` — usage, model boundary, and architecture decisions.
- `tests/` — deterministic tests that never load the real model in CI.
- `tools/sa3_boundary_pilot.py` — optional capability-research orchestration.
- `spec/` — private working material, intentionally excluded from Git.
- `models/` — persistent local source, environments, weights, and caches,
  intentionally excluded.
- `.local/` — generated candidates and disposable local records,
  intentionally excluded.

The shipped game consumes ordinary audio files. It does not need ScoreMatter,
Python, a model, a network connection, or a GPU. SonicMatter remains a separate
Foley project.

## Contributing

This is a small personal open-source project. Keep changes narrow and make the
first useful audio cheap to reach. Read [CONTRIBUTING.md](CONTRIBUTING.md)
before proposing a provider, model, dependency, audio asset, or release claim.

## License

Project-authored source code and public documentation are licensed under the
[MIT License](LICENSE). Dependencies, model code, model weights, datasets,
reference audio, and generated outputs retain separate terms and never inherit
MIT merely by passing through ScoreMatter.
