import { render } from "ink";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseOptions, USAGE } from "./cli.js";
import { reportError, runPlain } from "./drivers/plain.js";
import { createContext, INSTALLER_VERSION } from "./engine/installer.js";
import { sourceCommit } from "./engine/materialize.js";
import { ProcessRunner } from "./engine/runner.js";
import { App } from "./ui/App.js";

/** The plugin checkout: the directory holding install.js (the bundle) or, in dev, installer/.. */
function pluginRoot(): string {
  const here = path.dirname(fileURLToPath(import.meta.url));
  return path.basename(here) === "src" ? path.resolve(here, "..", "..") : here;
}

async function main(): Promise<number> {
  let options;
  try {
    options = parseOptions(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`install.js: ${(err as Error).message}\n${USAGE}\n`);
    return 2;
  }
  if (options.help) {
    process.stdout.write(USAGE + "\n");
    return 0;
  }
  if (options.version) {
    process.stdout.write(`second-opinion installer ${INSTALLER_VERSION}\n`);
    return 0;
  }
  const root = pluginRoot();
  const runner = new ProcessRunner();
  const interactive = process.stdin.isTTY && process.stdout.isTTY && !options.json && !options.plain && !process.env.CI;
  if (!interactive) return runPlain(root, options, process.env, runner, { stdout: process.stdout, stderr: process.stderr });

  const ctx = createContext(root, options, process.env, runner);
  if (options.dryRun) {
    // The guided interface has a review step; a dry run is the plain plan printout.
    return runPlain(root, { ...options, plain: true }, process.env, runner, { stdout: process.stdout, stderr: process.stderr });
  }
  let code = 130; // Ctrl+C unless a screen reports otherwise
  try {
    const commit = await sourceCommit(root, runner);
    const app = render(<App ctx={ctx} commit={commit} onExit={(c) => (code = c)} />, { exitOnCtrlC: true });
    await app.waitUntilExit();
  } catch (err) {
    return reportError(err, { stdout: process.stdout, stderr: process.stderr });
  }
  return code;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    process.stderr.write(`install.js: unexpected error: ${(err as Error)?.stack ?? String(err)}\n`);
    process.exit(1);
  },
);
