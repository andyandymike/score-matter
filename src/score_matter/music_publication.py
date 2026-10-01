"""Preview music metadata through Core's public complete-publication contract."""
from matter_audio_core.artifacts import Publication
from matter_audio_core.contracts import MAX_JSON_BYTES, canonical
from matter_audio_core.errors import AudioError


def validated_producer(store, request_id, binding, document, role, parents, limitations):
    data = canonical(document)
    if len(data) > MAX_JSON_BYTES:
        raise AudioError("json_too_large", "Musical document exceeds 1 MiB")

    def produce(publication):
        output = publication.add(data, {"kind": role, "content_type": "application/json"}, role=role, parents=parents)
        return {"annotation" if role == "music_annotation" else "plan": output,
                "document": document, "limitations": limitations}

    preview = Publication("0" * 32)
    extra = produce(preview)
    try:
        store.validate_publication(request_id, binding, preview, extra)
    except AudioError as exc:
        if exc.code != "publication_too_large":
            raise
        raise AudioError("json_too_large", "Complete musical publication exceeds 1 MiB") from exc
    return produce
