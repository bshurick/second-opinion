import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runPlain } from "../src/drivers/plain.js";
import { Capture, FakeRunner, miniRoot, opts, tmpDir, write } from "./helpers.js";

function scene() {
  const root = miniRoot();
  const home = tmpDir("sf-home-");
  const environ = { HOME: home, SECOND_OPINION_DATA: path.join(home, "data") };
  const target = path.join(home, ".claude", "plugins", "second-opinion");
  const link = path.join(home, ".claude", "skills", "second-opinion");
  return { root, home, environ, target, link };
}

/** A scene whose catalog also ships a "connect" skill with the E*Trade login script, so smoke can find it. */
function sceneWithConnect() {
  const s = scene();
  const catalogPath = path.join(s.root, "skills.json");
  const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
  catalog.skills.push({ name: "connect", family: "Fam three", requires: [], depends_on: [] });
  fs.writeFileSync(catalogPath, JSON.stringify(catalog));
  write(path.join(s.root, "skills", "connect", "SKILL.md"), "---\nname: connect\ndescription: Connect a brokerage.\n---\nbody\n");
  write(path.join(s.root, "skills", "connect", "scripts", "etrade-login.py"), "");
  return s;
}

const KEYS = ["--snaptrade-client-id", "id", "--snaptrade-consumer-key", "secret-key-1234"];

describe("plain driver", () => {
  it("installs everything with --json and prints one summary object on stdout", async () => {
    const { root, environ, target, link } = scene();
    const io = new Capture();
    const runner = new FakeRunner();
    const code = await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, runner, io);
    expect(code).toBe(0);
    const summary = JSON.parse(io.out);
    expect(summary).toMatchObject({ target, link, skills: { installed: ["a", "b", "c"], removed: [], refreshed: [] }, dependencies: { installed: true }, smoke: { imports: "ok", dcf: "skipped", status: "skipped" } });
    expect(summary.warnings).toEqual(["EDGAR_USER_AGENT not set; fundamental-research will flag the placeholder default until you re-run install.js"]);
    expect(io.out.trim().split("\n").length).toBe(1);
    expect(io.err).toContain("Installing to");
    expect(io.out + io.err).not.toContain("secret-key-1234");
    expect(fs.readlinkSync(link)).toBe(target);
    expect(fs.readFileSync(path.join(environ.SECOND_OPINION_DATA, ".env"), "utf8")).toContain("SNAPTRADE_CONSUMER_KEY=secret-key-1234");
    if (process.platform !== "win32") expect(fs.statSync(path.join(environ.SECOND_OPINION_DATA, ".env")).mode & 0o777).toBe(0o600);
    expect(fs.existsSync(path.join(target, ".env"))).toBe(false); // credentials live in the data dir, which survives updates
    expect(fs.readdirSync(path.join(target, "skills")).sort()).toEqual(["a", "b", "c", "setup"]);
  });

  it("pulls dependencies in and requires the key they need", async () => {
    const { root, environ } = scene();
    const io = new Capture();
    const code = await runPlain(root, opts(["--skills", "b", "--json", "--yes"]), environ, new FakeRunner(), io);
    expect(code).toBe(1);
    expect(io.err).toContain("b needs a: added a");
    expect(io.err).toContain(
      "install.js: SNAPTRADE_CLIENT_ID+SNAPTRADE_CONSUMER_KEY or ETRADE_CONSUMER_KEY+ETRADE_CONSUMER_SECRET is required by the selected skills — pass it as a flag, export it, or run interactively",
    );
  });

  it("no key is needed when no SnapTrade skill is selected", async () => {
    const { root, environ, target } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--skills", "c", "--json", "--yes", "--edgar-user-agent", "app me@x.io"]), environ, new FakeRunner(), io)).toBe(0);
    expect(io.err).toContain("No brokerage-backed skills selected");
    const env = fs.readFileSync(path.join(environ.SECOND_OPINION_DATA, ".env"), "utf8");
    expect(env).toContain("# No brokerage-backed skills installed.");
    expect(env).toContain('EDGAR_USER_AGENT="app me@x.io"'); // quoted: the value has a space
    expect(JSON.parse(io.out).warnings).toEqual([]);
  });

  it("keeps a still-complete broker credential pair in .env even when a different broker is chosen this run", async () => {
    const { root, environ, target } = scene();
    const io = new Capture();
    const code = await runPlain(
      root,
      opts([
        "--skills",
        "a",
        "--json",
        "--yes",
        "--snaptrade-client-id",
        "id",
        "--snaptrade-consumer-key",
        "secret-key-1234",
        "--etrade-consumer-key",
        "ek",
        "--etrade-consumer-secret",
        "es",
        "--brokers",
        "etrade",
      ]),
      environ,
      new FakeRunner(),
      io,
    );
    expect(code).toBe(0);
    const env = fs.readFileSync(path.join(environ.SECOND_OPINION_DATA, ".env"), "utf8");
    expect(env).toContain("SNAPTRADE_CLIENT_ID=id");
    expect(env).toContain("SNAPTRADE_CONSUMER_KEY=secret-key-1234");
    expect(env).toContain("ETRADE_CONSUMER_KEY=ek");
    expect(env).toContain("ETRADE_CONSUMER_SECRET=es");
  });

  it("re-runs preselect from installed.json, report the diff, and preserve unmanaged .env lines", async () => {
    const { root, environ, target } = scene();
    await runPlain(root, opts(["--skills", "a,c", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture());
    fs.appendFileSync(path.join(environ.SECOND_OPINION_DATA, ".env"), "MY_EXTRA=keep\n");
    const io = new Capture();
    expect(await runPlain(root, opts(["--plain", "--yes"]), environ, new FakeRunner(), io)).toBe(0);
    expect(io.out).toContain("will install (none); refresh a, c; remove (none)");
    expect(io.out).toContain("Installed: (none); refreshed: a, c; removed: (none)");
    expect(fs.readFileSync(path.join(environ.SECOND_OPINION_DATA, ".env"), "utf8")).toContain("# preserved from your previous .env\nMY_EXTRA=keep");
    const io2 = new Capture();
    expect(await runPlain(root, opts(["--without", "a", "--json", "--yes"]), environ, new FakeRunner(), io2)).toBe(0);
    expect(JSON.parse(io2.out).skills).toEqual({ installed: [], removed: ["a"], refreshed: ["c"] });
    expect(fs.existsSync(path.join(target, "skills", "a"))).toBe(false);
  });

  it("dry-run writes nothing and reports missing secrets as warnings", async () => {
    const { root, environ, target } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--all", "--dry-run", "--json"]), environ, new FakeRunner(), io)).toBe(0);
    expect(fs.existsSync(target)).toBe(false);
    const plan = JSON.parse(io.out);
    expect(plan.dry_run).toBe(true);
    expect(plan.skills.installed).toEqual(["a", "b", "c"]);
    expect(plan.warnings).toContain("SNAPTRADE_CLIENT_ID+SNAPTRADE_CONSUMER_KEY or ETRADE_CONSUMER_KEY+ETRADE_CONSUMER_SECRET is not set; a real run will need it");
    expect(io.err).not.toContain("Installing to");
  });

  it("uninstall: dry-run, requires --yes, keeps data unless --purge-data", async () => {
    const { root, environ, target, link } = scene();
    await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture());
    const dry = new Capture();
    expect(await runPlain(root, opts(["--uninstall", "--dry-run", "--json"]), environ, new FakeRunner(), dry)).toBe(0);
    expect(JSON.parse(dry.out)).toEqual({ dry_run: true, uninstall: { would_remove: [link, target] } });
    expect(fs.existsSync(target)).toBe(true);
    const noYes = new Capture();
    expect(await runPlain(root, opts(["--uninstall", "--json"]), environ, new FakeRunner(), noYes)).toBe(1);
    expect(noYes.err).toContain("requires --yes");
    const io = new Capture();
    expect(await runPlain(root, opts(["--uninstall", "--json", "--yes"]), environ, new FakeRunner(), io)).toBe(0);
    const res = JSON.parse(io.out);
    expect(res.removed).toEqual([link, target]);
    expect(res.kept[0]).toContain(environ.SECOND_OPINION_DATA);
    expect(fs.existsSync(environ.SECOND_OPINION_DATA)).toBe(true);
  });

  it("unknown skill is exit 2; missing python is a named exit 1", async () => {
    const { root, environ } = scene();
    const io = new Capture();
    expect(await runPlain(root, opts(["--skills", "zzz", "--json"]), environ, new FakeRunner(), io)).toBe(2);
    expect(io.err).toContain("unknown skill: zzz");
    const old = new FakeRunner();
    old.pythonVersion = "3.8.0";
    const io2 = new Capture();
    expect(await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, old, io2)).toBe(1);
    expect(io2.err).toMatch(/install\.js: no usable Python found .* — install Python 3\.10\+/);
  });

  it("link conflict without --yes degrades to a warning; with --yes it replaces", async () => {
    const { root, environ, link, target } = scene();
    const other = tmpDir();
    fs.mkdirSync(path.dirname(link), { recursive: true });
    fs.symlinkSync(other, link);
    const io = new Capture();
    expect(await runPlain(root, opts(["--all", "--json", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    const summary = JSON.parse(io.out);
    expect(summary.link).toBeNull();
    expect(summary.warnings.some((w: string) => w.startsWith(`could not link ${link}`))).toBe(true);
    expect(fs.readlinkSync(link)).toBe(other);
    const io2 = new Capture();
    expect(await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), io2)).toBe(0);
    expect(fs.readlinkSync(link)).toBe(target);
  });

  it("honors SECOND_OPINION_PYTHON and reports a non-executable one", async () => {
    const { root, environ } = scene();
    const py = path.join(root, "custom-python");
    write(py, "#!/bin/sh\n", 0o755);
    const runner = new FakeRunner();
    expect(await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), { ...environ, SECOND_OPINION_PYTHON: py }, runner, new Capture())).toBe(0);
    expect(runner.commands().some((c) => c.startsWith(`${py} -m venv`))).toBe(true);
    const io = new Capture();
    expect(await runPlain(root, opts(["--all", "--json", "--yes", ...KEYS]), { ...environ, SECOND_OPINION_PYTHON: "/nope" }, new FakeRunner(), io)).toBe(1);
    expect(io.err).toContain("/nope: SECOND_OPINION_PYTHON is not executable");
  });

  it('prints a "Connect E*Trade" next step only when the token needs a fresh login', async () => {
    const { root, environ } = sceneWithConnect();
    const etradeArgs = ["--skills", "a,connect", "--yes", "--brokers", "etrade", "--etrade-consumer-key", "ek", "--etrade-consumer-secret", "es"];

    const needsLogin = new FakeRunner();
    needsLogin.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: '{"token":"none"}', stderr: "" } : undefined));
    const io = new Capture();
    expect(await runPlain(root, opts(etradeArgs), environ, needsLogin, io)).toBe(0);
    expect(io.out).toContain('Next: in Claude say "Connect E*Trade" and paste the 5-character code it shows.');

    const alreadyLoggedIn = new FakeRunner();
    alreadyLoggedIn.rules.push((cmd) => (cmd.some((c) => c.endsWith("etrade-login.py")) ? { code: 0, stdout: '{"token":"usable"}', stderr: "" } : undefined));
    const io2 = new Capture();
    expect(await runPlain(root, opts(etradeArgs), environ, alreadyLoggedIn, io2)).toBe(0);
    expect(io2.out).not.toContain("Next: in Claude say");
  });
});
