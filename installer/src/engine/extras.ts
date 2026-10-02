import type { Extra, Skill } from "./catalog.js";
import { UsageError } from "./errors.js";
import type { InstalledRecord } from "./materialize.js";
import { parseList, resolveSelection, toggleSkill } from "./selection.js";

/** Every extra's key mapped to on (true) or off. */
export type ExtrasState = Record<string, boolean>;

/** `--extras follow_ups=off,trade-journal=on` → { follow_ups: false, "trade-journal": true }. */
export function parseExtrasFlag(raw: string, extras: Extra[]): Record<string, boolean> {
  const keys = extras.map((e) => e.key);
  const out: Record<string, boolean> = {};
  for (const item of parseList(raw)) {
    const eq = item.indexOf("=");
    const key = (eq < 0 ? item : item.slice(0, eq)).trim();
    const value = eq < 0 ? "" : item.slice(eq + 1).trim().toLowerCase();
    if (!keys.includes(key)) throw new UsageError(`--extras: unknown extra '${key}' (valid: ${keys.join(", ")})`);
    if (value !== "on" && value !== "off") throw new UsageError(`--extras: ${key} must be on or off, not '${value}'`);
    out[key] = value === "on";
  }
  return out;
}

/**
 * Non-skill extras before any flag: the previous record's switch when it has one, else the
 * declared default. Extras are opt-in, so a missing record (or one written before extras
 * existed) leaves them at their defaults, which are off; hooks/common.sh reads it the same way.
 */
export function nonSkillDefaults(extras: Extra[], previous: InstalledRecord | null): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const e of extras) {
    if (e.skill) continue;
    const prev = previous?.extras?.[e.key];
    out[e.key] = typeof prev === "boolean" ? prev : e.defaultOn;
  }
  return out;
}

/** Apply on/off changes: skill extras add (with dependencies) or remove the skill; non-skill extras set the switch. */
export function applyExtras(
  catalog: Skill[],
  extras: Extra[],
  selected: string[],
  nonSkill: Record<string, boolean>,
  changes: Record<string, boolean>,
): { selected: string[]; nonSkill: Record<string, boolean>; notes: string[] } {
  const byKey = new Map(extras.map((e) => [e.key, e]));
  let names = [...selected];
  const next = { ...nonSkill };
  const notes: string[] = [];
  for (const [key, on] of Object.entries(changes)) {
    const extra = byKey.get(key);
    if (!extra) throw new UsageError(`unknown extra '${key}'`);
    if (!extra.skill) {
      next[key] = on;
      continue;
    }
    if (names.includes(key) === on) continue;
    const r = toggleSkill(catalog, new Set(names), key);
    names = r.names;
    notes.push(...r.notes);
  }
  return { selected: resolveSelection(catalog, names).names, nonSkill: next, notes };
}

/** On/off for every extra, given the skill selection and the non-skill switches. */
export function extrasState(extras: Extra[], selected: string[], nonSkill: Record<string, boolean>): ExtrasState {
  const out: ExtrasState = {};
  for (const e of extras) out[e.key] = e.skill ? selected.includes(e.key) : Boolean(nonSkill[e.key]);
  return out;
}
