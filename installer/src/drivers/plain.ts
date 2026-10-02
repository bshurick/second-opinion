/**
 * Line-oriented driver: used with --json, --plain, or when stdin/stdout is not a terminal.
 * Never prompts. Confirmations need --yes; missing secrets are named errors.
 */
import { buildPlan, createContext, execute, initialExtras, initialSelection, initialValues, preflight, requirePython, type Context, type InstallEvent } from "../engine/installer.js";
import { InstallError, UsageError } from "../engine/errors.js";
import { loadCatalog, loadExtras } from "../engine/catalog.js";
import { planUninstall, uninstall } from "../engine/link.js";
import type { Options } from "../cli.js";
import type { Environ } from "../engine/paths.js";
import type { Runner } from "../engine/runner.js";
import path from "node:path";

export interface Streams {
  stdout: { write(s: string): unknown };
  stderr: { write(s: string): unknown };
}

const list = (xs: string[]) => (xs.length ? xs.join(", ") : "(none)");

export async function runPlain(root: string, options: Options, environ: Environ, runner: Runner, io: Streams): Promise<number> {
  const ctx = createContext(root, options, environ, runner);
  // Human lines go to stderr under --json so stdout stays a single JSON object.
  const human = (msg: string) => (options.json ? io.stderr : io.stdout).write(msg + "\n");
  const machine = (obj: unknown) => io.stdout.write(JSON.stringify(obj) + "\n");

  try {
    if (options.uninstall && ctx.configure) {
      throw new UsageError("this copy is managed by Claude Code; remove it with /plugin uninstall second-opinion@second-opinion");
    }
    if (options.uninstall) return await runUninstall(ctx, human, machine);

    const pre = await preflight(ctx);
    const python = requirePython(pre);
    const catalog = loadCatalog(ctx.root);
    const extraDefs = loadExtras(ctx.root);
    const sel = initialSelection(catalog, options, pre.previous, ctx.configure);
    const ex = initialExtras(options, extraDefs, catalog, sel.names, pre.previous);
    for (const n of [...sel.notes, ...ex.notes]) human(n);
    const plan = buildPlan(ctx, pre, python, ex.selected, initialValues(ctx), undefined, ex.nonSkill);
    const on = extraDefs.filter((e) => plan.extrasState[e.key]).map((e) => e.key);
    const off = extraDefs.filter((e) => !plan.extrasState[e.key]).map((e) => e.key);
    const extrasLine = `extras: on ${list(on)}; off ${list(off)}`;

    if (!options.dryRun) {
      if (ctx.configure) {
        human(`Configuring Second Opinion (plugin files are managed by Claude Code at ${ctx.root})\nSettings, extras and virtualenv: ${ctx.data}\nNothing outside that directory is written.\n`);
      } else {
        human(`Installing to ${ctx.target}\nSettings and virtualenv: ${ctx.data}\nLink: ${ctx.link}\nNothing outside these two directories and that one symlink is written.\n`);
      }
    }
    if (!plan.needs.has("brokerage")) human("No brokerage-backed skills selected; no SnapTrade or E*Trade key needed.");
    const diffLine = (verb: string) => `${verb} ${list(plan.diff.installed)}; refresh ${list(plan.diff.refreshed)}; remove ${list(plan.diff.removed)}`;

    if (options.dryRun) {
      const warnings = [...plan.warnings, ...plan.missing.map((k) => `${k} is not set; a real run will need it`)];
      if (!ctx.configure) human(`would install ${diffLine("").trimStart()}`);
      human(extrasLine);
      if (ctx.configure) human(`would write .env and installed.json to ${ctx.data}; venv at ${path.join(ctx.data, "venv")}; nothing copied or linked`);
      else human(`would write ${ctx.target} and link ${ctx.link}; .env, installed.json and venv in ${ctx.data}`);
      if (plan.leftovers.length) human(`would remove the old finance-analyst copy (with --yes): ${plan.leftovers.join(", ")}`);
      if (ctx.legacyData) human(`would move ${ctx.legacyData} to ${ctx.data}`);
      if (options.json) {
        machine({
          dry_run: true,
          mode: ctx.configure ? "configure" : "copy",
          target: ctx.target,
          data: ctx.data,
          link: options.noLink || ctx.configure ? null : ctx.link,
          legacy: { data: ctx.legacyData, remove: plan.leftovers },
          skills: plan.diff,
          dependencies: { venv: path.join(ctx.data, "venv") },
          python: python.version,
          extras: plan.extrasState,
          warnings,
        });
      }
      return 0;
    }

    if (!ctx.configure) human(diffLine("will install"));
    human(extrasLine);
    const summary = await execute(ctx, plan, {
      confirmLinkReplace: async () => options.yes,
      confirmLegacyRemove: async () => options.yes,
      onEvent: (e: InstallEvent) => {
        if (e.type === "step:start") human(`${e.label}...`);
        else if (e.type === "step:fail") human(`failed: ${e.error.format()}`);
        else if (e.type === "note") human(e.message);
      },
    });
    if (options.json) machine(summary);
    if (ctx.configure) {
      human(`Configured: settings and extras in ${summary.data}`);
      human("Start a new Claude Code session (or run /reload-plugins) to pick up the changes.");
    } else {
      human(`Installed: ${list(summary.skills.installed)}; refreshed: ${list(summary.skills.refreshed)}; removed: ${list(summary.skills.removed)}`);
      human(`Target: ${summary.target}` + (summary.link ? `\nLinked: ${summary.link}` : ""));
      human(summary.link ? "Start Claude Code: claude" : `Run Claude with: claude --plugin-dir ${summary.target}`);
    }
    human("Smoke: " + Object.entries(summary.smoke).map(([k, v]) => `${k}=${v}`).join(", "));
    if (summary.smoke.etrade === "no_login") human('Next: in Claude say "Connect E*Trade" and paste the 5-character code it shows.');
    for (const w of summary.warnings) human(`warning: ${w}`);
    human(ctx.configure ? "Re-run install.js any time to change keys or extras." : "Re-run install.js any time to add or remove skills or pick up a newer checkout.");
    return 0;
  } catch (err) {
    return reportError(err, io);
  }
}

async function runUninstall(ctx: Context, human: (m: string) => void, machine: (o: unknown) => void): Promise<number> {
  const { options } = ctx;
  if (options.dryRun) {
    const plan = planUninstall(ctx.target, ctx.link, ctx.data, options.purgeData);
    const paths = plan.remove.map((p) => p.split(" -> ")[0]!);
    human(paths.length ? "would remove: " + paths.join(", ") : "nothing to remove");
    if (options.json) machine({ dry_run: true, uninstall: { would_remove: paths } });
    return 0;
  }
  if (!options.yes) {
    throw new InstallError(
      options.json ? "uninstall requires --yes in --json mode" : "uninstall requires --yes when not run from a terminal",
      "pass --yes to confirm non-interactively",
    );
  }
  const res = await uninstall(ctx.target, ctx.link, ctx.data, options.purgeData, async () => true);
  for (const r of res.removed) human(`removed ${r}`);
  for (const k of res.kept) human(`kept ${k}`);
  if (options.json) machine(res);
  return 0;
}

export function reportError(err: unknown, io: Streams): number {
  if (err instanceof InstallError) {
    io.stderr.write(`install.js: ${err.format()}\n`);
    return 1;
  }
  if (err instanceof Error && err.name === "UsageError") {
    io.stderr.write(`install.js: ${err.message}\n`);
    return 2;
  }
  const e = err as NodeJS.ErrnoException;
  if (e && typeof e.code === "string" && ["EACCES", "EPERM", "ENOENT", "ENOTDIR", "EEXIST", "EROFS", "ENOSPC", "EBUSY"].includes(e.code)) {
    io.stderr.write(`install.js: ${e.message} — check the path is writable and the checkout is complete\n`);
    return 1;
  }
  io.stderr.write(`install.js: unexpected error: ${(err as Error)?.stack ?? String(err)}\n`);
  return 1;
}
