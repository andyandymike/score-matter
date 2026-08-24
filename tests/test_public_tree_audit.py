from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath

from tools.audit_public_tree import audit_paths


class PublicTreeAuditTests(unittest.TestCase):
    def _audit_one(self, logical: str, data: bytes = b"fixture") -> list[str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        target = repo.joinpath(*PurePosixPath(logical).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return audit_paths(repo, [PurePosixPath(logical)])

    def test_private_spec_is_rejected_even_if_force_added(self) -> None:
        problems = self._audit_one("spec/private.md")
        self.assertTrue(any("private/generated" in problem for problem in problems))

    def test_model_weight_is_rejected_anywhere(self) -> None:
        problems = self._audit_one("tests/fixture.safetensors")
        self.assertTrue(any("model/weight" in problem for problem in problems))

    def test_private_key_marker_is_rejected(self) -> None:
        problems = self._audit_one(
            "docs/example.txt", b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----\nnot-a-key"
        )
        self.assertTrue(any("private-key marker" in problem for problem in problems))

    def test_secret_suffix_is_rejected_even_without_a_marker(self) -> None:
        problems = self._audit_one("docs/example.pem", b"redacted")
        self.assertTrue(any("secret-bearing file suffix" in problem for problem in problems))

    def test_regular_source_file_is_accepted(self) -> None:
        self.assertEqual(self._audit_one("src/score_matter/example.py", b"VALUE = 1\n"), [])

    def test_audio_outside_fixture_lane_is_rejected(self) -> None:
        problems = self._audit_one("docs/demo.wav", b"RIFF")
        self.assertTrue(any("audio must stay local" in problem for problem in problems))

    def test_audio_fixture_requires_rights_record(self) -> None:
        problems = self._audit_one("tests/fixtures/audio/tiny.wav", b"RIFF")
        self.assertTrue(any("rights record" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
