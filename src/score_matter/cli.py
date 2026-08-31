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
from .director.evidence import DirectorEvidenceStore
from .director.host import (
    HOST_RESPONSE_CAPTURE_MAX_BYTES,
    build_host_agent_request,
    build_host_agent_submission,
    ingest_host_agent_submission,
    validate_host_agent_request,
)
from .director.kernel import director_kernel_manifest, director_kernel_sha256
from .director.phase_a import (
    command_backend_from_descriptor,
    load_phase_a_inventory,
    run_phase_a_inventory,
    verify_command_descriptor,
    verify_phase_a_preflight,
)
from .errors import BoundaryError, ScoreMatterError
from .providers import manual, mock, replay
from .providers.base import ExecutionContext
from .providers.registry import descriptor_for, provider_ids
from .store import ArtifactStore


HOST_SUBMISSION_READ_MAX_BYTES = 16 * 1024 * 1024


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="score-matter",
        description="Auditable, model-agnostic BGM authoring evidence core.",
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

    director_parser = commands.add_parser(
        "director", help="Run bounded, non-provider music-director experiments."
    )
    director_commands = director_parser.add_subparsers(
        dest="director_command", required=True
    )
    director_kernel = director_commands.add_parser(
        "kernel-digest",
        help="Print the runtime-recomputed Director kernel identity without a model call.",
    )
    director_kernel.set_defaults(handler=_handle_director_kernel_digest)
    host_parser = director_commands.add_parser(
        "host", help="Export or ingest model-agnostic host-agent planning packets."
    )
    host_commands = host_parser.add_subparsers(
        dest="director_host_command", required=True
    )
    host_request = host_commands.add_parser(
        "request",
        help="Write the exact packet to submit to the current host agent.",
    )
    host_request.add_argument("--run-id", required=True)
    host_request.add_argument("--context", type=Path, required=True)
    host_request.add_argument("--provider-descriptor", type=Path, required=True)
    host_request.add_argument("--evidence-root", type=Path, required=True)
    host_request.add_argument("--claim-path", type=Path, required=True)
    host_request.add_argument("--output", type=Path, required=True)
    host_request.set_defaults(handler=_handle_director_host_request)

    host_capture = host_commands.add_parser(
        "capture",
        help="Wrap one bare host-agent response without inventing unavailable observations.",
    )
    host_capture.add_argument("--request", type=Path, required=True)
    host_capture.add_argument("--response", type=Path, required=True)
    host_capture.add_argument("--submission-id", required=True)
    host_capture.add_argument("--host-product", required=True)
    host_capture.add_argument("--output", type=Path, required=True)
    host_capture.set_defaults(handler=_handle_director_host_capture)

    host_ingest = host_commands.add_parser(
        "ingest",
        help="Retain and validate one existing host-agent submission without a model call.",
    )
    host_ingest.add_argument("--request", type=Path, required=True)
    host_ingest.add_argument("--submission", type=Path, required=True)
    host_ingest.add_argument("--adjudication", type=Path)
    host_ingest.add_argument("--output", type=Path, required=True)
    host_ingest.set_defaults(handler=_handle_director_host_ingest)
    phase_a_parser = director_commands.add_parser(
        "phase-a", help="Preflight or run the frozen Director Phase A inventory."
    )
    phase_a_commands = phase_a_parser.add_subparsers(
        dest="director_phase_a_command", required=True
    )
    phase_a_preflight = phase_a_commands.add_parser(
        "preflight", help="Verify the complete frozen Phase A inventory without a model call."
    )
    _add_director_phase_a_inputs(phase_a_preflight)
    phase_a_preflight.set_defaults(handler=_handle_director_phase_a_preflight)

    phase_a_run = phase_a_commands.add_parser(
        "run", help="Execute or resume the exact frozen Phase A run inventory."
    )
    _add_director_phase_a_inputs(phase_a_run)
    phase_a_run.add_argument("--output", type=Path, required=True)
    phase_a_run.add_argument(
        "--resume",
        action="store_true",
        help="Reuse only complete, digest-matching run evidence in the output directory.",
    )
    phase_a_run.set_defaults(handler=_handle_director_phase_a_run)
    return parser


def _add_director_phase_a_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--provider-descriptor", type=Path, required=True)
    parser.add_argument("--command-descriptor", type=Path, required=True)
    parser.add_argument("--inventory-root", type=Path, required=True)


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


def _load_and_verify_director_phase_a(
    args: argparse.Namespace,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    evaluation_plan = load_contract(
        args.plan, expected_schema="score-director-evaluation-plan/v1"
    )
    phase_authorization = load_contract(
        args.authorization,
        expected_schema="score-director-phase-authorization/v1",
    )
    provider_descriptor = load_contract(
        args.provider_descriptor, expected_schema="score-provider-descriptor/v1"
    )
    command_descriptor = load_contract(
        args.command_descriptor,
        expected_schema="score-director-command-descriptor/v1",
    )
    contexts, adjudications = load_phase_a_inventory(args.inventory_root)
    verify_command_descriptor(
        evaluation_plan=evaluation_plan,
        command_descriptor=command_descriptor,
    )
    verify_phase_a_preflight(
        spec_path=args.spec,
        evaluation_plan=evaluation_plan,
        phase_authorization=phase_authorization,
        provider_descriptor=provider_descriptor,
        contexts=contexts,
        adjudications=adjudications,
        backend_id=command_descriptor["backend_id"],
    )
    return (
        evaluation_plan,
        phase_authorization,
        provider_descriptor,
        command_descriptor,
        contexts,
        adjudications,
    )


def _handle_director_phase_a_preflight(args: argparse.Namespace) -> int:
    (
        evaluation_plan,
        phase_authorization,
        _provider_descriptor,
        _command_descriptor,
        contexts,
        _adjudications,
    ) = _load_and_verify_director_phase_a(args)
    print(
        "SCORE_DIRECTOR_PHASE_A_PREFLIGHT_OK "
        f"evaluation_plan={evaluation_plan['evaluation_plan_id']} "
        f"plan_sha256={canonical_sha256(evaluation_plan)} "
        f"authorization_sha256={canonical_sha256(phase_authorization)} "
        f"fixtures={len(contexts)} runs={len(evaluation_plan['run_inventory'])} "
        "model_calls=0 assurance=process_observed pass_eligible=false"
    )
    return 0


def _handle_director_kernel_digest(args: argparse.Namespace) -> int:
    del args
    manifest = director_kernel_manifest()
    print(
        "SCORE_DIRECTOR_KERNEL_OK "
        f"sha256={director_kernel_sha256()} files={len(manifest['files'])} model_calls=0"
    )
    return 0


def _handle_director_host_request(args: argparse.Namespace) -> int:
    context = load_contract(
        args.context, expected_schema="score-director-context/v1"
    )
    provider_descriptor = load_contract(
        args.provider_descriptor, expected_schema="score-provider-descriptor/v1"
    )
    request = build_host_agent_request(
        run_id=args.run_id,
        context=context,
        provider_descriptor=provider_descriptor,
        evidence_root=args.evidence_root,
        ingest_claim_path=args.claim_path,
    )
    request_output = args.output.resolve(strict=False)
    frozen_evidence_root = Path(request["evidence_root"])
    frozen_claim_path = Path(request["ingest_claim_path"])
    if frozen_evidence_root.exists() or frozen_evidence_root.is_symlink():
        raise BoundaryError(
            "host request requires a fresh, nonexistent evidence_root",
            code="destination_exists",
        )
    if frozen_claim_path.exists() or frozen_claim_path.is_symlink():
        raise BoundaryError(
            "host request requires a fresh, nonexistent ingest claim path",
            code="director_host_ingest_already_claimed",
        )
    if (
        request_output == frozen_evidence_root
        or frozen_evidence_root in request_output.parents
    ):
        raise BoundaryError(
            "host request output must be outside its fresh evidence_root",
            code="director_host_path_invalid",
        )
    digest = write_canonical_no_replace(args.output, request)
    print(
        "SCORE_DIRECTOR_HOST_REQUEST_OK "
        f"run={request['run_id']} output={args.output.resolve()} sha256={digest} "
        "model_calls=0 pass_eligible=false"
    )
    return 0


def _handle_director_host_capture(args: argparse.Namespace) -> int:
    request = validate_host_agent_request(
        load_contract(args.request, expected_schema="score-director-host-request/v1")
    )
    frozen_evidence_root = Path(request["evidence_root"])
    for label, candidate in (
        ("host response", args.response.resolve(strict=False)),
        ("host submission", args.output.resolve(strict=False)),
    ):
        if (
            candidate == frozen_evidence_root
            or frozen_evidence_root in candidate.parents
        ):
            raise BoundaryError(
                f"{label} must be outside the fresh evidence_root",
                code="director_host_path_invalid",
            )
    raw_response = _read_bounded_host_file(
        args.response,
        label="host response",
        max_bytes=HOST_RESPONSE_CAPTURE_MAX_BYTES,
        too_large_code="director_host_response_too_large",
    )
    submission = build_host_agent_submission(
        request=request,
        raw_response=raw_response,
        submission_id=args.submission_id,
        host_product=args.host_product,
    )
    digest = write_canonical_no_replace(args.output, submission)
    print(
        "SCORE_DIRECTOR_HOST_CAPTURE_OK "
        f"run={submission['run_id']} output={args.output.resolve()} sha256={digest} "
        "model_calls=0 pass_eligible=false"
    )
    return 0


def _read_bounded_host_file(
    path: Path,
    *,
    label: str,
    max_bytes: int,
    too_large_code: str,
) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BoundaryError(f"{label} must be a regular non-symlink file: {path}")
    if path.stat().st_size > max_bytes:
        raise BoundaryError(
            f"{label} exceeds the CLI read ceiling of {max_bytes} bytes: {path}",
            code=too_large_code,
        )
    with path.open("rb") as reader:
        data = reader.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise BoundaryError(
            f"{label} exceeded the CLI read ceiling while being read: {path}",
            code=too_large_code,
        )
    return data


def _read_host_submission(path: Path) -> bytes:
    return _read_bounded_host_file(
        path,
        label="host submission",
        max_bytes=HOST_SUBMISSION_READ_MAX_BYTES,
        too_large_code="host_submission_too_large",
    )


def _handle_director_host_ingest(args: argparse.Namespace) -> int:
    request = validate_host_agent_request(
        load_contract(args.request, expected_schema="score-director-host-request/v1")
    )
    raw_submission = _read_host_submission(args.submission)
    adjudication = (
        None
        if args.adjudication is None
        else load_contract(
            args.adjudication,
            expected_schema="score-director-adjudication/v1",
        )
    )
    output = args.output
    frozen_output = Path(request["evidence_root"]).resolve(strict=False)
    if output.resolve(strict=False) != frozen_output:
        raise BoundaryError(
            "--output differs from the evidence_root bound by the host request",
            code="director_evidence_root_mismatch",
        )
    claim_path = Path(request["ingest_claim_path"])
    if claim_path.exists() or claim_path.is_symlink():
        raise BoundaryError(
            "the host request already has an ingest claim; redraw is forbidden",
            code="director_host_ingest_already_claimed",
        )
    if output.exists():
        raise BoundaryError(
            f"host ingest output already exists: {output}",
            code="destination_exists",
        )
    evidence = ingest_host_agent_submission(
        request=request,
        raw_submission=raw_submission,
        adjudication=adjudication,
        evidence_store=DirectorEvidenceStore(output),
    )
    conclusion = evidence.document["conclusion"]
    print(
        "SCORE_DIRECTOR_HOST_RESPONSE_RECORDED "
        f"conclusion={conclusion} receipt={evidence.file.path.resolve()} "
        f"receipt_sha256={evidence.file.sha256} model_calls=0 pass_eligible=false"
    )
    return 0 if conclusion in {
        "diagnostic_contract_validated",
        "diagnostic_adjudication_matched",
    } else 2


def _handle_director_phase_a_run(args: argparse.Namespace) -> int:
    (
        evaluation_plan,
        phase_authorization,
        provider_descriptor,
        command_descriptor,
        contexts,
        adjudications,
    ) = _load_and_verify_director_phase_a(args)

    output = args.output
    frozen_output = Path(evaluation_plan["evidence_root"]).resolve(strict=False)
    if output.resolve(strict=False) != frozen_output:
        raise BoundaryError(
            "--output differs from the unique evidence_root frozen by the plan",
            code="director_evidence_root_mismatch",
        )
    claim_path = Path(evaluation_plan["execution_claim_path"])
    if claim_path.exists() and not args.resume:
        raise BoundaryError(
            "the frozen Phase A execution claim already exists; redraw is forbidden",
            code="director_execution_already_claimed",
        )
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise BoundaryError(f"director output must be a regular directory: {output}")
        if not args.resume:
            raise BoundaryError(
                f"director output already exists; use --resume to verify retained runs: {output}",
                code="destination_exists",
            )
    evidence_store = DirectorEvidenceStore(output)
    backend = command_backend_from_descriptor(
        evaluation_plan=evaluation_plan,
        command_descriptor=command_descriptor,
    )
    results, report, report_file = run_phase_a_inventory(
        spec_path=args.spec,
        evaluation_plan=evaluation_plan,
        phase_authorization=phase_authorization,
        contexts=contexts,
        adjudications=adjudications,
        provider_descriptor=provider_descriptor,
        backend=backend,
        evidence_store=evidence_store,
        resume=args.resume,
        command_descriptor=command_descriptor,
    )
    print(
        "SCORE_DIRECTOR_PHASE_A_RECORDED "
        f"conclusion={report['conclusion']} "
        f"report={report_file.path.resolve()} "
        f"report_sha256={report_file.sha256} runs={len(results)}"
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
