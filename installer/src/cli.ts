import { parseArgs } from "node:util";
import { UsageError } from "./engine/errors.js";

export interface Options {
  target?: string;
  all: boolean;
  skills?: string;
  without?: string;
  /** `KEY=on|off,...` for optional extras (skill and non-skill). */
  extras?: string;
  snaptradeClientId?: string;
  snaptradeConsumerKey?: string;
  etradeConsumerKey?: string;
  etradeConsumerSecret?: string;
  etradeSandbox: boolean;
  brokers?: string;
  edgarUserAgent?: string;
  envFile?: string;
  noLink: boolean;
  noSmoke: boolean;
  json: boolean;
  dryRun: boolean;
  yes: boolean;
  uninstall: boolean;
  purgeData: boolean;
  help: boolean;
  version: boolean;
  /** Force the line-oriented driver even on a terminal. */
  plain: boolean;
  /** Configure only (data-dir .env, installed.json, venv); never copy or link. Implied inside a Claude Code plugin cache. */
  configure: boolean;
}

export const USAGE = `Usage: node install.js [options]

Install the Second Opinion plugin for Claude Code with the skills you choose.
Run it with no options for the guided installer.

Selection        --all | --skills a,b,c | --without x,y      (default: the core skills, or the previous selection)
                 --extras KEY=on|off,...   optional extras, off unless chosen: follow_ups, trade-journal, financial-education
Credentials      --snaptrade-client-id ID --snaptrade-consumer-key KEY
                 --etrade-consumer-key KEY --etrade-consumer-secret SECRET [--etrade-sandbox]
                 --brokers snaptrade,etrade   which brokerage connections to configure (default: whichever keys are present)
                 --edgar-user-agent "app me@x"
                 --env-file PATH   copy credentials from this .env (SNAPTRADE_* / ETRADE_* / EDGAR_USER_AGENT env vars also work)
Where            --target DIR      install directory (default ~/.claude/plugins/second-opinion)
                 --no-link         do not link into ~/.claude/skills
                 --configure       only write settings, extras and the venv to the data dir; copy and link
                                   nothing (automatic when run from a /plugin marketplace install)
Behaviour        --dry-run         show the plan and exit without writing anything
                 --no-smoke        skip the smoke test
                 --yes             accept every confirmation and the default for optional prompts
                 --json            machine summary on stdout; never prompts
                 --plain           line output instead of the guided interface
Uninstall        --uninstall [--purge-data]   remove the install; --purge-data also deletes the data dir
                 --help, --version

Exit codes: 0 ok; 1 a named failure (message on stderr); 2 bad arguments.`;

export function parseOptions(argv: string[]): Options {
  let parsed: ReturnType<typeof parseArgs>;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: false,
      strict: true,
      options: {
        target: { type: "string" },
        all: { type: "boolean", default: false },
        skills: { type: "string" },
        without: { type: "string" },
        extras: { type: "string" },
        "snaptrade-client-id": { type: "string" },
        "snaptrade-consumer-key": { type: "string" },
        "etrade-consumer-key": { type: "string" },
        "etrade-consumer-secret": { type: "string" },
        "etrade-sandbox": { type: "boolean", default: false },
        brokers: { type: "string" },
        "edgar-user-agent": { type: "string" },
        "env-file": { type: "string" },
        "no-link": { type: "boolean", default: false },
        "no-smoke": { type: "boolean", default: false },
        json: { type: "boolean", default: false },
        "dry-run": { type: "boolean", default: false },
        yes: { type: "boolean", short: "y", default: false },
        uninstall: { type: "boolean", default: false },
        "purge-data": { type: "boolean", default: false },
        help: { type: "boolean", short: "h", default: false },
        version: { type: "boolean", short: "V", default: false },
        plain: { type: "boolean", default: false },
        configure: { type: "boolean", default: false },
      },
    });
  } catch (err) {
    throw new UsageError((err as Error).message.replace(/\.$/, ""));
  }
  const v = parsed.values as Record<string, string | boolean | undefined>;
  const opts: Options = {
    target: v.target as string | undefined,
    all: Boolean(v.all),
    skills: v.skills as string | undefined,
    without: v.without as string | undefined,
    extras: v.extras as string | undefined,
    snaptradeClientId: v["snaptrade-client-id"] as string | undefined,
    snaptradeConsumerKey: v["snaptrade-consumer-key"] as string | undefined,
    etradeConsumerKey: v["etrade-consumer-key"] as string | undefined,
    etradeConsumerSecret: v["etrade-consumer-secret"] as string | undefined,
    etradeSandbox: Boolean(v["etrade-sandbox"]),
    brokers: v.brokers as string | undefined,
    edgarUserAgent: v["edgar-user-agent"] as string | undefined,
    envFile: v["env-file"] as string | undefined,
    noLink: Boolean(v["no-link"]),
    noSmoke: Boolean(v["no-smoke"]),
    json: Boolean(v.json),
    dryRun: Boolean(v["dry-run"]),
    yes: Boolean(v.yes),
    uninstall: Boolean(v.uninstall),
    purgeData: Boolean(v["purge-data"]),
    help: Boolean(v.help),
    version: Boolean(v.version),
    plain: Boolean(v.plain),
    configure: Boolean(v.configure),
  };
  const selectors = [opts.all, opts.skills !== undefined, opts.without !== undefined].filter(Boolean).length;
  if (selectors > 1) throw new UsageError("--all, --skills and --without are mutually exclusive");
  if (opts.purgeData && !opts.uninstall) throw new UsageError("--purge-data only applies with --uninstall");
  if (opts.configure && opts.uninstall) throw new UsageError("--configure and --uninstall are mutually exclusive (a /plugin install is removed with /plugin uninstall)");
  return opts;
}
