import { Box, Text } from "ink";
import { color, glyph } from "../theme.js";
import { Spinner } from "./Spinner.js";

export type StepStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface StepView {
  id: string;
  label: string;
  status: StepStatus;
  /** Result text after the label once done/skipped/failed. */
  detail?: string;
  /** Last line of live output while running. */
  live?: string;
  startedAt?: number;
  endedAt?: number;
}

function elapsed(s: StepView, now: number): string {
  if (!s.startedAt) return "";
  const ms = (s.endedAt ?? now) - s.startedAt;
  return ms >= 1000 ? ` ${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)}s` : "";
}

export function Steps({ steps, now = Date.now() }: { steps: StepView[]; now?: number }) {
  return (
    <Box flexDirection="column">
      {steps.map((s) => (
        <Box key={s.id} flexDirection="column">
          <Box>
            <Box width={2}>
              {s.status === "running" ? <Spinner /> : null}
              {s.status === "done" ? <Text color={color.ok}>{glyph.check}</Text> : null}
              {s.status === "failed" ? <Text color={color.err}>{glyph.cross}</Text> : null}
              {s.status === "skipped" ? <Text color={color.dim}>{glyph.dot}</Text> : null}
              {s.status === "pending" ? <Text color={color.dim}>{glyph.off}</Text> : null}
            </Box>
            <Text color={s.status === "pending" ? color.dim : undefined} bold={s.status === "running"}>
              {s.label}
            </Text>
            {s.detail ? (
              <Text color={s.status === "failed" ? color.err : color.dim}>
                {"  "}
                {s.detail}
              </Text>
            ) : null}
            {s.status === "running" || s.status === "done" ? <Text color={color.dim}>{elapsed(s, now)}</Text> : null}
          </Box>
          {s.status === "running" && s.live ? (
            <Box marginLeft={2}>
              <Text color={color.dim} wrap="truncate-end">
                {s.live}
              </Text>
            </Box>
          ) : null}
        </Box>
      ))}
    </Box>
  );
}
