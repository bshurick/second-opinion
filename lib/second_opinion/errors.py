"""Exception hierarchy shared by all plugin scripts.

Every error carries a machine-readable ``code`` and the process ``exit_code``
the script should return. ``output.run`` turns them into the JSON envelope.
"""
from __future__ import annotations

from typing import Any


class ScriptError(Exception):
    code = "SCRIPT_ERROR"
    exit_code = 1

    def __init__(self, message: str, *, code: str | None = None, exit_code: int | None = None, **extra: Any) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code
        self.extra: dict[str, Any] = extra


class InvalidInput(ScriptError):
    code = "INVALID_INPUT"
    exit_code = 2


class NotConfirmed(ScriptError):
    code = "NOT_CONFIRMED"
    exit_code = 3


class ConfigError(ScriptError):
    code = "CONFIG_MISSING"
    exit_code = 4


class ApiError(ScriptError):
    code = "API_ERROR"
    exit_code = 5


class DependencyMissing(ScriptError):
    code = "DEPENDENCY_MISSING"
    exit_code = 6
