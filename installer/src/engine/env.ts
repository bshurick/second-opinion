import fs from "node:fs";
import type { Environ } from "./paths.js";

export const ENV_KEYS = ["SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY", "ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET", "ETRADE_SANDBOX", "EDGAR_USER_AGENT", "BROKER_ACCOUNT_TYPES", "SNAPTRADE_ACCOUNT_TYPES"] as const;
export type EnvKey = (typeof ENV_KEYS)[number];
export type EnvValues = Partial<Record<EnvKey, string>>;
export type BrokerChoice = "snaptrade" | "etrade";

/** Brokers whose credential pair is complete. */
export function brokersFrom(values: EnvValues): Set<BrokerChoice> {
  const out = new Set<BrokerChoice>();
  if (values.SNAPTRADE_CLIENT_ID && values.SNAPTRADE_CONSUMER_KEY) out.add("snaptrade");
  if (values.ETRADE_CONSUMER_KEY && values.ETRADE_CONSUMER_SECRET) out.add("etrade");
  return out;
}

const managed = new Set<string>(ENV_KEYS);

/** A value as written on a KEY=VALUE line: matching outer quotes are stripped (no escapes),
 *  exactly like lib/second_opinion/config.py's parse_env_file. */
export function unquoteEnvValue(raw: string): string {
  const v = raw.trim();
  if (v.length >= 2 && (v[0] === '"' || v[0] === "'") && v[v.length - 1] === v[0]) return v.slice(1, -1);
  return v;
}

/** A value as it should appear on a KEY=VALUE line: double-quoted when it contains whitespace
 *  (or a quote) so `EDGAR_USER_AGENT="my-app-name me@example.com"` survives every reader; the
 *  Python loader accepts both forms. Values with no such characters are written bare. */
export function quoteEnvValue(value: string): string {
  if (!/[\s"']/.test(value)) return value;
  return value.includes('"') && !value.includes("'") ? `'${value}'` : `"${value}"`;
}

/** KEY=VALUE lines for managed keys with non-empty values; comments and blanks ignored. */
export function parseEnv(text: string): EnvValues {
  const out: EnvValues = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    const k = line.slice(0, i).trim();
    const v = unquoteEnvValue(line.slice(i + 1));
    if (managed.has(k) && v) out[k as EnvKey] = v;
  }
  return out;
}

/** Non-comment KEY=VALUE lines whose KEY the installer does not manage, verbatim. */
export function unmanagedEnvLines(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const key = line.slice(0, line.indexOf("=")).trim();
    if (!managed.has(key)) out.push(raw);
  }
  return out;
}

export function renderEnv(values: EnvValues, needs: ReadonlySet<string>, extra: string[] = [], brokers: ReadonlySet<BrokerChoice> = brokersFrom(values)): string {
  const lines = [
    "# Written by install.js — re-run it (or ask Claude to run the setup skill) to change these.",
    "# Scripts read this file; the process environment takes precedence.",
  ];
  if (needs.has("brokerage") && brokers.size) {
    if (brokers.has("snaptrade")) {
      lines.push("# SnapTrade Personal API key — https://dashboard.snaptrade.com/api-key");
      lines.push(`SNAPTRADE_CLIENT_ID=${quoteEnvValue(values.SNAPTRADE_CLIENT_ID ?? "")}`);
      lines.push(`SNAPTRADE_CONSUMER_KEY=${quoteEnvValue(values.SNAPTRADE_CONSUMER_KEY ?? "")}`);
    }
    if (brokers.has("etrade")) {
      lines.push("# E*Trade developer key — https://developer.etrade.com (tokens expire nightly; the connect skill re-authorizes)");
      lines.push(`ETRADE_CONSUMER_KEY=${quoteEnvValue(values.ETRADE_CONSUMER_KEY ?? "")}`);
      lines.push(`ETRADE_CONSUMER_SECRET=${quoteEnvValue(values.ETRADE_CONSUMER_SECRET ?? "")}`);
      lines.push(`ETRADE_SANDBOX=${values.ETRADE_SANDBOX === "1" ? "1" : "0"}`);
    }
    const types = values.BROKER_ACCOUNT_TYPES ?? values.SNAPTRADE_ACCOUNT_TYPES;
    lines.push("# Optional: <account_id>=cash,<account_id>=margin (only margin SnapTrade accounts need an entry; E*Trade reports its own)");
    lines.push(types ? `BROKER_ACCOUNT_TYPES=${quoteEnvValue(types)}` : "# BROKER_ACCOUNT_TYPES=");
  } else if (needs.has("brokerage")) {
    lines.push("# No brokerage key yet: re-run install.js to add a SnapTrade or E*Trade key.");
  } else {
    lines.push("# No brokerage-backed skills installed.");
  }
  if (needs.has("edgar")) {
    lines.push("# SEC EDGAR requires a User-Agent with a contact address (fundamental-research).");
    lines.push(`EDGAR_USER_AGENT=${quoteEnvValue(values.EDGAR_USER_AGENT ?? "")}`);
  } else {
    lines.push('# EDGAR_USER_AGENT="my-app-name me@example.com"   (only for fundamental-research)');
  }
  if (extra.length) {
    lines.push("# preserved from your previous .env");
    lines.push(...extra);
  }
  return lines.join("\n") + "\n";
}

function readIfFile(p: string | undefined): string | null {
  if (!p) return null;
  try {
    return fs.statSync(p).isFile() ? fs.readFileSync(p, "utf8") : null;
  } catch {
    return null;
  }
}

type EnvSources = string | undefined | (string | undefined)[];
const asList = (x: EnvSources): (string | undefined)[] => (Array.isArray(x) ? x : [x]);

/**
 * Precedence, lowest to highest: process environment, the existing .env files (in the order given:
 * older locations first, the data dir's last), then --env-file.
 */
export function envDefaults(existing: EnvSources, envFile: string | undefined, environ: Environ): EnvValues {
  const out: EnvValues = {};
  for (const k of ENV_KEYS) if (environ[k]) out[k] = environ[k];
  for (const file of [...asList(existing), envFile]) {
    const t = readIfFile(file);
    if (t !== null) Object.assign(out, parseEnv(t));
  }
  return out;
}

/** Unmanaged lines from the existing .env files (in the order given) then --env-file; the first occurrence of each key wins. */
export function preservedEnvLines(existing: EnvSources, envFile: string | undefined): string[] {
  const byKey = new Map<string, string>();
  for (const text of [...asList(existing), envFile].map(readIfFile)) {
    if (text === null) continue;
    for (const line of unmanagedEnvLines(text)) {
      const key = line.slice(0, line.indexOf("=")).trim();
      if (!byKey.has(key)) byKey.set(key, line);
    }
  }
  return [...byKey.values()];
}

/** "name email" with a contact address, as the SEC requires. */
export function validateEdgarUserAgent(value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  if (!/\S+\s+\S+@\S+\.\S+/.test(v)) return "use the form: app-name contact@email";
  return null;
}

/** Last four characters for display; never the full value. */
export function maskSecret(value: string): string {
  if (!value) return "";
  return value.length <= 4 ? "••••" : `••••${value.slice(-4)}`;
}
