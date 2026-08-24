from __future__ import annotations

import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from score_matter.cli import main


class CliTests(unittest.TestCase):
    def test_provider_probe_has_stable_success_sentinel(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["provider", "probe", "mock"])
        self.assertEqual(result, 0)
        self.assertIn("SCORE_PROVIDER_OK provider=mock", output.getvalue())

    def test_invalid_contract_has_stable_error_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text('{"schema":"unknown/v1"}', encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = main(["validate", str(path)])
        self.assertEqual(result, 2)
        self.assertIn("SCORE_ERROR code=unknown_schema", errors.getvalue())

    def test_mock_to_replay_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            store = root / "store"

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["demo", "init", str(bundle), "--provider", "mock"]), 0
                )
                self.assertEqual(
                    main(
                        [
                            "mock",
                            "execute",
                            "--bundle",
                            str(bundle),
                            "--store",
                            str(store),
                        ]
                    ),
                    0,
                )
            match = re.search(r"receipt=(.+?) receipt_sha256=", output.getvalue())
            self.assertIsNotNone(match)
            assert match is not None
            source_receipt = match.group(1)

            replay_output = io.StringIO()
            with redirect_stdout(replay_output):
                result = main(
                    [
                        "replay",
                        "verify",
                        source_receipt,
                        "--store",
                        str(store),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIn("SCORE_REPLAY_OK", replay_output.getvalue())


if __name__ == "__main__":
    unittest.main()
