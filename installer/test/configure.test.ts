import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runPlain } from "../src/drivers/plain.js";
import { legacyLeftovers } from "../src/engine/legacy.js";
import { cacheOnly, dataDir, isManagedRoot, migrateLegacyData } from "../src/engine/paths.js";
import { findPython } from "../src/engine/python.js";
import { Capture, extrasRoot, FakeRunner, miniRoot, opts, tmpDir, write } from "./helpers.js";

const KEYS = ["--snaptrade-client-id", "id", "--snaptrade-consumer-key", "secret-key-1234"];

function home() {
  const h = tmpDir("sf-home-");
  return { home: h, environ: { HOME: h }, data: path.join(h, ".claude", "plugins", "data", "second-opinion"), old: path.join(h, ".claude", "plugins", "data", "finance-analyst") };
}

/** A plugin root inside a Claude Code plugin cache, as a /plugin marketplace install leaves it. */
function cachedRoot(h: string): string {
  return extrasRoot(path.join(h, ".claude", "plugins", "cache", "second-opinion", "second-opinion", "1.0.0"));
}

describe("paths", () => {
  it("detects a Claude Code plugin cache or marketplace checkout", () => {
    expect(isManagedRoot("/u/.claude/plugins/cache/second-opinion/second-opinion/1.0.0")).toBe(true);
    expect(isManagedRoot("/u/.claude/plugins/marketplaces/second-opinion")).toBe(true);
    expect(isManagedRoot("/u/src/second-opinion")).toBe(false);
    expect(isManagedRoot("/u/.claude/plugins/second-opinion")).toBe(false);
  });

  it("accepts FINANCE_ANALYST_DATA when SECOND_OPINION_DATA is not set", () => {
    expect(dataDir({ HOME: "/h", FINANCE_ANALYST_DATA: "/old" })).toBe("/old");
    expect(dataDir({ HOME: "/h", FINANCE_ANALYST_DATA: "/old", SECOND_OPINION_DATA: "/new" })).toBe("/new");
  });

  it("accepts PROFICI_PYTHON and FINANCE_ANALYST_PYTHON as the interpreter override", async () => {
    for (const v of ["PROFICI_PYTHON", "FINANCE_ANALYST_PYTHON"]) {
      const probe = await findPython(new FakeRunner(), { [v]: "/nope/python" }, "linux");
      expect(probe.rejected).toEqual([{ command: "/nope/python", reason: `${v} is not executable` }]);
    }
  });
});

describe("data migration", () => {
  it("renames the pre-rename data dir once and never overwrites", () => {
    const { environ, data, old } = home();
    write(path.join(old, "journal.json"), "{}");
    expect(migrateLegacyData(environ)).toContain("moved your data");
    expect(fs.readFileSync(path.join(data, "journal.json"), "utf8")).toBe("{}");
    expect(fs.existsSync(old)).toBe(false);
    expect(migrateLegacyData(environ)).toBeNull(); // idempotent
    write(path.join(old, "journal.json"), "old");
    expect(migrateLegacyData(environ)).toBeNull();
    expect(fs.readFileSync(path.join(data, "journal.json"), "utf8")).toBe("{}");
    expect(fs.readFileSync(path.join(old, "journal.json"), "utf8")).toBe("old"); // never deleted
  });

  it("merges into a new dir that holds only caches", () => {
    const { environ, data, old } = home();
    write(path.join(old, "profile.json"), "{}");
    write(path.join(old, "edgar-cache", "x.json"), "old");
    write(path.join(data, "edgar-cache", "y.json"), "new");
    expect(cacheOnly(data)).toBe(true);
    expect(migrateLegacyData(environ)).toContain("moved your data");
    expect(fs.existsSync(path.join(data, "profile.json"))).toBe(true);
    expect(fs.readFileSync(path.join(old, "edgar-cache", "x.json"), "utf8")).toBe("old");
  });

  it("does nothing with an explicit data dir", () => {
    const { environ, old } = home();
    write(path.join(old, "profile.json"), "{}");
    expect(migrateLegacyData({ ...environ, SECOND_OPINION_DATA: path.join(environ.HOME, "elsewhere") })).toBeNull();
    expect(fs.existsSync(old)).toBe(true);
  });
});

describe("upgrading from finance-analyst", () => {
  function oldInstall(h: string) {
    const target = path.join(h, ".claude", "plugins", "finance-analyst");
    write(path.join(target, ".claude-plugin", "plugin.json"), '{"name":"finance-analyst"}');
    write(path.join(target, ".env"), "SNAPTRADE_CLIENT_ID=old-id\nSNAPTRADE_CONSUMER_KEY=old-key-9999\nMY_EXTRA=keep\n");
    write(path.join(target, "installed.json"), JSON.stringify({ skills: ["a", "c"], extras: { follow_ups: false } }));
    const link = path.join(h, ".claude", "skills", "finance-analyst");
    fs.mkdirSync(path.dirname(link), { recursive: true });
    fs.symlinkSync(target, link, "dir");
    return { target, link };
  }

  it("carries the old keys and selection over, moves the data, and removes the old copy with --yes", async () => {
    const { home: h, environ, data, old } = home();
    const { target, link } = oldInstall(h);
    write(path.join(old, "journal.json"), "{}");
    const root = miniRoot();
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes"]), environ, new FakeRunner(), io)).toBe(0);
    const summary = JSON.parse(io.out);
    expect(summary.skills.refreshed).toEqual(["a", "c"]);
    const env = fs.readFileSync(path.join(data, ".env"), "utf8");
    expect(env).toContain("SNAPTRADE_CONSUMER_KEY=old-key-9999");
    expect(env).toContain("MY_EXTRA=keep");
    expect(fs.readFileSync(path.join(data, "journal.json"), "utf8")).toBe("{}");
    expect(fs.existsSync(target) || fs.existsSync(link)).toBe(false);
    expect(summary.notes.join("\n")).toContain("removed the old finance-analyst copy");
  });

  it("without --yes keeps the old copy and warns", async () => {
    const { home: h, environ } = home();
    const { target } = oldInstall(h);
    const io = new Capture();
    expect(await runPlain(miniRoot(), opts(["--json", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    expect(fs.existsSync(target)).toBe(true);
    expect(JSON.parse(io.out).warnings.join("\n")).toContain("the old finance-analyst copy is still at");
  });

  it("never lists a directory that is not our plugin, or the root in use", () => {
    const { home: h, environ } = home();
    write(path.join(h, ".claude", "plugins", "finance-analyst", "notes.txt"), "mine");
    expect(legacyLeftovers(environ, miniRoot())).toEqual([]);
    const { target, link } = oldInstall(tmpDir("sf-home2-"));
    expect(legacyLeftovers({ HOME: path.dirname(path.dirname(path.dirname(target))) }, target)).toEqual([link]);
  });
});

describe("configure mode (a /plugin marketplace install)", () => {
  it("is automatic inside the plugin cache: writes only the data dir, records every extra, never copies or links", async () => {
    const { home: h, environ, data } = home();
    const root = cachedRoot(h);
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", ...KEYS]), environ, new FakeRunner(), io)).toBe(0);
    const summary = JSON.parse(io.out);
    expect(summary).toMatchObject({ mode: "configure", target: root, link: null, data, extras: { c: false, tips: false } });
    expect(fs.existsSync(path.join(h, ".claude", "plugins", "second-opinion"))).toBe(false);
    expect(fs.existsSync(path.join(h, ".claude", "skills"))).toBe(false);
    expect(fs.existsSync(path.join(root, ".env"))).toBe(false);
    expect(fs.readFileSync(path.join(data, ".env"), "utf8")).toContain("SNAPTRADE_CONSUMER_KEY=secret-key-1234");
    const rec = JSON.parse(fs.readFileSync(path.join(data, "installed.json"), "utf8"));
    expect(rec).toMatchObject({ skills: ["a", "b"], extras: { c: false, tips: false }, mode: "configure" });
    expect(io.err).toContain("/reload-plugins");
  });

  it("turns extras on and off and keeps them across runs", async () => {
    const { home: h, environ, data } = home();
    const root = cachedRoot(h);
    expect(await runPlain(root, opts(["--json", "--yes", "--extras", "c=on,tips=on", ...KEYS]), environ, new FakeRunner(), new Capture())).toBe(0);
    let rec = JSON.parse(fs.readFileSync(path.join(data, "installed.json"), "utf8"));
    expect(rec.extras).toEqual({ c: true, tips: true });
    const io = new Capture();
    expect(await runPlain(root, opts(["--json", "--yes", "--extras", "tips=off"]), environ, new FakeRunner(), io)).toBe(0);
    rec = JSON.parse(fs.readFileSync(path.join(data, "installed.json"), "utf8"));
    expect(rec.extras).toEqual({ c: true, tips: false });
    expect(fs.readFileSync(path.join(data, ".env"), "utf8")).toContain("SNAPTRADE_CONSUMER_KEY=secret-key-1234"); // kept
  });

  it("needs no brokerage key: it warns instead of failing", async () => {
    const { home: h, environ, data } = home();
    const io = new Capture();
    expect(await runPlain(cachedRoot(h), opts(["--json", "--yes"]), environ, new FakeRunner(), io)).toBe(0);
    expect(JSON.parse(io.out).warnings.join("\n")).toContain("no brokerage key configured yet");
    expect(fs.readFileSync(path.join(data, ".env"), "utf8")).toContain("# No brokerage key yet");
  });

  it("--configure forces it from a checkout; selection flags and --uninstall are refused", async () => {
    const { environ, data } = home();
    const root = extrasRoot();
    expect(await runPlain(root, opts(["--configure", "--json", "--yes", ...KEYS]), environ, new FakeRunner(), new Capture())).toBe(0);
    expect(fs.existsSync(path.join(data, "installed.json"))).toBe(true);
    const io = new Capture();
    expect(await runPlain(root, opts(["--configure", "--all", "--json", "--yes"]), environ, new FakeRunner(), io)).toBe(2);
    expect(io.err).toContain("use --extras");
    expect(() => opts(["--configure", "--uninstall"])).toThrow("mutually exclusive");
  });

  it("dry run reports the mode and writes nothing", async () => {
    const { home: h, environ, data } = home();
    const io = new Capture();
    expect(await runPlain(cachedRoot(h), opts(["--dry-run", "--json"]), environ, new FakeRunner(), io)).toBe(0);
    expect(JSON.parse(io.out)).toMatchObject({ dry_run: true, mode: "configure", link: null, data });
    expect(fs.existsSync(data)).toBe(false);
  });
});
