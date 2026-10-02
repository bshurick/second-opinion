import { Box, Text } from "ink";
import { Panel } from "../components/Panel.js";
import { color, glyph } from "../theme.js";

export function ErrorScreen({ message, hint }: { message: string; hint: string }) {
  return (
    <Panel tint={color.err} title={`${glyph.cross} ${message}`}>
      {hint ? (
        <Box marginTop={1}>
          <Text>
            <Text color={color.dim}>next step  </Text>
            {hint}
          </Text>
        </Box>
      ) : null}
      <Box marginTop={1}>
        <Text color={color.dim}>Nothing was changed. Re-run node install.js after fixing this.</Text>
      </Box>
    </Panel>
  );
}
