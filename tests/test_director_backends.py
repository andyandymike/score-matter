from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from score_matter.canonical import canonical_bytes, file_sha256
from score_matter.director.backends import (
    DirectorBackendFailure,
    DirectorCompletion,
    JsonlCommandDirectorBackend,
    ScriptedDirectorBackend,
    directory_manifest_sha256,
)
from score_matter.director.evidence import DirectorEvidenceStore
from score_matter.director.guards import PhaseAServices
from score_matter.errors import BoundaryError, DirectorError, IntegrityError


def _completion(response: dict[str, object] | None = None) -> DirectorCompletion:
    return DirectorCompletion(
        raw_exchange=b'{"fixture":true}',
        agent_response=response or {"terminal_state": "abstain"},
        input_tokens=12,
        output_tokens=7,
        elapsed_ms=3,
        external_cost_microusd=0,
        model_id="test.scripted",
        model_revision="fixture-v1",
    )


def _exchange() -> dict[str, object]:
    return {
        "protocol": "score-director-jsonl/v1",
        "model_id": "test.local-model",
        "model_revision": "fixture-revision",
        "usage": {
            "input_tokens": 31,
            "output_tokens": 17,
            "external_cost_microusd": 0,
        },
        "observed_tool_calls": [],
        "response": {"terminal_state": "abstain", "reason": "fixture"},
    }


class DirectorEvidenceTests(unittest.TestCase):
    def test_evidence_publication_is_canonical_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = DirectorEvidenceStore(Path(temporary) / "evidence")
            document = {"z": 2, "a": {"value": 1}}

            first = store.publish_json("run.fixture-01", "trace", document)
            repeated = store.publish_json(
                "run.fixture-01", "trace", {"a": {"value": 1}, "z": 2}
            )

            self.assertEqual(first.path, repeated.path)
            self.assertEqual(first.sha256, repeated.sha256)
            self.assertEqual(first.byte_count, repeated.byte_count)
            self.assertEqual(first.path.read_bytes(), canonical_bytes(document))

            with self.assertRaises(IntegrityError):
                store.publish_json(
                    "run.fixture-01", "trace", {"a": {"value": 1}, "z": 3}
                )
            self.assertEqual(first.path.read_bytes(), canonical_bytes(document))


class ScriptedDirectorBackendTests(unittest.TestCase):
    def test_scripted_backend_is_behaviorally_identified_as_a_fixture(self) -> None:
        expected = _completion()
        backend = ScriptedDirectorBackend(expected)

        observed = backend.complete(
            b'{"context":"fixture"}',
            services=PhaseAServices(),
            timeout_seconds=10,
        )

        self.assertEqual(backend.backend_id, "scripted_fixture")
        self.assertNotEqual(backend.backend_id, JsonlCommandDirectorBackend.backend_id)
        self.assertEqual(backend.call_count, 1)
        self.assertIs(observed, expected)

    def test_malicious_backend_calls_are_recorded_and_each_service_blocks(self) -> None:
        services = PhaseAServices()
        observed_codes: list[str] = []

        def malicious(
            request: bytes, visible_services: PhaseAServices, timeout_seconds: int
        ) -> DirectorCompletion:
            del request, timeout_seconds
            attempts = (
                (visible_services.generator, "generate"),
                (visible_services.critic, "rank"),
                (visible_services.reference_audio_reader, "read"),
            )
            for service, method in attempts:
                try:
                    service.invoke(method, "candidate", requested_by="malicious-fixture")
                except DirectorError as exc:
                    observed_codes.append(exc.code)
                else:  # pragma: no cover - the spy must always stop the call
                    raise AssertionError(f"forbidden service did not block: {method}")
            raise DirectorError(
                "malicious fixture attempted forbidden Phase A services",
                code="malicious_backend_blocked",
            )

        backend = ScriptedDirectorBackend(malicious)
        with self.assertRaises(DirectorError) as raised:
            backend.complete(b"{}", services=services, timeout_seconds=10)

        self.assertEqual(raised.exception.code, "malicious_backend_blocked")
        self.assertEqual(observed_codes, ["forbidden_phase_a_call"] * 3)
        self.assertEqual(
            services.counters(),
            {
                "generator_calls": 1,
                "critic_calls": 1,
                "reference_audio_reader_calls": 1,
            },
        )
        call_evidence = services.call_evidence()
        self.assertEqual(
            [item["service"] for item in call_evidence],
            ["generator", "critic", "reference_audio_reader"],
        )
        self.assertTrue(
            all(item["arguments_sha256"].startswith("sha256:") for item in call_evidence)
        )


class JsonlCommandDirectorBackendTests(unittest.TestCase):
    def _python_executable(self) -> Path:
        executable = Path(sys.executable).resolve()
        self.assertTrue(executable.is_file())
        self.assertFalse(executable.is_symlink())
        return executable

    def test_process_observed_jsonl_exchange_uses_sanitized_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "fixture_wrapper.py"
            wrapper.write_text(
                "\n".join(
                    [
                        "import json",
                        "import os",
                        "import sys",
                        "request = json.loads(sys.stdin.read())",
                        "secret_markers = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')",
                        "assert not any(any(marker in name.upper() for marker in secret_markers) for name in os.environ)",
                        "exchange = {",
                        "    'protocol': 'score-director-jsonl/v1',",
                        "    'model_id': 'test.local-wrapper',",
                        "    'model_revision': 'fixture-v1',",
                        "    'usage': {'input_tokens': 4, 'output_tokens': 3, 'external_cost_microusd': 0},",
                        "    'observed_tool_calls': [],",
                        "    'response': {'echo': request, 'terminal_state': 'abstain'},",
                        "}",
                        "sys.stdout.write(json.dumps(exchange, separators=(',', ':')) + '\\n')",
                    ]
                ),
                encoding="utf-8",
            )
            executable = self._python_executable()
            backend = JsonlCommandDirectorBackend(
                executable=executable,
                executable_sha256=file_sha256(executable),
                arguments=(str(wrapper),),
                environment={"HF_HUB_OFFLINE": "1"},
                working_directory=root,
            )

            completion = backend.complete(
                canonical_bytes({"context": "offline-fixture"}),
                services=PhaseAServices(),
                timeout_seconds=10,
            )

        self.assertEqual(completion.model_id, "test.local-wrapper")
        self.assertEqual(completion.model_revision, "fixture-v1")
        self.assertEqual(completion.agent_response["echo"], {"context": "offline-fixture"})
        self.assertEqual(completion.observed_tool_calls, ())
        self.assertEqual(completion.external_cost_microusd, 0)

    def test_exchange_requires_an_exact_closed_field_inventory(self) -> None:
        for mutation in ("extra", "missing"):
            with self.subTest(mutation=mutation):
                exchange = _exchange()
                if mutation == "extra":
                    exchange["unexpected"] = True
                else:
                    del exchange["response"]
                with self.assertRaises(DirectorError) as raised:
                    JsonlCommandDirectorBackend._parse_exchange(
                        canonical_bytes(exchange), elapsed_ms=1
                    )
                self.assertEqual(raised.exception.code, "director_protocol_invalid")

    def test_exchange_rejects_every_reported_tool_call(self) -> None:
        exchange = _exchange()
        exchange["observed_tool_calls"] = ["generator.generate"]

        with self.assertRaises(DirectorError) as raised:
            JsonlCommandDirectorBackend._parse_exchange(
                canonical_bytes(exchange), elapsed_ms=1
            )

        self.assertEqual(raised.exception.code, "director_tool_call_forbidden")

    def test_exchange_usage_is_closed_and_uses_non_negative_integers(self) -> None:
        invalid_usage_values = (-1, True, "1", 1.5)
        for value in invalid_usage_values:
            with self.subTest(value=value):
                exchange = _exchange()
                usage = copy.deepcopy(exchange["usage"])
                assert isinstance(usage, dict)
                usage["input_tokens"] = value
                exchange["usage"] = usage
                with self.assertRaises(DirectorError) as raised:
                    JsonlCommandDirectorBackend._parse_exchange(
                        canonical_bytes(exchange), elapsed_ms=1
                    )
                self.assertEqual(raised.exception.code, "director_protocol_invalid")

        exchange = _exchange()
        usage = copy.deepcopy(exchange["usage"])
        assert isinstance(usage, dict)
        usage["cached_tokens"] = 2
        exchange["usage"] = usage
        with self.assertRaises(DirectorError) as raised:
            JsonlCommandDirectorBackend._parse_exchange(
                canonical_bytes(exchange), elapsed_ms=1
            )
        self.assertEqual(raised.exception.code, "director_protocol_invalid")

    def test_executable_digest_mismatch_is_rejected_before_invocation(self) -> None:
        executable = self._python_executable()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(DirectorError) as raised:
                JsonlCommandDirectorBackend(
                    executable=executable,
                    executable_sha256="sha256:" + "0" * 64,
                    working_directory=temporary,
                )
        self.assertEqual(raised.exception.code, "director_component_mismatch")

    def test_secret_environment_names_are_rejected(self) -> None:
        executable = self._python_executable()
        for name in ("OPENAI_API_KEY", "HF_TOKEN", "MODEL_PASSWORD"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(BoundaryError):
                    JsonlCommandDirectorBackend(
                        executable=executable,
                        executable_sha256=file_sha256(executable),
                        environment={name: "must-not-cross-boundary"},
                        working_directory=temporary,
                    )

    def test_oversize_stdout_retains_only_exact_digest_and_byte_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "oversize_wrapper.py"
            wrapper.write_text(
                "import sys\nsys.stdin.buffer.read()\nsys.stdout.buffer.write(b'x' * 4096)\n",
                encoding="utf-8",
            )
            executable = self._python_executable()
            backend = JsonlCommandDirectorBackend(
                executable=executable,
                executable_sha256=file_sha256(executable),
                arguments=(str(wrapper),),
                working_directory=root,
                max_output_bytes=128,
            )

            with self.assertRaises(DirectorBackendFailure) as raised:
                backend.complete(
                    canonical_bytes({"context": "oversize-fixture"}),
                    services=PhaseAServices(),
                    timeout_seconds=10,
                )

        self.assertEqual(raised.exception.code, "director_output_too_large")
        retained = json.loads(raised.exception.raw_output)
        self.assertEqual(
            retained,
            {
                "protocol": "score-director-oversize-response/v1",
                "observed_sha256": "sha256:"
                + hashlib.sha256(b"x" * 4096).hexdigest(),
                "observed_byte_count": 4096,
                "retention": "digest_only_output_exceeded_frozen_ceiling",
            },
        )

    def test_bound_runtime_drift_is_rechecked_before_every_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "wrapper.py"
            model = root / "model.bin"
            wrapper.write_text("print('{}')\n", encoding="utf-8")
            model.write_bytes(b"frozen-model")
            executable = self._python_executable()
            backend = JsonlCommandDirectorBackend(
                executable=executable,
                executable_sha256=file_sha256(executable),
                arguments=(str(wrapper),),
                working_directory=root,
                component_sha256="sha256:" + "1" * 64,
                bound_artifacts={
                    str(wrapper): file_sha256(wrapper),
                    str(model): file_sha256(model),
                },
                working_directory_manifest_sha256=directory_manifest_sha256(root),
            )
            model.write_bytes(b"drifted-model")

            with self.assertRaises(DirectorError) as raised:
                backend.complete(
                    b"{}", services=PhaseAServices(), timeout_seconds=10
                )

        self.assertEqual(raised.exception.code, "director_component_mismatch")


if __name__ == "__main__":
    unittest.main()
