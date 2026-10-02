import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export interface RunOptions {
  /** Append stdout+stderr to this file with a timestamped header. */
  log?: string;
  /** Called with each line of output as it arrives (for live progress). */
  onLine?: (line: string) => void;
  timeoutMs?: number;
  cwd?: string;
  stdin?: string;
  env?: NodeJS.ProcessEnv;
}

export interface RunResult {
  /** Exit code; 127 when the program was not found, 124 on timeout. */
  code: number;
  stdout: string;
  stderr: string;
}

/** Everything that spawns a process goes through here so tests can substitute a fake. */
export interface Runner {
  run(cmd: string[], opts?: RunOptions): Promise<RunResult>;
}

const live = new Set<ReturnType<typeof spawn>>();
// Ctrl+C or a fatal error must not leave a pip or venv process running behind us.
process.on("exit", () => {
  for (const child of live) child.kill("SIGTERM");
});

export class ProcessRunner implements Runner {
  run(cmd: string[], opts: RunOptions = {}): Promise<RunResult> {
    const [program, ...args] = cmd;
    if (!program) return Promise.resolve({ code: 2, stdout: "", stderr: "empty command" });
    return new Promise((resolve) => {
      let stdout = "";
      let stderr = "";
      let pending = "";
      let settled = false;
      const finish = (code: number) => {
        if (settled) return;
        settled = true;
        if (child) live.delete(child);
        if (pending && opts.onLine) opts.onLine(pending);
        if (opts.log) appendLog(opts.log, cmd, stdout + stderr);
        resolve({ code, stdout, stderr });
      };
      let child: ReturnType<typeof spawn> | undefined;
      try {
        child = spawn(program, args, { cwd: opts.cwd, env: opts.env ?? process.env, stdio: ["pipe", "pipe", "pipe"] });
      } catch {
        finish(127);
        return;
      }
      live.add(child);
      const timer = setTimeout(() => {
        child.kill("SIGKILL");
        finish(124);
      }, opts.timeoutMs ?? 900_000);
      const feed = (chunk: Buffer) => {
        if (!opts.onLine) return;
        pending += chunk.toString();
        const parts = pending.split(/\r?\n/);
        pending = parts.pop() ?? "";
        for (const line of parts) if (line.trim()) opts.onLine(line);
      };
      child.stdout?.on("data", (c: Buffer) => {
        stdout += c.toString();
        feed(c);
      });
      child.stderr?.on("data", (c: Buffer) => {
        stderr += c.toString();
        feed(c);
      });
      child.on("error", (err: NodeJS.ErrnoException) => {
        clearTimeout(timer);
        finish(err.code === "ENOENT" ? 127 : 1);
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        finish(code ?? 1);
      });
      if (opts.stdin !== undefined) child.stdin?.end(opts.stdin);
      else child.stdin?.end();
    });
  }
}

function appendLog(file: string, cmd: string[], output: string): void {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, `== ${new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00")} $ ${cmd.join(" ")}\n${output}`);
  } catch {
    // logging must never fail an install
  }
}
