import { Box, Text } from "ink";
import type { ReactNode } from "react";
import { color } from "../theme.js";

/** A dim key in a fixed column and a value that wraps with a hanging indent. */
export function KeyValue({ k, width = 12, children }: { k: string; width?: number; children: ReactNode }) {
  return (
    <Box>
      <Box width={width} flexShrink={0}>
        <Text color={color.dim}>{k}</Text>
      </Box>
      <Box flexGrow={1} flexShrink={1}>
        {children}
      </Box>
    </Box>
  );
}
