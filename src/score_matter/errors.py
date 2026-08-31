from __future__ import annotations


class ScoreMatterError(Exception):
    """Expected fail-closed boundary error with a stable machine code."""

    code = "score_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ContractError(ScoreMatterError):
    code = "contract_invalid"


class BoundaryError(ScoreMatterError):
    code = "boundary_rejected"


class IntegrityError(ScoreMatterError):
    code = "integrity_failed"


class ProviderError(ScoreMatterError):
    code = "provider_failed"


class DirectorError(ScoreMatterError):
    """Fail-closed error raised by the non-provider director evidence lane."""

    code = "director_failed"
