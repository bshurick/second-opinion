import { Box, Text } from "ink";
import { useEffect, useState } from "react";
import type { Context, Preflight } from "../../engine/installer.js";
import { preflight } from "../../engine/installer.js";
import { PYTHON_FLOOR, pythonHint } from "../../engine/python.js";
import { Steps, type StepView } from "../components/Steps.js";
import { color } from "../theme.js";

interface Props {
  ctx: Context;
  onDone: (pre: Preflight) => void;
  /** Called with a message and hint when a check fails. */
  onFail: (message: string, hint: string) => void;
}

function describeInstall(pre: Preflight): string {
  const p = pre.previous;
  if (!p) return "none found (fresh install)";
  const when = p.installed_at ? p.installed_at.slice(0, 10) : "unknown date";
  return `${p.skills.length} skills, installed ${when}${p.installer_version ? ` by installer ${p.installer_version}` : ""}`;
}

/** Runs the environment checks with live spinners; settles to a list of ✔/✖ lines. */
export function PreflightScreen({ ctx, onDone, onFail }: Props) {
  const [steps, setSteps] = useState<StepView[]>([
    { id: "node", label: "Node.js", status: "done", detail: `v${process.versions.node}` },
    { id: "python", label: `Python ${PYTHON_FLOOR.join(".")}+ with venv`, status: "running", startedAt: Date.now() },
    { id: "existing", label: "Existing install", status: "pending" },
  ]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const pre = await preflight(ctx);
      if (cancelled) return;
      const py = pre.python.found;
      setSteps((prev) =>
        prev.map((s) => {
          if (s.id === "python") {
            return py
              ? { ...s, status: "done", endedAt: Date.now(), detail: `${py.version} (${py.command.join(" ")}${py.source !== "PATH" ? `, from ${py.source}` : ""})` }
              : { ...s, status: "failed", endedAt: Date.now(), detail: pre.python.rejected.map((r) => `${r.command}: ${r.reason}`).join("; ") };
          }
          if (s.id === "existing") return { ...s, status: "done", detail: describeInstall(pre) };
          return s;
        }),
      );
      // Let the settled checks paint before moving on.
      setTimeout(() => {
        if (cancelled) return;
        if (!py) onFail("no usable Python interpreter", pythonHint(pre.python));
        else onDone(pre);
      }, 150);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Box flexDirection="column">
      <Text bold>Checking your environment</Text>
      <Box marginTop={1} flexDirection="column">
        <Steps steps={steps} />
      </Box>
      {steps.some((s) => s.status === "failed") ? (
        <Box marginTop={1}>
          <Text color={color.err}>The plugin's skills run on Python; the installer needs an interpreter to build their virtualenv.</Text>
        </Box>
      ) : null}
    </Box>
  );
}
