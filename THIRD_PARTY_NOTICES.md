# Third-party notices

## Core Python dependencies

ScoreMatter currently declares two direct Python dependencies:

- `jsonschema 4.26.0` — MIT License; validates JSON Schema Draft 2020-12
  contracts.
- `rfc8785 0.1.4` — Apache License 2.0; produces RFC 8785/JCS canonical JSON
  bytes.

They and their transitive dependencies are installed from their own packages
and are not vendored into this repository. Each retains its own license and
notices.

## Models, audio, and data

The M0 bootstrap bundles no music model, model weight, codec model, dataset,
reference recording, generated production audio, or third-party audio asset.
Project-authored synthetic audio is generated only as ignored local test
evidence.

An optional Stable Audio 3 Small Music evaluation runtime may be installed by
an operator under the ignored `models/` root. Its upstream source, isolated
environment, optimized weights, T5Gemma component, and Hugging Face cache are
not tracked, bundled, redistributed, or licensed by ScoreMatter. The currently
documented reference installation is governed by the exact upstream license,
acceptable-use, gated-access, and component terms recorded in the
[SA3 local evaluation guide](docs/sa3-local-evaluation.md). Those terms can
change and must be reviewed for the intended action.

The ScoreMatter MIT license does not grant rights to that runtime or any other
provider, model, weight, dataset, input audio, generated output, or
consumer-game asset.
