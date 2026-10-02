import { Box, Text, useInput } from "ink";
import { useState } from "react";
import { color, glyph } from "../theme.js";

interface Props {
  label: string;
  /** Shown dim under the label. */
  help?: string[];
  placeholder?: string;
  /** Replace typed characters with dots. */
  mask?: boolean;
  /** Return an error message to block submit, or null to accept. Runs on the trimmed value. */
  validate?: (value: string) => string | null;
  /** Submitting an empty value: allowed when true (the caller decides what empty means). */
  allowEmpty?: boolean;
  onSubmit: (value: string) => void;
  onCancel?: () => void;
  isActive?: boolean;
}

// Control characters and newlines that can arrive with pasted text.
const CONTROL = /[\u0000-\u001f\u007f]/g;

/** One-line prompt with a cursor, backspace, left/right, and optional masking. */
export function TextInput({ label, help = [], placeholder, mask = false, validate, allowEmpty = false, onSubmit, onCancel, isActive = true }: Props) {
  const [value, setValue] = useState("");
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const submit = (raw: string) => {
    const v = raw.trim();
    if (!v && !allowEmpty) {
      setError("a value is required");
      return;
    }
    const err = validate?.(v) ?? null;
    if (err) {
      setError(err);
      return;
    }
    onSubmit(v);
  };

  const insert = (text: string): string => {
    const next = value.slice(0, cursor) + text + value.slice(cursor);
    setValue(next);
    setCursor(cursor + text.length);
    return next;
  };

  useInput(
    (input, key) => {
      if (key.return) return submit(value);
      if (key.escape) return onCancel?.();
      setError(null);
      if (key.backspace || key.delete) {
        if (cursor > 0) {
          setValue(value.slice(0, cursor - 1) + value.slice(cursor));
          setCursor(cursor - 1);
        }
        return;
      }
      if (key.leftArrow) return setCursor(Math.max(0, cursor - 1));
      if (key.rightArrow) return setCursor(Math.min(value.length, cursor + 1));
      if (key.ctrl && input === "u") {
        setValue("");
        setCursor(0);
        return;
      }
      if (key.ctrl || key.meta || key.tab || key.upArrow || key.downArrow) return;
      // A paste can arrive as one chunk, sometimes with the newline that followed it.
      const newline = input.search(/[\r\n]/);
      if (newline >= 0) {
        const next = insert(input.slice(0, newline).replace(CONTROL, ""));
        return submit(next);
      }
      const clean = input.replace(CONTROL, "");
      if (clean) insert(clean);
    },
    { isActive },
  );

  const shown = mask ? "•".repeat(value.length) : value;
  const before = shown.slice(0, cursor);
  const at = shown.slice(cursor, cursor + 1) || " ";
  const after = shown.slice(cursor + 1);

  return (
    <Box flexDirection="column">
      <Text bold>{label}</Text>
      {help.map((h) => (
        <Text key={h} color={color.dim}>
          {h}
        </Text>
      ))}
      <Box>
        <Text color={color.accent}>{glyph.pointer} </Text>
        {value ? (
          <Text>
            {before}
            <Text inverse>{at}</Text>
            {after}
          </Text>
        ) : (
          <Text>
            <Text inverse> </Text>
            <Text color={color.dim}>{placeholder ?? ""}</Text>
          </Text>
        )}
      </Box>
      {error ? (
        <Text color={color.err}>
          {glyph.cross} {error}
        </Text>
      ) : (
        <Text color={color.dim}>enter to continue{onCancel ? `  ${glyph.dot}  esc to go back` : ""}</Text>
      )}
    </Box>
  );
}
