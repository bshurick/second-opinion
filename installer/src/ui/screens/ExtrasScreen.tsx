import { Box, Text, useInput } from "ink";
import { useState } from "react";
import type { Extra } from "../../engine/catalog.js";
import type { ExtrasState } from "../../engine/extras.js";
import { KeyHints } from "../components/KeyHints.js";
import { color, glyph } from "../theme.js";

interface Props {
  extras: Extra[];
  initial: ExtrasState;
  onDone: (state: ExtrasState) => void;
  /** Opens the full per-skill picker; the `c` key only works when this is given. */
  onCustomize?: (state: ExtrasState) => void;
  onCancel?: () => void;
}

/**
 * Optional extras in plain words, all off unless the user turns them on. Each row says
 * what the extra does and, when it has one, what it costs (an extra step, a longer reply).
 */
export function ExtrasScreen({ extras, initial, onDone, onCustomize, onCancel }: Props) {
  const [state, setState] = useState<ExtrasState>(() => Object.fromEntries(extras.map((e) => [e.key, Boolean(initial[e.key])])));
  const [cursor, setCursor] = useState(0);

  useInput((input, key) => {
    if (key.upArrow || input === "k") setCursor((c) => (c - 1 + extras.length) % extras.length);
    else if (key.downArrow || input === "j") setCursor((c) => (c + 1) % extras.length);
    else if (input === " " && extras[cursor]) {
      const k = extras[cursor]!.key;
      setState((s) => ({ ...s, [k]: !s[k] }));
    } else if (key.return) onDone(state);
    else if (input === "c" && onCustomize) onCustomize(state);
    else if (key.escape && onCancel) onCancel();
  });

  const on = extras.filter((e) => state[e.key]).length;
  const hints: [string, string][] = [["↑↓", "move"], ["space", "toggle"], ["enter", "continue"]];
  if (onCustomize) hints.push(["c", "customize every skill"]);
  if (onCancel) hints.push(["esc", "back"]);

  return (
    <Box flexDirection="column">
      <Text bold>Optional extras</Text>
      <Text color={color.dim} wrap="wrap">
        Off unless you turn them on. Change them any time by running the installer again, or ask Claude to turn one on or off.
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {extras.map((e, i) => {
          const active = i === cursor;
          const isOn = state[e.key];
          return (
            <Box key={e.key} flexDirection="column" marginBottom={1}>
              <Box>
                <Text color={color.accent}>{active ? glyph.pointer : " "} </Text>
                <Text color={isOn ? color.ok : color.dim}>{isOn ? glyph.on : glyph.off} </Text>
                <Text bold={active} color={active ? color.accent : undefined}>
                  {e.label}
                </Text>
              </Box>
              <Box paddingLeft={4} flexDirection="column">
                <Text color={color.dim} wrap="wrap">
                  {e.blurb}
                </Text>
                {e.friction ? (
                  <Text color={color.warn} wrap="wrap">
                    {e.friction}
                  </Text>
                ) : null}
              </Box>
            </Box>
          );
        })}
      </Box>
      <Text>
        <Text bold>{on}</Text> of {extras.length} on
      </Text>
      <KeyHints hints={hints} />
    </Box>
  );
}
