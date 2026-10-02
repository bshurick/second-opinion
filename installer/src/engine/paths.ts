import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export type Environ = Readonly<Record<string, string | undefined>>;

export const PLUGIN_NAME = "second-opinion";
/** The plugin's name before 1.0: its install, link and data dir are migrated or cleaned up. */
export const LEGACY_NAME = "finance-analyst";

export function homeDir(environ: Environ): string {
  return environ.HOME || environ.USERPROFILE || os.homedir();
}

export function defaultTarget(environ: Environ): string {
  return path.join(homeDir(environ), ".claude", "plugins", PLUGIN_NAME);
}

export function defaultLink(environ: Environ): string {
  return path.join(homeDir(environ), ".claude", "skills", PLUGIN_NAME);
}

/** The data dir override, if any: SECOND_OPINION_DATA, or the older FINANCE_ANALYST_DATA. */
export function dataOverride(environ: Environ): string | undefined {
  return environ.SECOND_OPINION_DATA || environ.FINANCE_ANALYST_DATA || undefined;
}

/**
 * Persistent data dir shared with hooks/session-start.sh and lib/second_opinion/config.py (venv,
 * ledger, journal, caches, .env, installed.json). This is where the installer writes; it survives
 * plugin updates. Overridden by SECOND_OPINION_DATA (FINANCE_ANALYST_DATA still works), never by
 * CLAUDE_PLUGIN_DATA: Claude Code sets that in hook processes alone and names it after the load path.
 */
export function dataDir(environ: Environ): string {
  return dataOverride(environ) || path.join(homeDir(environ), ".claude", "plugins", "data", PLUGIN_NAME);
}

/** The pre-rename data dir, when there is no override and it still exists; else null. */
export function legacyDataDir(environ: Environ): string | null {
  if (dataOverride(environ)) return null;
  const old = path.join(homeDir(environ), ".claude", "plugins", "data", LEGACY_NAME);
  return isDir(old) ? old : null;
}

/** The pre-rename install directory and skills link (each may or may not exist). */
export function legacyTarget(environ: Environ): string {
  return path.join(homeDir(environ), ".claude", "plugins", LEGACY_NAME);
}

export function legacyLink(environ: Environ): string {
  return path.join(homeDir(environ), ".claude", "skills", LEGACY_NAME);
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

/** True when a directory holds nothing but regenerable caches (*-cache, *-cache.json), or nothing. */
export function cacheOnly(dir: string): boolean {
  try {
    return fs.readdirSync(dir).every((n) => n.endsWith("-cache") || n.endsWith("-cache.json") || n === ".DS_Store");
  } catch {
    return false;
  }
}

/**
 * One-time move of ~/.claude/plugins/data/finance-analyst to the new data dir, the same rule as
 * hooks/common.sh: rename when the new dir is absent; when it holds only caches, move each old entry
 * it lacks and remove the old dir only if that emptied it. Never overwrites, never deletes data.
 * Returns a one-line note when something moved, else null.
 */
export function migrateLegacyData(environ: Environ): string | null {
  const old = legacyDataDir(environ);
  if (!old) return null;
  const dest = dataDir(environ);
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.renameSync(old, dest);
    return `moved your data from ${tildify(old, environ)} to ${tildify(dest, environ)}`;
  }
  if (!isDir(dest) || !cacheOnly(dest)) return null;
  let moved = 0;
  for (const name of fs.readdirSync(old)) {
    if (fs.existsSync(path.join(dest, name))) continue;
    fs.renameSync(path.join(old, name), path.join(dest, name));
    moved++;
  }
  try {
    fs.rmdirSync(old);
  } catch {
    // not empty: clashing caches stay behind
  }
  return moved ? `moved your data from ${tildify(old, environ)} to ${tildify(dest, environ)}` : null;
}

/**
 * True when the plugin root sits in a Claude Code marketplace checkout or plugin cache
 * (~/.claude/plugins/cache/... or ~/.claude/plugins/marketplaces/...): Claude Code owns those
 * files, so the installer only configures (data dir) and never copies or links.
 */
export function isManagedRoot(root: string): boolean {
  const parts = path.resolve(root).split(path.sep);
  for (let i = 0; i + 2 < parts.length; i++) {
    if (parts[i] === ".claude" && parts[i + 1] === "plugins" && (parts[i + 2] === "cache" || parts[i + 2] === "marketplaces")) return true;
  }
  return false;
}

export function isWindows(platform: string = process.platform): boolean {
  return platform === "win32";
}

export function venvPython(venv: string, platform: string = process.platform): string {
  return isWindows(platform) ? path.join(venv, "Scripts", "python.exe") : path.join(venv, "bin", "python");
}

/** ~/x for display. */
export function tildify(p: string, environ: Environ): string {
  const home = homeDir(environ);
  return p === home || p.startsWith(home + path.sep) ? "~" + p.slice(home.length) : p;
}

export function expandUser(p: string, environ: Environ): string {
  if (p === "~") return homeDir(environ);
  if (p.startsWith("~/") || p.startsWith("~\\")) return path.join(homeDir(environ), p.slice(2));
  return p;
}
