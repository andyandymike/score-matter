from __future__ import annotations

from typing import Any

from score_matter.errors import ProviderError

from . import manual, mock, replay

_DESCRIPTORS = {
    "manual": manual.descriptor,
    "mock": mock.descriptor,
    "replay": replay.descriptor,
}


def provider_ids() -> tuple[str, ...]:
    return tuple(sorted(_DESCRIPTORS))


def descriptor_for(provider_id: str) -> dict[str, Any]:
    factory = _DESCRIPTORS.get(provider_id)
    if factory is None:
        raise ProviderError(f"unknown built-in provider: {provider_id}")
    return factory()
