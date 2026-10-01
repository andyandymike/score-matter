"""Proposed product regression tests: fake backend only, no model execution."""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from score_matter.authoring import SA3GenerationResult, SA3GenerationSettings, generate_sa3_wav
from score_matter.cli import main


class GenerationRecordRootTests(unittest.TestCase):
    @staticmethod
    def _runtime(root: Path) -> Path:
        for name in (
            '.venv/Scripts/python.exe', 'scripts/sa3_tflite.py', 'models/tokenizer.model',
            'models/tflite/sa3-m/dit_fp32.tflite', 'models/tflite/same-l/dec_fp32.tflite',
            'models/tflite/t5gemma/encoder_fp16.tflite',
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        return root

    @staticmethod
    def _fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        destination = Path(command[command.index('--out') + 1])
        seconds = int(command[command.index('--seconds') + 1])
        # Structural test fixture only, never a backend or listening candidate.
        with wave.open(str(destination), 'wb') as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(44100)
            writer.writeframes(b'\0' * (seconds * 44100 * 4))
        return subprocess.CompletedProcess(command, 0)

    def test_explicit_record_root_isolates_prompt_record_with_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            consumer = root / 'consumer'
            score_default = root / 'score-local'
            records = consumer / 'records'
            runtime = self._runtime(root / 'runtime')
            with (
                patch('score_matter.authoring.DEFAULT_OUTPUT_ROOT', score_default),
                patch('score_matter.authoring.subprocess.run', side_effect=self._fake_run) as backend,
            ):
                result = generate_sa3_wav('Neutral museum ambient.',
                    settings=SA3GenerationSettings(seconds=1, seed=2719),
                    output=consumer / 'candidate.wav', record_root=records, runtime_root=runtime)
            backend.assert_called_once()
            self.assertEqual(result.path, (consumer / 'candidate.wav').resolve())
            self.assertIsNone(result.record_warning)
            self.assertIsNotNone(result.record_path)
            assert result.record_path is not None
            self.assertEqual(result.record_path.parent, records.resolve())
            self.assertFalse(score_default.exists())
            record = json.loads(result.record_path.read_text(encoding='utf-8'))
            self.assertEqual(record['prompt'], 'Neutral museum ambient.')
            self.assertEqual(record['attempt_count'], 1)
            self.assertEqual(record['automatic_retries'], 0)

    def test_omitted_record_root_preserves_default_even_with_custom_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            score_default = root / 'score-local'
            consumer = root / 'consumer'
            runtime = self._runtime(root / 'runtime')
            with (
                patch('score_matter.authoring.DEFAULT_OUTPUT_ROOT', score_default),
                patch('score_matter.authoring.subprocess.run', side_effect=self._fake_run) as backend,
            ):
                result = generate_sa3_wav('Neutral museum ambient.',
                    settings=SA3GenerationSettings(seconds=1, seed=2719),
                    output_root=consumer, runtime_root=runtime)
            backend.assert_called_once()
            self.assertTrue(result.path.is_relative_to(consumer.resolve()))
            assert result.record_path is not None
            self.assertEqual(result.record_path.parent, score_default / 'records')
            self.assertFalse((consumer / 'records').exists())

    def test_unwritable_record_root_keeps_candidate_and_does_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records_file = root / 'not-a-directory'
            records_file.write_text('existing file', encoding='utf-8')
            runtime = self._runtime(root / 'runtime')
            with patch('score_matter.authoring.subprocess.run', side_effect=self._fake_run) as backend:
                result = generate_sa3_wav('Neutral museum ambient.',
                    settings=SA3GenerationSettings(seconds=1, seed=2719),
                    output=root / 'candidate.wav', record_root=records_file, runtime_root=runtime)
            backend.assert_called_once()
            self.assertTrue(result.path.is_file())
            self.assertIsNone(result.record_path)
            self.assertIsNotNone(result.record_warning)
            self.assertEqual(records_file.read_text(encoding='utf-8'), 'existing file')

    def test_cli_forwards_explicit_and_omitted_record_root(self) -> None:
        result = SA3GenerationResult(path=Path('candidate.wav'), record_path=None,
            record_warning=None, seed=2719, seconds=1, wall_seconds=0,
            media={}, sha256='sha256:' + 'a' * 64)
        for option, expected in (([], None), (['--record-root', 'consumer/records'], Path('consumer/records'))):
            with (
                self.subTest(option=option),
                patch('score_matter.cli.generate_sa3_wav', return_value=result) as backend,
                redirect_stdout(io.StringIO()),
            ):
                code = main(['generate', '--prompt', 'Neutral museum ambient.', '--seconds', '1', *option])
            self.assertEqual(code, 0)
            backend.assert_called_once()
            self.assertEqual(backend.call_args.kwargs['record_root'], expected)


if __name__ == '__main__':
    unittest.main()
