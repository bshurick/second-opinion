import { Box, Text } from "ink";
import { useEffect, useRef, useState } from "react";
import { InstallError } from "../../engine/errors.js";
import { execute, type Context, type InstallEvent, type Plan, type StepId, type Summary } from "../../engine/installer.js";
import { Steps, type StepView } from "../components/Steps.js";
import { color } from "../theme.js";

interface Props {
  ctx: Context;
  plan: Plan;
  replaceLink: boolean;
  onDone: (summary: Summary, steps: StepView[]) => void;
  onFail: (error: InstallError) => void;
}

const INITIAL: StepView[] = [
  { id: "deps", label: "Python dependencies", status: "pending" },
  { id: "copy", label: "Plugin files", status: "pending" },
  { id: "link", label: "Link into ~/.claude/skills", status: "pending" },
  { id: "smoke", label: "Smoke test", status: "pending" },
];

/** A /plugin install: Claude Code owns the files, so there is nothing to copy or link. */
const CONFIGURE_STEPS: StepView[] = [
  { id: "deps", label: "Python dependencies", status: "pending" },
  { id: "copy", label: "Settings", status: "pending" },
  { id: "smoke", label: "Smoke test", status: "pending" },
];

/** Runs the plan and mirrors engine events onto the step list. */
export function ProgressScreen({ ctx, plan, replaceLink, onDone, onFail }: Props) {
  const initial = ctx.configure ? CONFIGURE_STEPS : INITIAL;
  const [steps, setSteps] = useState<StepView[]>(initial);
  const latest = useRef<StepView[]>(initial);
  latest.current = steps;
  const [tick, setTick] = useState(Date.now());

  useEffect(() => {
    const t = setInterval(() => setTick(Date.now()), 250);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const patch = (id: StepId, f: (s: StepView) => StepView) => setSteps((prev) => prev.map((s) => (s.id === id ? f(s) : s)));
    const onEvent = (e: InstallEvent) => {
      switch (e.type) {
        case "step:start":
          patch(e.step, (s) => ({ ...s, status: "running", startedAt: Date.now(), live: undefined }));
          break;
        case "step:log":
          patch(e.step, (s) => ({ ...s, live: e.line.trim() }));
          break;
        case "step:done":
          patch(e.step, (s) => ({ ...s, status: "done", endedAt: Date.now(), detail: e.detail, live: undefined }));
          break;
        case "step:skip":
          patch(e.step, (s) => ({ ...s, status: "skipped", detail: e.reason }));
          break;
        case "step:fail":
          patch(e.step, (s) => ({ ...s, status: "failed", endedAt: Date.now(), detail: e.error.format(), live: undefined }));
          break;
        default:
          break;
      }
    };
    let cancelled = false;
    // The review screen listed the old finance-analyst copy for removal; choosing to go ahead is the consent.
    execute(ctx, plan, { onEvent, confirmLinkReplace: async () => replaceLink, confirmLegacyRemove: async () => true })
      .then((summary) => {
        if (!cancelled) setTimeout(() => onDone(summary, latest.current), 200);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const e = err instanceof InstallError ? err : new InstallError(String((err as Error)?.message ?? err), "check the path is writable and the checkout is complete");
        setTimeout(() => onFail(e), 200);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Box flexDirection="column">
      <Text bold>{ctx.configure ? "Configuring" : plan.previous ? "Updating" : "Installing"}</Text>
      <Box marginTop={1}>
        <Steps steps={steps} now={tick} />
      </Box>
      {steps.find((s) => s.id === "deps")?.status === "running" ? (
        <Box marginTop={1}>
          <Text color={color.dim}>First install downloads the SnapTrade SDK, yfinance and requests-oauthlib; this can take a minute.</Text>
        </Box>
      ) : null}
    </Box>
  );
}
