import path from "node:path";
import { describe, expect, it } from "vitest";
import { brokersFrom, envDefaults, maskSecret, parseEnv, preservedEnvLines, quoteEnvValue, renderEnv, unmanagedEnvLines, unquoteEnvValue, validateEdgarUserAgent } from "../src/engine/env.js";
import { tmpDir, write } from "./helpers.js";

describe("env", () => {
  it("parses managed keys and ignores comments, blanks and unknown keys", () => {
    expect(parseEnv("# c\nSNAPTRADE_CLIENT_ID=id\nSNAPTRADE_CONSUMER_KEY=\nOTHER=x\n\nEDGAR_USER_AGENT = app me@x.io\n")).toEqual({
      SNAPTRADE_CLIENT_ID: "id",
      EDGAR_USER_AGENT: "app me@x.io",
    });
  });

  it("renders only the needed keys", () => {
    const text = renderEnv({ SNAPTRADE_CLIENT_ID: "id", SNAPTRADE_CONSUMER_KEY: "k" }, new Set(["brokerage"]), [], new Set(["snaptrade"]));
    expect(text).toContain("SNAPTRADE_CLIENT_ID=id\nSNAPTRADE_CONSUMER_KEY=k\n");
    expect(text).toContain("# BROKER_ACCOUNT_TYPES=");
    expect(text).not.toMatch(/^ETRADE_CONSUMER_KEY=/m);
    expect(text).toContain('# EDGAR_USER_AGENT="my-app-name me@example.com"');
    const none = renderEnv({}, new Set(), [], new Set());
    expect(none).toContain("# No brokerage-backed skills installed.");
    expect(none).not.toMatch(/^SNAPTRADE_CLIENT_ID=/m);
  });

  it("renders E*Trade keys, sandbox flag and migrates SNAPTRADE_ACCOUNT_TYPES", () => {
    const values = { ETRADE_CONSUMER_KEY: "ek", ETRADE_CONSUMER_SECRET: "es", ETRADE_SANDBOX: "1", SNAPTRADE_ACCOUNT_TYPES: "x=margin", EDGAR_USER_AGENT: "app me@x.io" };
    const text = renderEnv(values, new Set(["brokerage", "edgar"]), [], new Set(["etrade"]));
    expect(text).toContain("ETRADE_CONSUMER_KEY=ek\nETRADE_CONSUMER_SECRET=es\nETRADE_SANDBOX=1\n");
    expect(text).toMatch(/^BROKER_ACCOUNT_TYPES=x=margin$/m);
    expect(text).not.toMatch(/^SNAPTRADE_CLIENT_ID=/m);
    expect(parseEnv(text)).toEqual({ ETRADE_CONSUMER_KEY: "ek", ETRADE_CONSUMER_SECRET: "es", ETRADE_SANDBOX: "1", BROKER_ACCOUNT_TYPES: "x=margin", EDGAR_USER_AGENT: "app me@x.io" });
    expect([...brokersFrom(values)]).toEqual(["etrade"]);
    expect([...brokersFrom({ ...values, SNAPTRADE_CLIENT_ID: "a", SNAPTRADE_CONSUMER_KEY: "b" })].sort()).toEqual(["etrade", "snaptrade"]);
    expect([...brokersFrom({ SNAPTRADE_CLIENT_ID: "a" })]).toEqual([]);
  });

  it("writes account types and edgar when present and round-trips", () => {
    const values = { SNAPTRADE_CLIENT_ID: "id", SNAPTRADE_CONSUMER_KEY: "k", SNAPTRADE_ACCOUNT_TYPES: "x=margin", EDGAR_USER_AGENT: "app me@x.io" };
    const text = renderEnv(values, new Set(["brokerage", "edgar"]));
    expect(text).toMatch(/^BROKER_ACCOUNT_TYPES=x=margin$/m);
    expect(parseEnv(text)).toEqual({ SNAPTRADE_CLIENT_ID: "id", SNAPTRADE_CONSUMER_KEY: "k", BROKER_ACCOUNT_TYPES: "x=margin", EDGAR_USER_AGENT: "app me@x.io" });
  });

  it("quotes values with whitespace when writing and strips quotes when reading", () => {
    expect(quoteEnvValue("abc123")).toBe("abc123");
    expect(quoteEnvValue("my-app-name me@example.com")).toBe('"my-app-name me@example.com"');
    expect(quoteEnvValue('say "hi" there')).toBe("'say \"hi\" there'");
    expect(unquoteEnvValue(' "a b" ')).toBe("a b");
    expect(unquoteEnvValue("'a b'")).toBe("a b");
    expect(unquoteEnvValue('"unbalanced')).toBe('"unbalanced');
    const text = renderEnv({ SNAPTRADE_CLIENT_ID: "id", SNAPTRADE_CONSUMER_KEY: "k", EDGAR_USER_AGENT: "my-app-name me@example.com" }, new Set(["brokerage", "edgar"]));
    expect(text).toMatch(/^EDGAR_USER_AGENT="my-app-name me@example.com"$/m);
    expect(text).toMatch(/^SNAPTRADE_CLIENT_ID=id$/m); // bare when nothing needs quoting
    expect(parseEnv(text).EDGAR_USER_AGENT).toBe("my-app-name me@example.com");
    // both spellings read back the same, also with a stray CR
    expect(parseEnv("EDGAR_USER_AGENT=my-app-name me@example.com\r\n").EDGAR_USER_AGENT).toBe("my-app-name me@example.com");
    expect(parseEnv("EDGAR_USER_AGENT='my-app-name me@example.com'\r\n").EDGAR_USER_AGENT).toBe("my-app-name me@example.com");
  });

  it("keeps unmanaged lines verbatim and appends them only when present", () => {
    expect(unmanagedEnvLines("A=1\nSNAPTRADE_CLIENT_ID=x\n# B=2\n  C = 3 \n")).toEqual(["A=1", "  C = 3 "]);
    expect(renderEnv({}, new Set())).not.toContain("preserved");
    expect(renderEnv({}, new Set(), ["A=1"], new Set())).toMatch(/# preserved from your previous \.env\nA=1\n$/);
  });

  it("defaults: environment < target .env < --env-file, and preserved lines dedupe by key", () => {
    const dir = tmpDir();
    const target = path.join(dir, "t", ".env");
    const file = path.join(dir, "f.env");
    write(target, "SNAPTRADE_CLIENT_ID=from-target\nEDGAR_USER_AGENT=t me@t.io\nX=1\n");
    write(file, "SNAPTRADE_CLIENT_ID=from-file\nX=2\nY=3\n");
    const environ = { SNAPTRADE_CLIENT_ID: "from-env", SNAPTRADE_CONSUMER_KEY: "env-key" };
    expect(envDefaults(target, file, environ)).toEqual({ SNAPTRADE_CLIENT_ID: "from-file", SNAPTRADE_CONSUMER_KEY: "env-key", EDGAR_USER_AGENT: "t me@t.io" });
    expect(envDefaults(target, undefined, environ).SNAPTRADE_CLIENT_ID).toBe("from-target");
    expect(envDefaults(path.join(dir, "missing"), undefined, environ).SNAPTRADE_CLIENT_ID).toBe("from-env");
    expect(preservedEnvLines(target, file)).toEqual(["X=1", "Y=3"]);
  });

  it("validates the EDGAR user agent and masks secrets", () => {
    expect(validateEdgarUserAgent("")).toBeNull();
    expect(validateEdgarUserAgent("second-opinion me@example.com")).toBeNull();
    expect(validateEdgarUserAgent("just-a-name")).toMatch(/app-name contact@email/);
    expect(maskSecret("")).toBe("");
    expect(maskSecret("abc")).toBe("••••");
    expect(maskSecret("abcdefgh")).toBe("••••efgh");
  });
});
