import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ensureDependencies } from "../src/engine/deps.js";
import { InstallError } from "../src/engine/errors.js";
import { venvPython } from "../src/engine/paths.js";
import { FakeRunner, tmpDir, write } from "./helpers.js";

function setup() {
  const dir = tmpDir();
  const data = path.join(dir, "data");
  const req = path.join(dir, "requirements.txt");
  write(req, "a==1\n");
  return { data, req };
}

describe("ensureDependencies", () => {
  it("creates the venv, installs and stamps", async () => {
    const { data, req } = setup();
    const runner = new FakeRunner();
    const phases: string[] = [];
    const res = await ensureDependencies(data, req, runner, ["/usr/bin/python3"], { onPhase: (p) => phases.push(p) });
    expect(res).toEqual({ venvPython: venvPython(path.join(data, "venv")), installed: true, createdVenv: true });
    expect(phases).toEqual(["venv", "pip"]);
    expect(runner.commands()[0]).toBe(`/usr/bin/python3 -m venv ${path.join(data, "venv")}`);
    expect(runner.commands()[1]).toContain("-m pip install --disable-pip-version-check -r");
    expect(fs.readFileSync(path.join(data, "requirements.installed.txt"), "utf8")).toBe("a==1\n");
    expect(runner.calls[0]!.opts.log).toBe(path.join(data, "install.log"));
  });

  it("skips pip when the stamp matches and reinstalls when requirements change", async () => {
    const { data, req } = setup();
    const runner = new FakeRunner();
    await ensureDependencies(data, req, runner, ["py"]);
    const again = await ensureDependencies(data, req, runner, ["py"]);
    expect(again.installed).toBe(false);
    expect(again.createdVenv).toBe(false);
    expect(runner.calls.length).toBe(2);
    fs.writeFileSync(req, "a==2\n");
    const third = await ensureDependencies(data, req, runner, ["py"]);
    expect(third.installed).toBe(true);
    expect(runner.calls.length).toBe(3);
  });

  it("names the log when pip fails and hints python3-venv when venv creation fails", async () => {
    const { data, req } = setup();
    const runner = new FakeRunner();
    runner.rules.push((cmd) => (cmd.includes("pip") ? { code: 1, stdout: "", stderr: "boom" } : undefined));
    await expect(ensureDependencies(data, req, runner, ["py"])).rejects.toMatchObject({ message: "pip install failed", hint: `see ${path.join(data, "install.log")}` });
    const bad = new FakeRunner();
    bad.rules.push((cmd) => (cmd[2] === "venv" ? { code: 1, stdout: "", stderr: "" } : undefined));
    const other = setup();
    const err = await ensureDependencies(other.data, other.req, bad, ["py"]).catch((e) => e);
    expect(err).toBeInstanceOf(InstallError);
    expect(err.hint).toContain("python3-venv");
  });
});
