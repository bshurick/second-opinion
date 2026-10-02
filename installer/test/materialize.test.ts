import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildTree, materialize, planDiff, readInstalled, sourceCommit } from "../src/engine/materialize.js";
import { FakeRunner, miniRoot, tmpDir } from "./helpers.js";

describe("materialize", () => {
  it("copies only the chosen skills plus setup, shipped top-level files, no caches or tests", () => {
    const root = miniRoot();
    const dest = path.join(tmpDir(), "t");
    buildTree(root, dest, ["a"]);
    expect(fs.readdirSync(path.join(dest, "skills")).sort()).toEqual(["a", "setup"]);
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
    expect(fs.readdirSync(path.join(target, "skills")).sort()).toEqual(["a", "setup"]);
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
