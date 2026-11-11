import fs from "node:fs";
import path from "node:path";
import { ALWAYS_SKILLS, canonicalSkills } from "./catalog.js";
import { InstallError } from "./errors.js";
import type { Runner } from "./runner.js";

export const INSTALLER_VERSION: string = process.env.INSTALLER_VERSION ?? "2.0.0-dev";
export const SHIPPED_TOP = [".claude-plugin", "hooks", "lib", "requirements.txt", "LICENSE", "README.md"] as const;
const EXCLUDE_DIRS = new Set(["__pycache__", ".pytest_cache", ".ruff_cache"]);

export interface InstalledRecord {
  skills: string[];
  source_path: string;
  source_commit: string | null;
  installer_version: string;
  installed_at: string;
  /** Optional switches on or off, as the installer sees them: read from settings.json, over a legacy
   *  installed.json `extras` map. Never written to installed.json any more. */
  extras?: Record<string, boolean>;
  /** "copy" (node install.js copied the plugin) or "configure" (Claude Code manages the files). */
  mode?: "copy" | "configure";
}

export interface SkillDiff {
  installed: string[];
  removed: string[];
  refreshed: string[];
}

export async function sourceCommit(root: string, runner: Runner): Promise<string | null> {
  const r = await runner.run(["git", "-C", root, "rev-parse", "HEAD"], { timeoutMs: 10_000 });
  const out = r.stdout.trim();
  return r.code === 0 && out ? out : null;
}

/** The first readable record among these directories (the data dir first, then older locations). */
export function readRecord(dirs: (string | null | undefined)[]): InstalledRecord | null {
  for (const dir of dirs) {
    if (!dir) continue;
    const rec = readInstalled(dir);
    if (!rec) continue;
    const fromSettings = readSettingsSwitches(dirs);
    return fromSettings ? { ...rec, extras: { ...(rec.extras ?? {}), ...fromSettings } } : rec;
  }
  return null;
}

/** installer extras key -> settings.json key (as second_opinion.config.EXTRA_SETTINGS). */
export const SWITCH_KEYS: Record<string, string> = {
  follow_ups: "replies.follow_ups",
  "trade-journal": "guardrails.pre_buy_check",
  "financial-education": "lessons",
};

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** settings.json in dir as an object; null when absent. Throws InstallError when corrupt or from a newer schema. */
function loadSettingsFile(dir: string): Record<string, unknown> | null {
  const p = path.join(dir, "settings.json");
  let raw: string;
  try {
    raw = fs.readFileSync(p, "utf8");
  } catch {
    return null;
  }
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new InstallError(`${p} is not valid JSON`, "fix or delete that file, then run the installer again");
  }
  if (!isObj(data)) throw new InstallError(`${p} is not a JSON object`, "fix or delete that file, then run the installer again");
  if (typeof data.schema === "number" && data.schema > 2) {
    throw new InstallError(`${p} was written by a newer Second Opinion (schema ${data.schema})`, "update this plugin, then run the installer again");
  }
  return data;
}

/** Switches recorded in the first readable settings.json among these directories; only keys present are returned. */
export function readSettingsSwitches(dirs: (string | null | undefined)[]): Record<string, boolean> | null {
  for (const dir of dirs) {
    if (!dir) continue;
    let data: Record<string, unknown> | null;
    try {
      data = loadSettingsFile(dir);
    } catch {
      continue;
    }
    if (!data) continue;
    const out: Record<string, boolean> = {};
    for (const [key, dotted] of Object.entries(SWITCH_KEYS)) {
      let cur: unknown = data;
      for (const k of dotted.split(".")) cur = isObj(cur) ? cur[k] : undefined;
      if (typeof cur === "boolean") out[key] = cur;
    }
    return out;
  }
  return null;
}

/** Refuse early (before any write) when dir/settings.json is corrupt or from a newer schema. */
export function checkSettings(dir: string): void {
  loadSettingsFile(dir);
}

/**
 * Save the switches (follow_ups, trade-journal, financial-education) through the plugin's own settings
 * CLI, run by the system Python found in preflight (that CLI imports only the standard library, so it
 * works before the venv exists). Going through Python means the first write also migrates the older
 * files into settings.json. A switch already saved with the same value is not written again.
 */
export async function writeSwitches(
  runner: Runner,
  python: string[],
  pluginRoot: string,
  dataDir: string,
  extras: Record<string, boolean>,
): Promise<void> {
  const script = path.join(pluginRoot, "skills", "get-started", "scripts", "settings.py");
  for (const [key, dotted] of Object.entries(SWITCH_KEYS)) {
    const want = extras[key];
    if (typeof want !== "boolean") continue;
    if (readSettingsSwitches([dataDir])?.[key] === want) continue;
    const r = await runner.run([...python, script, "set", dotted, want ? "on" : "off"], {
      env: { ...process.env, SECOND_OPINION_DATA: dataDir },
      timeoutMs: 60_000,
    });
    if (r.code !== 0) throw settingsCliError(r, dotted, dataDir);
  }
}

function settingsCliError(r: { code: number; stdout: string; stderr: string }, dotted: string, dataDir: string): InstallError {
  let body: { error?: unknown; hint?: unknown } = {};
  try {
    const parsed = JSON.parse(r.stdout) as unknown;
    if (isObj(parsed)) body = parsed;
  } catch {
    // not JSON: fall back to the raw output below
  }
  const file = path.join(dataDir, "settings.json");
  const why = typeof body.error === "string" ? body.error : (r.stderr || r.stdout).trim().split(/\r?\n/).pop() || `exit ${r.code}`;
  const hint =
    typeof body.hint === "string" && body.hint
      ? body.hint
      : r.code === 5
        ? `${file} is corrupt or was written by a newer Second Opinion; fix or move it aside, then run the installer again`
        : "check the Python found by the installer works, then run the installer again";
  return new InstallError(`could not save ${dotted} to settings.json: ${why}`, hint);
}

export function readInstalled(target: string): InstalledRecord | null {
  const p = path.join(target, "installed.json");
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as unknown;
    if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
    const rec = data as Partial<InstalledRecord>;
    const rawExtras = (data as { extras?: unknown }).extras;
    const extras =
      typeof rawExtras === "object" && rawExtras !== null && !Array.isArray(rawExtras)
        ? Object.fromEntries(Object.entries(rawExtras).filter((kv): kv is [string, boolean] => typeof kv[1] === "boolean"))
        : undefined;
    return {
      skills: Array.isArray(rec.skills) ? canonicalSkills(rec.skills.filter((s): s is string => typeof s === "string")) : [],
      source_path: typeof rec.source_path === "string" ? rec.source_path : "",
      source_commit: typeof rec.source_commit === "string" ? rec.source_commit : null,
      installer_version: typeof rec.installer_version === "string" ? rec.installer_version : "",
      installed_at: typeof rec.installed_at === "string" ? rec.installed_at : "",
      ...(extras ? { extras } : {}),
      ...((data as { mode?: unknown }).mode === "configure" || (data as { mode?: unknown }).mode === "copy" ? { mode: (data as { mode: "copy" | "configure" }).mode } : {}),
    };
  } catch {
    return null;
  }
}

export function planDiff(previous: string[] | null | undefined, selected: string[]): SkillDiff {
  const prev = new Set(previous ?? []);
  return {
    installed: selected.filter((s) => !prev.has(s)),
    removed: [...prev].filter((s) => !selected.includes(s)).sort(),
    refreshed: selected.filter((s) => prev.has(s)),
  };
}

function copyTree(src: string, dest: string): void {
  fs.cpSync(src, dest, {
    recursive: true,
    preserveTimestamps: true,
    filter: (p) => {
      const base = path.basename(p);
      return !EXCLUDE_DIRS.has(base) && !base.endsWith(".pyc");
    },
  });
}

/** Copy lib/, hooks/, metadata and the chosen skills (plus setup) into a fresh dest. */
export function buildTree(root: string, dest: string, skills: string[]): void {
  fs.mkdirSync(dest, { recursive: false });
  for (const top of SHIPPED_TOP) {
    const src = path.join(root, top);
    if (!fs.existsSync(src)) continue;
    if (fs.statSync(src).isDirectory()) copyTree(src, path.join(dest, top));
    else fs.copyFileSync(src, path.join(dest, top));
  }
  fs.mkdirSync(path.join(dest, "skills"));
  const names = [...skills, ...ALWAYS_SKILLS.filter((s) => !skills.includes(s))];
  for (const name of names) {
    const src = path.join(root, "skills", name);
    if (!fs.existsSync(src) || !fs.statSync(src).isDirectory()) throw new Error(`skill directory missing: ${src}`);
    copyTree(src, path.join(dest, "skills", name));
  }
}

export interface MaterializeOptions {
  commit?: string | null;
  /** Extra work on the staged tree before the swap; throwing leaves the old target intact. */
  build?: (staging: string) => void;
  now?: () => Date;
  /** Where .env and installed.json go: the data dir in a real run; the target when omitted. */
  configDir?: string;
}

export interface RecordOptions {
  commit?: string | null;
  now?: () => Date;
  mode?: "copy" | "configure";
}

export function makeRecord(root: string, skills: string[], opts: RecordOptions = {}): InstalledRecord {
  return {
    skills: [...skills],
    source_path: root,
    source_commit: opts.commit ?? null,
    installer_version: INSTALLER_VERSION,
    installed_at: (opts.now?.() ?? new Date()).toISOString().replace(/\.\d{3}Z$/, "+00:00"),
    ...(opts.mode ? { mode: opts.mode } : {}),
  };
}

/** Write .env (0600) and installed.json into dir, each through a temp file and a rename; switches go through writeSwitches. */
export function writeConfig(dir: string, envText: string, record: InstalledRecord): void {
  checkSettings(dir);
  fs.mkdirSync(dir, { recursive: true });
  const env = path.join(dir, ".env");
  fs.writeFileSync(`${env}.tmp`, envText, { mode: 0o600 });
  try {
    fs.chmodSync(`${env}.tmp`, 0o600);
  } catch {
    // best effort on filesystems without POSIX modes
  }
  fs.renameSync(`${env}.tmp`, env);
  const rec = path.join(dir, "installed.json");
  fs.writeFileSync(`${rec}.tmp`, JSON.stringify({ ...record, extras: undefined }, null, 1) + "\n");
  fs.renameSync(`${rec}.tmp`, rec);
}

/**
 * Build the target in a sibling `.building` directory and swap it into place at the end.
 * An interrupted or failed run leaves the previous install untouched.
 */
export function materialize(root: string, target: string, skills: string[], envText: string, opts: MaterializeOptions = {}): SkillDiff {
  const previous = opts.configDir ? readRecord([opts.configDir, target]) : readInstalled(target);
  const diff = planDiff(previous?.skills, skills);
  const parent = path.dirname(target);
  const building = path.join(parent, `${path.basename(target)}.building`);
  const old = path.join(parent, `${path.basename(target)}.previous`);
  for (const stale of [building, old]) if (fs.existsSync(stale)) fs.rmSync(stale, { recursive: true, force: true });
  fs.mkdirSync(parent, { recursive: true });
  const record = makeRecord(root, skills, { commit: opts.commit, now: opts.now, mode: "copy" });
  if (opts.configDir) checkSettings(opts.configDir);
  try {
    buildTree(root, building, skills);
    if (!opts.configDir) writeConfig(building, envText, record);
    opts.build?.(building);
  } catch (err) {
    fs.rmSync(building, { recursive: true, force: true });
    throw err;
  }
  if (fs.existsSync(target)) fs.renameSync(target, old);
  fs.renameSync(building, target);
  if (fs.existsSync(old)) fs.rmSync(old, { recursive: true, force: true });
  if (opts.configDir) writeConfig(opts.configDir, envText, record);
  return diff;
}
