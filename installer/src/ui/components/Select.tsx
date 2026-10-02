import { Box, Text, useInput } from "ink";
import { useState } from "react";
import { color, glyph } from "../theme.js";
import { KeyHints } from "./KeyHints.js";

export interface SelectOption<T extends string> {
  value: T;
  label: string;
  hint?: string;
  /** Painted in the warning color (destructive or noteworthy). */
  warn?: boolean;
}

interface Props<T extends string> {
  options: SelectOption<T>[];
  onSelect: (value: T) => void;
  initial?: T;
  /** Called on Escape when provided. */
  onCancel?: () => void;
  isActive?: boolean;
}

/** Single-choice list in the Claude Code style: a pointer, arrows or j/k, number keys, Enter. */
export function Select<T extends string>({ options, onSelect, initial, onCancel, isActive = true }: Props<T>) {
  const start = Math.max(0, options.findIndex((o) => o.value === initial));
  const [index, setIndex] = useState(start);
  useInput(
    (input, key) => {
      if (key.upArrow || input === "k") setIndex((i) => (i - 1 + options.length) % options.length);
      else if (key.downArrow || input === "j") setIndex((i) => (i + 1) % options.length);
      else if (key.return) onSelect(options[index]!.value);
      else if (key.escape && onCancel) onCancel();
      else if (/^[1-9]$/.test(input) && Number(input) <= options.length) {
        setIndex(Number(input) - 1);
        onSelect(options[Number(input) - 1]!.value);
      }
    },
    { isActive },
  );
  return (
    <Box flexDirection="column">
      {options.map((o, i) => {
        const active = i === index;
        const tint = active ? (o.warn ? color.warn : color.accent) : o.warn ? color.warn : undefined;
        return (
          <Box key={o.value}>
            <Text color={color.accent}>{active ? glyph.pointer : " "} </Text>
            <Text color={tint} bold={active}>
              {i + 1}. {o.label}
            </Text>
            {o.hint ? <Text color={color.dim}>  {o.hint}</Text> : null}
          </Box>
        );
      })}
      <Box marginTop={1}>
        <KeyHints hints={onCancel ? [["↑↓", "move"], ["enter", "select"], ["esc", "back"]] : [["↑↓", "move"], ["enter", "select"]]} />
      </Box>
    </Box>
  );
}
