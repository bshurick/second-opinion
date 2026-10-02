import { Box, Static, Text, useApp } from "ink";
import path from "node:path";
import { useRef, useState } from "react";
import { coreSkills, loadCatalog, loadExtras, type Extra, type Skill } from "../engine/catalog.js";
import { brokersFrom, type BrokerChoice, type EnvValues } from "../engine/env.js";
import { InstallError } from "../engine/errors.js";
import { applyExtras, extrasState, nonSkillDefaults, type ExtrasState } from "../engine/extras.js";
import { buildPlan, initialExtras, initialSelection, initialValues, INSTALLER_VERSION, type Context, type Plan, type Preflight, type Summary } from "../engine/installer.js";
import type { UninstallResult } from "../engine/link.js";
import { tildify } from "../engine/paths.js";
import { Header } from "./components/Header.js";
import type { StepView } from "./components/Steps.js";
import { CredentialsScreen } from "./screens/CredentialsScreen.js";
import { DoneScreen } from "./screens/DoneScreen.js";
import { ErrorScreen } from "./screens/ErrorScreen.js";
import { ExtrasScreen } from "./screens/ExtrasScreen.js";
import { ModeScreen, type Mode } from "./screens/ModeScreen.js";
import { PreflightScreen } from "./screens/PreflightScreen.js";
import { ProgressScreen } from "./screens/ProgressScreen.js";
import { ReviewScreen, type ReviewChoice } from "./screens/ReviewScreen.js";
import { SkillPickerScreen } from "./screens/SkillPickerScreen.js";
import { UninstallScreen } from "./screens/UninstallScreen.js";
import { color, glyph } from "./theme.js";

type Phase =
  | { name: "preflight" }
  | { name: "mode"; pre: Preflight }
  /** scope "core": the wizard's first step (extras hidden); "all": every skill, extras included. */
  | { name: "pick"; pre: Preflight; initial: string[]; scope: "core" | "all"; nonSkill: Record<string, boolean> }
  /** base: the skill selection the extras are applied to. */
  | { name: "extras"; pre: Preflight; base: string[]; nonSkill: Record<string, boolean>; state: ExtrasState; back: () => void }
  | { name: "credentials"; pre: Preflight; selected: string[]; nonSkill: Record<string, boolean> }
  | { name: "review"; pre: Preflight; plan: Plan }
  | { name: "progress"; pre: Preflight; plan: Plan; replaceLink: boolean }
  | { name: "done"; summary: Summary; updated: boolean }
  | { name: "uninstall" }
  | { name: "uninstalled"; result: UninstallResult | null }
  | { name: "error"; message: string; hint: string };

interface Props {
  ctx: Context;
  /** Source checkout commit, resolved before the first render so the static header can show it. */
  commit: string | null;
  onExit: (code: number) => void;
}

/** A completed step, kept above the live screen. */
interface Done {
  id: number;
  text: string;
  tint?: string;
}

export function App({ ctx: initialCtx, commit, onExit }: Props) {
  const { exit } = useApp();
  const [ctx, setCtx] = useState(initialCtx);
  const [phase, setPhase] = useState<Phase>({ name: "preflight" });
  const [history, setHistory] = useState<Done[]>([]);
  const [catalog] = useState<Skill[]>(() => loadCatalog(initialCtx.root));
  const [extras] = useState<Extra[]>(() => loadExtras(initialCtx.root));
  const core = coreSkills(catalog);
  const coreNames = new Set(core.map((s) => s.name));
  const nextId = useRef(0);

  const finish = (code: number) => {
    onExit(code);
    exit();
  };
  const record = (text: string, tint: string = color.ok) => setHistory((h) => [...h, { id: nextId.current++, text, tint }]);
  const fail = (message: string, hint: string) => {
    setPhase({ name: "error", message, hint });
    setTimeout(() => finish(1), 50);
  };

  const afterPreflight = (pre: Preflight) => {
    const py = pre.python.found!;
    record(`Python ${py.version} ${glyph.dot} ${py.command.join(" ")}`);
    if (ctx.options.uninstall && ctx.configure) return fail("this copy is managed by Claude Code", "remove it with /plugin uninstall second-opinion@second-opinion");
    if (ctx.options.uninstall) return setPhase({ name: "uninstall" });
    if (ctx.configure) return startConfigure(pre);
    const sel = initialSelection(catalog, ctx.options, pre.previous);
    if (pre.previous) {
      record(`Existing install ${glyph.dot} ${pre.previous.skills.length} skills`, color.dim);
      if (sel.explicit || ctx.options.extras !== undefined) return startExplicit(pre, sel.names);
      return setPhase({ name: "mode", pre });
    }
    record("Fresh install", color.dim);
    if (sel.explicit || ctx.options.extras !== undefined) return startExplicit(pre, sel.names);
    setPhase({ name: "pick", pre, initial: sel.names.filter((n) => coreNames.has(n)), scope: "core", nonSkill: nonSkillDefaults(extras, null) });
  };

  /** A /plugin install ships every skill: extras (unless --extras chose them), then keys. */
  const startConfigure = (pre: Preflight) => {
    let sel;
    try {
      sel = initialSelection(catalog, ctx.options, pre.previous, true);
    } catch (err) {
      return fail((err as Error).message, "run node install.js --extras KEY=on|off instead");
    }
    record(pre.previous ? "Configuring your plugin install" : "Configuring a new plugin install", color.dim);
    if (ctx.options.extras !== undefined) return startExplicit(pre, sel.names);
    openExtras(pre, sel.names, nonSkillDefaults(extras, pre.previous), () => finish(0));
  };

  /** Flags chose the selection: apply --extras on top and go straight to credentials. */
  const startExplicit = (pre: Preflight, names: string[]) => {
    const ex = initialExtras(ctx.options, extras, catalog, names, pre.previous);
    for (const n of ex.notes) record(n, color.dim);
    startCredentials(pre, ex.selected, ex.nonSkill);
  };

  const onMode = (pre: Preflight, mode: Mode) => {
    if (mode === "quit") return finish(0);
    if (mode === "uninstall") return setPhase({ name: "uninstall" });
    const sel = initialSelection(catalog, ctx.options, pre.previous);
    const nonSkill = nonSkillDefaults(extras, pre.previous);
    if (mode === "update") {
      record(`Skills ${glyph.dot} keeping ${sel.names.length}`);
      return startCredentials(pre, sel.names, nonSkill);
    }
    if (mode === "extras") return openExtras(pre, sel.names, nonSkill, () => setPhase({ name: "mode", pre }));
    setPhase({ name: "pick", pre, initial: sel.names, scope: "all", nonSkill });
  };

  const openExtras = (pre: Preflight, base: string[], nonSkill: Record<string, boolean>, back: () => void) =>
    setPhase({ name: "extras", pre, base, nonSkill, state: extrasState(extras, base, nonSkill), back });

  const startCredentials = (pre: Preflight, selected: string[], nonSkill: Record<string, boolean>) => setPhase({ name: "credentials", pre, selected, nonSkill });

  const recordExtras = (state: ExtrasState) => {
    const on = extras.filter((e) => state[e.key]).map((e) => e.label);
    record(`Extras ${glyph.dot} ${on.length ? on.join(", ") : "all off"}`);
  };

  const onPicked = (pre: Preflight, selected: string[], scope: "core" | "all", nonSkill: Record<string, boolean>) => {
    if (scope === "core" && extras.length) {
      // The core step keeps any skill extras already chosen (after Back from review) for the extras step.
      return openExtras(pre, selected, nonSkill, () => setPhase({ name: "pick", pre, initial: selected, scope: "core", nonSkill }));
    }
    record(`Skills ${glyph.dot} ${selected.length} of ${catalog.length} selected`);
    startCredentials(pre, selected, nonSkill);
  };

  const onExtras = (pre: Preflight, base: string[], nonSkill: Record<string, boolean>, state: ExtrasState) => {
    const r = applyExtras(catalog, extras, base, nonSkill, state);
    recordExtras(extrasState(extras, r.selected, r.nonSkill));
    for (const n of r.notes) record(n, color.dim);
    if (!ctx.configure) record(`Skills ${glyph.dot} ${r.selected.length} of ${catalog.length} selected`);
    startCredentials(pre, r.selected, r.nonSkill);
  };

  const onCustomize = (pre: Preflight, base: string[], nonSkill: Record<string, boolean>, state: ExtrasState) => {
    const r = applyExtras(catalog, extras, base, nonSkill, state);
    setPhase({ name: "pick", pre, initial: r.selected, scope: "all", nonSkill: r.nonSkill });
  };

  const onCredentials = (pre: Preflight, selected: string[], nonSkill: Record<string, boolean>, values: EnvValues, brokers: Set<BrokerChoice>) => {
    const plan = buildPlan(ctx, pre, pre.python.found!, selected, values, brokers, nonSkill);
    if (plan.needs.size) {
      const parts = [
        ...(plan.brokers.has("snaptrade") ? ["SnapTrade key set"] : []),
        ...(plan.brokers.has("etrade") ? ["E*Trade key set"] : []),
        ...(plan.needs.has("edgar") ? [plan.values.EDGAR_USER_AGENT ? "EDGAR contact set" : "EDGAR contact skipped"] : []),
      ];
      record(`Credentials ${glyph.dot} ${parts.join(", ")}`);
    }
    setPhase({ name: "review", pre, plan });
  };

  const onReview = (pre: Preflight, plan: Plan, choice: ReviewChoice) => {
    switch (choice) {
      case "quit":
        return finish(0);
      case "back":
        setHistory((h) => h.filter((d) => !d.text.startsWith("Skills") && !d.text.startsWith("Credentials") && !d.text.startsWith("Extras")));
        if (ctx.configure) return openExtras(pre, plan.selected, plan.extras, () => finish(0));
        if (!plan.previous) return setPhase({ name: "pick", pre, initial: plan.selected, scope: "core", nonSkill: plan.extras });
        return setPhase({ name: "pick", pre, initial: plan.selected, scope: "all", nonSkill: plan.extras });
      case "install-no-link": {
        const next = { ...ctx, options: { ...ctx.options, noLink: true } };
        setCtx(next);
        return setPhase({ name: "progress", pre, plan: buildPlan(next, pre, plan.python, plan.selected, plan.values, plan.brokers, plan.extras), replaceLink: false });
      }
      case "install-replace-link":
        return setPhase({ name: "progress", pre, plan, replaceLink: true });
      default:
        return setPhase({ name: "progress", pre, plan, replaceLink: false });
    }
  };

  const onInstalled = (plan: Plan, summary: Summary, steps: StepView[]) => {
    for (const s of steps) {
      if (s.status === "done") record(`${s.label}${s.detail ? ` ${glyph.dot} ${s.detail}` : ""}`);
      else if (s.status === "skipped") record(`${s.label} ${glyph.dot} skipped (${s.detail ?? ""})`, color.dim);
    }
    setPhase({ name: "done", summary, updated: Boolean(plan.previous) });
    setTimeout(() => finish(0), 50);
  };

  const onUninstalled = (result: UninstallResult | null) => {
    setPhase({ name: "uninstalled", result });
    setTimeout(() => finish(0), 50);
  };

  return (
    <Box flexDirection="column">
      <Static items={[{ id: -1, text: "" }, ...history]}>
        {(item) =>
          item.id === -1 ? (
            <Header key="header" version={INSTALLER_VERSION} commit={commit} target={tildify(ctx.target, ctx.environ)} data={tildify(ctx.data, ctx.environ)} link={tildify(ctx.link, ctx.environ)} configure={ctx.configure} />
          ) : (
            <Text key={item.id} color={item.tint}>
              {glyph.check} {item.text}
            </Text>
          )
        }
      </Static>
      <Box flexDirection="column" marginTop={history.length ? 1 : 0}>
        {phase.name === "preflight" ? <PreflightScreen ctx={ctx} onDone={afterPreflight} onFail={fail} /> : null}
        {phase.name === "mode" ? <ModeScreen previous={phase.pre.previous!} onSelect={(m) => onMode(phase.pre, m)} /> : null}
        {phase.name === "pick" ? (
          <SkillPickerScreen
            key={phase.scope}
            catalog={phase.scope === "core" ? core : catalog}
            title={phase.scope === "core" ? "Choose the core skills" : undefined}
            initial={phase.scope === "core" ? phase.initial.filter((n) => coreNames.has(n)) : phase.initial}
            onDone={(s) =>
              onPicked(phase.pre, phase.scope === "core" ? [...s, ...phase.initial.filter((n) => !coreNames.has(n))] : s, phase.scope, phase.nonSkill)
            }
            onCancel={phase.pre.previous ? () => setPhase({ name: "mode", pre: phase.pre }) : undefined}
          />
        ) : null}
        {phase.name === "extras" ? (
          <ExtrasScreen
            extras={extras}
            initial={phase.state}
            onDone={(state) => onExtras(phase.pre, phase.base, phase.nonSkill, state)}
            onCustomize={ctx.configure ? undefined : (state) => onCustomize(phase.pre, phase.base, phase.nonSkill, state)}
            onCancel={phase.back}
          />
        ) : null}
        {phase.name === "credentials" ? (
          <CredentialsScreen
            key={phase.selected.join(",")}
            needs={buildPlan(ctx, phase.pre, phase.pre.python.found!, phase.selected, initialValues(ctx)).needs}
            existing={initialValues(ctx)}
            brokers={brokersFrom(initialValues(ctx))}
            acceptDefaults={ctx.options.yes}
            onDone={(values, brokers) => onCredentials(phase.pre, phase.selected, phase.nonSkill, values, brokers)}
            onCancel={() =>
              ctx.configure
                ? openExtras(phase.pre, phase.selected, phase.nonSkill, () => finish(0))
                : setPhase({ name: "pick", pre: phase.pre, initial: phase.selected, scope: phase.pre.previous ? "all" : "core", nonSkill: phase.nonSkill })
            }
          />
        ) : null}
        {phase.name === "review" ? <ReviewScreen ctx={ctx} plan={phase.plan} onChoose={(c) => onReview(phase.pre, phase.plan, c)} /> : null}
        {phase.name === "progress" ? (
          <ProgressScreen ctx={ctx} plan={phase.plan} replaceLink={phase.replaceLink} onDone={(s, steps) => onInstalled(phase.plan, s, steps)} onFail={(e: InstallError) => fail(e.message, e.hint)} />
        ) : null}
        {phase.name === "done" ? <DoneScreen ctx={ctx} summary={phase.summary} updated={phase.updated} /> : null}
        {phase.name === "uninstall" ? <UninstallScreen ctx={ctx} onDone={onUninstalled} onFail={(e) => fail(e.message, e.hint)} /> : null}
        {phase.name === "uninstalled" && phase.result === null ? <Text color={color.dim}>Nothing changed.</Text> : null}
        {phase.name === "error" ? <ErrorScreen message={phase.message} hint={phase.hint} /> : null}
      </Box>
    </Box>
  );
}
