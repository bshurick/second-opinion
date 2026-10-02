import fs from "node:fs";
import path from "node:path";

export type Requirement = "brokerage" | "edgar";

export interface Skill {
  name: string;
  family: string;
  requires: Requirement[];
  dependsOn: string[];
  description: string;
  /** An optional extra: off unless chosen, offered on the installer's Extras step. */
  extra: boolean;
  /** Selected on a fresh install without selection flags. False only for extras declared default-off. */
  defaultOn: boolean;
}

/**
 * An optional feature the installer offers in plain words. A skill extra is a skill
 * installed or left out; a non-skill extra is a switch recorded in installed.json.
 */
export interface Extra {
  key: string;
  label: string;
  blurb: string;
  friction?: string;
  defaultOn: boolean;
  skill: boolean;
}

export const ALWAYS_SKILLS = ["setup"] as const;
export const KNOWN_REQUIREMENTS: Requirement[] = ["brokerage", "edgar"];

/** First sentence of the SKILL.md frontmatter description; '' if absent. */
export function skillDescription(root: string, name: string): string {
  const file = path.join(root, "skills", name, "SKILL.md");
  if (!fs.existsSync(file)) return "";
  const text = fs.readFileSync(file, "utf8");
  const m = /^description:\s*(.+)$/m.exec(text);
  if (!m) return "";
  const desc = m[1]!.trim();
  const first = desc.split(/(?<=[.!?])\s/, 1)[0] ?? desc;
  return first.trim();
}

function readCatalogFile(root: string): { skills: unknown[]; extras: unknown[] } {
  const raw = JSON.parse(fs.readFileSync(path.join(root, "skills.json"), "utf8")) as unknown;
  if (typeof raw !== "object" || raw === null || !Array.isArray((raw as { skills?: unknown }).skills)) {
    throw new Error("skills.json is missing 'skills'");
  }
  const extras = (raw as { extras?: unknown }).extras;
  return { skills: (raw as { skills: unknown[] }).skills, extras: Array.isArray(extras) ? extras : [] };
}

export function loadCatalog(root: string): Skill[] {
  const entries = readCatalogFile(root).skills;
  return entries.map((entry, i) => {
    if (typeof entry !== "object" || entry === null) throw new Error(`skills.json entry ${i} is not an object`);
    const e = entry as Record<string, unknown>;
    for (const key of ["name", "family"]) {
      if (typeof e[key] !== "string" || !e[key]) throw new Error(`skills.json entry ${i} is missing '${key}'`);
    }
    const requires = (Array.isArray(e.requires) ? e.requires : []) as string[];
    for (const r of requires) {
      if (!KNOWN_REQUIREMENTS.includes(r as Requirement)) throw new Error(`skills.json entry ${i}: unknown requirement '${r}'`);
    }
    return {
      name: e.name as string,
      family: e.family as string,
      requires: requires as Requirement[],
      dependsOn: (Array.isArray(e.depends_on) ? e.depends_on : []) as string[],
      description: skillDescription(root, e.name as string),
      extra: e.extra === true,
      defaultOn: e.extra === true ? e.default === true : true,
    };
  });
}

function extraText(e: Record<string, unknown>, key: string, where: string): string {
  if (typeof e[key] !== "string" || !e[key]) throw new Error(`skills.json ${where} is missing '${key}'`);
  return e[key] as string;
}

/** Skill extras in catalog order, then the non-skill extras from the top-level "extras" list. */
export function loadExtras(root: string): Extra[] {
  const file = readCatalogFile(root);
  const names = new Set(loadCatalog(root).map((s) => s.name));
  const out: Extra[] = [];
  for (const entry of file.skills) {
    const e = entry as Record<string, unknown>;
    if (e.extra !== true) continue;
    const where = `skill '${String(e.name)}'`;
    out.push({
      key: e.name as string,
      label: extraText(e, "label", where),
      blurb: extraText(e, "blurb", where),
      ...(typeof e.friction === "string" && e.friction ? { friction: e.friction } : {}),
      defaultOn: e.default === true,
      skill: true,
    });
  }
  file.extras.forEach((entry, i) => {
    if (typeof entry !== "object" || entry === null) throw new Error(`skills.json extras entry ${i} is not an object`);
    const e = entry as Record<string, unknown>;
    const key = extraText(e, "key", `extras entry ${i}`);
    if (names.has(key)) throw new Error(`skills.json: extra '${key}' has the same name as a skill`);
    out.push({
      key,
      label: extraText(e, "label", `extra '${key}'`),
      blurb: extraText(e, "blurb", `extra '${key}'`),
      ...(typeof e.friction === "string" && e.friction ? { friction: e.friction } : {}),
      defaultOn: e.default === true,
      skill: false,
    });
  });
  return out;
}

/** Skills that are not extras, in catalog order. */
export function coreSkills(catalog: Skill[]): Skill[] {
  return catalog.filter((s) => !s.extra);
}

/** Families in catalog order. */
export function families(catalog: Skill[]): string[] {
  const out: string[] = [];
  for (const s of catalog) if (!out.includes(s.family)) out.push(s.family);
  return out;
}

export function requirementsFor(catalog: Skill[], names: Iterable<string>): Set<Requirement> {
  const wanted = new Set(names);
  const out = new Set<Requirement>();
  for (const s of catalog) if (wanted.has(s.name)) for (const r of s.requires) out.add(r);
  return out;
}
