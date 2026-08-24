from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from score_matter.canonical import (
    canonical_bytes,
    canonical_sha256,
    load_json_bytes,
    publish_bytes_no_replace,
)
from score_matter.errors import ContractError, IntegrityError


class CanonicalJsonTests(unittest.TestCase):
    def test_jcs_is_order_independent(self) -> None:
        left = {"z": 1, "a": [True, None, "music"]}
        right = {"a": [True, None, "music"], "z": 1}
        self.assertEqual(canonical_bytes(left), b'{"a":[true,null,"music"],"z":1}')
        self.assertEqual(canonical_sha256(left), canonical_sha256(right))

    def test_duplicate_key_is_rejected(self) -> None:
        with self.assertRaises(ContractError) as raised:
            load_json_bytes(b'{"schema":"x","schema":"y"}')
        self.assertEqual(raised.exception.code, "duplicate_json_key")

    def test_nonfinite_number_is_rejected(self) -> None:
        with self.assertRaises(ContractError) as raised:
            load_json_bytes(b'{"value":NaN}')
        self.assertEqual(raised.exception.code, "nonfinite_json")

    def test_utf8_bom_is_rejected(self) -> None:
        with self.assertRaises(ContractError) as raised:
            load_json_bytes(b"\xef\xbb\xbf{}")
        self.assertEqual(raised.exception.code, "json_bom_forbidden")

    def test_immutable_publication_never_replaces_different_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "immutable.json"
            publish_bytes_no_replace(target, b"first")
            publish_bytes_no_replace(target, b"first")
            with self.assertRaises(IntegrityError):
                publish_bytes_no_replace(target, b"second")
            self.assertEqual(target.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
