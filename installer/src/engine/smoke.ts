import fs from "node:fs";
import path from "node:path";
import type { Runner } from "./runner.js";

export type SmokeStatus = "ok" | "failed" | "skipped";
export type ConnectStatus = "ok" | "no_keys" | "no_login" | "rejected" | "failed" | "skipped";

export interface SmokeResult {
  imports: SmokeStatus;
  dcf: SmokeStatus;
  status: ConnectStatus;
  etrade: ConnectStatus;
}

export const SMOKE_SKIPPED: SmokeResult = { imports: "skipped", dcf: "skipped", status: "skipped", etrade: "skipped" };

const SMOKE_DCF_INPUT = {
  fcf0: 1000.0,
  growth_rate: 0.05,
  years: 5,
  terminal_growth: 0.02,
  wacc: 0.09,
  net_debt: 0.0,
  shares_outstanding: 100.0,
};

/**
 * Three network-free-where-possible checks against the new target:
 * imports of both dependencies, a fixed DCF run, and (only with keys) connect/status.py.
 */
export async function smoke(target: string, venvPy: string, brokers: ReadonlySet<string>, runner: Runner, onCheck?: (name: keyof SmokeResult, value: string) => void): Promise<SmokeResult> {
  const out: SmokeResult = { ...SMOKE_SKIPPED };
  const imp = await runner.run(
    [venvPy, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import second_opinion, yfinance, requests_oauthlib", path.join(target, "lib")],
    { cwd: target, timeoutMs: 120_000 },
  );
  out.imports = imp.code === 0 ? "ok" : "failed";
  onCheck?.("imports", out.imports);

  const dcf = path.join(target, "skills", "valuation", "scripts", "dcf.py");
  if (fs.existsSync(path.dirname(dcf))) {
    const r = await runner.run([venvPy, dcf], { cwd: target, stdin: JSON.stringify(SMOKE_DCF_INPUT), timeoutMs: 120_000 });
    let ok = false;
    if (r.code === 0) {
      try {
        ok = "fair_value_per_share" in (JSON.parse(r.stdout || "{}") as object);
      } catch {
        ok = false;
      }
    }
    out.dcf = ok ? "ok" : "failed";
  } else {
    out.dcf = "skipped";
  }
  onCheck?.("dcf", out.dcf);

  const status = path.join(target, "skills", "connect", "scripts", "status.py");
  if (!brokers.has("snaptrade")) out.status = "no_keys";
  else if (!fs.existsSync(path.dirname(status))) out.status = "skipped";
  else {
    const r = await runner.run([venvPy, status], { cwd: target, timeoutMs: 120_000 });
    out.status = r.code === 0 ? "ok" : r.code === 4 || r.code === 5 ? "rejected" : "failed";
  }
  onCheck?.("status", out.status);

  const login = path.join(target, "skills", "connect", "scripts", "etrade-login.py");
  if (!brokers.has("etrade")) out.etrade = "no_keys";
  else if (!fs.existsSync(login)) out.etrade = "skipped";
  else {
    const r = await runner.run([venvPy, login, "--status"], { cwd: target, timeoutMs: 60_000 });
    if (r.code === 0) {
      let token: unknown;
      try {
        token = (JSON.parse(r.stdout || "{}") as { token?: unknown }).token;
      } catch {
        token = undefined;
      }
      out.etrade = token === "usable" ? "ok" : token === "none" || token === "expired" ? "no_login" : "failed";
    } else {
      out.etrade = r.code === 4 ? "rejected" : "failed";
    }
  }
  onCheck?.("etrade", out.etrade);
  return out;
}
