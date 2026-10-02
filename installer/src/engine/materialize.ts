import fs from "node:fs";
import path from "node:path";
import { ALWAYS_SKILLS } from "./catalog.js";
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
  /** Every optional extra on or off (non-skill switches such as follow_ups, and skill extras such as
   *  trade-journal). Absent in records written before extras existed; only `true` turns one on. */
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
    if (rec) return rec;
  }
  return null;
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
      skills: Array.isArray(rec.skills) ? rec.skills.filter((s): s is string => typeof s === "string") : [],
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
  /** Extras written to installed.json. */
  extras?: Record<string, boolean>;
  /** Where .env and installed.json go: the data dir in a real run; the target when omitted. */
  configDir?: string;
}

export interface RecordOptions {
  commit?: string | null;
  now?: () => Date;
  extras?: Record<string, boolean>;
  mode?: "copy" | "configure";
}

export function makeRecord(root: string, skills: string[], opts: RecordOptions = {}): InstalledRecord {
  return {
    skills: [...skills],
    source_path: root,
    source_commit: opts.commit ?? null,
    installer_version: INSTALLER_VERSION,
    installed_at: (opts.now?.() ?? new Date()).toISOString().replace(/\.\d{3}Z$/, "+00:00"),
    extras: { ...(opts.extras ?? {}) },
    ...(opts.mode ? { mode: opts.mode } : {}),
  };
}

/** Write .env (0600) and installed.json into dir, each through a temp file and a rename. */
export function writeConfig(dir: string, envText: string, record: InstalledRecord): void {
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
  fs.writeFileSync(`${rec}.tmp`, JSON.stringify(record, null, 1) + "\n");
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
  const record = makeRecord(root, skills, { commit: opts.commit, now: opts.now, extras: opts.extras, mode: "copy" });
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
