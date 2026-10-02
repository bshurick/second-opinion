import fs from "node:fs";
import path from "node:path";
import { InstallError } from "./errors.js";
import { venvPython } from "./paths.js";
import type { Runner } from "./runner.js";

export interface DepsResult {
  venvPython: string;
  /** True when pip ran this time (false when the stamp already matched). */
  installed: boolean;
  /** True when a fresh virtualenv was created. */
  createdVenv: boolean;
}

export interface DepsOptions {
  onLine?: (line: string) => void;
  onPhase?: (phase: "venv" | "pip" | "skip") => void;
  platform?: string;
}

function sameContents(a: string, b: string): boolean {
  try {
    return fs.readFileSync(a).equals(fs.readFileSync(b));
  } catch {
    return false;
  }
}

/**
 * Build the venv at <data>/venv with `python`, then pip install requirements.txt
 * when it differs from the stamp. Same layout and stamp as hooks/session-start.sh,
 * so the hook is a no-op after a successful install.
 */
export async function ensureDependencies(
  data: string,
  requirements: string,
  runner: Runner,
  python: string[],
  opts: DepsOptions = {},
): Promise<DepsResult> {
  fs.mkdirSync(data, { recursive: true });
  const venv = path.join(data, "venv");
  const py = venvPython(venv, opts.platform);
  const stamp = path.join(data, "requirements.installed.txt");
  const log = path.join(data, "install.log");
  let createdVenv = false;
  if (!fs.existsSync(py)) {
    opts.onPhase?.("venv");
    const r = await runner.run([...python, "-m", "venv", venv], { log, onLine: opts.onLine });
    if (r.code !== 0 || !fs.existsSync(py)) {
      throw new InstallError(
        "could not create the virtualenv",
        "install the venv module (Debian/Ubuntu: apt install python3-venv) or set SECOND_OPINION_PYTHON to a working interpreter",
      );
    }
    createdVenv = true;
  }
  if (fs.existsSync(stamp) && sameContents(requirements, stamp)) {
    opts.onPhase?.("skip");
    return { venvPython: py, installed: false, createdVenv };
  }
  opts.onPhase?.("pip");
  const r = await runner.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements], { log, onLine: opts.onLine });
  if (r.code !== 0) throw new InstallError("pip install failed", `see ${log}`);
  fs.copyFileSync(requirements, stamp);
  return { venvPython: py, installed: true, createdVenv };
}
