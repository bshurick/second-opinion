from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def load_script(rel: str) -> ModuleType:
    path = PLUGIN_ROOT / "skills" / rel
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def run_json(mod: ModuleType, argv: list[str], capsys) -> tuple[int, dict | list]:
    rc = mod.main(argv)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else None)
