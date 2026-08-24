from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from score_matter.errors import BoundaryError
from score_matter.paths import resolve_inside, validate_relative_path


class SafePathTests(unittest.TestCase):
    def test_normal_store_path_is_accepted(self) -> None:
        self.assertEqual(
            validate_relative_path("artifacts/sha256/ab/payload.wav").as_posix(),
            "artifacts/sha256/ab/payload.wav",
        )

    def test_traversal_and_windows_forms_are_rejected(self) -> None:
        for value in (
            "../secret",
            "a/../secret",
            "/absolute",
            "C:/secret",
            "a\\secret",
            "con/file",
        ):
            with self.subTest(value=value), self.assertRaises(BoundaryError):
                validate_relative_path(value)

    def test_store_symlink_ancestor_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "store"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            link = root / "artifacts"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable on this platform")
            with self.assertRaises(BoundaryError):
                resolve_inside(root, "artifacts/payload.wav")


if __name__ == "__main__":
    unittest.main()
