import path from "node:path";
import { describe, expect, it } from "vitest";
import { findPython, pythonHint } from "../src/engine/python.js";
import { smoke } from "../src/engine/smoke.js";
import { FakeRunner, miniRoot, write } from "./helpers.js";

describe("findPython", () => {
  it("prefers SECOND_OPINION_PYTHON when executable, then PATH", async () => {
    const root = miniRoot();
    const py = path.join(root, "mypy");
    write(py, "#!/bin/sh\n", 0o755);
    const runner = new FakeRunner();
    const probe = await findPython(runner, { SECOND_OPINION_PYTHON: py }, "darwin");
    expect(probe.found).toEqual({ command: [py], version: "3.12.1", hasVenv: true, source: "SECOND_OPINION_PYTHON" });
    const plain = await findPython(new FakeRunner(), {}, "darwin");
    expect(plain.found?.command).toEqual(["python3"]);
    expect(plain.found?.source).toBe("PATH");
  });

  it("rejects old versions, missing venv, a non-executable override, and reports every candidate", async () => {
    const old = new FakeRunner();
    old.pythonVersion = "3.9.7";
    const probe = await findPython(old, { SECOND_OPINION_PYTHON: "/nope/python" }, "linux");
    expect(probe.found).toBeNull();
    expect(probe.rejected).toEqual([{ command: "/nope/python", reason: "SECOND_OPINION_PYTHON is not executable" }]);
    expect(pythonHint(probe)).toContain("point SECOND_OPINION_PYTHON");
    const viaPath = await findPython(old, {}, "linux");
    expect(viaPath.rejected.map((r) => r.command)).toEqual(["python3", "python"]);
    expect(viaPath.rejected[0]!.reason).toContain("older than 3.10");
    expect(pythonHint(viaPath)).toContain("Python 3.10+");
    const novenv = new FakeRunner();
    novenv.hasVenv = false;
    const p2 = await findPython(novenv, {}, "linux");
    expect(p2.found).toBeNull();
    expect(pythonHint(p2)).toContain("python3-venv");
    const missing = new FakeRunner();
    missing.rules.push(() => ({ code: 127, stdout: "", stderr: "" }));
    const p3 = await findPython(missing, {}, "win32");
    expect(p3.rejected.map((r) => r.command)).toEqual(["python3", "python", "py -3"]);
  });
});

describe("smoke", () => {
  it("runs all three with keys and records the results", async () => {
    const root = miniRoot();
    write(path.join(root, "skills", "valuation", "scripts", "dcf.py"), "");
    write(path.join(root, "skills", "connect", "scripts", "status.py"), "");
    const runner = new FakeRunner();
    const seen: string[] = [];
    const res = await smoke(root, "/venv/bin/python", new Set(["snaptrade"]), runner, (k, v) => seen.push(`${k}=${v}`));
    expect(res).toEqual({ imports: "ok", dcf: "ok", status: "ok", etrade: "no_keys" });
    expect(seen).toEqual(["imports=ok", "dcf=ok", "status=ok", "etrade=no_keys"]);
    expect(runner.calls[1]!.opts.stdin).toContain("fcf0");
    expect(runner.calls.every((c) => c.opts.cwd === root)).toBe(true);
  });

  it("marks failures, no_keys, rejected and skipped", async () => {
    const root = miniRoot();
    write(path.join(root, "skills", "valuation", "scripts", "dcf.py"), "");
    const runner = new FakeRunner();
    runner.rules.push((cmd) => (cmd.includes("-c") ? { code: 1, stdout: "", stderr: "" } : undefined));
    runner.rules.push((cmd) => (cmd.some((c) => c.endsWith("dcf.py")) ? { code: 0, stdout: "{}", stderr: "" } : undefined));
    expect(await smoke(root, "py", new Set(), runner)).toEqual({ imports: "failed", dcf: "failed", status: "no_keys", etrade: "no_keys" });
    write(path.join(root, "skills", "connect", "scripts", "status.py"), "");
    const rej = new FakeRunner();
    rej.rules.push((cmd) => (cmd.some((c) => c.endsWith("status.py")) ? { code: 4, stdout: "", stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["snaptrade"]), rej)).status).toBe("rejected");
    const bare = miniRoot();
    expect(await smoke(bare, "py", new Set(["snaptrade"]), new FakeRunner())).toEqual({ imports: "ok", dcf: "skipped", status: "skipped", etrade: "no_keys" });
  });

  it("checks the E*Trade token status when etrade is chosen", async () => {
    const root = miniRoot();
    write(path.join(root, "skills", "connect", "scripts", "etrade-login.py"), "");
    const runner = new FakeRunner();
    runner.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: '{"token":"usable"}', stderr: "" } : undefined));
    const res = await smoke(root, "py", new Set(["etrade"]), runner);
    expect(res.status).toBe("no_keys");
    expect(res.etrade).toBe("ok");
    expect(runner.commands().some((c) => c.endsWith("etrade-login.py --status"))).toBe(true);
    const bad = new FakeRunner();
    bad.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 4, stdout: "", stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["etrade"]), bad)).etrade).toBe("rejected");
  });

  it("reads the stored token state from --status JSON, and treats an unparseable exit 0 as failed", async () => {
    const root = miniRoot();
    write(path.join(root, "skills", "connect", "scripts", "etrade-login.py"), "");

    const usable = new FakeRunner();
    usable.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: '{"token":"usable"}', stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["etrade"]), usable)).etrade).toBe("ok");

    const none = new FakeRunner();
    none.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: '{"token":"none"}', stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["etrade"]), none)).etrade).toBe("no_login");

    const expired = new FakeRunner();
    expired.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: '{"token":"expired"}', stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["etrade"]), expired)).etrade).toBe("no_login");

    const garbage = new FakeRunner();
    garbage.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: "not json", stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["etrade"]), garbage)).etrade).toBe("failed");

    const rejected = new FakeRunner();
    rejected.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 4, stdout: "", stderr: "" } : undefined));
    expect((await smoke(root, "py", new Set(["etrade"]), rejected)).etrade).toBe("rejected");
  });
});
