import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runPlain } from "../src/drivers/plain.js";
import { loadCatalog, loadExtras } from "../src/engine/catalog.js";
import { applyExtras, extrasState, nonSkillDefaults, parseExtrasFlag } from "../src/engine/extras.js";
import { initialSelection } from "../src/engine/installer.js";
import { readInstalled, type InstalledRecord } from "../src/engine/materialize.js";
import { Capture, extrasRoot, FakeRunner, opts, tmpDir, write } from "./helpers.js";

const record = (r: Partial<InstalledRecord>): InstalledRecord => ({ skills: [], source_path: "", source_commit: null, installer_version: "", installed_at: "", ...r });
const KEYS = ["--snaptrade-client-id", "id", "--snaptrade-consumer-key", "secret-key-1234"];

describe("parseExtrasFlag", () => {
  const ex = loadExtras(extrasRoot());
  it("parses key=on|off pairs", () => {
    expect(parseExtrasFlag("c=on, tips=off", ex)).toEqual({ c: true, tips: false });
    expect(parseExtrasFlag("", ex)).toEqual({});
  });
  it("names the valid keys and values on error", () => {
    expect(() => parseExtrasFlag("nope=on", ex)).toThrow("--extras: unknown extra 'nope' (valid: c, tips)");
    expect(() => parseExtrasFlag("c=maybe", ex)).toThrow("--extras: c must be on or off, not 'maybe'");
    expect(() => parseExtrasFlag("c", ex)).toThrow("--extras: c must be on or off, not ''");
  });
});

describe("nonSkillDefaults", () => {
  const ex = loadExtras(extrasRoot());
  it("fresh installs use the declared defaults", () => expect(nonSkillDefaults(ex, null)).toEqual({ tips: false }));
  it("records from before extras leave non-skill extras off (extras are opt-in)", () => expect(nonSkillDefaults(ex, record({ skills: ["a"] }))).toEqual({ tips: false }));
  it("records with extras are read; a key missing from the record takes its default", () => {
    expect(nonSkillDefaults(ex, record({ skills: ["a"], extras: { tips: true } }))).toEqual({ tips: true });
    expect(nonSkillDefaults(ex, record({ skills: ["a"], extras: {} }))).toEqual({ tips: false });
  });
});

describe("applyExtras", () => {
  const root = extrasRoot();
  const cat = loadCatalog(root);
  const ex = loadExtras(root);
  it("turning a skill extra on pulls its dependency in with a note", () => {
    const r = applyExtras(cat, ex, [], { tips: false }, { c: true });
    expect(r.selected).toEqual(["a", "c"]);
    expect(r.notes).toEqual(["c needs a: added a"]);
  });
  it("turning a skill extra off removes it; non-skill keys set the switch", () => {
    const r = applyExtras(cat, ex, ["a", "b", "c"], { tips: false }, { c: false, tips: true });
    expect(r.selected).toEqual(["a", "b"]);
    expect(r.nonSkill).toEqual({ tips: true });
  });
  it("extrasState reports every extra", () => {
    expect(extrasState(ex, ["a", "c"], { tips: false })).toEqual({ c: true, tips: false });
  });
});

describe("initialSelection with extras", () => {
  const cat = loadCatalog(extrasRoot());
  it("a fresh install selects core skills only", () => expect(initialSelection(cat, opts([]), null).names).toEqual(["a", "b"]));
  it("--all still selects every skill, extras included", () => expect(initialSelection(cat, opts(["--all"]), null).names).toEqual(["a", "b", "c"]));
});

describe("readInstalled extras", () => {
  it("keeps boolean extras and drops anything else", () => {
    const dir = tmpDir();
    write(path.join(dir, "installed.json"), JSON.stringify({ skills: ["a"], extras: { tips: false, junk: "yes" } }));
    expect(readInstalled(dir)!.extras).toEqual({ tips: false });
    write(path.join(dir, "installed.json"), JSON.stringify({ skills: ["a"] }));
    expect(readInstalled(dir)!.extras).toBeUndefined();
  });
});

function scene() {
  const root = extrasRoot();
  const home = tmpDir("sf-home-");
  const environ = { HOME: home, SECOND_OPINION_DATA: path.join(home, "data") };
  const target = path.join(home, ".claude", "plugins", "second-opinion");
  return { root, environ, target, data: environ.SECOND_OPINION_DATA };
}
/** The record now lives in the data dir, where it survives plugin updates. */
const installed = (data: string) => JSON.parse(fs.readFileSync(path.join(data, "installed.json"), "utf8"));

describe("plain driver with extras", () => {
  it("a fresh install leaves extras off, records them, and reports them", async () => {
    const { root, environ, target, data } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b"], extras: { c: false, tips: false }, mode: "copy" });
    expect(fs.existsSync(path.join(target, "installed.json"))).toBe(false);
    expect(JSON.parse(io.out).extras).toEqual({ c: false, tips: false });
  });

  it("an install from before extras keeps its skills; non-skill extras stay off (opt-in)", async () => {
    const { root, environ, target, data } = scene();
    write(path.join(target, "installed.json"), JSON.stringify({ skills: ["a", "b", "c"], source_path: "", source_commit: null, installer_version: "2.0.0", installed_at: "" }));
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b", "c"], extras: { tips: false } });
    expect(JSON.parse(io.out).extras).toEqual({ c: true, tips: false });
  });

  it("--extras applies on top of --skills and pulls dependencies", async () => {
    const { root, environ, data } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--skills", "b", "--extras", "c=on,tips=on", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b", "c"], extras: { tips: true } });
  });

  it("--extras on an existing install changes only the extras", async () => {
    const { root, environ, data } = scene();
    await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture());
    const io = new Capture();
    expect(await runPlain(root, opts(["--extras", "c=off,tips=on", "--json", "--yes"]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b"], extras: { tips: true } });
    expect(JSON.parse(io.out).skills).toEqual({ installed: [], removed: ["c"], refreshed: ["a", "b"] });
  });

  it("an unknown extra is a usage error (exit 2)", async () => {
    const { root, environ } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--extras", "bogus=on", "--json", "--yes"]), environ, new FakeRunner(), io)).toBe(2);
    expect(io.err).toContain("unknown extra 'bogus'");
  });

  it("dry-run JSON lists extras", async () => {
    const { root, environ } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--dry-run", "--json", "--extras", "tips=on"]), environ, new FakeRunner(), io)).toBe(0);
    expect(JSON.parse(io.out).extras).toEqual({ c: false, tips: true });
  });
});
