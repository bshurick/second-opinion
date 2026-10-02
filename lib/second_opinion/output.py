"""JSON-on-stdout conventions and the exit-code mapping used by every script.

Exit codes: 0 ok, 2 invalid input, 3 not confirmed, 4 config missing,
5 API error, 6 dependency missing. Errors are printed to stdout as
``{"error": ..., "code": ..., ...extra}`` so the calling agent always gets JSON.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from typing import Any

from second_opinion import config
from second_opinion.errors import ScriptError

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_NOT_CONFIRMED = 3
EXIT_CONFIG_MISSING = 4
EXIT_API_ERROR = 5
EXIT_DEPENDENCY_MISSING = 6


def emit(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def fail(message: str, code: str, exit_code: int, **extra: Any) -> int:
    emit({"error": message, "code": code, **extra})
    return exit_code


def run(fn: Callable[[list[str]], Any], argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = fn(args)
    except ScriptError as e:
        return fail(str(e), e.code, e.exit_code, **e.extra)
    except ImportError as e:
        return fail(
            f"missing dependency: {e.name or e}",
            "DEPENDENCY_MISSING",
            EXIT_DEPENDENCY_MISSING,
            missing=e.name,
            requirements=str(config.PLUGIN_ROOT / "requirements.txt"),
            install_log=os.environ.get("SNAPTRADE_INSTALL_LOG"),
        )
    except Exception as e:  # noqa: BLE001 — every script must end in JSON
        sys.stderr.write(traceback.format_exc())
        return fail(str(e), "API_ERROR", EXIT_API_ERROR, http_status=getattr(e, "status", None), type=e.__class__.__name__)
    if result is None:
        return EXIT_OK
    if isinstance(result, int):
        return result
    emit(result)
    return EXIT_OK
