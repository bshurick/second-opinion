import { Text } from "ink";
import { color, glyph } from "../theme.js";

/** Footer line such as "↑↓ move · space toggle · enter continue". */
export function KeyHints({ hints }: { hints: [key: string, action: string][] }) {
  return (
    <Text color={color.dim}>
      {hints.map(([k, a], i) => (
        <Text key={k}>
          {i > 0 ? `  ${glyph.dot}  ` : ""}
          <Text bold color={color.dim}>
            {k}
          </Text>{" "}
          {a}
        </Text>
      ))}
    </Text>
  );
}
