import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { RunOptions, RunResult, Runner } from "../src/engine/runner.js";
import type { Options } from "../src/cli.js";
import { parseOptions } from "../src/cli.js";

export const REAL_ROOT = path.resolve(__dirname, "..", "..");

export function tmpDir(prefix = "sf-installer-"): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

export function write(file: string, text: string, mode?: number): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
  if (mode !== undefined) fs.chmodSync(file, mode);
}

/** A small plugin checkout: three skills, one dependency edge, one key requirement, one edgar. */
export function miniRoot(dir = tmpDir("sf-root-")): string {
  const catalog = {
    skills: [
      { name: "a", family: "Fam one", requires: ["brokerage"], depends_on: [] },
      { name: "b", family: "Fam one", requires: [], depends_on: ["a"] },
      { name: "c", family: "Fam two", requires: ["edgar"], depends_on: [] },
    ],
  };
  write(path.join(dir, "skills.json"), JSON.stringify(catalog));
  for (const [name, desc] of [
    ["a", "Skill A does things. Second sentence."],
    ["b", "Skill B needs A"],
    ["c", "Skill C reads EDGAR!"],
    ["get-started", "Get-started skill."],
  ] as const) {
    write(path.join(dir, "skills", name, "SKILL.md"), `---\nname: ${name}\ndescription: ${desc}\n---\nbody\n`);
    write(path.join(dir, "skills", name, "scripts", "run.py"), "print('ok')\n", 0o755);
    write(path.join(dir, "skills", name, "scripts", "__pycache__", "x.pyc"), "junk");
  }
  write(path.join(dir, "lib", "second_opinion", "__init__.py"), "");
  write(path.join(dir, "hooks", "hooks.json"), "{}");
  write(path.join(dir, "hooks", "session-start.sh"), "#!/bin/sh\n", 0o755);
  write(path.join(dir, ".claude-plugin", "plugin.json"), '{"name":"second-opinion"}');
  write(path.join(dir, "requirements.txt"), "pkg==1\n");
  write(path.join(dir, "LICENSE"), "MIT");
  write(path.join(dir, "README.md"), "# readme");
  write(path.join(dir, "tests", "test_x.py"), "");
  write(path.join(dir, "scripts", "tool.sh"), "");
  return dir;
}

/**
 * miniRoot plus extras: c becomes a skill extra that needs a (brokerage), and a
 * non-skill extra "follow_ups" is declared. All extras are off by default.
 */
export function extrasRoot(dir = tmpDir("sf-extras-")): string {
  miniRoot(dir);
  const catalog = {
    skills: [
      { name: "a", family: "Fam one", requires: ["brokerage"], depends_on: [] },
      { name: "b", family: "Fam one", requires: [], depends_on: ["a"] },
      { name: "c", family: "Fam two", requires: ["edgar"], depends_on: ["a"], extra: true, default: false, label: "Skill C extra", blurb: "Does C.", friction: "Adds a step." },
    ],
    extras: [{ key: "follow_ups", label: "Tips", blurb: "Shows follow_ups.", default: false }],
  };
  write(path.join(dir, "skills.json"), JSON.stringify(catalog));
  return dir;
}

export interface Call {
  cmd: string[];
  opts: RunOptions;
}

/**
 * Fake process runner. Creating a venv writes the interpreter file so later
 * existence checks pass; every other command succeeds unless a rule says otherwise.
 */
export class FakeRunner implements Runner {
  calls: Call[] = [];
  rules: ((cmd: string[], opts: RunOptions) => RunResult | undefined)[] = [];
  pythonVersion = "3.12.1";
  hasVenv = true;

  async run(cmd: string[], opts: RunOptions = {}): Promise<RunResult> {
    this.calls.push({ cmd, opts });
    for (const rule of this.rules) {
      const r = rule(cmd, opts);
      if (r) return r;
    }
    if (cmd[1] === "-m" && cmd[2] === "venv") {
      const venv = cmd[3]!;
      const py = process.platform === "win32" ? path.join(venv, "Scripts", "python.exe") : path.join(venv, "bin", "python");
      write(py, "#!/bin/sh\n", 0o755);
      return { code: 0, stdout: "", stderr: "" };
    }
    if (cmd[1] === "-c" && String(cmd[2]).includes("version_info")) {
      return { code: 0, stdout: `${this.pythonVersion}\n${this.hasVenv ? "venv" : "novenv"}\n`, stderr: "" };
    }
    if (cmd[0] === "git") return { code: 0, stdout: "abc123\n", stderr: "" };
    const cli = cmd.findIndex((c) => c.endsWith(path.join("get-started", "scripts", "settings.py")));
    if (cli >= 0 && cmd[cli + 1] === "set") return fakeSettingsSet(cmd[cli + 2]!, cmd[cli + 3]!, opts.env?.SECOND_OPINION_DATA);
    if (cmd.some((c) => c.endsWith("dcf.py"))) return { code: 0, stdout: '{"fair_value_per_share": 12.3}', stderr: "" };
    return { code: 0, stdout: "", stderr: "" };
  }

  commands(): string[] {
    return this.calls.map((c) => c.cmd.join(" "));
  }
}

/** Stands in for `settings.py set KEY on|off` (the real CLI is exercised in install_e2e.test.ts). */
function fakeSettingsSet(key: string, value: string, dataDir: string | undefined): RunResult {
  if (!dataDir) return { code: 4, stdout: '{"error": "no SECOND_OPINION_DATA"}', stderr: "" };
  const file = path.join(dataDir, "settings.json");
  let doc: Record<string, unknown> = { schema: 1 };
  if (fs.existsSync(file)) {
    try {
      doc = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
    } catch {
      return { code: 5, stdout: JSON.stringify({ error: `settings at ${file} is not readable JSON`, code: "SETTINGS_CORRUPT", hint: "fix it by hand" }), stderr: "" };
    }
    if (typeof doc.schema === "number" && doc.schema > 1) {
      return { code: 5, stdout: JSON.stringify({ error: "settings were written by a newer plugin", code: "SETTINGS_NEWER", hint: "update the Second Opinion plugin" }), stderr: "" };
    }
  }
  const parts = key.split(".");
  let cur = doc;
  for (const p of parts.slice(0, -1)) {
    if (typeof cur[p] !== "object" || cur[p] === null) cur[p] = {};
    cur = cur[p] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]!] = value === "on";
  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(file, JSON.stringify(doc, null, 1) + "\n");
  return { code: 0, stdout: JSON.stringify({ key, value: value === "on" }), stderr: "" };
}

export function opts(argv: string[] = []): Options {
  return parseOptions(argv);
}

export class Capture {
  out = "";
  err = "";
  stdout = { write: (s: string) => void (this.out += s) };
  stderr = { write: (s: string) => void (this.err += s) };
}
