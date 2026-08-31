from __future__ import annotations

import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from score_matter.authoring import SA3GenerationResult
from score_matter.cli import main
from score_matter.errors import DirectorError


class CliTests(unittest.TestCase):
    def test_generate_cli_is_one_candidate_with_no_automatic_retry(self) -> None:
        candidate = Path("C:/local/score-matter/candidate.wav")
        generation = SA3GenerationResult(
            path=candidate,
            record_path=candidate.with_suffix(".generation.json"),
            record_warning=None,
            seed=2719,
            seconds=20,
            wall_seconds=53.25,
            media={
                "codec": "pcm_s16le",
                "sample_rate_hz": 44100,
                "channels": 2,
                "frame_count": 882000,
            },
            sha256="sha256:" + "a" * 64,
        )
        output = io.StringIO()
        with (
            patch(
                "score_matter.cli.generate_sa3_wav", return_value=generation
            ) as generate_mock,
            redirect_stdout(output),
        ):
            result = main(
                [
                    "generate",
                    "--prompt",
                    "Quiet star-map BGM",
                    "--seed",
                    "2719",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn(
            "SCORE_GENERATE_START candidates=1 automatic_retries=0 seconds=20",
            output.getvalue(),
        )
        self.assertIn(f"SCORE_GENERATE_OK path={candidate}", output.getvalue())
        self.assertIn("attempts=1 automatic_retries=0", output.getvalue())
        generate_mock.assert_called_once()
        settings = generate_mock.call_args.kwargs["settings"]
        self.assertEqual(settings.seed, 2719)
        self.assertEqual(settings.steps, 8)
        self.assertEqual(settings.threads, 8)
        self.assertEqual(settings.cfg, 1.0)

    def test_director_kernel_digest_has_stable_no_call_sentinel(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["director", "kernel-digest"])
        self.assertEqual(result, 0)
        self.assertIn("SCORE_DIRECTOR_KERNEL_OK sha256=sha256:", output.getvalue())
        self.assertIn("model_calls=0", output.getvalue())

    _PHASE_A_SCENARIOS = (
        "p01",
        "p02",
        "p03",
        "p04",
        "p05",
        "p06",
        "p07",
        "p08",
        "m01",
        "m02",
        "x01",
        "x02",
        "s01",
        "s02",
    )

    @staticmethod
    def _director_phase_a_argv(
        command: str, root: Path, *, output: Path | None = None, resume: bool = False
    ) -> list[str]:
        arguments = [
            "director",
            "phase-a",
            command,
            "--spec",
            str(root / "spec.md"),
            "--plan",
            str(root / "plan.json"),
            "--authorization",
            str(root / "authorization.json"),
            "--provider-descriptor",
            str(root / "provider.json"),
            "--command-descriptor",
            str(root / "command.json"),
            "--inventory-root",
            str(root / "inventory"),
        ]
        if output is not None:
            arguments.extend(["--output", str(output)])
        if resume:
            arguments.append("--resume")
        return arguments

    def _director_phase_a_documents(
        self, root: Path
    ) -> tuple[
        dict[Path, dict[str, object]],
        dict[str, dict[str, object]],
        dict[str, dict[str, object]],
    ]:
        plan: dict[str, object] = {
            "evaluation_plan_id": "phase-a-cli-test",
            "evidence_root": str((root / "evidence").resolve()),
            "execution_claim_path": str((root / "claims" / "phase-a.json").resolve()),
            "run_inventory": [
                {"run_id": f"run-{index:02d}"} for index in range(16)
            ],
        }
        documents = {
            root / "plan.json": plan,
            root / "authorization.json": {"decision": "allow"},
            root / "provider.json": {"provider_id": "fixture-provider"},
            root / "command.json": {"backend_id": "local_jsonl_command"},
        }
        contexts = {scenario_id: {} for scenario_id in self._PHASE_A_SCENARIOS}
        adjudications = {scenario_id: {} for scenario_id in self._PHASE_A_SCENARIOS}
        return documents, contexts, adjudications

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

    def test_director_phase_a_preflight_loads_and_verifies_frozen_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents, contexts, adjudications = self._director_phase_a_documents(root)

            def fake_load(path: Path, *, expected_schema: str | None = None):
                del expected_schema
                return documents[Path(path)]

            output = io.StringIO()
            with (
                patch("score_matter.cli.load_contract", side_effect=fake_load) as load_mock,
                patch(
                    "score_matter.cli.load_phase_a_inventory",
                    return_value=(contexts, adjudications),
                ) as inventory_mock,
                patch("score_matter.cli.verify_command_descriptor") as command_mock,
                patch("score_matter.cli.verify_phase_a_preflight") as preflight_mock,
                patch("score_matter.cli.command_backend_from_descriptor") as backend_mock,
                redirect_stdout(output),
            ):
                result = main(self._director_phase_a_argv("preflight", root))

        self.assertEqual(result, 0)
        self.assertIn("SCORE_DIRECTOR_PHASE_A_PREFLIGHT_OK", output.getvalue())
        self.assertIn("fixtures=14 runs=16 model_calls=0", output.getvalue())
        self.assertEqual(
            load_mock.call_args_list,
            [
                call(
                    root / "plan.json",
                    expected_schema="score-director-evaluation-plan/v1",
                ),
                call(
                    root / "authorization.json",
                    expected_schema="score-director-phase-authorization/v1",
                ),
                call(
                    root / "provider.json",
                    expected_schema="score-provider-descriptor/v1",
                ),
                call(
                    root / "command.json",
                    expected_schema="score-director-command-descriptor/v1",
                ),
            ],
        )
        inventory_mock.assert_called_once_with(root / "inventory")
        command_mock.assert_called_once_with(
            evaluation_plan=documents[root / "plan.json"],
            command_descriptor=documents[root / "command.json"],
        )
        preflight_mock.assert_called_once_with(
            spec_path=root / "spec.md",
            evaluation_plan=documents[root / "plan.json"],
            phase_authorization=documents[root / "authorization.json"],
            provider_descriptor=documents[root / "provider.json"],
            contexts=contexts,
            adjudications=adjudications,
            backend_id="local_jsonl_command",
        )
        backend_mock.assert_not_called()

    def test_director_phase_a_run_preflights_then_uses_frozen_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root = root / "evidence"
            documents, contexts, adjudications = self._director_phase_a_documents(root)

            def fake_load(path: Path, *, expected_schema: str | None = None):
                del expected_schema
                return documents[Path(path)]

            backend = SimpleNamespace(backend_id="local_jsonl_command")
            report_file = SimpleNamespace(
                path=evidence_root / "phase-a-report.json",
                sha256="sha256:" + "a" * 64,
            )
            output = io.StringIO()
            with (
                patch("score_matter.cli.load_contract", side_effect=fake_load),
                patch(
                    "score_matter.cli.load_phase_a_inventory",
                    return_value=(contexts, adjudications),
                ),
                patch("score_matter.cli.verify_command_descriptor"),
                patch("score_matter.cli.verify_phase_a_preflight") as preflight_mock,
                patch(
                    "score_matter.cli.command_backend_from_descriptor",
                    return_value=backend,
                ) as backend_mock,
                patch(
                    "score_matter.cli.run_phase_a_inventory",
                    return_value=([object()] * 16, {"conclusion": "planning_blocked"}, report_file),
                ) as run_mock,
                redirect_stdout(output),
            ):
                result = main(
                    self._director_phase_a_argv(
                        "run", root, output=evidence_root
                    )
                )

        self.assertEqual(result, 0)
        self.assertIn(
            "SCORE_DIRECTOR_PHASE_A_RECORDED conclusion=planning_blocked",
            output.getvalue(),
        )
        self.assertIn("runs=16", output.getvalue())
        preflight_mock.assert_called_once()
        backend_mock.assert_called_once_with(
            evaluation_plan=documents[root / "plan.json"],
            command_descriptor=documents[root / "command.json"],
        )
        run_mock.assert_called_once()
        run_arguments = run_mock.call_args.kwargs
        self.assertIs(run_arguments["evaluation_plan"], documents[root / "plan.json"])
        self.assertIs(
            run_arguments["phase_authorization"], documents[root / "authorization.json"]
        )
        self.assertIs(
            run_arguments["provider_descriptor"], documents[root / "provider.json"]
        )
        self.assertIs(run_arguments["backend"], backend)
        self.assertIs(
            run_arguments["command_descriptor"], documents[root / "command.json"]
        )
        self.assertFalse(run_arguments["resume"])

    def test_director_phase_a_run_fails_before_creating_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root = root / "evidence"
            documents, contexts, adjudications = self._director_phase_a_documents(root)

            def fake_load(path: Path, *, expected_schema: str | None = None):
                del expected_schema
                return documents[Path(path)]

            errors = io.StringIO()
            with (
                patch("score_matter.cli.load_contract", side_effect=fake_load),
                patch(
                    "score_matter.cli.load_phase_a_inventory",
                    return_value=(contexts, adjudications),
                ),
                patch("score_matter.cli.verify_command_descriptor"),
                patch(
                    "score_matter.cli.verify_phase_a_preflight",
                    side_effect=DirectorError(
                        "Phase A execution is not authorized",
                        code="director_phase_not_authorized",
                    ),
                ),
                patch("score_matter.cli.command_backend_from_descriptor") as backend_mock,
                patch("score_matter.cli.run_phase_a_inventory") as run_mock,
                redirect_stderr(errors),
            ):
                result = main(
                    self._director_phase_a_argv(
                        "run", root, output=evidence_root
                    )
                )

            self.assertFalse(evidence_root.exists())

        self.assertEqual(result, 2)
        self.assertIn(
            "SCORE_ERROR code=director_phase_not_authorized", errors.getvalue()
        )
        backend_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_director_phase_a_rejects_runtime_identity_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            base = self._director_phase_a_argv("run", root, output=output)
            for option in ("--backend", "--model", "--policy", "--settings"):
                errors = io.StringIO()
                with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                    main([*base, option, "unfrozen-override"])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("unrecognized arguments", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
