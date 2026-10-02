import fs from "node:fs";
import path from "node:path";
import { InstallError } from "./errors.js";

export type LinkState =
  | { kind: "absent" }
  | { kind: "ours" }
  | { kind: "symlink"; to: string }
  | { kind: "directory" }
  | { kind: "file" };

/** What is at the link path right now, relative to the intended target. */
export function inspectLink(link: string, target: string): LinkState {
  let st: fs.Stats;
  try {
    st = fs.lstatSync(link);
  } catch {
    return { kind: "absent" };
  }
  if (st.isSymbolicLink()) {
    const to = fs.readlinkSync(link);
    try {
      if (fs.realpathSync(link) === fs.realpathSync(target)) return { kind: "ours" };
    } catch {
      // dangling link or missing target: treat as foreign
    }
    return { kind: "symlink", to };
  }
  return st.isDirectory() ? { kind: "directory" } : { kind: "file" };
}

export function describeLinkState(link: string, state: LinkState): string {
  switch (state.kind) {
    case "symlink":
      return `${link} is a symlink to ${state.to}`;
    case "directory":
      return `${link} is a real directory`;
    case "file":
      return `${link} is a real file`;
    default:
      return "";
  }
}

/**
 * Point `link` at `target`. Anything else already there is replaced only with consent.
 */
export async function linkPlugin(target: string, link: string, confirm: (question: string) => Promise<boolean>): Promise<string> {
  const state = inspectLink(link, target);
  if (state.kind === "ours") return link;
  if (state.kind !== "absent") {
    const ok = await confirm(`${describeLinkState(link, state)}; replace it with a link to ${target}?`);
    if (!ok) {
      throw new InstallError(
        `link ${link} already exists and replacement was declined`,
        "re-run with a different link path or remove it yourself, or use --no-link",
      );
    }
    if (state.kind === "directory") fs.rmSync(link, { recursive: true, force: true });
    else fs.unlinkSync(link);
  }
  fs.mkdirSync(path.dirname(link), { recursive: true });
  fs.symlinkSync(target, link, "dir");
  return link;
}

export interface UninstallPlan {
  /** Paths (with symlink arrows) that will be removed. */
  remove: string[];
  /** What stays behind and why. */
  keep: string[];
}

export function planUninstall(target: string, link: string, data: string, purge: boolean): UninstallPlan {
  const remove: string[] = [];
  const keep: string[] = [];
  const linkState = (() => {
    try {
      return fs.lstatSync(link);
    } catch {
      return null;
    }
  })();
  if (linkState?.isSymbolicLink()) remove.push(`${link} -> ${fs.readlinkSync(link)}`);
  else if (linkState?.isDirectory()) keep.push(`${link} is a real directory; left in place`);
  else if (linkState) remove.push(link);
  const targetState = (() => {
    try {
      return fs.lstatSync(target);
    } catch {
      return null;
    }
  })();
  if (targetState?.isSymbolicLink()) remove.push(`${target} -> ${fs.readlinkSync(target)}`);
  else if (targetState) remove.push(target);
  if (fs.existsSync(data)) {
    if (purge) remove.push(data);
    else keep.push(`${data} (venv, ledger, journal, snapshots, caches) — pass --purge-data to delete`);
  }
  return { remove, keep };
}

export interface UninstallResult {
  removed: string[];
  kept: string[];
}

export async function uninstall(
  target: string,
  link: string,
  data: string,
  purge: boolean,
  confirm: (question: string) => Promise<boolean>,
): Promise<UninstallResult> {
  const plan = planUninstall(target, link, data, purge);
  const question = plan.remove.length ? "remove: " + plan.remove.join(", ") : "nothing to remove; continue?";
  if (!(await confirm(question))) throw new InstallError("uninstall declined");
  const removed: string[] = [];
  const kept: string[] = [];
  let linkStat: fs.Stats | null = null;
  try {
    linkStat = fs.lstatSync(link);
  } catch {
    linkStat = null;
  }
  if (linkStat?.isSymbolicLink() || linkStat?.isFile()) {
    fs.unlinkSync(link);
    removed.push(link);
  } else if (linkStat?.isDirectory()) {
    kept.push(`${link} is a real directory; left in place`);
  }
  if (fs.existsSync(target) || isSymlink(target)) {
    fs.rmSync(target, { recursive: true, force: true });
    removed.push(target);
  }
  if (fs.existsSync(data)) {
    if (purge) {
      fs.rmSync(data, { recursive: true, force: true });
      removed.push(data);
    } else {
      kept.push(`${data} (venv, ledger, journal, snapshots, caches) — pass --purge-data to delete`);
    }
  }
  return { removed, kept };
}

function isSymlink(p: string): boolean {
  try {
    return fs.lstatSync(p).isSymbolicLink();
  } catch {
    return false;
  }
}
