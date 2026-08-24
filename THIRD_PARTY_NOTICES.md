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

The ScoreMatter MIT license does not grant rights to any future provider,
model, weight, dataset, input audio, generated output, or consumer-game asset.
