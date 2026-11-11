import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runPlain } from "../src/drivers/plain.js";
import { loadCatalog, loadExtras } from "../src/engine/catalog.js";
import { applyExtras, extrasState, nonSkillDefaults, parseExtrasFlag } from "../src/engine/extras.js";
import { initialSelection } from "../src/engine/installer.js";
import { readInstalled, readRecord, type InstalledRecord } from "../src/engine/materialize.js";
import { Capture, extrasRoot, FakeRunner, opts, tmpDir, write } from "./helpers.js";

const record = (r: Partial<InstalledRecord>): InstalledRecord => ({ skills: [], source_path: "", source_commit: null, installer_version: "", installed_at: "", ...r });
const KEYS = ["--snaptrade-client-id", "id", "--snaptrade-consumer-key", "secret-key-1234"];

describe("parseExtrasFlag", () => {
  const ex = loadExtras(extrasRoot());
  it("parses key=on|off pairs", () => {
    expect(parseExtrasFlag("c=on, follow_ups=off", ex)).toEqual({ c: true, follow_ups: false });
    expect(parseExtrasFlag("", ex)).toEqual({});
  });
  it("names the valid keys and values on error", () => {
    expect(() => parseExtrasFlag("nope=on", ex)).toThrow("--extras: unknown extra 'nope' (valid: c, follow_ups)");
    expect(() => parseExtrasFlag("c=maybe", ex)).toThrow("--extras: c must be on or off, not 'maybe'");
    expect(() => parseExtrasFlag("c", ex)).toThrow("--extras: c must be on or off, not ''");
  });
});

describe("nonSkillDefaults", () => {
  const ex = loadExtras(extrasRoot());
  it("fresh installs use the declared defaults", () => expect(nonSkillDefaults(ex, null)).toEqual({ follow_ups: false }));
  it("records from before extras leave non-skill extras off (extras are opt-in)", () => expect(nonSkillDefaults(ex, record({ skills: ["a"] }))).toEqual({ follow_ups: false }));
  it("records with extras are read; a key missing from the record takes its default", () => {
    expect(nonSkillDefaults(ex, record({ skills: ["a"], extras: { follow_ups: true } }))).toEqual({ follow_ups: true });
    expect(nonSkillDefaults(ex, record({ skills: ["a"], extras: {} }))).toEqual({ follow_ups: false });
  });
});

describe("applyExtras", () => {
  const root = extrasRoot();
  const cat = loadCatalog(root);
  const ex = loadExtras(root);
  it("turning a skill extra on pulls its dependency in with a note", () => {
    const r = applyExtras(cat, ex, [], { follow_ups: false }, { c: true });
    expect(r.selected).toEqual(["a", "c"]);
    expect(r.notes).toEqual(["c needs a: added a"]);
  });
  it("turning a skill extra off removes it; non-skill keys set the switch", () => {
    const r = applyExtras(cat, ex, ["a", "b", "c"], { follow_ups: false }, { c: false, follow_ups: true });
    expect(r.selected).toEqual(["a", "b"]);
    expect(r.nonSkill).toEqual({ follow_ups: true });
  });
  it("extrasState reports every extra", () => {
    expect(extrasState(ex, ["a", "c"], { follow_ups: false })).toEqual({ c: true, follow_ups: false });
  });
});

describe("initialSelection with extras", () => {
  const cat = loadCatalog(extrasRoot());
  it("a fresh install selects core skills only", () => expect(initialSelection(cat, opts([]), null).names).toEqual(["a", "b"]));
  it("--all still selects every skill, extras included", () => expect(initialSelection(cat, opts(["--all"]), null).names).toEqual(["a", "b", "c"]));
});

describe("previous switches from settings.json", () => {
  it("settings.json wins over a legacy installed.json extras", () => {
    const dir = tmpDir();
    write(path.join(dir, "installed.json"), JSON.stringify({ skills: ["a"], extras: { follow_ups: false, "trade-journal": true } }));
    write(path.join(dir, "settings.json"), JSON.stringify({ schema: 1, replies: { follow_ups: true }, guardrails: { pre_buy_check: false } }));
    expect(readRecord([dir])!.extras).toEqual({ follow_ups: true, "trade-journal": false });
    expect(nonSkillDefaults(loadExtras(extrasRoot()), readRecord([dir]))).toEqual({ follow_ups: true });
  });
  it("a legacy installed.json extras still counts when there is no settings.json", () => {
    const dir = tmpDir();
    write(path.join(dir, "installed.json"), JSON.stringify({ skills: ["a"], extras: { follow_ups: true } }));
    expect(readRecord([dir])!.extras).toEqual({ follow_ups: true });
  });
});

describe("readInstalled extras", () => {
  it("keeps boolean extras and drops anything else", () => {
    const dir = tmpDir();
    write(path.join(dir, "installed.json"), JSON.stringify({ skills: ["a"], extras: { follow_ups: false, junk: "yes" } }));
    expect(readInstalled(dir)!.extras).toEqual({ follow_ups: false });
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
const settings = (data: string) => JSON.parse(fs.readFileSync(path.join(data, "settings.json"), "utf8"));
const installed = (data: string) => JSON.parse(fs.readFileSync(path.join(data, "installed.json"), "utf8"));

describe("a skill extra that is on by default", () => {
  const defaultOnRoot = () => {
    const root = extrasRoot();
    const file = path.join(root, "skills.json");
    const catalog = JSON.parse(fs.readFileSync(file, "utf8"));
    catalog.skills.find((s: { name: string }) => s.name === "c").default = true;
    fs.writeFileSync(file, JSON.stringify(catalog));
    return root;
  };

  it("is selected on a fresh install", () => {
    expect(initialSelection(loadCatalog(defaultOnRoot()), opts([]), null).names).toContain("c");
  });

  it("stays off when an existing install has it off", () => {
    const previous = record({ skills: ["a", "b"], extras: { c: false } });
    expect(initialSelection(loadCatalog(defaultOnRoot()), opts([]), previous).names).not.toContain("c");
    expect(initialSelection(loadCatalog(defaultOnRoot()), opts([]), previous, true).names).not.toContain("c");
  });
});

describe("plain driver with extras", () => {
  it("a fresh install leaves extras off, records them, and reports them", async () => {
    const { root, environ, target, data } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b"], mode: "copy" });
    expect(installed(data).extras).toBeUndefined();
    expect(settings(data).replies.follow_ups).toBe(false);
    expect(fs.existsSync(path.join(target, "installed.json"))).toBe(false);
    expect(JSON.parse(io.out).extras).toEqual({ c: false, follow_ups: false });
  });

  it("an install from before extras keeps its skills; non-skill extras stay off (opt-in)", async () => {
    const { root, environ, target, data } = scene();
    write(path.join(target, "installed.json"), JSON.stringify({ skills: ["a", "b", "c"], source_path: "", source_commit: null, installer_version: "2.0.0", installed_at: "" }));
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b", "c"] });
    expect(settings(data).replies.follow_ups).toBe(false);
    expect(JSON.parse(io.out).extras).toEqual({ c: true, follow_ups: false });
  });

  it("--extras applies on top of --skills and pulls dependencies", async () => {
    const { root, environ, data } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--skills", "b", "--extras", "c=on,follow_ups=on", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b", "c"] });
    expect(settings(data).replies.follow_ups).toBe(true);
  });

  it("--extras on an existing install changes only the extras", async () => {
    const { root, environ, data } = scene();
    await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture());
    const io = new Capture();
    expect(await runPlain(root, opts(["--extras", "c=off,follow_ups=on", "--json", "--yes"]), environ, new FakeRunner(), io)).toBe(0);
    expect(installed(data)).toMatchObject({ skills: ["a", "b"] });
    expect(settings(data).replies.follow_ups).toBe(true);
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
    expect(await runPlain(root, opts(["--dry-run", "--json", "--extras", "follow_ups=on"]), environ, new FakeRunner(), io)).toBe(0);
    expect(JSON.parse(io.out).extras).toEqual({ c: false, follow_ups: true });
  });
});

describe("a settings switch never uninstalls a skill on a guided re-run", () => {
  function tjScene() {
    const s = scene();
    const extra = { family: "x", requires: [], depends_on: [], extra: true, label: "L", blurb: "B", friction: "F", default: true };
    write(path.join(s.root, "skills.json"), JSON.stringify({ skills: [{ name: "a", family: "F", requires: [], depends_on: [] }, { name: "trade-journal", ...extra }], extras: [] }));
    write(path.join(s.root, "skills", "trade-journal", "SKILL.md"), "x");
    return s;
  }
  it("keeps trade-journal installed and pre_buy_check false", async () => {
    const { root, environ, data } = tjScene();
    write(path.join(data, "installed.json"), JSON.stringify({ skills: ["a", "trade-journal"], source_path: "", source_commit: null, installer_version: "2.0.0", installed_at: "" }));
    write(path.join(data, "settings.json"), JSON.stringify({ schema: 1, guardrails: { pre_buy_check: false } }));
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(JSON.parse(io.out).skills.removed).toEqual([]);
    expect(installed(data).skills).toContain("trade-journal");
    expect(settings(data).guardrails.pre_buy_check).toBe(false);
  });
  it("--extras still decides", async () => {
    const { root, environ, data } = tjScene();
    write(path.join(data, "installed.json"), JSON.stringify({ skills: ["a", "trade-journal"], source_path: "", source_commit: null, installer_version: "2.0.0", installed_at: "" }));
    write(path.join(data, "settings.json"), JSON.stringify({ schema: 1, guardrails: { pre_buy_check: false } }));
    expect(await runPlain(root, opts(["--extras", "trade-journal=on", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture())).toBe(0);
    expect(settings(data).guardrails.pre_buy_check).toBe(true);
    expect(installed(data).skills).toEqual(["a", "trade-journal"]);
  });

  const seed = (data: string, skills: string[], preBuy: boolean) => {
    write(path.join(data, "installed.json"), JSON.stringify({ skills, source_path: "", source_commit: null, installer_version: "2.0.0", installed_at: "" }));
    write(path.join(data, "settings.json"), JSON.stringify({ schema: 1, guardrails: { pre_buy_check: preBuy } }));
  };
  it("--without another skill keeps trade-journal and its saved switch", async () => {
    const { root, environ, data } = tjScene();
    seed(data, ["a", "trade-journal"], false);
    expect(await runPlain(root, opts(["--without", "a", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture())).toBe(0);
    expect(installed(data).skills).toEqual(["trade-journal"]);
    expect(settings(data).guardrails.pre_buy_check).toBe(false);
  });
  it("--skills dropping trade-journal turns its switch off", async () => {
    const { root, environ, data } = tjScene();
    seed(data, ["a", "trade-journal"], true);
    expect(await runPlain(root, opts(["--skills", "a", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture())).toBe(0);
    expect(installed(data).skills).toEqual(["a"]);
    expect(settings(data).guardrails.pre_buy_check).toBe(false);
  });
  it("--all re-adding trade-journal turns its switch on", async () => {
    const { root, environ, data } = tjScene();
    seed(data, ["a"], false);
    expect(await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture())).toBe(0);
    expect(installed(data).skills).toEqual(["a", "trade-journal"]);
    expect(settings(data).guardrails.pre_buy_check).toBe(true);
  });
  it("writes through the settings CLI in the installed copy, with the Python found in preflight", async () => {
    const { root, environ, target, data } = tjScene();
    seed(data, ["a", "trade-journal"], true);
    const runner = new FakeRunner();
    expect(await runPlain(root, opts(["--skills", "a", "--json", "--yes", ...KEYS]), environ, runner, new Capture())).toBe(0);
    const call = runner.calls.find((c) => c.cmd.includes("set"))!;
    expect(call.cmd).toEqual(["python3", path.join(target, "skills", "get-started", "scripts", "settings.py"), "set", "guardrails.pre_buy_check", "off"]);
    expect(call.opts.env?.SECOND_OPINION_DATA).toBe(data);
  });
  it("a settings CLI failure fails the install with its hint", async () => {
    const { root, environ, data } = tjScene();
    seed(data, ["a", "trade-journal"], true);
    const runner = new FakeRunner();
    runner.rules.push((cmd) => (cmd.includes("set") ? { code: 5, stdout: JSON.stringify({ error: "settings at x holds an invalid value", hint: "fix x by hand" }), stderr: "" } : undefined));
    const io = new Capture();
    expect(await runPlain(root, opts(["--skills", "a", "--json", "--yes", ...KEYS]), environ, runner, io)).not.toBe(0);
    expect(io.err + io.out).toContain("fix x by hand");
  });
});
