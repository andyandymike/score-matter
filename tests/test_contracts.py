from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from score_matter.bundle import load_execution_bundle
from score_matter.canonical import canonical_bytes
from score_matter.contracts import SCHEMA_FILES, load_contract, schema_document, validate_document
from score_matter.demo import create_demo_bundle
from score_matter.errors import ContractError
from score_matter.providers import mock


class ContractTests(unittest.TestCase):
    def test_every_packaged_schema_is_well_formed(self) -> None:
        for schema_id in SCHEMA_FILES:
            with self.subTest(schema_id=schema_id):
                self.assertIsInstance(schema_document(schema_id), dict)

    def test_unknown_field_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = create_demo_bundle(Path(temporary) / "bundle", provider_id="mock")
            brief = load_contract(root / "brief.json")
            brief["surprise"] = True
            with self.assertRaises(ContractError):
                validate_document(brief)

    def test_required_unsupported_control_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = create_demo_bundle(Path(temporary) / "bundle", provider_id="mock")
            request = load_contract(root / "resolved-request.json")
            request["controls"][0]["enforcement"] = "required"
            with self.assertRaises(ContractError) as raised:
                validate_document(request)
            self.assertEqual(raised.exception.code, "required_control_unsupported")

    def test_stale_hash_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = create_demo_bundle(Path(temporary) / "bundle", provider_id="mock")
            brief = copy.deepcopy(load_contract(root / "brief.json"))
            brief["music"]["mood"] = ["tense"]
            (root / "brief.json").write_bytes(canonical_bytes(brief))
            with self.assertRaisesRegex(ContractError, "stale binding"):
                load_execution_bundle(
                    root,
                    expected_provider_id="mock",
                    provider_descriptor=mock.descriptor(),
                )

    def test_provider_options_must_match_builtin_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = create_demo_bundle(Path(temporary) / "bundle", provider_id="mock")
            request = load_contract(root / "resolved-request.json")
            request["provider_options"] = {"schema": "score-provider-options/manual/v1"}
            (root / "resolved-request.json").write_bytes(canonical_bytes(request))
            with self.assertRaisesRegex(ContractError, "provider_options.schema"):
                load_execution_bundle(
                    root,
                    expected_provider_id="mock",
                    provider_descriptor=mock.descriptor(),
                )


if __name__ == "__main__":
    unittest.main()
