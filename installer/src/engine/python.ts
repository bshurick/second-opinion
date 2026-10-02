import fs from "node:fs";
import type { Environ } from "./paths.js";
import { isWindows } from "./paths.js";
import type { Runner } from "./runner.js";

export const PYTHON_FLOOR: [number, number] = [3, 10];

export interface PythonInfo {
  /** Command used to invoke it (a path or a PATH name). */
  command: string[];
  version: string;
  hasVenv: boolean;
  /** Where it came from, for the preflight screen. */
  source: "SECOND_OPINION_PYTHON" | "FINANCE_ANALYST_PYTHON" | "PROFICI_PYTHON" | "PATH";
}

export interface PythonProbe {
  found: PythonInfo | null;
  /** Every candidate tried and why it was rejected. */
  rejected: { command: string; reason: string }[];
}

const OVERRIDES = ["SECOND_OPINION_PYTHON", "FINANCE_ANALYST_PYTHON", "PROFICI_PYTHON"] as const;

const PROBE = "import sys, importlib.util; print('%d.%d.%d' % sys.version_info[:3]); print('venv' if importlib.util.find_spec('venv') else 'novenv')";

/**
 * Find an interpreter that can build the plugin's virtualenv.
 * SECOND_OPINION_PYTHON when set (and only that; the older FINANCE_ANALYST_PYTHON and PROFICI_PYTHON
 * are accepted in its place); otherwise python3 / python (and `py -3` on Windows) from PATH.
 */
export async function findPython(runner: Runner, environ: Environ, platform: string = process.platform): Promise<PythonProbe> {
  const rejected: PythonProbe["rejected"] = [];
  const candidates: { command: string[]; source: PythonInfo["source"] }[] = [];
  const override = OVERRIDES.find((v) => environ[v]);
  if (override) {
    // An explicit override is honored strictly: a broken one is reported, not worked around.
    candidates.push({ command: [environ[override]!], source: override });
  } else {
    candidates.push({ command: ["python3"], source: "PATH" }, { command: ["python"], source: "PATH" });
    if (isWindows(platform)) candidates.push({ command: ["py", "-3"], source: "PATH" });
  }

  for (const c of candidates) {
    const label = c.command.join(" ");
    if (c.source !== "PATH") {
      try {
        fs.accessSync(c.command[0]!, fs.constants.X_OK);
      } catch {
        rejected.push({ command: label, reason: `${c.source} is not executable` });
        continue;
      }
    }
    const r = await runner.run([...c.command, "-c", PROBE], { timeoutMs: 15_000 });
    if (r.code === 127) {
      rejected.push({ command: label, reason: "not found" });
      continue;
    }
    const [version = "", venv = ""] = r.stdout.trim().split(/\r?\n/);
    const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
    if (r.code !== 0 || !m) {
      rejected.push({ command: label, reason: "did not report a version" });
      continue;
    }
    const major = Number(m[1]);
    const minor = Number(m[2]);
    if (major < PYTHON_FLOOR[0] || (major === PYTHON_FLOOR[0] && minor < PYTHON_FLOOR[1])) {
      rejected.push({ command: label, reason: `Python ${version} is older than ${PYTHON_FLOOR.join(".")}` });
      continue;
    }
    if (venv !== "venv") {
      rejected.push({ command: label, reason: "the venv module is missing (Debian/Ubuntu: apt install python3-venv)" });
      continue;
    }
    return { found: { command: c.command, version, hasVenv: true, source: c.source }, rejected };
  }
  return { found: null, rejected };
}

/** One-line fix for a failed probe. */
export function pythonHint(probe: PythonProbe): string {
  const bad = probe.rejected.find((r) => r.reason.endsWith("PYTHON is not executable"));
  if (bad) return `point ${bad.reason.split(" ")[0]} at a working python3 interpreter or unset it`;
  const venvMissing = probe.rejected.find((r) => r.reason.includes("venv module"));
  if (venvMissing) return venvMissing.reason.replace("the venv module is missing", "install the venv module") + ", or set SECOND_OPINION_PYTHON to a working interpreter";
  return `install Python ${PYTHON_FLOOR.join(".")}+ and make sure python3 is on your PATH, or set SECOND_OPINION_PYTHON to a working interpreter`;
}
