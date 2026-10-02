import { describe, expect, it } from "vitest";
import { parseOptions, USAGE } from "../src/cli.js";
import { parseBrokers } from "../src/engine/installer.js";

describe("parseOptions", () => {
  it("parses every flag in both forms", () => {
    const o = parseOptions(["--target", "/t", "--skills=a,b", "--snaptrade-client-id", "id", "--snaptrade-consumer-key=k", "--etrade-consumer-key", "ek", "--etrade-consumer-secret=es", "--etrade-sandbox", "--brokers", "snaptrade,etrade", "--edgar-user-agent", "app me@x", "--env-file", "e", "--no-link", "--no-smoke", "--json", "--dry-run", "-y"]);
    expect(o).toMatchObject({ target: "/t", skills: "a,b", snaptradeClientId: "id", snaptradeConsumerKey: "k", etradeConsumerKey: "ek", etradeConsumerSecret: "es", etradeSandbox: true, brokers: "snaptrade,etrade", edgarUserAgent: "app me@x", envFile: "e", noLink: true, noSmoke: true, json: true, dryRun: true, yes: true, all: false, uninstall: false });
    expect(parseOptions(["--uninstall", "--purge-data"])).toMatchObject({ uninstall: true, purgeData: true });
    expect(parseOptions([])).toMatchObject({ all: false, yes: false, help: false });
    expect(parseOptions(["--extras", "follow_ups=off"])).toMatchObject({ extras: "follow_ups=off" });
    expect(USAGE).toContain("--extras");
  });

  it("rejects conflicting or unknown flags with a usage error", () => {
    expect(() => parseOptions(["--all", "--skills", "a"])).toThrow("mutually exclusive");
    expect(() => parseOptions(["--purge-data"])).toThrow("--purge-data only applies with --uninstall");
    expect(() => parseOptions(["--bogus"])).toThrow(/bogus/);
    expect(() => parseOptions(["extra"])).toThrow(/extra/);
    expect(USAGE).toContain("--uninstall");
  });
});

describe("parseBrokers", () => {
  it("accepts snaptrade and etrade, and rejects anything else naming the accepted values", () => {
    expect([...parseBrokers("snaptrade,etrade")].sort()).toEqual(["etrade", "snaptrade"]);
    expect(() => parseBrokers("foo")).toThrow("--brokers accepts snaptrade and etrade, not 'foo'");
    expect(() => parseBrokers("snaptrade,foo")).toThrow(/--brokers accepts snaptrade and etrade/);
    try {
      parseBrokers("foo");
      throw new Error("expected parseBrokers to throw");
    } catch (err) {
      expect((err as Error).name).toBe("UsageError");
    }
  });
});
