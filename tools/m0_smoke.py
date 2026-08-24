from __future__ import annotations

import tempfile
from pathlib import Path

from score_matter.bundle import load_execution_bundle
from score_matter.canonical import canonical_sha256
from score_matter.demo import create_demo_bundle
from score_matter.providers import mock, replay
from score_matter.providers.base import ExecutionContext
from score_matter.store import ArtifactStore


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="score-matter-m0-") as temporary:
        root = Path(temporary)
        bundle_root = create_demo_bundle(root / "bundle", provider_id="mock")
        descriptor = mock.descriptor()
        bundle = load_execution_bundle(
            bundle_root,
            expected_provider_id="mock",
            provider_descriptor=descriptor,
        )
        store = ArtifactStore(root / "store")
        source_file, source_receipt = mock.execute(bundle, ExecutionContext(store))
        replay_file, replay_receipt = replay.verify(
            source_file.absolute_path, ExecutionContext(store)
        )

        if replay_receipt["source_run_receipt_sha256"] != canonical_sha256(source_receipt):
            raise RuntimeError("replay receipt did not bind the source receipt")
        if replay_receipt["artifacts"] != source_receipt["artifacts"]:
            raise RuntimeError("replay receipt changed the verified artifact inventory")
        print(
            "SCORE_M0_BOOTSTRAP_OK "
            f"artifact_sha256={source_receipt['artifacts'][0]['artifact_sha256']} "
            f"replay_receipt_sha256={replay_file.sha256}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
