import fs from "node:fs";
import path from "node:path";
import type { Options } from "../cli.js";
import { loadCatalog, loadExtras, requirementsFor, type Extra, type Requirement, type Skill } from "./catalog.js";
import { ensureDependencies } from "./deps.js";
import { brokersFrom, envDefaults, preservedEnvLines, renderEnv, type BrokerChoice, type EnvValues } from "./env.js";
import { InstallError, UsageError } from "./errors.js";
import { applyExtras, extrasState, nonSkillDefaults, parseExtrasFlag, type ExtrasState } from "./extras.js";
import { legacyLeftovers, removeLeftovers } from "./legacy.js";
import { inspectLink, linkPlugin, type LinkState } from "./link.js";
import { INSTALLER_VERSION, makeRecord, materialize, planDiff, readRecord, sourceCommit, writeConfig, type InstalledRecord, type SkillDiff } from "./materialize.js";
import { dataDir, defaultLink, defaultTarget, expandUser, isManagedRoot, legacyDataDir, legacyTarget, migrateLegacyData, tildify, type Environ } from "./paths.js";
import { findPython, pythonHint, type PythonInfo, type PythonProbe } from "./python.js";
import type { Runner } from "./runner.js";
import { parseList, resolveSelection } from "./selection.js";
import { smoke, SMOKE_SKIPPED, type SmokeResult } from "./smoke.js";

export { INSTALLER_VERSION };

/** Everything a run needs, resolved once from flags and environment. */
export interface Context {
  root: string;
  environ: Environ;
  runner: Runner;
  options: Options;
  target: string;
  link: string;
  /** Where the venv, .env and installed.json are written (survives plugin updates). */
  data: string;
  /** The pre-rename data dir while it still exists (read for settings, moved on a real run). */
  legacyData: string | null;
  /**
   * Configure only: Claude Code manages the plugin files (a /plugin marketplace install), so the run
   * writes the data dir alone and never copies or links. target is then the plugin root itself.
   */
  configure: boolean;
}

export function createContext(root: string, options: Options, environ: Environ, runner: Runner): Context {
  const configure = options.configure || isManagedRoot(root);
  return {
    root,
    environ,
    runner,
    options,
    target: configure ? root : options.target ? path.resolve(expandUser(options.target, environ)) : defaultTarget(environ),
    link: defaultLink(environ),
    data: dataDir(environ),
    legacyData: legacyDataDir(environ),
    configure,
  };
}

/** Directories that may hold an earlier installed.json, newest location first. */
function recordDirs(ctx: Context): (string | null)[] {
  return [ctx.data, ctx.legacyData, ctx.configure ? null : ctx.target, legacyTarget(ctx.environ)];
}

/** Existing .env files, oldest location first (later files override earlier ones). */
function envFiles(ctx: Context): string[] {
  const files = [path.join(legacyTarget(ctx.environ), ".env"), path.join(ctx.target, ".env")];
  if (ctx.legacyData) files.push(path.join(ctx.legacyData, ".env"));
  files.push(path.join(ctx.data, ".env"));
  return files;
}

export interface Preflight {
  node: string;
  python: PythonProbe;
  previous: InstalledRecord | null;
  commit: string | null;
}

export async function preflight(ctx: Context): Promise<Preflight> {
  const [python, commit] = await Promise.all([findPython(ctx.runner, ctx.environ), sourceCommit(ctx.root, ctx.runner)]);
  return { node: process.versions.node, python, previous: readRecord(recordDirs(ctx)), commit };
}

export function requirePython(pre: Preflight): PythonInfo {
  if (pre.python.found) return pre.python.found;
  const first = pre.python.rejected[0];
  const what = first && pre.python.rejected.length === 1 ? `${first.command}: ${first.reason}` : `no usable Python found (tried ${pre.python.rejected.map((r) => r.command).join(", ")})`;
  throw new InstallError(what, pythonHint(pre.python));
}

/** Skills chosen before any interaction: flags, then the previous install, then every skill that is on by default. */
export function initialSelection(catalog: Skill[], options: Options, previous: InstalledRecord | null, configure = false): { names: string[]; notes: string[]; explicit: boolean } {
  const all = catalog.map((s) => s.name);
  const known = new Set(all);
  if (configure) {
    // Claude Code ships every skill; the selection only says which skill extras are on.
    if (options.all || options.skills !== undefined || options.without !== undefined) {
      throw new UsageError("--all, --skills and --without do not apply to a /plugin install, which ships every skill; use --extras to turn extras on or off");
    }
    // A skill extra is on when the record says so (extras[key], else its skills list); no record: its default.
    const on = (s: Skill) => {
      if (!previous) return s.defaultOn;
      const flag = previous.extras?.[s.name];
      return typeof flag === "boolean" ? flag : previous.skills.includes(s.name);
    };
    const names = catalog.filter((s) => !s.extra || on(s)).map((s) => s.name);
    return { ...resolveSelection(catalog, names), explicit: true };
  }
  if (options.all) return { ...resolveSelection(catalog, all), explicit: true };
  if (options.skills !== undefined) {
    const chosen = parseList(options.skills);
    for (const n of chosen) if (!known.has(n)) throw new UsageError(`unknown skill: ${n}`);
    return { ...resolveSelection(catalog, chosen), explicit: true };
  }
  if (options.without !== undefined) {
    const drop = new Set(parseList(options.without));
    for (const d of drop) if (!known.has(d)) throw new UsageError(`unknown skill: ${d}`);
    return { ...resolveSelection(catalog, all.filter((n) => !drop.has(n)), { dropDependents: true }), explicit: true };
  }
  if (previous?.skills.length) {
    const kept = previous.skills.filter((n) => known.has(n));
    return { ...resolveSelection(catalog, kept), explicit: false };
  }
  return { ...resolveSelection(catalog, catalog.filter((s) => s.defaultOn).map((s) => s.name)), explicit: false };
}

/**
 * Extras before any interaction: non-skill switches from the previous record (or the
 * declared defaults), then --extras applied on top of the skill selection.
 */
export function initialExtras(
  options: Options,
  extras: Extra[],
  catalog: Skill[],
  selected: string[],
  previous: InstalledRecord | null,
): { selected: string[]; nonSkill: Record<string, boolean>; notes: string[] } {
  const nonSkill = nonSkillDefaults(extras, previous);
  if (options.extras === undefined) return { selected, nonSkill, notes: [] };
  return applyExtras(catalog, extras, selected, nonSkill, parseExtrasFlag(options.extras, extras));
}

/** Credential values known before prompting: env, older .env locations, the data dir's .env, --env-file, then flags. */
export function initialValues(ctx: Context): EnvValues {
  const envFile = ctx.options.envFile ? expandUser(ctx.options.envFile, ctx.environ) : undefined;
  const values = envDefaults(envFiles(ctx), envFile, ctx.environ);
  if (ctx.options.snaptradeClientId) values.SNAPTRADE_CLIENT_ID = ctx.options.snaptradeClientId;
  if (ctx.options.snaptradeConsumerKey) values.SNAPTRADE_CONSUMER_KEY = ctx.options.snaptradeConsumerKey;
  if (ctx.options.etradeConsumerKey) values.ETRADE_CONSUMER_KEY = ctx.options.etradeConsumerKey;
  if (ctx.options.etradeConsumerSecret) values.ETRADE_CONSUMER_SECRET = ctx.options.etradeConsumerSecret;
  if (ctx.options.etradeSandbox) values.ETRADE_SANDBOX = "1";
  if (ctx.options.edgarUserAgent) values.EDGAR_USER_AGENT = ctx.options.edgarUserAgent;
  return values;
}

export function preservedLines(ctx: Context): string[] {
  const envFile = ctx.options.envFile ? expandUser(ctx.options.envFile, ctx.environ) : undefined;
  return preservedEnvLines([...envFiles(ctx)].reverse(), envFile);
}

/** The reviewed plan: what will be written and what it needs. */
export interface Plan {
  catalog: Skill[];
  selected: string[];
  needs: Set<Requirement>;
  diff: SkillDiff;
  previous: InstalledRecord | null;
  values: EnvValues;
  preserved: string[];
  python: PythonInfo;
  commit: string | null;
  linkState: LinkState;
  /** Missing required credentials, by env key. */
  missing: string[];
  warnings: string[];
  brokers: Set<BrokerChoice>;
  /** Non-skill extras to record in installed.json. */
  extras: Record<string, boolean>;
  /** Every extra on or off, for review and summaries. */
  extrasState: ExtrasState;
  /** The pre-rename copy and link to remove so skills do not load twice. */
  leftovers: string[];
}

export function parseBrokers(raw: string): Set<BrokerChoice> {
  const out = new Set<BrokerChoice>();
  for (const b of parseList(raw)) {
    if (b !== "snaptrade" && b !== "etrade") throw new UsageError(`--brokers accepts snaptrade and etrade, not '${b}'`);
    out.add(b);
  }
  return out;
}

export function buildPlan(
  ctx: Context,
  pre: Preflight,
  python: PythonInfo,
  selected: string[],
  values: EnvValues,
  brokers?: Set<BrokerChoice>,
  nonSkill?: Record<string, boolean>,
): Plan {
  const catalog = loadCatalog(ctx.root);
  const extraDefs = loadExtras(ctx.root);
  const extras = nonSkill ?? nonSkillDefaults(extraDefs, pre.previous);
  const needs = requirementsFor(catalog, selected);
  const missing: string[] = [];
  const warnings: string[] = [];
  const chosen = brokers ?? (ctx.options.brokers ? parseBrokers(ctx.options.brokers) : brokersFrom(values));
  if (needs.has("brokerage")) {
    if (chosen.size === 0) missing.push("SNAPTRADE_CLIENT_ID+SNAPTRADE_CONSUMER_KEY or ETRADE_CONSUMER_KEY+ETRADE_CONSUMER_SECRET");
    if (chosen.has("snaptrade")) for (const key of ["SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY"] as const) if (!values[key]) missing.push(key);
    if (chosen.has("etrade")) for (const key of ["ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET"] as const) if (!values[key]) missing.push(key);
  }
  if (needs.has("edgar") && !values.EDGAR_USER_AGENT) {
    warnings.push("EDGAR_USER_AGENT not set; fundamental-research will flag the placeholder default until you re-run install.js");
  }
  if (ctx.configure && missing.length) {
    // A /plugin install already has every skill; without a key the brokerage skills say how to add one.
    warnings.push("no brokerage key configured yet; run node install.js in a terminal to add a SnapTrade or E*Trade key");
    missing.length = 0;
  }
  return {
    catalog,
    selected,
    needs,
    diff: planDiff(pre.previous?.skills, selected),
    previous: pre.previous,
    values,
    preserved: preservedLines(ctx),
    python,
    commit: pre.commit,
    linkState: ctx.options.noLink || ctx.configure ? { kind: "absent" } : inspectLink(ctx.link, ctx.target),
    missing,
    warnings,
    brokers: chosen,
    extras,
    extrasState: extrasState(extraDefs, selected, extras),
    leftovers: legacyLeftovers(ctx.environ, ctx.root),
  };
}

export type StepId = "deps" | "copy" | "link" | "smoke";

export type InstallEvent =
  | { type: "step:start"; step: StepId; label: string }
  | { type: "step:log"; step: StepId; line: string }
  | { type: "step:done"; step: StepId; detail?: string }
  | { type: "step:skip"; step: StepId; reason: string }
  | { type: "step:fail"; step: StepId; error: InstallError }
  | { type: "warning"; message: string }
  | { type: "note"; message: string };

export interface Summary {
  target: string;
  link: string | null;
  skills: SkillDiff;
  dependencies: { venv: string; installed: boolean };
  smoke: SmokeResult;
  warnings: string[];
  /** Every extra on or off after this run. */
  extras: ExtrasState;
  /** "copy" (files copied and linked) or "configure" (data dir only; Claude Code manages the files). */
  mode: "copy" | "configure";
  /** Where .env, installed.json and the venv live. */
  data: string;
  /** Informational lines: a data-dir move, old copies removed. */
  notes: string[];
}

export interface ExecuteHooks {
  onEvent?: (event: InstallEvent) => void;
  /** Asked once when the link path holds something else. */
  confirmLinkReplace: (question: string) => Promise<boolean>;
  /** Asked once when the pre-rename copy or link exists; omitted means keep them and warn. */
  confirmLegacyRemove?: (question: string) => Promise<boolean>;
}

/**
 * Run the plan: move pre-rename data, venv + deps, copy (or, configuring, settings only), link,
 * remove the pre-rename copy, smoke. Throws InstallError on a hard failure.
 */
export async function execute(ctx: Context, plan: Plan, hooks: ExecuteHooks): Promise<Summary> {
  const emit = (e: InstallEvent) => hooks.onEvent?.(e);
  const warnings = [...plan.warnings];
  const notes: string[] = [];
  const note = (message: string) => {
    notes.push(message);
    emit({ type: "note", message });
  };
  if (plan.missing.length) {
    throw new InstallError(`${plan.missing[0]} is required by the selected skills`, "pass it as a flag, export it, or run interactively");
  }
  try {
    const moved = migrateLegacyData(ctx.environ);
    if (moved) note(moved);
  } catch (err) {
    warnings.push(`could not move ${ctx.legacyData}: ${(err as Error).message}; scripts keep reading it until it moves`);
  }
  // Render every broker whose credentials are still complete, not just the ones the user
  // picked this run: switching brokers must never silently drop a still-valid credential pair.
  const brokersToRender = new Set([...plan.brokers, ...brokersFrom(plan.values)]);
  const envText = renderEnv(plan.values, plan.needs, plan.preserved, brokersToRender);

  const req = path.join(ctx.root, "requirements.txt");
  emit({ type: "step:start", step: "deps", label: "Python dependencies" });
  let deps;
  try {
    deps = await ensureDependencies(ctx.data, req, ctx.runner, plan.python.command, {
      onLine: (line) => emit({ type: "step:log", step: "deps", line }),
      onPhase: (phase) => {
        if (phase === "venv") emit({ type: "step:log", step: "deps", line: `creating virtualenv at ${path.join(ctx.data, "venv")}` });
        if (phase === "pip") emit({ type: "step:log", step: "deps", line: "pip install -r requirements.txt" });
      },
    });
  } catch (err) {
    emit({ type: "step:fail", step: "deps", error: asInstallError(err) });
    throw err;
  }
  emit({ type: "step:done", step: "deps", detail: deps.installed ? (deps.createdVenv ? "virtualenv created, packages installed" : "packages installed") : "already up to date" });

  const recordExtras = { ...plan.extras, ...plan.extrasState };
  emit({ type: "step:start", step: "copy", label: ctx.configure ? "Settings" : "Plugin files" });
  let diff: SkillDiff;
  try {
    if (ctx.configure) {
      diff = planDiff(plan.previous?.skills, plan.selected);
      writeConfig(ctx.data, envText, makeRecord(ctx.root, plan.selected, { commit: plan.commit, extras: recordExtras, mode: "configure" }));
    } else {
      materialize(ctx.root, ctx.target, plan.selected, envText, { commit: plan.commit, extras: recordExtras, configDir: ctx.data });
      diff = plan.diff; // against the record found in preflight, wherever it lived
    }
  } catch (err) {
    const e = err instanceof InstallError ? err : new InstallError(String((err as Error).message ?? err), "check the path is writable and the checkout is complete");
    emit({ type: "step:fail", step: "copy", error: e });
    throw e;
  }
  emit({
    type: "step:done",
    step: "copy",
    detail: ctx.configure ? `.env and extras → ${tildify(ctx.data, ctx.environ)}` : `${plan.selected.length} skills → ${tildify(ctx.target, ctx.environ)}`,
  });

  let linked: string | null = null;
  if (ctx.configure) {
    // Claude Code loads a /plugin install itself: nothing to link.
  } else if (ctx.options.noLink) {
    emit({ type: "step:skip", step: "link", reason: "--no-link" });
    warnings.push(`not linked; run: claude --plugin-dir ${ctx.target}`);
  } else {
    emit({ type: "step:start", step: "link", label: "Link into ~/.claude/skills" });
    try {
      linked = await linkPlugin(ctx.target, ctx.link, hooks.confirmLinkReplace);
      emit({ type: "step:done", step: "link", detail: tildify(ctx.link, ctx.environ) });
    } catch (err) {
      const msg = err instanceof InstallError ? err.message : String((err as Error).message ?? err);
      warnings.push(`could not link ${ctx.link}: ${msg}; run: claude --plugin-dir ${ctx.target}`);
      emit({ type: "step:skip", step: "link", reason: msg });
    }
  }

  if (plan.leftovers.length) {
    const shown = plan.leftovers.map((p) => tildify(p, ctx.environ)).join(", ");
    const ok = hooks.confirmLegacyRemove ? await hooks.confirmLegacyRemove(`remove the old finance-analyst copy (${shown}) so skills do not load twice? Your data stays.`) : false;
    if (ok) {
      try {
        const removed = removeLeftovers(plan.leftovers);
        if (removed.length) note(`removed the old finance-analyst copy: ${removed.map((p) => tildify(p, ctx.environ)).join(", ")}`);
      } catch (err) {
        warnings.push(`could not remove ${shown}: ${(err as Error).message}`);
      }
    } else {
      warnings.push(`the old finance-analyst copy is still at ${shown}; remove it (your data is elsewhere) or every skill loads twice`);
    }
  }

  let smokeRes: SmokeResult = { ...SMOKE_SKIPPED };
  if (ctx.options.noSmoke) {
    emit({ type: "step:skip", step: "smoke", reason: "--no-smoke" });
  } else {
    emit({ type: "step:start", step: "smoke", label: "Smoke test" });
    smokeRes = await smoke(ctx.target, deps.venvPython, plan.needs.has("brokerage") ? plan.brokers : new Set(), ctx.runner, (name, value) =>
      emit({ type: "step:log", step: "smoke", line: `${name}: ${value}` }),
    );
    if (smokeRes.imports === "failed") warnings.push(`dependency import failed; see ${path.join(ctx.data, "install.log")}`);
    if (smokeRes.status === "rejected") warnings.push("SnapTrade rejected the key or no brokerage is connected yet; run the connect skill");
    if (smokeRes.etrade === "rejected") warnings.push("E*Trade key not accepted (or ETRADE_CONSUMER_SECRET missing); check .env or re-run install.js");
    const failed = Object.values(smokeRes).includes("failed");
    emit({ type: "step:done", step: "smoke", detail: `imports ${smokeRes.imports}, dcf ${smokeRes.dcf}, status ${smokeRes.status}, etrade ${smokeRes.etrade}${failed ? " (see warnings)" : ""}` });
  }
  for (const w of warnings) emit({ type: "warning", message: w });
  return {
    target: ctx.target,
    link: linked,
    skills: diff,
    dependencies: { venv: deps.venvPython, installed: deps.installed },
    smoke: smokeRes,
    warnings,
    extras: plan.extrasState,
    mode: ctx.configure ? "configure" : "copy",
    data: ctx.data,
    notes,
  };
}

function asInstallError(err: unknown): InstallError {
  return err instanceof InstallError ? err : new InstallError(String((err as Error)?.message ?? err));
}

/** True when the target directory exists on disk (installed.json or not). */
export function targetExists(ctx: Context): boolean {
  return fs.existsSync(ctx.target);
}
