from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from score_matter.bundle import load_execution_bundle
from score_matter.canonical import canonical_sha256, file_sha256, write_canonical_no_replace
from score_matter.demo import create_demo_bundle
from score_matter.errors import ContractError, IntegrityError
from score_matter.media import render_mock_sine_wav
from score_matter.providers import manual, mock, replay
from score_matter.providers.base import ExecutionContext
from score_matter.store import ArtifactStore


def fixed_context(store: ArtifactStore, execution_id: str) -> ExecutionContext:
    moments = iter(
        [
            datetime(2026, 8, 24, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 24, 1, 0, 1, tzinfo=timezone.utc),
        ]
    )
    return ExecutionContext(
        store=store,
        clock=lambda: next(moments),
        execution_id_factory=lambda: execution_id,
    )


class M0FlowTests(unittest.TestCase):
    def test_mock_generation_is_deterministic_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="mock")
            descriptor = mock.descriptor()
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="mock",
                provider_descriptor=descriptor,
            )

            first_store = ArtifactStore(root / "first-store")
            first_file, first = mock.execute(
                bundle, fixed_context(first_store, "run.mock.first")
            )
            second_store = ArtifactStore(root / "second-store")
            _, second = mock.execute(bundle, fixed_context(second_store, "run.mock.second"))

            self.assertEqual(
                first["artifacts"][0]["artifact_sha256"],
                second["artifacts"][0]["artifact_sha256"],
            )
            self.assertNotEqual(first["execution_id"], second["execution_id"])
            self.assertNotEqual(canonical_sha256(first), canonical_sha256(second))
            self.assertEqual(first["reproducibility"], "best_effort")
            self.assertFalse(first["bit_exact_regeneration_guaranteed"])
            replay_file, replay_receipt = replay.verify(
                first_file.absolute_path,
                fixed_context(first_store, "run.replay.first"),
            )
            self.assertTrue(replay_file.absolute_path.is_file())
            self.assertEqual(
                replay_receipt["source_run_receipt_sha256"], canonical_sha256(first)
            )
            self.assertFalse(replay_receipt["bit_exact_regeneration_guaranteed"])

    def test_replay_rejects_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="mock")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="mock",
                provider_descriptor=mock.descriptor(),
            )
            store = ArtifactStore(root / "store")
            receipt_file, receipt = mock.execute(
                bundle, fixed_context(store, "run.mock.tamper")
            )
            artifact = store.root / Path(receipt["artifacts"][0]["store_path"])
            artifact.write_bytes(b"tampered")
            with self.assertRaises(IntegrityError):
                replay.verify(
                    receipt_file.absolute_path,
                    fixed_context(store, "run.replay.tamper"),
                )

    def test_replay_rejects_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="mock")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="mock",
                provider_descriptor=mock.descriptor(),
            )
            store = ArtifactStore(root / "store")
            receipt_file, receipt = mock.execute(
                bundle, fixed_context(store, "run.mock.missing")
            )
            artifact = store.root / Path(receipt["artifacts"][0]["store_path"])
            artifact.unlink()
            with self.assertRaises(IntegrityError):
                replay.verify(
                    receipt_file.absolute_path,
                    fixed_context(store, "run.replay.missing"),
                )

    def test_manual_ingest_preserves_exact_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="manual")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="manual",
                provider_descriptor=manual.descriptor(),
            )
            audio = root / "owned-source.wav"
            render_mock_sine_wav(
                audio,
                sample_rate_hz=48000,
                channels=2,
                duration_samples=4800,
                frequency_hz=330,
                amplitude=0.1,
                seed=19,
            )
            source_record = {
                "schema": "score-manual-source/v1",
                "source_id": "test.owned-source",
                "audio_sha256": file_sha256(audio),
                "supplied_by": "test.fixture",
                "source_kind": "project_authored",
                "intended_use": "internal_eval",
                "rights_evidence_reference": "test-only synthetic source",
                "rights_reviewed": False,
            }
            source_record_path = root / "source-record.json"
            write_canonical_no_replace(source_record_path, source_record)
            store = ArtifactStore(root / "store")
            _, receipt = manual.ingest(
                bundle,
                fixed_context(store, "run.manual.first"),
                audio_path=audio,
                source_record_path=source_record_path,
            )
            self.assertEqual(receipt["artifacts"][0]["artifact_sha256"], file_sha256(audio))
            self.assertIn("manual_source_rights_not_reviewed", receipt["warnings"])

    def test_manual_ingest_rejects_intended_use_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="manual")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="manual",
                provider_descriptor=manual.descriptor(),
            )
            audio = root / "source.wav"
            render_mock_sine_wav(
                audio,
                sample_rate_hz=48000,
                channels=2,
                duration_samples=4800,
                frequency_hz=440,
                amplitude=0.1,
                seed=1,
            )
            source_record_path = root / "source-record.json"
            write_canonical_no_replace(
                source_record_path,
                {
                    "schema": "score-manual-source/v1",
                    "source_id": "test.mismatch",
                    "audio_sha256": file_sha256(audio),
                    "supplied_by": "test.fixture",
                    "source_kind": "unknown",
                    "intended_use": "local_preview",
                    "rights_evidence_reference": "unreviewed",
                    "rights_reviewed": False,
                },
            )
            with self.assertRaises(ContractError) as raised:
                manual.ingest(
                    bundle,
                    fixed_context(ArtifactStore(root / "store"), "run.manual.mismatch"),
                    audio_path=audio,
                    source_record_path=source_record_path,
                )
            self.assertEqual(raised.exception.code, "source_use_mismatch")

    def test_manual_ingest_rejects_source_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="manual")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="manual",
                provider_descriptor=manual.descriptor(),
            )
            audio = root / "source.wav"
            render_mock_sine_wav(
                audio,
                sample_rate_hz=48000,
                channels=2,
                duration_samples=4800,
                frequency_hz=440,
                amplitude=0.1,
                seed=2,
            )
            source_record_path = root / "source-record.json"
            write_canonical_no_replace(
                source_record_path,
                {
                    "schema": "score-manual-source/v1",
                    "source_id": "test.bad-hash",
                    "audio_sha256": "sha256:" + "0" * 64,
                    "supplied_by": "test.fixture",
                    "source_kind": "unknown",
                    "intended_use": "internal_eval",
                    "rights_evidence_reference": "unreviewed",
                    "rights_reviewed": False,
                },
            )
            with self.assertRaises(IntegrityError):
                manual.ingest(
                    bundle,
                    fixed_context(ArtifactStore(root / "store"), "run.manual.bad-hash"),
                    audio_path=audio,
                    source_record_path=source_record_path,
                )

    def test_manual_ingest_rejects_media_contract_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="manual")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="manual",
                provider_descriptor=manual.descriptor(),
            )
            audio = root / "short-source.wav"
            render_mock_sine_wav(
                audio,
                sample_rate_hz=48000,
                channels=2,
                duration_samples=2400,
                frequency_hz=440,
                amplitude=0.1,
                seed=3,
            )
            source_record_path = root / "source-record.json"
            write_canonical_no_replace(
                source_record_path,
                {
                    "schema": "score-manual-source/v1",
                    "source_id": "test.bad-media",
                    "audio_sha256": file_sha256(audio),
                    "supplied_by": "test.fixture",
                    "source_kind": "project_authored",
                    "intended_use": "internal_eval",
                    "rights_evidence_reference": "test-only synthetic source",
                    "rights_reviewed": False,
                },
            )
            with self.assertRaises(ContractError):
                manual.ingest(
                    bundle,
                    fixed_context(ArtifactStore(root / "store"), "run.manual.bad-media"),
                    audio_path=audio,
                    source_record_path=source_record_path,
                )

    def test_execution_id_collision_does_not_replace_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = create_demo_bundle(root / "bundle", provider_id="mock")
            bundle = load_execution_bundle(
                bundle_root,
                expected_provider_id="mock",
                provider_descriptor=mock.descriptor(),
            )
            store = ArtifactStore(root / "store")
            first_file, _ = mock.execute(
                bundle, fixed_context(store, "run.mock.collision")
            )
            original = first_file.absolute_path.read_bytes()
            with self.assertRaises(IntegrityError):
                mock.execute(bundle, fixed_context(store, "run.mock.collision"))
            self.assertEqual(first_file.absolute_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
