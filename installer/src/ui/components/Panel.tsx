import { Box, Text } from "ink";
import type { ReactNode } from "react";
import { color } from "../theme.js";

/** A rounded box with an optional title in the accent color. */
export function Panel({ title, children, tint = color.accent, width }: { title?: string; children: ReactNode; tint?: string; width?: number }) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={tint} paddingX={1} width={width}>
      {title ? (
        <Box>
          <Text bold color={tint}>
            {title}
          </Text>
        </Box>
      ) : null}
      {children}
    </Box>
  );
}
