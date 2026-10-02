import fs from "node:fs";
import path from "node:path";
import { LEGACY_NAME, legacyLink, legacyTarget, PLUGIN_NAME, type Environ } from "./paths.js";

/** A directory that holds one of our plugin manifests (old or new name). */
function isOurPlugin(dir: string): boolean {
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(dir, ".claude-plugin", "plugin.json"), "utf8")) as { name?: unknown };
    return manifest.name === LEGACY_NAME || manifest.name === PLUGIN_NAME;
  } catch {
    return false;
  }
}

/**
 * The pre-rename copy and its skills link (~/.claude/plugins/finance-analyst and
 * ~/.claude/skills/finance-analyst), when present: left in place they load every skill twice.
 * A symlink is always listed (removing it touches nothing it points at); a real directory only
 * when it holds our plugin manifest. Never the plugin root this run uses. The data dir is not here.
 */
export function legacyLeftovers(environ: Environ, root: string): string[] {
  const out: string[] = [];
  const here = safeReal(root);
  for (const p of [legacyLink(environ), legacyTarget(environ)]) {
    let st: fs.Stats;
    try {
      st = fs.lstatSync(p);
    } catch {
      continue;
    }
    if (st.isSymbolicLink()) out.push(p);
    else if (st.isDirectory() && isOurPlugin(p) && safeReal(p) !== here) out.push(p);
  }
  return out;
}

/** Remove the listed leftovers (unlink symlinks, delete copies). Returns what was removed. */
export function removeLeftovers(paths: string[]): string[] {
  const removed: string[] = [];
  for (const p of paths) {
    let st: fs.Stats;
    try {
      st = fs.lstatSync(p);
    } catch {
      continue;
    }
    if (st.isSymbolicLink() || st.isFile()) fs.unlinkSync(p);
    else fs.rmSync(p, { recursive: true, force: true });
    removed.push(p);
  }
  return removed;
}

function safeReal(p: string): string {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
}
