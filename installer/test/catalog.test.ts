import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { coreSkills, families, loadCatalog, loadExtras, requirementsFor, skillDescription } from "../src/engine/catalog.js";
import { extrasRoot, miniRoot, REAL_ROOT, tmpDir, write } from "./helpers.js";

describe("catalog", () => {
  it("reads the real catalog with a description for every skill", () => {
    const cat = loadCatalog(REAL_ROOT);
    const raw = JSON.parse(fs.readFileSync(path.join(REAL_ROOT, "skills.json"), "utf8"));
    expect(cat.length).toBe(raw.skills.length);
    for (const s of cat) {
      expect(s.description, s.name).not.toBe("");
      expect(s.description.endsWith(".")).toBe(true);
    }
    expect(families(cat)).toEqual(["Getting started", "Accounts and holdings", "History and decisions", "Planning", "Research and markets", "Learning"]);
    const journal = cat.find((s) => s.name === "trade-journal")!;
    expect(journal.dependsOn).toEqual(["trade-review"]);
  });

  it("takes the first sentence of the description", () => {
    const root = miniRoot();
    expect(skillDescription(root, "a")).toBe("Skill A does things.");
    expect(skillDescription(root, "c")).toBe("Skill C reads EDGAR!");
    expect(skillDescription(root, "nope")).toBe("");
  });

  it("rejects a catalog without skills or with a malformed entry", () => {
    const dir = tmpDir();
    write(path.join(dir, "skills.json"), JSON.stringify({ nope: [] }));
    expect(() => loadCatalog(dir)).toThrow("missing 'skills'");
    fs.writeFileSync(path.join(dir, "skills.json"), JSON.stringify({ skills: [{ name: "x" }] }));
    expect(() => loadCatalog(dir)).toThrow("missing 'family'");
    fs.writeFileSync(path.join(dir, "skills.json"), JSON.stringify({ skills: [{ name: "x", family: "f", requires: ["magic"] }] }));
    expect(() => loadCatalog(dir)).toThrow("unknown requirement");
  });

  it("loads extras: skill extras first, then non-skill extras", () => {
    const root = extrasRoot();
    const cat = loadCatalog(root);
    expect(cat.find((s) => s.name === "c")).toMatchObject({ extra: true, defaultOn: false });
    expect(cat.find((s) => s.name === "a")).toMatchObject({ extra: false, defaultOn: true });
    expect(loadExtras(root)).toEqual([
      { key: "c", label: "Skill C extra", blurb: "Does C.", friction: "Adds a step.", defaultOn: false, skill: true },
      { key: "tips", label: "Tips", blurb: "Shows tips.", defaultOn: false, skill: false },
    ]);
    expect(coreSkills(cat).map((s) => s.name)).toEqual(["a", "b"]);
    expect(loadExtras(miniRoot())).toEqual([]);
  });

  it("the real catalog marks trade-journal and financial-education as extras and declares follow_ups", () => {
    const extras = loadExtras(REAL_ROOT);
    expect(extras.map((e) => e.key)).toEqual(["trade-journal", "financial-education", "follow_ups"]);
    for (const e of extras) {
      expect(e.defaultOn, e.key).toBe(false);
      expect(e.label && e.blurb, e.key).toBeTruthy();
    }
    expect(extras.find((e) => e.key === "trade-journal")!.friction).toMatch(/every buy/);
  });

  it("rejects an extra without a label or blurb, or a non-skill extra that shadows a skill", () => {
    const dir = tmpDir();
    write(path.join(dir, "skills.json"), JSON.stringify({ skills: [{ name: "x", family: "f", extra: true, blurb: "b" }] }));
    expect(() => loadExtras(dir)).toThrow("missing 'label'");
    fs.writeFileSync(path.join(dir, "skills.json"), JSON.stringify({ skills: [{ name: "x", family: "f" }], extras: [{ key: "t", label: "T" }] }));
    expect(() => loadExtras(dir)).toThrow("missing 'blurb'");
    fs.writeFileSync(path.join(dir, "skills.json"), JSON.stringify({ skills: [{ name: "x", family: "f" }], extras: [{ key: "x", label: "T", blurb: "b" }] }));
    expect(() => loadExtras(dir)).toThrow("extra 'x' has the same name as a skill");
  });

  it("collects requirements for a selection", () => {
    const cat = loadCatalog(miniRoot());
    expect([...requirementsFor(cat, ["b"])]).toEqual([]);
    expect([...requirementsFor(cat, ["a", "c"])].sort()).toEqual(["brokerage", "edgar"]);
  });
});
