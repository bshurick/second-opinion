import type { Skill } from "./catalog.js";

export interface Resolution {
  /** Selected names in catalog order. */
  names: string[];
  /** Human notes explaining every automatic change. */
  notes: string[];
}

/**
 * Apply dependency rules to a selection.
 * Default: a selected skill pulls in what it depends on.
 * dropDependents: a missing dependency drops the skills that need it instead.
 */
export function resolveSelection(catalog: Skill[], selected: Iterable<string>, opts: { dropDependents?: boolean } = {}): Resolution {
  const byName = new Map(catalog.map((s) => [s.name, s]));
  const chosen = new Set(selected);
  for (const n of chosen) if (!byName.has(n)) throw new Error(`unknown skill: ${n}`);
  const notes: string[] = [];
  if (opts.dropDependents) {
    let changed = true;
    while (changed) {
      changed = false;
      for (const s of catalog) {
        if (!chosen.has(s.name)) continue;
        const missing = s.dependsOn.filter((d) => !chosen.has(d));
        if (missing.length) {
          chosen.delete(s.name);
          notes.push(`${s.name} needs ${missing.join(", ")}, which is not selected: dropped ${s.name}`);
          changed = true;
        }
      }
    }
  } else {
    const queue = catalog.filter((s) => chosen.has(s.name));
    while (queue.length) {
      const s = queue.shift()!;
      for (const d of s.dependsOn) {
        if (!chosen.has(d)) {
          chosen.add(d);
          notes.push(`${s.name} needs ${d}: added ${d}`);
          queue.push(byName.get(d)!);
        }
      }
    }
  }
  return { names: catalog.filter((s) => chosen.has(s.name)).map((s) => s.name), notes };
}

/**
 * Interactive toggle: flipping one skill keeps the set consistent.
 * Selecting adds dependencies; deselecting drops dependents (transitively).
 */
export function toggleSkill(catalog: Skill[], selected: ReadonlySet<string>, name: string): Resolution {
  const next = new Set(selected);
  if (next.has(name)) {
    next.delete(name);
    const dropped: string[] = [];
    let changed = true;
    while (changed) {
      changed = false;
      for (const s of catalog) {
        if (next.has(s.name) && s.dependsOn.some((d) => !next.has(d))) {
          next.delete(s.name);
          dropped.push(s.name);
          changed = true;
        }
      }
    }
    const notes = dropped.map((d) => `${d} needs ${name}: also deselected ${d}`);
    return { names: catalog.filter((s) => next.has(s.name)).map((s) => s.name), notes };
  }
  next.add(name);
  return resolveSelection(catalog, next);
}

export function parseList(text: string | undefined): string[] {
  return (text ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}
