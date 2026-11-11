import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { InstallError } from "../src/engine/errors.js";
import { buildTree, makeRecord, materialize, planDiff, readInstalled, sourceCommit, writeConfig, writeSwitches } from "../src/engine/materialize.js";
import { FakeRunner, miniRoot, tmpDir } from "./helpers.js";

describe("materialize", () => {
  it("copies only the chosen skills plus setup, shipped top-level files, no caches or tests", () => {
    const root = miniRoot();
    const dest = path.join(tmpDir(), "t");
    buildTree(root, dest, ["a"]);
    expect(fs.readdirSync(path.join(dest, "skills")).sort()).toEqual(["a", "get-started"]);
    for (const top of [".claude-plugin", "hooks", "lib", "requirements.txt", "LICENSE", "README.md"]) expect(fs.existsSync(path.join(dest, top)), top).toBe(true);
    expect(fs.existsSync(path.join(dest, "tests"))).toBe(false);
    expect(fs.existsSync(path.join(dest, "scripts"))).toBe(false);
    expect(fs.existsSync(path.join(dest, "skills", "a", "scripts", "__pycache__"))).toBe(false);
    expect(fs.statSync(path.join(dest, "skills", "a", "scripts", "run.py")).mode & 0o111).not.toBe(0);
    expect(fs.statSync(path.join(dest, "hooks", "session-start.sh")).mode & 0o111).not.toBe(0);
  });

  it("plans a diff", () => {
    expect(planDiff(["a", "b"], ["b", "c"])).toEqual({ installed: ["c"], removed: ["a"], refreshed: ["b"] });
    expect(planDiff(null, ["a"])).toEqual({ installed: ["a"], removed: [], refreshed: [] });
  });

  it("writes .env (0600) and installed.json, and re-runs remove dropped skills", () => {
    const root = miniRoot();
    const target = path.join(tmpDir(), "plugin");
    const now = () => new Date("2026-09-05T12:00:00Z");
    const first = materialize(root, target, ["a", "b"], "K=v\n", { commit: "abc", now });
    expect(first).toEqual({ installed: ["a", "b"], removed: [], refreshed: [] });
    expect(fs.readFileSync(path.join(target, ".env"), "utf8")).toBe("K=v\n");
    if (process.platform !== "win32") expect(fs.statSync(path.join(target, ".env")).mode & 0o777).toBe(0o600);
    const rec = readInstalled(target)!;
    expect(rec.skills).toEqual(["a", "b"]);
    expect(rec.source_commit).toBe("abc");
    expect(rec.source_path).toBe(root);
    expect(rec.installed_at).toBe("2026-09-05T12:00:00+00:00");
    fs.writeFileSync(path.join(target, "skills", "a", "marker"), "old");
    const second = materialize(root, target, ["a", "c"], "K=v2\n");
    expect(second).toEqual({ installed: ["c"], removed: ["b"], refreshed: ["a"] });
    expect(fs.existsSync(path.join(target, "skills", "b"))).toBe(false);
    expect(fs.existsSync(path.join(target, "skills", "a", "marker"))).toBe(false);
    expect(fs.existsSync(path.join(path.dirname(target), "plugin.building"))).toBe(false);
    expect(fs.existsSync(path.join(path.dirname(target), "plugin.previous"))).toBe(false);
  });

  it("leaves the previous target intact when the build step fails", () => {
    const root = miniRoot();
    const target = path.join(tmpDir(), "plugin");
    materialize(root, target, ["a"], "one\n");
    expect(() => materialize(root, target, ["a", "c"], "two\n", { build: () => { throw new Error("boom"); } })).toThrow("boom");
    expect(fs.readFileSync(path.join(target, ".env"), "utf8")).toBe("one\n");
    expect(fs.readdirSync(path.join(target, "skills")).sort()).toEqual(["a", "get-started"]);
    expect(fs.existsSync(path.join(path.dirname(target), "plugin.building"))).toBe(false);
  });

  it("readInstalled tolerates garbage and sourceCommit tolerates no git", async () => {
    const dir = tmpDir();
    expect(readInstalled(dir)).toBeNull();
    fs.writeFileSync(path.join(dir, "installed.json"), "not json");
    expect(readInstalled(dir)).toBeNull();
    fs.writeFileSync(path.join(dir, "installed.json"), "[1]");
    expect(readInstalled(dir)).toBeNull();
    const runner = new FakeRunner();
    runner.rules.push((cmd) => (cmd[0] === "git" ? { code: 128, stdout: "", stderr: "fatal" } : undefined));
    expect(await sourceCommit(dir, runner)).toBeNull();
    expect(await sourceCommit(dir, new FakeRunner())).toBe("abc123");
  });
});

describe("writeSwitches", () => {
  const read = (d: string) => JSON.parse(fs.readFileSync(path.join(d, "settings.json"), "utf8"));
  const ALL = { follow_ups: true, "trade-journal": false, "financial-education": false };

  it("runs the plugin's settings CLI with the given Python and the data dir, one set per switch", async () => {
    const dir = tmpDir();
    const runner = new FakeRunner();
    await writeSwitches(runner, ["/usr/bin/python3"], "/plugin", dir, ALL);
    const script = path.join("/plugin", "skills", "get-started", "scripts", "settings.py");
    expect(runner.calls.map((c) => c.cmd)).toEqual([
      ["/usr/bin/python3", script, "set", "replies.follow_ups", "on"],
      ["/usr/bin/python3", script, "set", "guardrails.pre_buy_check", "off"],
      ["/usr/bin/python3", script, "set", "lessons", "off"],
    ]);
    for (const c of runner.calls) expect(c.opts.env?.SECOND_OPINION_DATA).toBe(dir);
    expect(read(dir)).toMatchObject({ replies: { follow_ups: true }, guardrails: { pre_buy_check: false }, lessons: false });
  });

  it("skips a switch already saved with that value, and non-switch keys", async () => {
    const dir = tmpDir();
    fs.writeFileSync(path.join(dir, "settings.json"), JSON.stringify({ schema: 1, replies: { follow_ups: true }, lessons: false }));
    const runner = new FakeRunner();
    await writeSwitches(runner, ["python3"], "/plugin", dir, { ...ALL, c: true });
    expect(runner.commands()).toEqual([`python3 ${path.join("/plugin", "skills", "get-started", "scripts", "settings.py")} set guardrails.pre_buy_check off`]);
  });

  it("a failing CLI fails the install with its error and hint", async () => {
    const dir = tmpDir();
    const runner = new FakeRunner();
    runner.rules.push(() => ({ code: 5, stdout: JSON.stringify({ error: "settings were written by a newer plugin (schema 2, this one writes 1)", code: "SETTINGS_NEWER", hint: "update the Second Opinion plugin; settings.json is left untouched" }), stderr: "" }));
    const err = await writeSwitches(runner, ["python3"], "/plugin", dir, ALL).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(InstallError);
    expect((err as InstallError).message).toContain("newer plugin");
    expect((err as InstallError).hint).toBe("update the Second Opinion plugin; settings.json is left untouched");
  });

  it("an exit 5 without JSON still names settings.json as corrupt or newer", async () => {
    const dir = tmpDir();
    const runner = new FakeRunner();
    runner.rules.push(() => ({ code: 5, stdout: "", stderr: "Traceback ...\nboom" }));
    const err = (await writeSwitches(runner, ["python3"], "/plugin", dir, ALL).catch((e: unknown) => e)) as InstallError;
    expect(err.message).toContain("boom");
    expect(err.hint).toMatch(/settings\.json is corrupt or was written by a newer Second Opinion/);
  });

  it("writeConfig refuses a corrupt or newer settings.json before writing .env, and never writes extras", () => {
    const dir = tmpDir();
    writeConfig(dir, "K=v\n", makeRecord("/r", ["a"]));
    expect(JSON.parse(fs.readFileSync(path.join(dir, "installed.json"), "utf8"))).not.toHaveProperty("extras");
    expect(fs.existsSync(path.join(dir, "settings.json"))).toBe(false);
    const bad = tmpDir();
    fs.writeFileSync(path.join(bad, "settings.json"), JSON.stringify({ schema: 3 }));
    expect(() => writeConfig(bad, "K=v\n", makeRecord("/r", ["a"]))).toThrow(InstallError);
    expect(fs.existsSync(path.join(bad, ".env"))).toBe(false);
    fs.writeFileSync(path.join(bad, "settings.json"), "{oops");
    expect(() => writeConfig(bad, "K=v\n", makeRecord("/r", ["a"]))).toThrow(/settings\.json/);
    expect(fs.readFileSync(path.join(bad, "settings.json"), "utf8")).toBe("{oops");
  });
});
