"""Osarai — Outillage Python déterministe de validation et génération statique."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

__version__ = "0.1.0"

USER_AGENT = f"Osarai/{__version__} (+https://github.com/Seburan/osarai)"


class ExitCode(IntEnum):
    """Codes de sortie typés de la CLI `osarai`."""

    OK = 0
    VALIDATION_ERROR = 2
    RATE_LIMITED = 3
    LICENSE_DISALLOWED = 4
    UPSTREAM_NOT_FOUND = 5


class OsaraiError(Exception):
    """Exception métier transportant un `ExitCode` et des détails JSON optionnels."""

    def __init__(
        self,
        message: str,
        exit_code: ExitCode = ExitCode.VALIDATION_ERROR,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


__all__ = ["ExitCode", "OsaraiError", "USER_AGENT", "__version__"]
