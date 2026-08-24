from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .bundle import load_execution_bundle
from .canonical import canonical_sha256, file_sha256, write_canonical_no_replace
from .contracts import load_contract, validate_document
from .demo import create_demo_bundle
from .errors import BoundaryError, ScoreMatterError
from .providers import manual, mock, replay
from .providers.base import ExecutionContext
from .providers.registry import descriptor_for, provider_ids
from .store import ArtifactStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="score-matter",
        description="Auditable, local-first BGM authoring evidence core.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser("validate", help="Validate a strict contract document.")
    validate_parser.add_argument("document", type=Path)
    validate_parser.set_defaults(handler=_handle_validate)

    digest_parser = commands.add_parser("digest", help="Print a validated document's JCS digest.")
    digest_parser.add_argument("document", type=Path)
    digest_parser.set_defaults(handler=_handle_digest)

    provider_parser = commands.add_parser("provider", help="Inspect built-in providers.")
    provider_commands = provider_parser.add_subparsers(dest="provider_command", required=True)
    probe_parser = provider_commands.add_parser("probe", help="Emit a provider descriptor.")
    probe_parser.add_argument("provider_id", choices=provider_ids())
    probe_parser.add_argument("--output", type=Path)
    probe_parser.set_defaults(handler=_handle_provider_probe)

    demo_parser = commands.add_parser("demo", help="Create bounded synthetic input bundles.")
    demo_commands = demo_parser.add_subparsers(dest="demo_command", required=True)
    demo_init = demo_commands.add_parser("init", help="Create a new mock/manual demo bundle.")
    demo_init.add_argument("output", type=Path)
    demo_init.add_argument("--provider", choices=("mock", "manual"), default="mock")
    demo_init.set_defaults(handler=_handle_demo_init)

    mock_parser = commands.add_parser(
        "mock", help="Run deterministic synthetic fixture generation."
    )
    mock_commands = mock_parser.add_subparsers(dest="mock_command", required=True)
    mock_execute = mock_commands.add_parser("execute", help="Execute a validated mock bundle.")
    mock_execute.add_argument("--bundle", type=Path, required=True)
    mock_execute.add_argument("--store", type=Path, default=Path(".local"))
    mock_execute.set_defaults(handler=_handle_mock_execute)

    manual_parser = commands.add_parser("manual", help="Record and ingest manually supplied WAV.")
    manual_commands = manual_parser.add_subparsers(dest="manual_command", required=True)
    source_parser = manual_commands.add_parser(
        "source-record", help="Create a non-approving source declaration bound to WAV bytes."
    )
    source_parser.add_argument("audio", type=Path)
    source_parser.add_argument("output", type=Path)
    source_parser.add_argument("--source-id", required=True)
    source_parser.add_argument("--supplied-by", required=True)
    source_parser.add_argument(
        "--source-kind",
        choices=("project_authored", "user_owned", "commissioned", "licensed", "unknown"),
        required=True,
    )
    source_parser.add_argument(
        "--intended-use", choices=("local_preview", "internal_eval"), required=True
    )
    source_parser.add_argument("--rights-evidence-reference", required=True)
    source_parser.set_defaults(handler=_handle_manual_source_record)

    ingest_parser = manual_commands.add_parser("ingest", help="Ingest a source-bound PCM WAV.")
    ingest_parser.add_argument("--bundle", type=Path, required=True)
    ingest_parser.add_argument("--audio", type=Path, required=True)
    ingest_parser.add_argument("--source-record", type=Path, required=True)
    ingest_parser.add_argument("--store", type=Path, default=Path(".local"))
    ingest_parser.set_defaults(handler=_handle_manual_ingest)

    replay_parser = commands.add_parser("replay", help="Verify frozen run evidence.")
    replay_commands = replay_parser.add_subparsers(dest="replay_command", required=True)
    replay_verify = replay_commands.add_parser(
        "verify", help="Verify artifacts and write a subject-external replay receipt."
    )
    replay_verify.add_argument("run_receipt", type=Path)
    replay_verify.add_argument("--store", type=Path, default=Path(".local"))
    replay_verify.set_defaults(handler=_handle_replay_verify)
    return parser


def _print_json(document: dict[str, Any]) -> None:
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))


def _handle_validate(args: argparse.Namespace) -> int:
    document = load_contract(args.document)
    digest = canonical_sha256(document)
    print(f"SCORE_CONTRACT_OK schema={document['schema']} sha256={digest}")
    return 0


def _handle_digest(args: argparse.Namespace) -> int:
    document = load_contract(args.document)
    print(canonical_sha256(document))
    return 0


def _handle_provider_probe(args: argparse.Namespace) -> int:
    descriptor = descriptor_for(args.provider_id)
    digest = canonical_sha256(descriptor)
    if args.output is not None:
        write_canonical_no_replace(args.output, descriptor)
    else:
        _print_json(descriptor)
    print(f"SCORE_PROVIDER_OK provider={args.provider_id} sha256={digest}")
    return 0


def _handle_demo_init(args: argparse.Namespace) -> int:
    output = create_demo_bundle(args.output, provider_id=args.provider)
    print(f"SCORE_DEMO_OK provider={args.provider} path={output}")
    return 0


def _handle_mock_execute(args: argparse.Namespace) -> int:
    descriptor = mock.descriptor()
    bundle = load_execution_bundle(
        args.bundle,
        expected_provider_id="mock",
        provider_descriptor=descriptor,
    )
    store = ArtifactStore(args.store)
    receipt_file, receipt = mock.execute(bundle, ExecutionContext(store))
    artifact = receipt["artifacts"][0]
    print(
        "SCORE_MOCK_EXECUTE_OK "
        f"receipt={receipt_file.absolute_path} receipt_sha256={receipt_file.sha256} "
        f"artifact_sha256={artifact['artifact_sha256']}"
    )
    return 0


def _handle_manual_source_record(args: argparse.Namespace) -> int:
    if args.audio.is_symlink() or not args.audio.is_file():
        raise BoundaryError(f"manual audio must be a regular non-symlink file: {args.audio}")
    document = {
        "schema": "score-manual-source/v1",
        "source_id": args.source_id,
        "audio_sha256": file_sha256(args.audio),
        "supplied_by": args.supplied_by,
        "source_kind": args.source_kind,
        "intended_use": args.intended_use,
        "rights_evidence_reference": args.rights_evidence_reference,
        "rights_reviewed": False,
    }
    validate_document(document)
    digest = write_canonical_no_replace(args.output, document)
    print(f"SCORE_MANUAL_SOURCE_OK path={args.output.resolve()} sha256={digest}")
    return 0


def _handle_manual_ingest(args: argparse.Namespace) -> int:
    descriptor = manual.descriptor()
    bundle = load_execution_bundle(
        args.bundle,
        expected_provider_id="manual",
        provider_descriptor=descriptor,
    )
    source_record = load_contract(args.source_record, expected_schema="score-manual-source/v1")
    if source_record["intended_use"] != bundle.brief["intended_use"]:
        raise BoundaryError(
            "manual source intended_use does not match the bound Brief",
            code="source_use_mismatch",
        )
    store = ArtifactStore(args.store)
    receipt_file, receipt = manual.ingest(
        bundle,
        ExecutionContext(store),
        audio_path=args.audio,
        source_record_path=args.source_record,
    )
    artifact = receipt["artifacts"][0]
    print(
        "SCORE_MANUAL_INGEST_OK "
        f"receipt={receipt_file.absolute_path} receipt_sha256={receipt_file.sha256} "
        f"artifact_sha256={artifact['artifact_sha256']} rights_reviewed=false"
    )
    return 0


def _handle_replay_verify(args: argparse.Namespace) -> int:
    store = ArtifactStore(args.store)
    receipt_file, receipt = replay.verify(args.run_receipt, ExecutionContext(store))
    print(
        "SCORE_REPLAY_OK "
        f"receipt={receipt_file.absolute_path} receipt_sha256={receipt_file.sha256} "
        f"source_run_receipt_sha256={receipt['source_run_receipt_sha256']} "
        f"artifacts={len(receipt['artifacts'])}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ScoreMatterError as exc:
        message = " ".join(str(exc).splitlines())
        print(f"SCORE_ERROR code={exc.code} message={message}", file=sys.stderr)
        return 2
